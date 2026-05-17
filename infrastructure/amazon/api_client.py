"""Amazon SP-API client."""
import logging
import time
from typing import Any, Dict, Optional

import requests

from infrastructure.exceptions import AppException
from infrastructure.amazon.config import AmazonConfig
from infrastructure.amazon.token_manager import AmazonTokenManager

logger = logging.getLogger(__name__)


class AmazonAPIException(AppException):
    """Amazon SP-API request failure."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ):
        super().__init__(message, code="AMAZON_API_ERROR")
        self.status_code = status_code
        self.response_body = response_body
        self.request_id = request_id


class AmazonAPIClient:
    """Executes Amazon SP-API requests through the required bastion proxy."""

    RETRY_STATUS_CODES = {429, 500, 503}
    SECRET_KEYS = {
        "access_token",
        "client_secret",
        "refresh_token",
        "lwa_client_secret",
        "amazon_lwa_client_secret",
        "amazon_refresh_token",
    }

    def __init__(
        self,
        token_manager: Optional[AmazonTokenManager] = None,
        max_retries: int = 3,
        timeout: int = 30,
    ):
        AmazonConfig.validate_credentials()
        AmazonConfig.validate_proxy_required()
        self.token_manager = token_manager or AmazonTokenManager()
        self.max_retries = max_retries
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Execute an SP-API request and return headers plus parsed body."""
        url = AmazonConfig.get_sp_api_url(path)
        request_headers = {
            "x-amz-access-token": self.token_manager.get_token(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if headers:
            request_headers.update(headers)

        for attempt in range(self.max_retries + 1):
            response = requests.request(
                method.upper(),
                url,
                headers=request_headers,
                params=params,
                json=json,
                timeout=self.timeout,
                proxies=AmazonConfig.get_proxy_dict(),
            )
            request_id = self._request_id(response.headers)

            if response.status_code in self.RETRY_STATUS_CODES and attempt < self.max_retries:
                wait_time = self._retry_wait(attempt, response.headers)
                logger.warning(
                    "Amazon SP-API retryable response status=%s request_id=%s wait=%s",
                    response.status_code,
                    request_id,
                    wait_time,
                )
                time.sleep(wait_time)
                continue

            body = self._parse_body(response)
            if response.status_code >= 400:
                raise AmazonAPIException(
                    self._error_message(body, response.status_code),
                    status_code=response.status_code,
                    response_body=body,
                    request_id=request_id,
                )

            return {
                "headers": dict(response.headers),
                "body": body,
            }

        raise AmazonAPIException("Amazon SP-API retry loop exited unexpectedly")

    @classmethod
    def redact(cls, payload: Any) -> Any:
        """Redact known secret fields from log payloads."""
        if isinstance(payload, dict):
            redacted = {}
            for key, value in payload.items():
                if key.lower() in cls.SECRET_KEYS:
                    redacted[key] = "***"
                else:
                    redacted[key] = cls.redact(value)
            return redacted
        if isinstance(payload, list):
            return [cls.redact(item) for item in payload]
        return payload

    @staticmethod
    def _request_id(headers: Dict[str, str]) -> Optional[str]:
        return headers.get("x-amzn-RequestId") or headers.get("x-amzn-requestid")

    @staticmethod
    def _retry_wait(attempt: int, headers: Dict[str, str]) -> int:
        retry_after = headers.get("Retry-After")
        if retry_after:
            try:
                return max(1, int(float(retry_after)))
            except ValueError:
                pass
        return 2 ** attempt

    @staticmethod
    def _parse_body(response) -> Dict[str, Any]:
        if not response.text:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}

    @staticmethod
    def _error_message(body: Dict[str, Any], status_code: int) -> str:
        errors = body.get("errors")
        if isinstance(errors, list) and errors:
            message = errors[0].get("message")
            if message:
                return message
        return f"Amazon SP-API request failed with status {status_code}"
