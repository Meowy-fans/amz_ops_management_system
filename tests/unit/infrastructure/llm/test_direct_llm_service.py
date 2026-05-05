import pytest

from infrastructure.llm.implementations.direct_llm_service import DirectLLMService
from infrastructure.llm.types import LLMRequest


class FakeClient:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _service_with_clients(clients, default_provider="qwen"):
    service = object.__new__(DirectLLMService)
    service.config = {
        "default_provider": default_provider,
        "providers": {
            "qwen": {"default_model": "qwen-plus"},
            "deepseek": {"default_model": "deepseek-chat"},
        },
        "task_routing": {"detail": "deepseek"},
    }
    service.clients = clients
    service.default_provider = default_provider
    return service


def test_direct_llm_service_raises_when_no_clients_can_initialize():
    with pytest.raises(RuntimeError, match="没有可用的LLM客户端"):
        DirectLLMService({"providers": {}})


def test_select_provider_uses_task_routing_or_default_provider():
    service = _service_with_clients({})

    assert service._select_provider("detail") == "deepseek"
    assert service._select_provider("unknown") == "qwen"


def test_generate_routes_to_selected_provider_and_uses_request_model():
    deepseek = FakeClient([{"content": {"title": "Cabinet"}, "usage": {"tokens": 8}}])
    service = _service_with_clients({"deepseek": deepseek, "qwen": FakeClient([])})
    request = LLMRequest(
        task_type="detail",
        system_prompt="system",
        user_prompt="user",
        model="custom-model",
        json_mode=True,
        temperature=0.2,
    )

    response = service.generate(request)

    assert response.content == {"title": "Cabinet"}
    assert response.usage == {"tokens": 8}
    assert response.model == "custom-model"
    assert response.provider == "deepseek"
    assert deepseek.calls == [
        {
            "system_prompt": "system",
            "user_prompt": "user",
            "model": "custom-model",
            "json_mode": True,
            "temperature": 0.2,
        }
    ]


def test_generate_uses_provider_default_model_when_request_model_missing():
    qwen = FakeClient([{"content": "ok"}])
    service = _service_with_clients({"qwen": qwen})
    request = LLMRequest(
        task_type="unknown",
        system_prompt="system",
        user_prompt="user",
    )

    response = service.generate(request)

    assert response.content == "ok"
    assert response.model == "qwen-plus"
    assert response.provider == "qwen"
    assert qwen.calls[0]["model"] == "qwen-plus"


def test_generate_raises_when_selected_provider_is_unavailable():
    service = _service_with_clients({"qwen": FakeClient([])})
    request = LLMRequest(task_type="detail", system_prompt="system", user_prompt="user")

    with pytest.raises(ValueError, match="LLM提供商不可用: deepseek"):
        service.generate(request)


def test_generate_falls_back_to_alternate_provider_when_primary_fails():
    deepseek = FakeClient([RuntimeError("primary down")])
    qwen = FakeClient([{"content": {"title": "Fallback"}, "usage": {"tokens": 3}}])
    service = _service_with_clients({"deepseek": deepseek, "qwen": qwen})
    request = LLMRequest(
        task_type="detail",
        system_prompt="system",
        user_prompt="user",
        json_mode=True,
        temperature=0.4,
    )

    response = service.generate(request)

    assert response.content == {"title": "Fallback"}
    assert response.usage == {"tokens": 3}
    assert response.model == "qwen-plus"
    assert response.provider == "qwen"
    assert qwen.calls[0]["json_mode"] is True


def test_generate_reraises_when_primary_fails_and_no_fallback_available():
    qwen = FakeClient([RuntimeError("qwen down")])
    service = _service_with_clients({"qwen": qwen})
    request = LLMRequest(task_type="unknown", system_prompt="system", user_prompt="user")

    with pytest.raises(RuntimeError, match="qwen down"):
        service.generate(request)


def test_fallback_generate_uses_fallback_provider_default_model():
    deepseek = FakeClient([{"content": "fallback"}])
    service = _service_with_clients({"deepseek": deepseek})
    request = LLMRequest(
        task_type="unknown",
        system_prompt="system",
        user_prompt="user",
        json_mode=False,
        temperature=0.6,
    )

    response = service._fallback_generate(request, "deepseek")

    assert response.content == "fallback"
    assert response.model == "deepseek-chat"
    assert response.provider == "deepseek"
    assert deepseek.calls[0]["model"] == "deepseek-chat"


def test_health_check_returns_true_after_first_healthy_client():
    qwen = FakeClient([{"content": "OK"}])
    service = _service_with_clients({"qwen": qwen})

    assert service.health_check() is True
    assert qwen.calls[0]["user_prompt"] == "Say OK"
    assert qwen.calls[0]["temperature"] == 0.1


def test_health_check_returns_false_when_all_clients_fail_or_return_empty():
    qwen = FakeClient([RuntimeError("down")])
    deepseek = FakeClient([{"content": ""}])
    service = _service_with_clients({"qwen": qwen, "deepseek": deepseek})

    assert service.health_check() is False
