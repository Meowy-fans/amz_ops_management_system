"""Shared scanner and sanitizer for pesticide/antimicrobial claim compliance."""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Order matters: longer phrases before shorter ones.
PESTICIDE_CLAIM_PATTERNS: List[str] = [
    r"\banti[-\s]?bacterial\b",
    r"\banti[-\s]?microbial\b",
    r"\bantimicrobial\b",
    r"\bbacteria\s+buildup\b",
    r"\bbacteria(?:l)?\b",
    r"\bgerms?\b",
    r"\bdisinfect\w*\b",
    r"\bsanitiz\w*\b",
    r"\bvirus(?:es)?\b",
    r"\banti[-\s]?mold\b",
    r"\bmold\s+and\s+mildew\b",
    r"\binhibit(?:s)?\s+mold\b",
    r"\bmildew\b",
    r"\bmold\b",
    r"\bpesticid\w*\b",
    r"\binsect(?:s)?\b",
]

_COMPILED_PATTERNS = [
    (pattern, re.compile(pattern, re.IGNORECASE))
    for pattern in PESTICIDE_CLAIM_PATTERNS
]

_REPLACEMENT_RULES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bbacteria\s+buildup\b", re.IGNORECASE), "soap residue and water spots"),
    (re.compile(r"\bmold\s+and\s+mildew\b", re.IGNORECASE), "moisture in humid bathrooms"),
    (re.compile(r"\binhibit(?:s)?\s+mold(?:\s+and\s+mildew)?(?:\s+growth)?\b", re.IGNORECASE),
     "help reduce moisture pooling"),
    (re.compile(r"\banti[-\s]?bacterial\b", re.IGNORECASE), "easy-to-clean"),
    (re.compile(r"\banti[-\s]?microbial\b", re.IGNORECASE), "easy-to-clean"),
    (re.compile(r"\bantimicrobial\b", re.IGNORECASE), "easy-to-clean"),
    (re.compile(r"\banti[-\s]?mold\b", re.IGNORECASE), "moisture-resistant"),
    (re.compile(r"\bdisinfect\w*\b", re.IGNORECASE), "easy to clean"),
    (re.compile(r"\bsanitiz\w*\b", re.IGNORECASE), "easy to clean"),
    (re.compile(r"\bgerms?\b", re.IGNORECASE), "everyday grime"),
    (re.compile(r"\bvirus(?:es)?\b", re.IGNORECASE), "everyday grime"),
    (re.compile(r"\bpesticid\w*\b", re.IGNORECASE), ""),
    (re.compile(r"\binsect(?:s)?\b", re.IGNORECASE), ""),
    (re.compile(r"\bbacteria(?:l)?\b", re.IGNORECASE), "everyday stains"),
    (re.compile(r"\bmildew\b", re.IGNORECASE), "moisture"),
    (re.compile(r"\bmold\b", re.IGNORECASE), "moisture"),
]


@dataclass
class ClaimHit:
    pattern: str
    matched_text: str
    field: str
    start: int = 0
    end: int = 0


@dataclass
class ComplianceFix:
    field: str
    pattern: str
    matched_text: str
    replacement: str
    before: str
    after: str


@dataclass
class ComplianceScanResult:
    hits: List[ClaimHit] = field(default_factory=list)
    fixes: List[ComplianceFix] = field(default_factory=list)
    sanitized_fields: Dict[str, str] = field(default_factory=dict)
    clean: bool = True


class ComplianceClaimScanner:
    """Detect and sanitize Amazon pesticide/device claim risks in listing text."""

    def scan_text(self, text: str, field: str = "combined") -> List[ClaimHit]:
        hits: List[ClaimHit] = []
        if not text:
            return hits
        for pattern, compiled in _COMPILED_PATTERNS:
            for match in compiled.finditer(text):
                hits.append(
                    ClaimHit(
                        pattern=pattern,
                        matched_text=match.group(),
                        field=field,
                        start=match.start(),
                        end=match.end(),
                    )
                )
        return hits

    def scan_fields(self, fields: Dict[str, str]) -> List[ClaimHit]:
        hits: List[ClaimHit] = []
        for field_name, value in fields.items():
            hits.extend(self.scan_text(value or "", field_name))
        return hits

    def sanitize_text(self, text: str) -> Tuple[str, List[ComplianceFix]]:
        if not text:
            return text, []
        fixes: List[ComplianceFix] = []
        sanitized = text
        for pattern, replacement in _REPLACEMENT_RULES:
            while True:
                match = pattern.search(sanitized)
                if not match:
                    break
                before = sanitized
                sanitized = (
                    sanitized[: match.start()]
                    + replacement
                    + sanitized[match.end() :]
                )
                fixes.append(
                    ComplianceFix(
                        field="",
                        pattern=pattern.pattern,
                        matched_text=match.group(),
                        replacement=replacement,
                        before=before,
                        after=sanitized,
                    )
                )
        sanitized = re.sub(r"\s{2,}", " ", sanitized)
        sanitized = re.sub(r"\s+,", ",", sanitized)
        return sanitized.strip(), fixes

    def sanitize_fields(
        self, fields: Dict[str, str]
    ) -> Tuple[Dict[str, str], List[ComplianceFix]]:
        sanitized_fields: Dict[str, str] = {}
        all_fixes: List[ComplianceFix] = []
        for field_name, value in fields.items():
            cleaned, fixes = self.sanitize_text(value or "")
            sanitized_fields[field_name] = cleaned
            for fix in fixes:
                fix.field = field_name
                all_fixes.append(fix)
        return sanitized_fields, all_fixes

    def scan_and_sanitize(self, fields: Dict[str, str]) -> ComplianceScanResult:
        hits = self.scan_fields(fields)
        sanitized_fields, fixes = self.sanitize_fields(fields)
        remaining = self.scan_fields(sanitized_fields)
        return ComplianceScanResult(
            hits=hits,
            fixes=fixes,
            sanitized_fields=sanitized_fields,
            clean=not remaining,
        )

    @staticmethod
    def content_fields_from_enriched(content: Any) -> Dict[str, str]:
        """Build field map from EnrichedProductContent-like object."""
        return {
            "title": getattr(content, "title", "") or "",
            "bullet_1": getattr(content, "bullet_1", "") or "",
            "bullet_2": getattr(content, "bullet_2", "") or "",
            "bullet_3": getattr(content, "bullet_3", "") or "",
            "bullet_4": getattr(content, "bullet_4", "") or "",
            "bullet_5": getattr(content, "bullet_5", "") or "",
            "description": getattr(content, "description", "") or "",
            "search_terms": getattr(content, "search_terms", "") or "",
            "generic_keyword": getattr(content, "generic_keyword", "") or "",
        }

    @staticmethod
    def apply_fields_to_enriched(content: Any, fields: Dict[str, str]) -> None:
        content.title = fields.get("title", content.title)
        content.bullet_1 = fields.get("bullet_1", content.bullet_1)
        content.bullet_2 = fields.get("bullet_2", content.bullet_2)
        content.bullet_3 = fields.get("bullet_3", content.bullet_3)
        content.bullet_4 = fields.get("bullet_4", content.bullet_4)
        content.bullet_5 = fields.get("bullet_5", content.bullet_5)
        content.description = fields.get("description", content.description)
        content.search_terms = fields.get("search_terms", content.search_terms)
        content.generic_keyword = fields.get("generic_keyword", content.generic_keyword)

    @staticmethod
    def sanitize_supplier_text(text: str) -> str:
        """Light cleanup for Giga source text before LLM prompt injection."""
        if not text:
            return text
        scanner = ComplianceClaimScanner()
        cleaned, _ = scanner.sanitize_text(text)
        return cleaned
