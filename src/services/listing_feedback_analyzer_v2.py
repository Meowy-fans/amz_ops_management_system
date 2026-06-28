"""Classify Amazon listing feedback for rule vs content routing (S11)."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from src.repositories.amazon_api_submission_repository import AmazonAPISubmissionRepository


ROUTE_RULE_LAYER = "rule_layer"
ROUTE_RULE_OR_DATA = "rule_or_data"
ROUTE_CONTENT_LAYER = "content_layer"
ROUTE_LOG_ONLY = "log_only"
ROUTE_UNKNOWN = "unknown"

ISSUE_CODE_FAMILIES = (
    "90220",
    "99022",
    "90244",
    "100339",
    "WARNING",
)


@dataclass
class FeedbackIssueGroup:
    code: str
    route: str
    action: str
    count: int
    sample_messages: List[str] = field(default_factory=list)
    attribute_names: List[str] = field(default_factory=list)
    submission_ids: List[int] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "route": self.route,
            "action": self.action,
            "count": self.count,
            "sample_messages": self.sample_messages,
            "attribute_names": self.attribute_names,
            "submission_ids": self.submission_ids,
        }


@dataclass
class FeedbackAnalysisReport:
    product_type: str
    submissions_scanned: int
    issue_count: int
    groups: List[FeedbackIssueGroup] = field(default_factory=list)
    omit_suggestions: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "product_type": self.product_type,
            "submissions_scanned": self.submissions_scanned,
            "issue_count": self.issue_count,
            "groups": [group.as_dict() for group in self.groups],
            "omit_suggestions": self.omit_suggestions,
        }


class ListingFeedbackAnalyzerV2:
    """Triage Amazon submission issues into rule-layer vs content-layer routes."""

    def __init__(
        self,
        db: Session,
        submission_repo: AmazonAPISubmissionRepository | None = None,
    ):
        self.db = db
        self.submission_repo = submission_repo or AmazonAPISubmissionRepository(db)

    def analyze_category(
        self,
        product_type: str,
        *,
        limit: int = 50,
        issue_codes: Optional[Iterable[str]] = None,
    ) -> FeedbackAnalysisReport:
        normalized = str(product_type or "").strip().upper()
        codes = list(issue_codes or ISSUE_CODE_FAMILIES)
        seen_submission_ids: set[int] = set()
        grouped: Dict[str, FeedbackIssueGroup] = {}
        omit_suggestions: set[str] = set()
        total_issues = 0

        for code in codes:
            submissions = self.submission_repo.list_submissions_with_issue_code(
                normalized,
                issue_code=code,
                limit=int(limit),
            )
            for submission in submissions:
                submission_id = int(submission.get("id") or 0)
                seen_submission_ids.add(submission_id)
                for issue in self._extract_issues(submission.get("response_body"), code):
                    total_issues += 1
                    triage = self.classify_issue(issue)
                    key = triage["code"]
                    group = grouped.get(key)
                    if group is None:
                        group = FeedbackIssueGroup(
                            code=key,
                            route=triage["route"],
                            action=triage["action"],
                            count=0,
                        )
                        grouped[key] = group
                    group.count += 1
                    message = str(issue.get("message") or "").strip()
                    if message and message not in group.sample_messages:
                        group.sample_messages.append(message)
                    for attr in issue.get("attributeNames") or []:
                        text = str(attr or "").strip()
                        if text and text not in group.attribute_names:
                            group.attribute_names.append(text)
                    if submission_id and submission_id not in group.submission_ids:
                        group.submission_ids.append(submission_id)
                    if triage["route"] == ROUTE_RULE_LAYER and key == "99022":
                        for attr in issue.get("attributeNames") or []:
                            root = str(attr or "").split(".")[0].strip()
                            if root:
                                omit_suggestions.add(root)

        groups = sorted(grouped.values(), key=lambda item: (-item.count, item.code))
        return FeedbackAnalysisReport(
            product_type=normalized,
            submissions_scanned=len(seen_submission_ids),
            issue_count=total_issues,
            groups=groups,
            omit_suggestions=sorted(omit_suggestions),
        )

    @classmethod
    def classify_issue(cls, issue: Dict[str, Any]) -> Dict[str, str]:
        code = str(issue.get("code") or "").strip() or "UNKNOWN"
        severity = str(issue.get("severity") or "").strip().upper()
        message = str(issue.get("message") or "").strip().lower()

        if code == "90220":
            return {
                "code": code,
                "route": ROUTE_RULE_LAYER,
                "action": "learn → YAML placeholder → approve-rule",
            }
        if code == "99022" or "partial" in message or "does not match" in message:
            return {
                "code": code if code != "UNKNOWN" else "99022",
                "route": ROUTE_RULE_LAYER,
                "action": "suggest omit_attribute / coverage_ignore via approve-rule",
            }
        if code == "90244" or "enum" in message or "not in the enumeration" in message:
            return {
                "code": code if code != "UNKNOWN" else "90244",
                "route": ROUTE_RULE_OR_DATA,
                "action": "review enum source mapping or data normalizer",
            }
        if code == "100339" or "html" in message or "description" in message:
            return {
                "code": code if code != "UNKNOWN" else "100339",
                "route": ROUTE_CONTENT_LAYER,
                "action": "route to content pipeline; do not auto patch YAML rules",
            }
        if severity == "WARNING" or code.upper().startswith("WARNING"):
            return {
                "code": code,
                "route": ROUTE_LOG_ONLY,
                "action": "log only; no auto patch",
            }
        return {
            "code": code,
            "route": ROUTE_UNKNOWN,
            "action": "manual triage",
        }

    @staticmethod
    def _extract_issues(response_body: Any, code_filter: str) -> List[Dict[str, Any]]:
        payload = ListingFeedbackAnalyzerV2._coerce_json(response_body)
        issues = payload.get("issues") or []
        if not isinstance(issues, list):
            return []
        matched: List[Dict[str, Any]] = []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            code = str(issue.get("code") or "").strip()
            if code_filter == "WARNING":
                severity = str(issue.get("severity") or "").strip().upper()
                if severity == "WARNING" or code.upper().startswith("WARNING"):
                    matched.append(issue)
            elif code == code_filter:
                matched.append(issue)
        return matched

    @staticmethod
    def _coerce_json(value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}
