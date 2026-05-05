import re

import pytest

from infrastructure.llm.implementations.autogen_llm_service import AutoGenLLMService
from infrastructure.llm.types import LLMRequest


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self.payload = payload or {}
        self.text = text

    def json(self):
        return self.payload


@pytest.fixture
def autogen_settings(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.llm.implementations.autogen_llm_service.settings.AUTOGEN_BASE_URL",
        "http://autogen.local",
    )
    monkeypatch.setattr(
        "infrastructure.llm.implementations.autogen_llm_service.settings.AUTOGEN_TIMEOUT_SECONDS",
        20,
    )
    monkeypatch.setattr(
        "infrastructure.llm.implementations.autogen_llm_service.settings.AUTOGEN_GLOBAL_MAX_ROUNDS",
        5,
    )
    monkeypatch.setattr(
        "infrastructure.llm.implementations.autogen_llm_service.settings.AUTOGEN_TERMINATION_KEYWORD",
        "DONE",
    )
    monkeypatch.setattr(
        "infrastructure.llm.implementations.autogen_llm_service.settings.AUTOGEN_FALLBACK_MODEL",
        "qwen-fallback",
    )
    monkeypatch.setattr(
        "infrastructure.llm.implementations.autogen_llm_service.settings.QWEN_MODEL",
        "qwen-default",
    )


def test_generate_posts_payload_and_parses_json_final_message(monkeypatch, autogen_settings):
    calls = []

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse(
            payload={
                "session_id": "session-1",
                "metadata": {"trace": "t1"},
                "final_message": '{"title": "Cabinet"}',
            }
        )

    monkeypatch.setattr(
        "infrastructure.llm.implementations.autogen_llm_service.requests.post",
        fake_post,
    )
    service = AutoGenLLMService()
    request = LLMRequest(
        task_type="detail",
        system_prompt="system",
        user_prompt="user",
        model="qwen-main",
        metadata={
            "session_id": "session-1",
            "output_schema": {"type": "object"},
        },
    )

    response = service.generate(request)

    payload = calls[0]["json"]["request"]
    assert response.content == {"title": "Cabinet"}
    assert response.model == "qwen-main"
    assert response.provider == "autogen"
    assert response.metadata == {
        "session_id": "session-1",
        "metadata": {"trace": "t1"},
    }
    assert calls[0]["url"] == "http://autogen.local/v1/autogen/execute"
    assert calls[0]["timeout"] == 20
    assert payload["session_id"] == "session-1"
    assert payload["task"] == "user"
    assert payload["agents"][0]["system_message"] == "system"
    assert payload["agents"][0]["llm_config"]["model_name"] == "qwen-main"
    assert payload["agents"][0]["output_schema"] == {"type": "object"}
    assert payload["workflow"] == {
        "type": "sequential",
        "agent_names": ["Worker"],
        "global_max_rounds": 5,
        "termination_keyword": "DONE",
    }


def test_generate_uses_default_model_and_generated_session_id(monkeypatch, autogen_settings):
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json["request"])
        return FakeResponse(payload={"final_message": "plain text"})

    monkeypatch.setattr(
        "infrastructure.llm.implementations.autogen_llm_service.requests.post",
        fake_post,
    )
    service = AutoGenLLMService()

    response = service.generate(
        LLMRequest(task_type="mapping", system_prompt="system", user_prompt="user")
    )

    assert response.content == "plain text"
    assert response.model == "qwen-default"
    assert re.fullmatch(r"mapping-[0-9a-f]{12}", calls[0]["session_id"])


def test_generate_falls_back_to_configured_model_after_primary_failure(
    monkeypatch,
    autogen_settings,
):
    calls = []
    responses = [
        FakeResponse(status_code=429, text="rate limited"),
        FakeResponse(payload={"final_message": {"ok": True}}),
    ]

    def fake_post(url, json, timeout):
        calls.append(json["request"]["agents"][0]["llm_config"]["model_name"])
        return responses.pop(0)

    monkeypatch.setattr(
        "infrastructure.llm.implementations.autogen_llm_service.requests.post",
        fake_post,
    )
    service = AutoGenLLMService()

    response = service.generate(
        LLMRequest(
            task_type="detail",
            system_prompt="system",
            user_prompt="user",
            model="qwen-main",
        )
    )

    assert response.content == {"ok": True}
    assert response.model == "qwen-fallback"
    assert calls == ["qwen-main", "qwen-fallback"]


def test_generate_reraises_original_error_when_fallback_fails(
    monkeypatch,
    autogen_settings,
):
    responses = [
        FakeResponse(status_code=429, text="rate limited"),
        FakeResponse(status_code=500, text="fallback failed"),
    ]

    def fake_post(url, json, timeout):
        return responses.pop(0)

    monkeypatch.setattr(
        "infrastructure.llm.implementations.autogen_llm_service.requests.post",
        fake_post,
    )
    service = AutoGenLLMService()

    with pytest.raises(RuntimeError, match="upstream_error_429"):
        service.generate(
            LLMRequest(
                task_type="detail",
                system_prompt="system",
                user_prompt="user",
                model="qwen-main",
            )
        )


def test_generate_reraises_when_no_fallback_model(monkeypatch, autogen_settings):
    monkeypatch.setattr(
        "infrastructure.llm.implementations.autogen_llm_service.settings.AUTOGEN_FALLBACK_MODEL",
        None,
    )

    def fake_post(url, json, timeout):
        return FakeResponse(status_code=500, text="down")

    monkeypatch.setattr(
        "infrastructure.llm.implementations.autogen_llm_service.requests.post",
        fake_post,
    )
    service = AutoGenLLMService()

    with pytest.raises(RuntimeError, match="upstream_error_500:down"):
        service.generate(
            LLMRequest(task_type="detail", system_prompt="system", user_prompt="user")
        )


def test_health_check_returns_true_for_ok_status(monkeypatch, autogen_settings):
    def fake_get(url, timeout):
        assert url == "http://autogen.local/"
        assert timeout == 10
        return FakeResponse(payload={"status": "ok"})

    monkeypatch.setattr(
        "infrastructure.llm.implementations.autogen_llm_service.requests.get",
        fake_get,
    )
    service = AutoGenLLMService()

    assert service.health_check() is True


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(status_code=503, payload={"status": "ok"}),
        FakeResponse(status_code=200, payload={"status": "down"}),
    ],
)
def test_health_check_returns_false_for_unhealthy_responses(
    monkeypatch,
    autogen_settings,
    response,
):
    monkeypatch.setattr(
        "infrastructure.llm.implementations.autogen_llm_service.requests.get",
        lambda url, timeout: response,
    )
    service = AutoGenLLMService()

    assert service.health_check() is False


def test_health_check_returns_false_for_request_errors(monkeypatch, autogen_settings):
    def fake_get(url, timeout):
        raise RuntimeError("down")

    monkeypatch.setattr(
        "infrastructure.llm.implementations.autogen_llm_service.requests.get",
        fake_get,
    )
    service = AutoGenLLMService()

    assert service.health_check() is False


def test_parse_final_message_returns_dict_string_or_raw_value(autogen_settings):
    service = AutoGenLLMService()

    assert service._parse_final_message({"ok": True}) == {"ok": True}
    assert service._parse_final_message('{"ok": true}') == {"ok": True}
    assert service._parse_final_message("plain") == "plain"
    assert service._parse_final_message(["raw"]) == ["raw"]


def test_raise_for_status_contract(autogen_settings):
    service = AutoGenLLMService()

    assert service._raise_for_status(FakeResponse(status_code=204)) is None
    with pytest.raises(RuntimeError, match="upstream_error_408"):
        service._raise_for_status(FakeResponse(status_code=408))
    with pytest.raises(RuntimeError, match="upstream_error_500:server failed"):
        service._raise_for_status(FakeResponse(status_code=500, text="server failed"))


def test_fallback_model_returns_none_when_missing_or_same(monkeypatch, autogen_settings):
    service = AutoGenLLMService()
    assert service._fallback_model("qwen-fallback") is None

    monkeypatch.setattr(
        "infrastructure.llm.implementations.autogen_llm_service.settings.AUTOGEN_FALLBACK_MODEL",
        "",
    )
    service = AutoGenLLMService()
    assert service._fallback_model("qwen-main") is None
