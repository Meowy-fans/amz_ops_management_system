"""Amazon SP-API configuration."""
from typing import Dict, Optional

from src.config.settings import settings


class AmazonConfig:
    """Holds Amazon SP-API settings."""

    APP_ENV = settings.APP_ENV
    LWA_CLIENT_ID = settings.AMAZON_LWA_CLIENT_ID
    LWA_CLIENT_SECRET = settings.AMAZON_LWA_CLIENT_SECRET
    REFRESH_TOKEN = settings.AMAZON_REFRESH_TOKEN
    SELLER_ID = settings.AMAZON_SELLER_ID
    MARKETPLACE_ID = settings.AMAZON_MARKETPLACE_ID
    SP_API_ENDPOINT = settings.AMAZON_SP_API_ENDPOINT.rstrip("/")
    REGION = settings.AMAZON_REGION
    HTTPS_PROXY = settings.AMAZON_HTTPS_PROXY
    EXPECTED_EGRESS_IP = settings.AMAZON_EXPECTED_EGRESS_IP

    LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"

    @classmethod
    def validate_credentials(cls) -> bool:
        """Validate that required Amazon SP-API credentials are present."""
        required = {
            "AMAZON_LWA_CLIENT_ID": cls.LWA_CLIENT_ID,
            "AMAZON_LWA_CLIENT_SECRET": cls.LWA_CLIENT_SECRET,
            "AMAZON_REFRESH_TOKEN": cls.REFRESH_TOKEN,
            "AMAZON_SELLER_ID": cls.SELLER_ID,
            "AMAZON_MARKETPLACE_ID": cls.MARKETPLACE_ID,
            "AMAZON_SP_API_ENDPOINT": cls.SP_API_ENDPOINT,
            "AMAZON_REGION": cls.REGION,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError(f"Amazon SP-API configuration missing: {', '.join(missing)}")
        return True

    @classmethod
    def validate_proxy_required(cls) -> bool:
        """Fail closed in production when the bastion proxy is not configured."""
        if cls.APP_ENV == "production" and not cls.HTTPS_PROXY:
            raise ValueError(
                "AMAZON_HTTPS_PROXY is required in production; "
                "Amazon SP-API direct egress is not allowed."
            )
        return True

    @classmethod
    def get_proxy_dict(cls) -> Optional[Dict[str, str]]:
        """Return requests-compatible proxy configuration."""
        if not cls.HTTPS_PROXY:
            return None
        return {
            "http": cls.HTTPS_PROXY,
            "https": cls.HTTPS_PROXY,
        }

    @classmethod
    def get_sp_api_url(cls, path: str) -> str:
        """Build a full SP-API URL from an absolute API path."""
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{cls.SP_API_ENDPOINT}{path}"
