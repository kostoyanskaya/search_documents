from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    llm_provider: str = "deepseek"  # "deepseek" | "openai" | anything, combined with the two overrides below
    llm_model: str = ""             # e.g. "gpt-4o", "gpt-4o-mini", "deepseek-chat" — empty = provider default
    llm_base_url: str = ""          # e.g. "https://api.openai.com/v1" — empty = provider default
    llm_api_key: str = ""
    embedding_model: str = "intfloat/multilingual-e5-small"
    max_upload_mb: int = 200
    max_files_per_upload: int = 40
    retrieval_top_k: int = 8
    chunk_size: int = 900
    chunk_overlap: int = 150
    cors_origins: str = "http://localhost:5173"
    session_cookie_name: str = "docmind_session"
    session_ttl_hours: int = 4
    session_cookie_secure: bool = False
    cleanup_interval_minutes: int = 15

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()