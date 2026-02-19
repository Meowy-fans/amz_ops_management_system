import json
import uuid
import logging
import requests
from typing import Dict, Any, Optional
from src.config.settings import settings
from infrastructure.llm.interface import LLMServiceInterface
from infrastructure.llm.types import LLMRequest, LLMResponse

logger = logging.getLogger(__name__)

class AutoGenLLMService(LLMServiceInterface):
    def __init__(self):
        self.base_url = settings.AUTOGEN_BASE_URL
        self.timeout = settings.AUTOGEN_TIMEOUT_SECONDS
        self.global_max_rounds = settings.AUTOGEN_GLOBAL_MAX_ROUNDS
        self.termination_keyword = settings.AUTOGEN_TERMINATION_KEYWORD
        self.fallback_model = settings.AUTOGEN_FALLBACK_MODEL

    def generate(self, request: LLMRequest) -> LLMResponse:
        session_id = self._get_session_id(request)
        model_name = request.model if request.model else self._default_model()
        payload = self._build_payload(session_id=session_id, system_message=request.system_prompt, task=request.user_prompt, model_name=model_name, output_schema=request.metadata.get("output_schema"), rounds=self.global_max_rounds, termination=self.termination_keyword)
        url = f"{self.base_url}/v1/autogen/execute"

        try:
            resp = requests.post(url, json={"request": payload}, timeout=self.timeout)
            self._raise_for_status(resp)
            data = resp.json()
            content = self._parse_final_message(data.get("final_message"))
            return LLMResponse(content=content, usage=None, model=model_name, provider="autogen", metadata={"session_id": data.get("session_id"), "metadata": data.get("metadata")})
        except Exception as e:
            fallback_model = self._fallback_model(model_name)
            if fallback_model and fallback_model != model_name:
                try:
                    payload["agents"][0]["llm_config"]["model_name"] = fallback_model
                    resp = requests.post(url, json={"request": payload}, timeout=self.timeout)
                    self._raise_for_status(resp)
                    data = resp.json()
                    content = self._parse_final_message(data.get("final_message"))
                    return LLMResponse(content=content, usage=None, model=fallback_model, provider="autogen", metadata={"session_id": data.get("session_id"), "metadata": data.get("metadata")})
                except Exception:
                    raise e
            raise e

    def health_check(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/", timeout=min(self.timeout, 10))
            if resp.status_code == 200:
                j = resp.json()
                return j.get("status") == "ok"
            return False
        except Exception:
            return False

    def _build_payload(self, session_id: str, system_message: str, task: str, model_name: str, output_schema: Optional[Dict], rounds: int, termination: str) -> Dict[str, Any]:
        agent = {"name": "Worker", "system_message": system_message, "llm_config": {"model_name": model_name, "extra_config": {}}}
        if output_schema:
            agent["output_schema"] = output_schema
        workflow = {"type": "sequential", "agent_names": ["Worker"], "global_max_rounds": rounds, "termination_keyword": termination}
        return {"session_id": session_id, "task": task, "agents": [agent], "workflow": workflow}

    def _parse_final_message(self, final_message: Any) -> Any:
        if isinstance(final_message, dict):
            return final_message
        if isinstance(final_message, str):
            s = final_message.strip()
            try:
                return json.loads(s)
            except Exception:
                return s
        return final_message

    def _get_session_id(self, request: LLMRequest) -> str:
        sid = None
        meta = request.metadata or {}
        sid = meta.get("session_id")
        return sid if sid else f"{request.task_type}-{uuid.uuid4().hex[:12]}"

    def _default_model(self) -> str:
        return settings.QWEN_MODEL

    def _raise_for_status(self, resp: requests.Response):
        if 200 <= resp.status_code < 300:
            return
        if resp.status_code in (429, 408):
            raise RuntimeError(f"upstream_error_{resp.status_code}")
        try:
            msg = resp.text
        except Exception:
            msg = ""
        raise RuntimeError(f"upstream_error_{resp.status_code}:{msg}")

    def _fallback_model(self, model_name: str) -> Optional[str]:
        fm = self.fallback_model
        if not fm:
            return None
        if fm == model_name:
            return None
        return fm

