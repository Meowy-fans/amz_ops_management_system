"""Valid-value alignment helpers for Amazon data mapping."""
import difflib
import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    normalized = str(text)
    normalized = unicodedata.normalize("NFKC", normalized)
    normalized = normalized.casefold()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = normalized.replace("-", " ")
    normalized = normalized.replace("_", " ")
    normalized = normalized.replace("  ", " ")
    return normalized


def fuzzy_select(value: str, candidates: List[str], cutoff: float = 0.9) -> Optional[str]:
    norm_candidates = {
        normalize_text(candidate): candidate
        for candidate in candidates
    }
    norm_value = normalize_text(value)
    matches = difflib.get_close_matches(
        norm_value,
        list(norm_candidates.keys()),
        n=1,
        cutoff=cutoff,
    )
    if matches:
        return norm_candidates[matches[0]]
    return None


def align_to_valid_values(
    mapped_data: Dict[str, Any],
    template_rules: Dict[str, Any],
) -> Dict[str, Any]:
    """Align mapped string values to Amazon template valid values."""
    if not template_rules:
        return mapped_data

    try:
        valid_values = template_rules.get("valid_values", [])
        attr_to_values = {
            str(item.get("attribute")).strip(): item.get("values", [])
            for item in valid_values
            if item.get("attribute")
        }

        for field_name, value in list(mapped_data.items()):
            candidates = attr_to_values.get(field_name)
            if not candidates or value is None or isinstance(value, list):
                continue
            if not isinstance(value, str) or value in candidates:
                continue

            norm_val = normalize_text(value)
            exact = next(
                (
                    candidate
                    for candidate in candidates
                    if normalize_text(str(candidate)) == norm_val
                ),
                None,
            )
            if exact is not None:
                mapped_data[field_name] = exact
                continue

            match = fuzzy_select(value, candidates, cutoff=0.9)
            if match is not None:
                mapped_data[field_name] = match
    except Exception as exc:
        logger.warning(f"有效值对齐失败: {exc}")

    return mapped_data
