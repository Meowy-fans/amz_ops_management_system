"""Tests for listing feedback analyzer (S11)."""

from src.services.listing_feedback_analyzer_v2 import (
    ROUTE_CONTENT_LAYER,
    ROUTE_LOG_ONLY,
    ROUTE_RULE_LAYER,
    ROUTE_RULE_OR_DATA,
    ListingFeedbackAnalyzerV2,
)


def test_classify_issue_routes_known_codes():
    assert ListingFeedbackAnalyzerV2.classify_issue({"code": "90220"})["route"] == ROUTE_RULE_LAYER
    assert ListingFeedbackAnalyzerV2.classify_issue({"code": "99022"})["route"] == ROUTE_RULE_LAYER
    assert ListingFeedbackAnalyzerV2.classify_issue({"code": "90244"})["route"] == ROUTE_RULE_OR_DATA
    assert ListingFeedbackAnalyzerV2.classify_issue({"code": "100339"})["route"] == ROUTE_CONTENT_LAYER
    assert (
        ListingFeedbackAnalyzerV2.classify_issue(
            {"code": "123", "severity": "WARNING", "message": "minor"}
        )["route"]
        == ROUTE_LOG_ONLY
    )


def test_classify_issue_detects_html_description_without_code():
    triage = ListingFeedbackAnalyzerV2.classify_issue(
        {"code": "99999", "message": "HTML tags are not allowed in product description"}
    )
    assert triage["route"] == ROUTE_CONTENT_LAYER


class FakeSubmissionRepo:
    def __init__(self, submissions):
        self.submissions = submissions

    def list_submissions_with_issue_code(self, product_type, issue_code, limit=100):
        return [
            row
            for row in self.submissions
            if any(
                issue.get("code") == issue_code
                or (
                    issue_code == "WARNING"
                    and str(issue.get("severity") or "").upper() == "WARNING"
                )
                for issue in (row.get("response_body") or {}).get("issues", [])
            )
        ][: int(limit)]


def test_analyze_category_groups_issues_and_omit_suggestions():
    submissions = [
        {
            "id": 1,
            "response_body": {
                "issues": [
                    {
                        "code": "99022",
                        "message": "Value does not match schema",
                        "attributeNames": ["merchant_suggested_asin"],
                    }
                ]
            },
        },
        {
            "id": 2,
            "response_body": {
                "issues": [
                    {
                        "code": "100339",
                        "message": "HTML tags are not allowed",
                        "attributeNames": ["product_description"],
                    }
                ]
            },
        },
    ]
    analyzer = ListingFeedbackAnalyzerV2(
        db=object(),
        submission_repo=FakeSubmissionRepo(submissions),
    )

    report = analyzer.analyze_category("BED_FRAME", limit=10)

    assert report.issue_count == 2
    routes = {group.route for group in report.groups}
    assert ROUTE_RULE_LAYER in routes
    assert ROUTE_CONTENT_LAYER in routes
    assert "merchant_suggested_asin" in report.omit_suggestions
