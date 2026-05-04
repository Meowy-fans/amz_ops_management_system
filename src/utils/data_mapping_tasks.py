"""Task extraction helpers for data mapping."""
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


def collect_llm_tasks_from_mapping(
    mapping_config: Dict,
    template_rules: Dict,
) -> List[Dict]:
    """Extract LLM-enhanced field tasks with optional valid-value constraints."""
    llm_tasks = []

    valid_values_map = {}
    for item in template_rules.get("valid_values", []):
        attr = item.get("attribute")
        if attr:
            normalized_key = str(attr).strip().lower()
            valid_values_map[normalized_key] = item.get("values", [])

    for field_name, rule in mapping_config.items():
        if rule.get("source_type") == "llm_enhanced":
            task = {
                "field_name": field_name,
                "description": rule.get("description", ""),
                "output_type": rule.get("output_type", "string"),
            }

            normalized_field = str(field_name).strip().lower()
            if normalized_field in valid_values_map:
                task["valid_options"] = valid_values_map[normalized_field]

            llm_tasks.append(task)

    logger.debug(f"提取 {len(llm_tasks)} 个LLM任务")
    return llm_tasks
