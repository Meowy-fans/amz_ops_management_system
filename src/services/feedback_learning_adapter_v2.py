"""V2 feedback learning adapter for Amazon missing-required signals."""

from __future__ import annotations

from typing import Any, Dict, List

from src.repositories.amazon_listing_learned_required_paths_v2_repository import (
    AmazonListingLearnedRequiredPathsV2Repository,
)

DEFAULT_PATH_KEY_VERSION = "v2_path_keys_2026_06"
MISSING_REQUIRED_CODE = "90220"


class FeedbackLearningAdapterV2:
    """Learn required path_keys from Amazon 90220 missing-required feedback."""

    def __init__(
        self,
        db: Any = None,
        repository: AmazonListingLearnedRequiredPathsV2Repository | None = None,
        submission_repo: Any = None,
        path_key_version: str = DEFAULT_PATH_KEY_VERSION,
    ):
        self.db = db
        self.repository = repository or (
            AmazonListingLearnedRequiredPathsV2Repository(db) if db is not None else None
        )
        self._submission_repo = submission_repo
        self.path_key_version = path_key_version

    def learn_from_submission(self, submission: Dict[str, Any]) -> int:
        """Parse one amazon_api_submissions row, upsert learned path_keys.

        Returns count of learned path_keys upserted.
        """
        category = str(submission.get("product_type") or "").strip().upper()
        if not category:
            return 0
        submission_id = submission.get("id")
        issues = self._extract_90220_issues(submission.get("response_body"))
        if not issues:
            return 0
        count = 0
        for issue in issues:
            for attribute_name in issue.get("attributeNames") or []:
                text = str(attribute_name or "").strip()
                if not text:
                    continue
                self.repository.upsert_learned(
                    category=category,
                    path_key=text,
                    path_key_version=self.path_key_version,
                    attribute=text,
                    source_submission_id=submission_id,
                )
                count += 1
        return count

    def learn_from_recent_submissions(
        self,
        category: str,
        limit: int = 100,
    ) -> Dict[str, int]:
        """Scan recent amazon_api_submissions for 90220 issues and learn.

        Returns {"submissions_scanned": int, "paths_learned": int}.
        """
        normalized = str(category or "").strip().upper()
        if not normalized:
            return {"submissions_scanned": 0, "paths_learned": 0}
        submissions = self._get_submission_repo().list_submissions_with_issue_code(
            product_type=normalized,
            issue_code=MISSING_REQUIRED_CODE,
            limit=limit,
        )
        paths_learned = 0
        for submission in submissions:
            paths_learned += self.learn_from_submission(submission)
        return {
            "submissions_scanned": len(submissions),
            "paths_learned": paths_learned,
        }

    def get_learned_required_paths(self, category: str) -> List[str]:
        """Return learned required path_keys for one category."""
        normalized = str(category or "").strip().upper()
        if not normalized:
            return []
        return self.repository.list_for_category(normalized)

    @staticmethod
    def _extract_90220_issues(response_body: Any) -> List[Dict[str, Any]]:
        if not isinstance(response_body, dict):
            return []
        issues = response_body.get("issues")
        if not isinstance(issues, list):
            return []
        return [
            issue
            for issue in issues
            if isinstance(issue, dict)
            and str(issue.get("code") or "") == MISSING_REQUIRED_CODE
        ]

    def _get_submission_repo(self):
        if self._submission_repo is None:
            from src.repositories.amazon_api_submission_repository import (
                AmazonAPISubmissionRepository,
            )

            self._submission_repo = AmazonAPISubmissionRepository(self.db)
        return self._submission_repo
