from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "UVDB"
    app_env: str = "development"
    log_level: str = "INFO"
    bot_token: str = ""
    bot_polling_enabled: bool = True
    database_url: str = "sqlite+aiosqlite:///./uvdb.db"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "development-only-change-me"
    admin_username: str = "admin"
    admin_password: str = ""
    youtube_cookies_b64: str = ""
    instagram_cookies_b64: str = ""
    youtube_proxy_url: str = ""
    max_file_size: int = 500 * 1024 * 1024
    max_source_file_size: int = 1024 * 1024 * 1024
    max_video_duration: int = 60 * 60
    max_concurrent_downloads: int = 3
    download_timeout: int = 1200
    request_total_timeout: int = 1800
    telegram_upload_timeout: int = 600
    telegram_direct_file_size: int = 50 * 1024 * 1024
    bot_public_url: str = "https://t.me/donins_bot"
    pixeldrain_api_key: str = ""
    pixeldrain_link_ttl_seconds: int = 2 * 60 * 60
    retry_count: int = 2
    temp_retention_minutes: int = 30
    daily_download_limit: int = 5
    active_request_limit: int = 2
    temp_dir: Path = Field(default=Path("storage/temp"))

    @property
    def arq_redis_settings(self):
        from arq.connections import RedisSettings

        return RedisSettings.from_dsn(self.redis_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
