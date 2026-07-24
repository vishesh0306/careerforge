from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str
    redis_url: str
    gemini_api_key: str = Field(min_length=1)

    # Optional — job search sources that need a key degrade gracefully (skip themselves)
    # when these are unset, rather than failing the whole search.
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None
    jsearch_rapidapi_key: str | None = None


settings = Settings()
