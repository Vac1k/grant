from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Grant Matching Tool"
    app_env: str = Field(default="local", validation_alias="APP_ENV")
    database_url: str = Field(
        default="postgresql+psycopg://grant:grant@localhost:5432/grant",
        validation_alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", validation_alias="REDIS_URL")
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    llm_model: str = Field(default="gpt-4.1-mini", validation_alias="LLM_MODEL")
    embedding_model: str = Field(
        default="text-embedding-3-small",
        validation_alias="EMBEDDING_MODEL",
    )
    http_user_agent: str = Field(
        default="AIGrantMatchingTool/0.1 (+local MVP)",
        validation_alias="HTTP_USER_AGENT",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
