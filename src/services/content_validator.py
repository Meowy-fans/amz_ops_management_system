"""Content validation for LLM-generated Amazon listings."""
import re
from typing import List

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

_PESTICIDE_CLAIM_PATTERNS = [
    r"\banti[-\s]?bacterial\b",
    r"\banti[-\s]?microbial\b",
    r"\bantimicrobial\b",
    r"\bbacteria(?:l)?\b",
    r"\bgerms?\b",
    r"\bdisinfect\w*\b",
    r"\bsanitiz\w*\b",
    r"\bvirus(?:es)?\b",
    r"\banti[-\s]?mold\b",
    r"\bmildew\b",
    r"\bpesticid\w*\b",
    r"\binsect(?:s)?\b",
]


def validate_content(
    title: str = "",
    bullets: List[str] = None,
    description: str = "",
    search_terms: str = "",
) -> List[str]:
    """Validate generated content against Amazon style rules.

    Returns a list of warning strings (empty = no issues).
    """
    warnings: List[str] = []
    bullets = bullets or []

    # Length checks
    if len(title) > 200:
        warnings.append(f"Title too long ({len(title)}/200 chars)")
    for i, b in enumerate(bullets, 1):
        if len(b) > 500:
            warnings.append(f"Bullet {i} too long ({len(b)}/500 chars)")
    if len(description) > 2000:
        warnings.append(f"Description too long ({len(description)}/2000 chars)")
    if len(search_terms) > 250:
        warnings.append(f"Search terms too long ({len(search_terms)}/250 chars)")

    # Prohibited words
    combined = " ".join([title, description, search_terms, *bullets])
    for pattern in _PROHIBITED:
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            warnings.append(f"Prohibited pattern '{match.group()}' found")

    for pattern in _PESTICIDE_CLAIM_PATTERNS:
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            warnings.append(
                f"Potential pesticide/device claim '{match.group()}' found"
            )

    # HTML safety
    if description and _UNSAFE_HTML.search(description):
        warnings.append("Unsafe HTML tags in description (only <b> and <br/> allowed)")

    # ALL CAPS
    if title and title.isupper():
        warnings.append("Title is ALL CAPS")

    return warnings
