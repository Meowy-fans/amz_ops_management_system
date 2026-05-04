"""LLM enrichment helpers for Amazon data mapping."""
import json
import logging
from typing import Any, Callable, Dict, List

from infrastructure.llm import LLMRequest

logger = logging.getLogger(__name__)


def enrich_product_attributes(
    product_data: Dict[str, Any],
    llm_tasks: List[Dict],
    template_rules: Dict,
    llm_service,
    strip_html: Callable[[str | None], str],
) -> Dict[str, Any]:
    """Use LLM to enrich product attributes for Amazon template fields."""
    raw_data = product_data.get("raw_data", {}) or {}

    product_profile = {
        "name": product_data.get("product_name"),
        "description": strip_html(
            product_data.get("product_description") or raw_data.get("description")
        ),
        "attributes": raw_data.get("attributes", {}),
        "characteristics": raw_data.get("characteristics", []),
        "dimensions_and_weight": {
            "assembledLength": raw_data.get("assembledLength"),
            "assembledWidth": raw_data.get("assembledWidth"),
            "assembledHeight": raw_data.get("assembledHeight"),
        },
    }

    valid_values_map = {
        str(item.get("attribute")).strip().lower(): item.get("values", [])
        for item in template_rules.get("valid_values", [])
        if item.get("attribute")
    }

    processed_tasks = []
    for task in llm_tasks:
        field_name = task.get("field_name")
        normalized_field_name = str(field_name).strip().lower()

        if normalized_field_name in valid_values_map:
            task["valid_options"] = valid_values_map[normalized_field_name]

        processed_tasks.append(task)

    user_content_data = {
        "product_profile": product_profile,
        "tasks": processed_tasks,
    }
    user_content_str = json.dumps(user_content_data, indent=2, ensure_ascii=False)

    from src.utils.prompt_manager import PromptManager

    prompt_manager = PromptManager()
    system_prompt = prompt_manager.get_prompt("prod_attribute_enrichment")

    if not system_prompt:
        logger.error("未找到 prod_attribute_enrichment Prompt")
        return {}

    try:
        request = LLMRequest(
            task_type="product_attribute_enrichment",
            system_prompt=system_prompt,
            user_prompt=user_content_str,
            json_mode=True,
            temperature=0.7,
        )

        response = llm_service.generate(request)
        llm_result = response.content

        logger.info(f"LLM成功生成 {len(llm_result)} 个增强字段")
        return llm_result

    except Exception as e:
        logger.error(f"调用LLM失败: {e}", exc_info=True)
        return {}
