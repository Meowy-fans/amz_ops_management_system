"""Candidate SKU scope controls for API-native listing creation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from infrastructure.amazon.api_client import AmazonAPIException


@dataclass(frozen=True)
class ListingScope:
    """Operator-specified SKU scope for a listing run."""

    sku_list: tuple[str, ...] = ()
    sku_file: Optional[str] = None
    only_not_on_amazon: bool = False

    @classmethod
    def from_inputs(
        cls,
        sku_list: Optional[Sequence[str]] = None,
        sku_file: Optional[str] = None,
        only_not_on_amazon: bool = False,
    ) -> "ListingScope":
        skus = _normalize_skus(sku_list or [])
        if sku_file:
            skus.extend(_read_sku_file(sku_file))
        return cls(
            sku_list=tuple(_dedupe_preserve_order(skus)),
            sku_file=sku_file,
            only_not_on_amazon=only_not_on_amazon,
        )

    @property
    def requested(self) -> bool:
        return bool(self.sku_list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "requested_skus": list(self.sku_list),
            "sku_file": self.sku_file,
            "only_not_on_amazon": self.only_not_on_amazon,
        }


@dataclass(frozen=True)
class ScopeSelection:
    """Selected SKUs and audit rows produced by scope filtering."""

    selected_skus: List[str]
    pre_submit_results: List[Dict[str, Any]]
    scope: ListingScope


class ProductListingScopeFilter:
    """Applies operator SKU scope before payload building."""

    INCLUDED_DATA = ["summaries", "issues", "attributes", "productTypes"]

    def __init__(self, product_listing_repo, listings_client: Any = None):
        self.product_listing_repo = product_listing_repo
        self.listings_client = listings_client

    def apply(self, category_name: str, scope: ListingScope) -> ScopeSelection:
        all_pending_skus = self.product_listing_repo.get_pending_listing_skus()
        if not all_pending_skus:
            raise ValueError("没有待发品SKU")

        pre_results: List[Dict[str, Any]] = []
        candidates = self._apply_requested_scope(
            all_pending_skus=all_pending_skus,
            scope=scope,
            pre_results=pre_results,
        )
        if not candidates:
            return ScopeSelection([], pre_results, scope)

        selected = self._apply_category_scope(
            candidates=candidates,
            category_name=category_name,
            record_mismatches=scope.requested,
            pre_results=pre_results,
        )
        if not selected:
            return ScopeSelection([], pre_results, scope)

        if scope.only_not_on_amazon:
            selected = self._apply_amazon_existence_scope(selected, pre_results)

        return ScopeSelection(selected, pre_results, scope)

    def _apply_requested_scope(
        self,
        all_pending_skus: List[str],
        scope: ListingScope,
        pre_results: List[Dict[str, Any]],
    ) -> List[str]:
        if not scope.requested:
            return all_pending_skus

        eligible = set(all_pending_skus)
        candidates: List[str] = []
        for sku in scope.sku_list:
            if sku in eligible:
                candidates.append(sku)
            else:
                pre_results.append(_scope_block(
                    sku=sku,
                    code="NOT_PENDING_OR_NOT_ELIGIBLE",
                    message="SKU is not locally eligible for listing creation",
                ))
        return candidates

    def _apply_category_scope(
        self,
        candidates: List[str],
        category_name: str,
        record_mismatches: bool,
        pre_results: List[Dict[str, Any]],
    ) -> List[str]:
        mapping = self.product_listing_repo.get_sku_to_category_mapping(candidates)
        category_by_sku = {sku: category for sku, category in mapping}
        selected: List[str] = []
        for sku in candidates:
            category = category_by_sku.get(sku)
            if category and category.upper() == category_name.upper():
                selected.append(sku)
            elif record_mismatches:
                pre_results.append(_scope_block(
                    sku=sku,
                    code="CATEGORY_MISMATCH_OR_UNMAPPED",
                    message=f"SKU is not mapped to category {category_name}",
                ))
        return selected

    def _apply_amazon_existence_scope(
        self,
        candidates: List[str],
        pre_results: List[Dict[str, Any]],
    ) -> List[str]:
        selected: List[str] = []
        client = self._get_listings_client()
        for sku in candidates:
            try:
                response = client.get_listings_item(
                    sku=sku,
                    included_data=self.INCLUDED_DATA,
                )
            except AmazonAPIException as exc:
                if exc.status_code == 404:
                    selected.append(sku)
                    continue
                pre_results.append(_scope_block(
                    sku=sku,
                    code="EXISTING_LISTING_CHECK_FAILED",
                    message=str(exc),
                ))
                continue

            pre_results.append({
                "sku": sku,
                "status": "skipped_existing_scope",
                "issues": 0,
                "blocking_codes": [],
                "message": "SKU already exists on Amazon and was excluded by scope",
                "response_body": response.get("body", {}),
            })
        return selected

    def _get_listings_client(self):
        if self.listings_client is not None:
            return self.listings_client
        from infrastructure.amazon.listings_client import AmazonListingsClient

        self.listings_client = AmazonListingsClient()
        return self.listings_client


def _scope_block(sku: str, code: str, message: str) -> Dict[str, Any]:
    return {
        "sku": sku,
        "status": "blocked_scope_filter",
        "issues": 1,
        "blocking_codes": [code],
        "message": message,
    }


def _normalize_skus(values: Iterable[str]) -> List[str]:
    skus: List[str] = []
    for value in values:
        for token in str(value).replace(",", "\n").splitlines():
            sku = token.strip()
            if sku:
                skus.append(sku)
    return skus


def _read_sku_file(path: str) -> List[str]:
    text = Path(path).read_text(encoding="utf-8")
    values = []
    for line in text.splitlines():
        clean = line.split("#", 1)[0].strip()
        if clean:
            values.append(clean)
    return _normalize_skus(values)


def _dedupe_preserve_order(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
