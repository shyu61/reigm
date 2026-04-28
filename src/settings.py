"""Project-wide settings loaded from `.env` via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    dataimpulse_username: str = ""
    dataimpulse_password: str = ""


settings = Settings()
