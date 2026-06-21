import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@db:5432/transactions_db"
    REDIS_URL: str = "redis://redis:6379/0"
    LLM_PROVIDER: str = "gemini"  # "gemini" or "openai"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""  # e.g., gemini-1.5-flash, gpt-4o-mini
    UPLOAD_DIR: str = "uploads"
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
