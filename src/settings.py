"""Project-wide settings loaded from `.env` via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    dataimpulse_login: str = ""
    dataimpulse_password: str = ""

    aws_profile_name: str = "default"
    s3_region: str = "ap-northeast-1"
    s3_bucket_name: str = "reigm-data"


settings = Settings()
