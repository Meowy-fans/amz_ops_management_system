import time

import pytest
import requests

from infrastructure.amazon.api_client import AmazonAPIClient, AmazonAPIException
from infrastructure.amazon.config import AmazonConfig
from infrastructure.amazon.token_manager import AmazonTokenManager


class FakeResponse:
    def __init__(
        self,
        status_code=200,
        payload=None,
        headers=None,
        text="response-text",
        raise_error=None,
    ):
        self.status_code = status_code
        self.payload = payload or {}
        self.headers = headers or {"x-amzn-RequestId": "req-1"}
        self.text = text
        self.raise_error = raise_error

    def raise_for_status(self):
        if self.raise_error:
            raise self.raise_error

    def json(self):
        return self.payload


class FakeTokenManager:
    def get_token(self):
        return "access-token"


@pytest.fixture(autouse=True)
def reset_amazon_config_and_cache():
    original = {
        "LWA_CLIENT_ID": AmazonConfig.LWA_CLIENT_ID,
        "LWA_CLIENT_SECRET": AmazonConfig.LWA_CLIENT_SECRET,
        "REFRESH_TOKEN": AmazonConfig.REFRESH_TOKEN,
        "SELLER_ID": AmazonConfig.SELLER_ID,
        "MARKETPLACE_ID": AmazonConfig.MARKETPLACE_ID,
        "SP_API_ENDPOINT": AmazonConfig.SP_API_ENDPOINT,
        "REGION": AmazonConfig.REGION,
        "HTTPS_PROXY": AmazonConfig.HTTPS_PROXY,
        "EXPECTED_EGRESS_IP": AmazonConfig.EXPECTED_EGRESS_IP,
        "APP_ENV": AmazonConfig.APP_ENV,
    }
    original_cache = AmazonTokenManager._token_cache.copy()
    AmazonTokenManager._token_cache = {"access_token": None, "expires_at": 0}
    yield
    for key, value in original.items():
        setattr(AmazonConfig, key, value)
    AmazonTokenManager._token_cache = original_cache


def _valid_config(proxy="http://100.85.252.67:18080", app_env="production"):
    AmazonConfig.LWA_CLIENT_ID = "client-id"
    AmazonConfig.LWA_CLIENT_SECRET = "client-secret"
    AmazonConfig.REFRESH_TOKEN = "refresh-token"
    AmazonConfig.SELLER_ID = "seller-id"
    AmazonConfig.MARKETPLACE_ID = "ATVPDKIKX0DER"
    AmazonConfig.SP_API_ENDPOINT = "https://sellingpartnerapi-na.amazon.com"
    AmazonConfig.REGION = "NA"
    AmazonConfig.HTTPS_PROXY = proxy
    AmazonConfig.EXPECTED_EGRESS_IP = "139.224.107.221"
    AmazonConfig.APP_ENV = app_env


def test_config_validate_credentials_rejects_missing_required_value():
    _valid_config()
    AmazonConfig.REFRESH_TOKEN = ""

    with pytest.raises(ValueError, match="AMAZON_REFRESH_TOKEN"):
        AmazonConfig.validate_credentials()


def test_config_validate_proxy_fails_closed_in_production():
    _valid_config(proxy="", app_env="production")

    with pytest.raises(ValueError, match="AMAZON_HTTPS_PROXY"):
        AmazonConfig.validate_proxy_required()


def test_config_proxy_dict_uses_amazon_specific_proxy():
    _valid_config(proxy="http://100.85.252.67:18080")

    assert AmazonConfig.get_proxy_dict() == {
        "http": "http://100.85.252.67:18080",
        "https": "http://100.85.252.67:18080",
    }


def test_token_manager_refreshes_lwa_token_through_proxy(monkeypatch):
    _valid_config()
    post_calls = []

    def fake_post(url, data, headers, timeout, proxies):
        post_calls.append(
            {
                "url": url,
                "data": data,
                "headers": headers,
                "timeout": timeout,
                "proxies": proxies,
            }
        )
        return FakeResponse(payload={"access_token": "fresh-token", "expires_in": 3600})

    monkeypatch.setattr("infrastructure.amazon.token_manager.requests.post", fake_post)
    manager = AmazonTokenManager()

    assert manager.get_token() == "fresh-token"
    assert post_calls[0]["url"] == "https://api.amazon.com/auth/o2/token"
    assert post_calls[0]["data"] == {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-token",
        "client_id": "client-id",
        "client_secret": "client-secret",
    }
    assert post_calls[0]["proxies"] == {
        "http": "http://100.85.252.67:18080",
        "https": "http://100.85.252.67:18080",
    }
    assert manager._token_cache["expires_at"] > time.time()


def test_api_client_request_uses_token_and_proxy(monkeypatch):
    _valid_config()
    request_calls = []

    def fake_request(method, url, headers, params, json, timeout, proxies):
        request_calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "params": params,
                "json": json,
                "timeout": timeout,
                "proxies": proxies,
            }
        )
        return FakeResponse(payload={"ok": True})

    monkeypatch.setattr("infrastructure.amazon.api_client.requests.request", fake_request)
    client = AmazonAPIClient(token_manager=FakeTokenManager(), max_retries=0)

    result = client.request("GET", "/listings/2021-08-01/items/seller-id/SKU1")

    assert result["body"] == {"ok": True}
    assert request_calls[0]["url"] == (
        "https://sellingpartnerapi-na.amazon.com"
        "/listings/2021-08-01/items/seller-id/SKU1"
    )
    assert request_calls[0]["headers"]["x-amz-access-token"] == "access-token"
    assert request_calls[0]["proxies"]["https"] == "http://100.85.252.67:18080"


def test_api_client_retries_rate_limit(monkeypatch):
    _valid_config()
    responses = [
        FakeResponse(status_code=429, payload={"errors": [{"message": "rate limited"}]}),
        FakeResponse(payload={"ok": True}),
    ]
    sleep_calls = []

    def fake_request(*args, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr("infrastructure.amazon.api_client.requests.request", fake_request)
    monkeypatch.setattr("infrastructure.amazon.api_client.time.sleep", sleep_calls.append)
    client = AmazonAPIClient(token_manager=FakeTokenManager(), max_retries=1)

    assert client.request("GET", "/reports/2021-06-30/reports")["body"] == {"ok": True}
    assert sleep_calls == [1]


def test_api_client_raises_with_request_id_and_redacts_secrets(monkeypatch):
    _valid_config()

    def fake_request(*args, **kwargs):
        return FakeResponse(
            status_code=400,
            payload={"errors": [{"message": "bad request"}]},
            headers={"x-amzn-RequestId": "req-bad"},
        )

    monkeypatch.setattr("infrastructure.amazon.api_client.requests.request", fake_request)
    client = AmazonAPIClient(token_manager=FakeTokenManager(), max_retries=0)

    with pytest.raises(AmazonAPIException) as exc:
        client.request("POST", "/feeds/2021-06-30/feeds", json={"refresh_token": "secret"})

    assert exc.value.status_code == 400
    assert exc.value.request_id == "req-bad"
    assert AmazonAPIClient.redact({"client_secret": "secret", "safe": "value"}) == {
        "client_secret": "***",
        "safe": "value",
    }
