from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    firecrawl_api_key: str
    firecrawl_proxy: str = "stealth"  # basic | stealth | auto
    cache_ttl_seconds: int = 600
    cache_max_entries: int = 512
    firecrawl_daily_credit_ceiling: int = 400

    # parsing
    min_results_threshold: int = 3  # below this, selector parse is treated as a miss
    request_timeout_seconds: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
