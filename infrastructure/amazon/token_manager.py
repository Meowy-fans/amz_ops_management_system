"""Amazon LWA token manager."""
import logging
import time
from threading import Lock
from typing import Dict

import requests

from infrastructure.amazon.config import AmazonConfig

logger = logging.getLogger(__name__)


class AmazonTokenManager:
    """Caches Amazon LWA access tokens."""

    _lock = Lock()
    _token_cache: Dict = {
        "access_token": None,
        "expires_at": 0,
    }

    def get_token(self) -> str:
        """Return a valid LWA access token."""
        if time.time() < self._token_cache["expires_at"] - 300:
            return self._token_cache["access_token"]
        return self._refresh_token()

    def _refresh_token(self) -> str:
        """Refresh the LWA access token through the configured bastion proxy."""
        AmazonConfig.validate_credentials()
        AmazonConfig.validate_proxy_required()

        with self._lock:
            if time.time() < self._token_cache["expires_at"] - 300:
                return self._token_cache["access_token"]

            logger.info("Refreshing Amazon LWA access token")
            response = requests.post(
                AmazonConfig.LWA_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": AmazonConfig.REFRESH_TOKEN,
                    "client_id": AmazonConfig.LWA_CLIENT_ID,
                    "client_secret": AmazonConfig.LWA_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
                proxies=AmazonConfig.get_proxy_dict(),
            )
            response.raise_for_status()
            token_data = response.json()
            access_token = token_data["access_token"]
            expires_in = int(token_data.get("expires_in", 3600))
            self._token_cache = {
                "access_token": access_token,
                "expires_at": time.time() + expires_in,
            }
            return access_token

    def force_refresh(self) -> str:
        """Force refresh the cached token."""
        self._token_cache["expires_at"] = 0
        return self.get_token()
