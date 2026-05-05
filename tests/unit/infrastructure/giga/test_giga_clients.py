import json
import time

import pytest
import requests

from infrastructure.giga.api_client import GigaAPIClient, GigaAPIException
from infrastructure.giga.config import GigaConfig
from infrastructure.giga.token_manager import GigaTokenManager


class FakeResponse:
    def __init__(
        self,
        status_code=200,
        payload=None,
        headers=None,
        text="response-text",
        raise_error=None,
        json_error=None,
    ):
        self.status_code = status_code
        self.payload = payload or {}
        self.headers = headers or {"x-request-id": "req-1"}
        self.text = text
        self.raise_error = raise_error
        self.json_error = json_error

    def raise_for_status(self):
        if self.raise_error:
            raise self.raise_error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


class FakeTokenManager:
    def __init__(self):
        self.force_refresh_count = 0

    def get_token(self):
        return {"token_type": "Bearer", "access_token": "old-token"}

    def force_refresh(self):
        self.force_refresh_count += 1
        return {"token_type": "Bearer", "access_token": "new-token"}


@pytest.fixture(autouse=True)
def reset_giga_token_manager():
    original_instance = GigaTokenManager._instance
    original_cache = GigaTokenManager._token_cache.copy()
    GigaTokenManager._instance = None
    GigaTokenManager._token_cache = {"token_data": None, "expires_at": 0}
    yield
    GigaTokenManager._instance = original_instance
    GigaTokenManager._token_cache = original_cache


def _api_client(token_manager=None, max_retries=0):
    client = object.__new__(GigaAPIClient)
    client.token_manager = token_manager or FakeTokenManager()
    client.max_retries = max_retries
    return client


def test_giga_config_validate_accepts_credentials(monkeypatch):
    monkeypatch.setattr(GigaConfig, "CLIENT_ID", "client")
    monkeypatch.setattr(GigaConfig, "CLIENT_SECRET", "secret")

    assert GigaConfig.validate() is True


def test_giga_config_validate_rejects_missing_credentials(monkeypatch):
    monkeypatch.setattr(GigaConfig, "CLIENT_ID", "")
    monkeypatch.setattr(GigaConfig, "CLIENT_SECRET", "secret")

    with pytest.raises(ValueError, match="Giga API凭证未配置"):
        GigaConfig.validate()


def test_giga_config_get_endpoint_url_returns_full_url(monkeypatch):
    monkeypatch.setattr(GigaConfig, "BASE_URL", "https://giga.example")

    assert (
        GigaConfig.get_endpoint_url("product_list")
        == "https://giga.example/api-b2b-v1/product/skus"
    )


def test_giga_config_get_endpoint_url_rejects_unknown_endpoint():
    with pytest.raises(ValueError, match="未知端点: unknown"):
        GigaConfig.get_endpoint_url("unknown")


def test_token_manager_returns_cached_token_when_still_valid():
    manager = GigaTokenManager()
    manager._token_cache = {
        "token_data": {"access_token": "cached"},
        "expires_at": time.time() + 1000,
    }

    assert manager.get_token() == {"access_token": "cached"}


def test_token_manager_refreshes_token_and_updates_cache(monkeypatch):
    monkeypatch.setattr(GigaConfig, "CLIENT_ID", "client")
    monkeypatch.setattr(GigaConfig, "CLIENT_SECRET", "secret")
    monkeypatch.setattr(
        GigaConfig,
        "get_endpoint_url",
        classmethod(lambda cls, endpoint: "https://giga.example/token"),
    )
    post_calls = []

    def fake_post(**kwargs):
        post_calls.append(kwargs)
        return FakeResponse(payload={"access_token": "fresh", "expires_in": 3600})

    monkeypatch.setattr("infrastructure.giga.token_manager.requests.post", fake_post)
    manager = GigaTokenManager()

    token = manager.get_token()

    assert token == {"access_token": "fresh", "expires_in": 3600}
    assert manager._token_cache["token_data"] == token
    assert manager._token_cache["expires_at"] > time.time()
    assert post_calls[0]["url"] == "https://giga.example/token"
    assert post_calls[0]["data"] == {
        "grant_type": "client_credentials",
        "client_id": "client",
        "client_secret": "secret",
    }
    assert post_calls[0]["headers"] == {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    assert post_calls[0]["timeout"] == 10


def test_token_manager_force_refresh_ignores_cached_token(monkeypatch):
    manager = GigaTokenManager()
    manager._token_cache = {
        "token_data": {"access_token": "cached"},
        "expires_at": time.time() + 1000,
    }
    monkeypatch.setattr(
        manager,
        "_refresh_token",
        lambda: {"access_token": "forced"},
    )

    assert manager.force_refresh() == {"access_token": "forced"}
    assert manager._token_cache["expires_at"] == 0


def test_api_client_execute_get_success(monkeypatch):
    monkeypatch.setattr(
        GigaConfig,
        "get_endpoint_url",
        classmethod(lambda cls, endpoint: "https://giga.example/products"),
    )
    get_calls = []

    def fake_get(url, params, headers, timeout):
        get_calls.append(
            {"url": url, "params": params, "headers": headers, "timeout": timeout}
        )
        return FakeResponse(payload={"success": True, "data": [1]})

    monkeypatch.setattr("infrastructure.giga.api_client.requests.get", fake_get)
    client = _api_client()

    result = client.execute("product_list", {"page": 1}, method="GET")

    assert result == {
        "headers": {"x-request-id": "req-1"},
        "body": {"success": True, "data": [1]},
    }
    assert get_calls[0]["headers"]["Authorization"] == "Bearer old-token"
    assert get_calls[0]["params"] == {"page": 1}


def test_api_client_execute_post_refreshes_token_on_401(monkeypatch):
    token_manager = FakeTokenManager()
    monkeypatch.setattr(
        GigaConfig,
        "get_endpoint_url",
        classmethod(lambda cls, endpoint: "https://giga.example/details"),
    )
    responses = [
        FakeResponse(status_code=401, payload={"success": False}),
        FakeResponse(payload={"success": True, "data": {"sku": "G1"}}),
    ]
    post_calls = []

    def fake_post(url, json, headers, timeout):
        post_calls.append({"headers": dict(headers), "json": json})
        return responses.pop(0)

    monkeypatch.setattr("infrastructure.giga.api_client.requests.post", fake_post)
    client = _api_client(token_manager=token_manager)

    result = client.execute("product_details", {"sku": "G1"})

    assert result["body"] == {"success": True, "data": {"sku": "G1"}}
    assert token_manager.force_refresh_count == 1
    assert post_calls[0]["headers"]["Authorization"] == "Bearer old-token"
    assert post_calls[1]["headers"]["Authorization"] == "Bearer new-token"


def test_api_client_execute_raises_business_error_with_response_body(monkeypatch):
    monkeypatch.setattr(
        GigaConfig,
        "get_endpoint_url",
        classmethod(lambda cls, endpoint: "https://giga.example/products"),
    )

    def fake_post(*args, **kwargs):
        return FakeResponse(
            status_code=200,
            payload={"success": False, "message": "business failed"},
        )

    monkeypatch.setattr("infrastructure.giga.api_client.requests.post", fake_post)
    client = _api_client()

    with pytest.raises(GigaAPIException) as exc_info:
        client.execute("product_list", {})

    assert str(exc_info.value) == "business failed"
    assert exc_info.value.code == "GIGA_API_ERROR"
    assert exc_info.value.status_code == 200
    assert exc_info.value.response_body == {
        "success": False,
        "message": "business failed",
    }


def test_api_client_execute_raises_response_format_error(monkeypatch):
    monkeypatch.setattr(
        GigaConfig,
        "get_endpoint_url",
        classmethod(lambda cls, endpoint: "https://giga.example/products"),
    )

    def fake_post(*args, **kwargs):
        return FakeResponse(json_error=json.JSONDecodeError("bad json", "", 0))

    monkeypatch.setattr("infrastructure.giga.api_client.requests.post", fake_post)
    client = _api_client()

    with pytest.raises(GigaAPIException, match="响应格式错误"):
        client.execute("product_list", {})


def test_api_client_execute_retries_timeout_then_succeeds(monkeypatch):
    monkeypatch.setattr(
        GigaConfig,
        "get_endpoint_url",
        classmethod(lambda cls, endpoint: "https://giga.example/products"),
    )
    monkeypatch.setattr("infrastructure.giga.api_client.time.sleep", lambda seconds: None)
    responses = [
        requests.exceptions.Timeout(),
        FakeResponse(payload={"success": True, "data": []}),
    ]

    def fake_post(*args, **kwargs):
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("infrastructure.giga.api_client.requests.post", fake_post)
    client = _api_client(max_retries=1)

    assert client.execute("product_list", {})["body"] == {"success": True, "data": []}


def test_api_client_execute_raises_timeout_after_retries(monkeypatch):
    monkeypatch.setattr(
        GigaConfig,
        "get_endpoint_url",
        classmethod(lambda cls, endpoint: "https://giga.example/products"),
    )
    monkeypatch.setattr("infrastructure.giga.api_client.time.sleep", lambda seconds: None)

    def fake_post(*args, **kwargs):
        raise requests.exceptions.Timeout()

    monkeypatch.setattr("infrastructure.giga.api_client.requests.post", fake_post)
    client = _api_client(max_retries=1)

    with pytest.raises(GigaAPIException, match="请求超时"):
        client.execute("product_list", {})


def test_api_client_execute_retries_retryable_request_exception(monkeypatch):
    monkeypatch.setattr(
        GigaConfig,
        "get_endpoint_url",
        classmethod(lambda cls, endpoint: "https://giga.example/products"),
    )
    monkeypatch.setattr("infrastructure.giga.api_client.time.sleep", lambda seconds: None)
    retry_response = FakeResponse(status_code=503)
    request_error = requests.exceptions.RequestException("server busy")
    request_error.response = retry_response
    responses = [request_error, FakeResponse(payload={"success": True})]

    def fake_post(*args, **kwargs):
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("infrastructure.giga.api_client.requests.post", fake_post)
    client = _api_client(max_retries=1)

    assert client.execute("product_list", {})["body"] == {"success": True}


def test_api_client_execute_wraps_non_retryable_request_exception(monkeypatch):
    monkeypatch.setattr(
        GigaConfig,
        "get_endpoint_url",
        classmethod(lambda cls, endpoint: "https://giga.example/products"),
    )
    request_error = requests.exceptions.RequestException("bad request")
    request_error.response = FakeResponse(status_code=400)

    def fake_post(*args, **kwargs):
        raise request_error

    monkeypatch.setattr("infrastructure.giga.api_client.requests.post", fake_post)
    client = _api_client(max_retries=1)

    with pytest.raises(GigaAPIException, match="请求失败: bad request"):
        client.execute("product_list", {})
