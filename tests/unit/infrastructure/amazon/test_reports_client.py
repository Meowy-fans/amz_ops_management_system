import gzip

import pytest

from infrastructure.amazon.reports_client import AmazonReportsClient


class FakeAPIClient:
    def __init__(self):
        self.calls = []
        self.responses = []

    def request(self, method, path, params=None, json=None, headers=None):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "params": params,
                "json": json,
                "headers": headers,
            }
        )
        return self.responses.pop(0)


class FakeDownloadResponse:
    def __init__(self, content=b"data", status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("download failed")


def test_create_report_uses_listing_report_type_and_marketplace():
    api = FakeAPIClient()
    api.responses.append({"body": {"reportId": "R1"}})
    client = AmazonReportsClient(api_client=api, marketplace_id="ATVPDKIKX0DER")

    report_id = client.create_merchant_listings_report()

    assert report_id == "R1"
    assert api.calls == [
        {
            "method": "POST",
            "path": "/reports/2021-06-30/reports",
            "params": None,
            "json": {
                "reportType": "GET_MERCHANT_LISTINGS_ALL_DATA",
                "marketplaceIds": ["ATVPDKIKX0DER"],
            },
            "headers": None,
        }
    ]


def test_get_report_and_get_document_call_expected_paths():
    api = FakeAPIClient()
    api.responses.extend([
        {"body": {"processingStatus": "DONE"}},
        {"body": {"url": "https://doc.example/report.txt"}},
    ])
    client = AmazonReportsClient(api_client=api)

    assert client.get_report("R1") == {"processingStatus": "DONE"}
    assert client.get_report_document("D1") == {"url": "https://doc.example/report.txt"}

    assert api.calls[0]["path"] == "/reports/2021-06-30/reports/R1"
    assert api.calls[1]["path"] == "/reports/2021-06-30/documents/D1"


def test_wait_for_report_returns_document_id_when_done(monkeypatch):
    api = FakeAPIClient()
    client = AmazonReportsClient(api_client=api)
    statuses = [
        {"processingStatus": "IN_PROGRESS"},
        {"processingStatus": "DONE", "reportDocumentId": "D1"},
    ]
    monkeypatch.setattr(client, "get_report", lambda report_id: statuses.pop(0))
    sleeps = []
    monkeypatch.setattr("infrastructure.amazon.reports_client.time.sleep", sleeps.append)

    assert client.wait_for_report("R1", poll_interval_seconds=3, timeout_seconds=30) == "D1"
    assert sleeps == [3]


def test_wait_for_report_raises_for_cancelled_report(monkeypatch):
    client = AmazonReportsClient(api_client=FakeAPIClient())
    monkeypatch.setattr(client, "get_report", lambda report_id: {"processingStatus": "CANCELLED"})

    with pytest.raises(RuntimeError, match="CANCELLED"):
        client.wait_for_report("R1", poll_interval_seconds=0, timeout_seconds=1)


def test_download_document_uses_proxy_and_decodes_gzip(monkeypatch):
    client = AmazonReportsClient(api_client=FakeAPIClient(), proxy_url="http://proxy:18080")
    calls = []

    def fake_get(url, timeout, proxies):
        calls.append({"url": url, "timeout": timeout, "proxies": proxies})
        return FakeDownloadResponse(content=gzip.compress("listing-id\tasin1\nL1\tA1\n".encode()))

    monkeypatch.setattr("infrastructure.amazon.reports_client.requests.get", fake_get)

    text = client.download_report_document(
        {
            "url": "https://doc.example/report.txt.gz",
            "compressionAlgorithm": "GZIP",
        }
    )

    assert text == "listing-id\tasin1\nL1\tA1\n"
    assert calls[0]["proxies"] == {
        "http": "http://proxy:18080",
        "https": "http://proxy:18080",
    }
