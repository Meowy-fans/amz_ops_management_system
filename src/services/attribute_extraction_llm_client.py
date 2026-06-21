"""LLM client adapter for evidence-bound attribute extraction."""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from infrastructure.llm.types import LLMRequest


class AttributeExtractionLLMClient:
    """Adapts the shared LLM service to LLMAttributeExtractor's protocol."""

    def __init__(self, llm_service: Any = None):
        self._llm_service = llm_service

    def extract_attribute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        llm = self._llm_service or self._get_llm_service()
        response = llm.generate(
            LLMRequest(
                task_type="product_attribute_extraction",
                system_prompt=self._system_prompt(),
                user_prompt=self._user_prompt(context),
                json_mode=True,
                temperature=0.0,
            )
        )
        raw = response.content if hasattr(response, "content") else response
        if isinstance(raw, dict):
            return raw
        return self._parse_json(str(raw or ""))

    @staticmethod
    def _get_llm_service():
        from infrastructure.llm.factory import get_llm_service

        return get_llm_service()

    @staticmethod
    def _system_prompt() -> str:
        try:
            from src.utils.prompt_manager import PromptManager

            prompt = PromptManager().get_prompt("product_attribute_extraction")
            if prompt:
                return prompt
        except Exception:
            pass
        return (
            "You extract one Amazon listing attribute from product facts. "
            "Return only JSON with value, evidence, and confidence. "
            "Return null value when source evidence is absent."
        )

    @staticmethod
    def _user_prompt(context: Dict[str, Any]) -> str:
        output_contract = {
            "value": "string | number | boolean | object | null",
            "evidence": "short exact source phrase, empty when value is null",
            "confidence": "low | medium",
        }
        return (
            "Extract only the requested attribute from the supplied product facts.\n"
            "Rules:\n"
            "- Do not invent values.\n"
            "- Use null when the text does not explicitly support a value.\n"
            "- Evidence must quote or closely paraphrase the source fact.\n"
            "- If enum_locked is true, value must be one of valid_values exactly.\n\n"
            f"CONTEXT:\n{json.dumps(context, ensure_ascii=False)}\n\n"
            f"OUTPUT_CONTRACT:\n{json.dumps(output_contract, ensure_ascii=False)}"
        )

    @staticmethod
    def _parse_json(raw_text: str) -> Dict[str, Any]:
        text = str(raw_text or "").strip()
        if not text:
            return {}
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
