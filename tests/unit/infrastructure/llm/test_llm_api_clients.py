import json
from http import HTTPStatus
from types import SimpleNamespace

import pytest
import requests

from infrastructure.llm.clients.deepseek_client import DeepSeekAPIClient
from infrastructure.llm.clients.qwen_client import QwenAPIClient


class FakeResponse:
    def __init__(self, payload, raise_error=None):
        self.payload = payload
        self.raise_error = raise_error

    def raise_for_status(self):
        if self.raise_error:
            raise self.raise_error

    def json(self):
        return self.payload


def test_deepseek_client_requires_api_key(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.llm.clients.deepseek_client.settings.DEEPSEEK_API_KEY",
        None,
    )

    with pytest.raises(ValueError, match="未找到DEEPSEEK_API_KEY配置"):
        DeepSeekAPIClient()


def test_deepseek_client_generate_text_response(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.llm.clients.deepseek_client.settings.DEEPSEEK_API_KEY",
        "deepseek-key",
    )
    post_calls = []

    def fake_post(url, json, headers, timeout):
        post_calls.append(
            {"url": url, "json": json, "headers": headers, "timeout": timeout}
        )
        return FakeResponse(
            {
                "choices": [{"message": {"content": "plain text"}}],
                "usage": {"total_tokens": 12},
            }
        )

    monkeypatch.setattr("infrastructure.llm.clients.deepseek_client.requests.post", fake_post)
    client = DeepSeekAPIClient()

    result = client.generate("system", "user", "deepseek-chat", temperature=0.2)

    assert result == {"content": "plain text", "usage": {"total_tokens": 12}}
    assert post_calls[0]["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert post_calls[0]["json"]["response_format"] == {"type": "text"}
    assert post_calls[0]["json"]["temperature"] == 0.2
    assert post_calls[0]["headers"]["Authorization"] == "Bearer deepseek-key"
    assert post_calls[0]["timeout"] == 600


def test_deepseek_client_generate_json_response(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.llm.clients.deepseek_client.settings.DEEPSEEK_API_KEY",
        "deepseek-key",
    )

    def fake_post(*args, **kwargs):
        return FakeResponse(
            {
                "choices": [{"message": {"content": '{"title": "Cabinet"}'}}],
                "usage": {"total_tokens": 8},
            }
        )

    monkeypatch.setattr("infrastructure.llm.clients.deepseek_client.requests.post", fake_post)
    client = DeepSeekAPIClient()

    result = client.generate("system", "user", "deepseek-chat", json_mode=True)

    assert result == {"content": {"title": "Cabinet"}, "usage": {"total_tokens": 8}}


def test_deepseek_client_rejects_empty_content(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.llm.clients.deepseek_client.settings.DEEPSEEK_API_KEY",
        "deepseek-key",
    )

    def fake_post(*args, **kwargs):
        return FakeResponse({"choices": [{"message": {"content": "  "}}]})

    monkeypatch.setattr("infrastructure.llm.clients.deepseek_client.requests.post", fake_post)
    client = DeepSeekAPIClient()

    with pytest.raises(ValueError, match="API返回空内容"):
        client.generate("system", "user", "deepseek-chat")


def test_deepseek_client_wraps_invalid_json_content(monkeypatch, caplog):
    monkeypatch.setattr(
        "infrastructure.llm.clients.deepseek_client.settings.DEEPSEEK_API_KEY",
        "deepseek-key",
    )

    def fake_post(*args, **kwargs):
        return FakeResponse({"choices": [{"message": {"content": "{bad-json"}}]})

    monkeypatch.setattr("infrastructure.llm.clients.deepseek_client.requests.post", fake_post)
    client = DeepSeekAPIClient()
    caplog.set_level("ERROR")

    with pytest.raises(ValueError, match="无效JSON响应"):
        client.generate("system", "user", "deepseek-chat", json_mode=True)
    assert "provider=deepseek" in caplog.text
    assert "content_len=9" in caplog.text
    assert "{bad-json" in caplog.text


def test_deepseek_client_reraises_request_errors(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.llm.clients.deepseek_client.settings.DEEPSEEK_API_KEY",
        "deepseek-key",
    )
    request_error = requests.exceptions.RequestException("network down")

    def fake_post(*args, **kwargs):
        return FakeResponse({}, raise_error=request_error)

    monkeypatch.setattr("infrastructure.llm.clients.deepseek_client.requests.post", fake_post)
    client = DeepSeekAPIClient()

    with pytest.raises(requests.exceptions.RequestException, match="network down"):
        client.generate("system", "user", "deepseek-chat")


def test_qwen_client_requires_api_key(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.llm.clients.qwen_client.settings.DASHSCOPE_API_KEY",
        None,
    )

    with pytest.raises(EnvironmentError, match="请设置DASHSCOPE_API_KEY配置"):
        QwenAPIClient()


def test_qwen_client_generate_text_response(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.llm.clients.qwen_client.settings.DASHSCOPE_API_KEY",
        "dashscope-key",
    )
    call_args = []

    def fake_call(**kwargs):
        call_args.append(kwargs)
        return SimpleNamespace(
            status_code=HTTPStatus.OK,
            output=SimpleNamespace(
                choices=[{"message": {"content": "plain text"}}]
            ),
            usage={"total_tokens": 10},
        )

    monkeypatch.setattr(
        "infrastructure.llm.clients.qwen_client.dashscope.Generation.call",
        fake_call,
    )
    client = QwenAPIClient()

    result = client.generate("system", "user", "qwen-plus", temperature=0.3)

    assert result == {"content": "plain text", "usage": {"total_tokens": 10}}
    assert call_args[0]["model"] == "qwen-plus"
    assert call_args[0]["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]
    assert call_args[0]["result_format"] == "message"
    assert call_args[0]["temperature"] == 0.3


def test_qwen_client_generate_json_response(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.llm.clients.qwen_client.settings.DASHSCOPE_API_KEY",
        "dashscope-key",
    )
    call_args = []

    def fake_call(**kwargs):
        call_args.append(kwargs)
        return SimpleNamespace(
            status_code=HTTPStatus.OK,
            output=SimpleNamespace(
                choices=[{"message": {"content": '{"title": "Cabinet"}'}}]
            ),
        )

    monkeypatch.setattr(
        "infrastructure.llm.clients.qwen_client.dashscope.Generation.call",
        fake_call,
    )
    client = QwenAPIClient()

    assert client.generate("system", "user", "qwen-plus", json_mode=True) == {
        "content": {"title": "Cabinet"},
        "usage": {},
    }
    assert call_args[0]["response_format"] == {"type": "json_object"}
    assert call_args[0]["result_format"] == "message"
    assert call_args[0]["messages"][0] == {
        "role": "system",
        "content": "Return valid JSON only. The output must be a JSON object.",
    }


def test_qwen_client_json_mode_does_not_duplicate_existing_json_instruction(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.llm.clients.qwen_client.settings.DASHSCOPE_API_KEY",
        "dashscope-key",
    )
    call_args = []

    def fake_call(**kwargs):
        call_args.append(kwargs)
        return SimpleNamespace(
            status_code=HTTPStatus.OK,
            output=SimpleNamespace(
                choices=[{"message": {"content": '{"title": "Cabinet"}'}}]
            ),
        )

    monkeypatch.setattr(
        "infrastructure.llm.clients.qwen_client.dashscope.Generation.call",
        fake_call,
    )
    client = QwenAPIClient()

    client.generate("Return JSON only.", "user", "qwen-plus", json_mode=True)

    assert call_args[0]["response_format"] == {"type": "json_object"}
    assert call_args[0]["messages"] == [
        {"role": "system", "content": "Return JSON only."},
        {"role": "user", "content": "user"},
    ]


def test_qwen_client_raises_for_non_ok_response(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.llm.clients.qwen_client.settings.DASHSCOPE_API_KEY",
        "dashscope-key",
    )

    def fake_call(**kwargs):
        return SimpleNamespace(
            status_code=HTTPStatus.BAD_REQUEST,
            code="BadRequest",
            message="invalid",
        )

    monkeypatch.setattr(
        "infrastructure.llm.clients.qwen_client.dashscope.Generation.call",
        fake_call,
    )
    client = QwenAPIClient()

    with pytest.raises(ValueError, match="API错误: BadRequest - invalid"):
        client.generate("system", "user", "qwen-plus")


def test_qwen_client_wraps_invalid_json_content(monkeypatch, caplog):
    monkeypatch.setattr(
        "infrastructure.llm.clients.qwen_client.settings.DASHSCOPE_API_KEY",
        "dashscope-key",
    )

    def fake_call(**kwargs):
        return SimpleNamespace(
            status_code=HTTPStatus.OK,
            output=SimpleNamespace(choices=[{"message": {"content": "{bad-json"}}]),
        )

    monkeypatch.setattr(
        "infrastructure.llm.clients.qwen_client.dashscope.Generation.call",
        fake_call,
    )
    client = QwenAPIClient()
    caplog.set_level("ERROR")

    with pytest.raises(ValueError, match="无效JSON响应"):
        client.generate("system", "user", "qwen-plus", json_mode=True)
    assert "provider=qwen" in caplog.text
    assert "content_len=9" in caplog.text
    assert "{bad-json" in caplog.text


def test_qwen_client_reraises_generation_errors(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.llm.clients.qwen_client.settings.DASHSCOPE_API_KEY",
        "dashscope-key",
    )

    def fake_call(**kwargs):
        raise RuntimeError("dashscope down")

    monkeypatch.setattr(
        "infrastructure.llm.clients.qwen_client.dashscope.Generation.call",
        fake_call,
    )
    client = QwenAPIClient()

    with pytest.raises(RuntimeError, match="dashscope down"):
        client.generate("system", "user", "qwen-plus")
