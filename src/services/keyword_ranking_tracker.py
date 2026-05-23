"""Keyword Ranking Tracker.

Tracks keyword position changes over time for managed products.
Phase 2: uses Catalog Items API keyword search to infer ranking.
Phase 3+: integrates with dedicated rank-tracking services.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


# ── output models ───────────────────────────────────────────────────


@dataclass
class KeywordRankSnapshot:
    """Single keyword position snapshot for an ASIN."""

    asin: str = ""
    keyword: str = ""
    position: Optional[int] = None  # None = not in results
    previous_position: Optional[int] = None
    position_change: int = 0  # positive = improved (lower number)
    snapshot_time: str = ""


@dataclass
class RankingReport:
    """Aggregated ranking report for a product."""

    sku: str = ""
    asin: str = ""
    snapshot_time: str = ""
    keywords: List[KeywordRankSnapshot] = field(default_factory=list)
    improved_keywords: List[str] = field(default_factory=list)
    declined_keywords: List[str] = field(default_factory=list)
    new_keywords: List[str] = field(default_factory=list)
    lost_keywords: List[str] = field(default_factory=list)


# ── service ─────────────────────────────────────────────────────────


class KeywordRankingTracker:
    """Tracks keyword ranking changes for products.

    Uses Catalog Items API searchCatalogItems to check if an ASIN
    appears in keyword search results.

    Limitations:
      - searchCatalogItems is NOT a rank tracker — it only returns
        top results for a keyword search. Absence ≠ not ranking.
      - For precise rank tracking, integrate with third-party services
        (Helium 10 API, Jungle Scout API) or manual tracking.
    """

    def __init__(
        self,
        db: Session,
        catalog_client: Any = None,
    ):
        self.db = db
        self._catalog_client = catalog_client

    # ── public API ──────────────────────────────────────────────────

    def add_tracking(
        self,
        sku: str,
        asin: str,
        keywords: List[str],
    ) -> int:
        """Register keywords to track for a product."""
        now = datetime.now().isoformat()
        count = 0
        for kw in keywords:
            self.db.execute(
                text("""
                    INSERT INTO keyword_ranking_tracking (sku, asin, keyword, created_at, last_checked_at)
                    VALUES (:sku, :asin, :keyword, :now, NULL)
                    ON CONFLICT (asin, keyword) DO NOTHING
                """),
                {"sku": sku, "asin": asin, "keyword": kw, "now": now},
            )
            count += 1
        self.db.commit()
        logger.info("Added %d keywords for tracking SKU=%s ASIN=%s", len(keywords), sku, asin)
        return count

    def remove_tracking(self, asin: str, keyword: str) -> bool:
        """Remove a tracked keyword."""
        result = self.db.execute(
            text("DELETE FROM keyword_ranking_tracking WHERE asin=:asin AND keyword=:keyword"),
            {"asin": asin, "keyword": keyword},
        )
        self.db.commit()
        return result.rowcount > 0

    def get_tracked_keywords(self, asin: str) -> List[str]:
        """Get all tracked keywords for an ASIN."""
        rows = self.db.execute(
            text("SELECT keyword FROM keyword_ranking_tracking WHERE asin=:asin ORDER BY keyword"),
            {"asin": asin},
        ).fetchall()
        return [r[0] for r in rows]

    def check_rankings(
        self,
        asin: str,
        keywords: Optional[List[str]] = None,
    ) -> RankingReport:
        """Check current keyword rankings for a product.

        Searches each keyword and checks if our ASIN appears in results.
        """
        if keywords is None:
            keywords = self.get_tracked_keywords(asin)

        catalog = self._get_catalog_client()
        now = datetime.now().isoformat()

        report = RankingReport(
            sku="",
            asin=asin,
            snapshot_time=now,
        )

        previous = self._get_previous_snapshot(asin)
        prev_map = {p["keyword"]: p["position"] for p in previous}

        for kw in keywords:
            snapshot = KeywordRankSnapshot(
                asin=asin,
                keyword=kw,
                snapshot_time=now,
                previous_position=prev_map.get(kw),
            )

            if catalog:
                try:
                    resp = catalog.search_catalog_items(keywords=[kw])
                    body = resp.get("body") or resp
                    items = body.get("items") or []
                    found = False
                    for idx, item in enumerate(items):
                        if item.get("asin") == asin:
                            snapshot.position = idx + 1
                            found = True
                            break
                    if not found:
                        snapshot.position = None
                except Exception as exc:
                    logger.warning("Keyword search failed for '%s': %s", kw, exc)
                    snapshot.position = None

            # Compute change
            if snapshot.position and snapshot.previous_position:
                snapshot.position_change = snapshot.previous_position - snapshot.position
            elif snapshot.position and snapshot.previous_position is None:
                snapshot.position_change = 999  # new keyword
            elif snapshot.position is None and snapshot.previous_position:
                snapshot.position_change = -999  # lost keyword

            report.keywords.append(snapshot)

        # Classify
        for s in report.keywords:
            if s.position_change >= 999:
                report.new_keywords.append(s.keyword)
            elif s.position_change <= -999:
                report.lost_keywords.append(s.keyword)
            elif s.position_change > 0:
                report.improved_keywords.append(s.keyword)
            elif s.position_change < 0:
                report.declined_keywords.append(s.keyword)

        # Save snapshot
        self._save_snapshot(report)

        return report

    def check_batch(
        self,
        asin_keywords_map: Dict[str, List[str]],
    ) -> Dict[str, RankingReport]:
        """Check rankings for multiple ASINs."""
        results = {}
        for asin, keywords in asin_keywords_map.items():
            try:
                results[asin] = self.check_rankings(asin, keywords)
            except Exception as exc:
                logger.error("Rank check failed for %s: %s", asin, exc)
                results[asin] = RankingReport(asin=asin, snapshot_time=datetime.now().isoformat())
        return results

    # ── persistence ─────────────────────────────────────────────────

    def _get_previous_snapshot(self, asin: str) -> List[Dict[str, Any]]:
        """Get the most recent snapshot for an ASIN."""
        try:
            rows = self.db.execute(
                text("""
                    SELECT DISTINCT ON (keyword)
                        keyword, position
                    FROM keyword_ranking_log
                    WHERE asin = :asin
                    ORDER BY keyword, snapshot_time DESC
                """),
                {"asin": asin},
            ).fetchall()
            return [{"keyword": r[0], "position": r[1]} for r in rows]
        except Exception:
            return []

    def _save_snapshot(self, report: RankingReport) -> None:
        """Persist ranking snapshot to database."""
        for s in report.keywords:
            self.db.execute(
                text("""
                    INSERT INTO keyword_ranking_log (asin, keyword, position, snapshot_time)
                    VALUES (:asin, :keyword, :position, :snapshot_time)
                """),
                {
                    "asin": s.asin,
                    "keyword": s.keyword,
                    "position": s.position,
                    "snapshot_time": s.snapshot_time,
                },
            )
        self.db.commit()
        logger.info(
            "Saved %d ranking snapshots for ASIN=%s", len(report.keywords), report.asin
        )

    def _get_catalog_client(self):
        if self._catalog_client is not None:
            return self._catalog_client
        try:
            from infrastructure.amazon.catalog_client import AmazonCatalogClient
            self._catalog_client = AmazonCatalogClient()
            return self._catalog_client
        except Exception:
            return None
