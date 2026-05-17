from typing import Optional
from pathlib import Path
from pydantic import PostgresDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Application Settings
    Loads configuration from environment variables and .env file
    """
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore"
    )

    # App Config
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/app.log"
    
    # Database Config
    DATABASE_HOST: str
    DATABASE_PORT: int = 5432
    DATABASE_NAME: str
    DATABASE_USER: str
    DATABASE_PASSWORD: str

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        """Construct SQLAlchemy Database URL"""
        return f"postgresql+psycopg2://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"

    # LLM Config
    LLM_SERVICE_MODE: str = "direct"
    LLM_PROVIDER: str = "qwen"
    
    # Optional API Keys
    DEEPSEEK_API_KEY: Optional[str] = None
    DASHSCOPE_API_KEY: Optional[str] = None
    
    # Giga Config
    GIGA_BASE_URL: str = "https://api.gigacloudlogistics.com"
    GIGA_CLIENT_ID: Optional[str] = None
    GIGA_CLIENT_SECRET: Optional[str] = None

    # Amazon SP-API Config
    AMAZON_LWA_CLIENT_ID: Optional[str] = None
    AMAZON_LWA_CLIENT_SECRET: Optional[str] = None
    AMAZON_REFRESH_TOKEN: Optional[str] = None
    AMAZON_SELLER_ID: Optional[str] = None
    AMAZON_MARKETPLACE_ID: str = "ATVPDKIKX0DER"
    AMAZON_SP_API_ENDPOINT: str = "https://sellingpartnerapi-na.amazon.com"
    AMAZON_REGION: str = "NA"
    AMAZON_HTTPS_PROXY: Optional[str] = None
    AMAZON_EXPECTED_EGRESS_IP: Optional[str] = None

    # AutoGen Config
    AUTOGEN_BASE_URL: str = "http://localhost:8000"
    AUTOGEN_TIMEOUT_SECONDS: int = 300
    AUTOGEN_GLOBAL_MAX_ROUNDS: int = 1
    AUTOGEN_TERMINATION_KEYWORD: str = "TERMINATE"
    AUTOGEN_FALLBACK_MODEL: str = "deepseek-chat"

    # Legacy/Other
    QWEN_MODEL: str = "qwen-plus"
    DEEPSEEK_MODEL: str = "deepseek-chat"

settings = Settings()
