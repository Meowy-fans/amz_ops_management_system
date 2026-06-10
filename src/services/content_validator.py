"""Content validation for LLM-generated Amazon listings."""
import re
from dataclasses import dataclass, field
from typing import List

from src.services.compliance_claim_scanner import ComplianceClaimScanner

# Prohibited word patterns (Amazon style rules)
_PROHIBITED = [
    r"\b(best|#1|amazing|incredible|top-rated|unbeatable|greatest)\b",
    r"\b(cheap|affordable|free shipping|on sale|discount|bargain)\b",
    r"\b(limited time|while supplies last|hurry|act now|don't miss)\b",
    r"\b(we\s|our\s|\bI\s|\bus\s)",
    r"https?://",
    r"[\w.-]+@[\w.-]+",
    r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
]

_UNSAFE_HTML = re.compile(r"<(?!b>|/b>|br\s*/?>)[a-zA-Z][^>]*>", re.IGNORECASE)


@dataclass
class ValidationResult:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def all_messages(self) -> List[str]:
        return [*self.errors, *self.warnings]


def validate_content(
    title: str = "",
    bullets: List[str] = None,
    description: str = "",
    search_terms: str = "",
) -> ValidationResult:
    """Validate generated content against Amazon style and compliance rules."""
    result = ValidationResult()
    bullets = bullets or []
    scanner = ComplianceClaimScanner()

    # Length checks
    if len(title) > 200:
        result.warnings.append(f"Title too long ({len(title)}/200 chars)")
    for i, b in enumerate(bullets, 1):
        if len(b) > 500:
            result.warnings.append(f"Bullet {i} too long ({len(b)}/500 chars)")
    if len(description) > 2000:
        result.warnings.append(f"Description too long ({len(description)}/2000 chars)")
    if len(search_terms) > 250:
        result.warnings.append(f"Search terms too long ({len(search_terms)}/250 chars)")

    field_map = {
        "title": title,
        "description": description,
        "search_terms": search_terms,
        "generic_keyword": "",
    }
    for index, bullet in enumerate(bullets, 1):
        field_map[f"bullet_{index}"] = bullet

    claim_hits = scanner.scan_fields(field_map)
    for hit in claim_hits:
        result.errors.append(
            "Potential pesticide/device claim "
            f"'{hit.matched_text}' found in {hit.field}"
        )

    # Prohibited words
    combined = " ".join([title, description, search_terms, *bullets])
    for pattern in _PROHIBITED:
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            result.warnings.append(f"Prohibited pattern '{match.group()}' found")

    # HTML safety
    if description and _UNSAFE_HTML.search(description):
        result.warnings.append("Unsafe HTML tags in description (only <b> and <br/> allowed)")

    # ALL CAPS
    if title and title.isupper():
        result.warnings.append("Title is ALL CAPS")

    return result
