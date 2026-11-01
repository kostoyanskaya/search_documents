from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_timeout_s: float = 45.0
    llm_max_retries: int = 2
    llm_json_mode: bool = True
    llm_max_concurrent: int = 8
    llm_daily_request_cap: int = 5000

    embedding_model: str = "intfloat/multilingual-e5-base"
    embedding_revision: str | None = None
    embedding_batch_size: int = 32

    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    reranker_revision: str | None = None
    rerank_candidates: int = 15
    rerank_confident_score: float = 0.5
    rerank_min_score: float = 0.01

    chunk_size: int = 900
    chunk_overlap: int = 120
    retrieval_top_k: int = 8
    candidate_pool: int = 40
    max_chunks_per_doc_in_context: int = 3
    min_dense_similarity: float = 0.0

    max_upload_mb: int = 50
    max_files_per_upload: int = 50
    max_request_mb: int = 200
    max_docs_per_session: int = 50
    max_chunks_per_session: int = 50_000
    max_session_total_mb: int = 300
    max_pdf_pages: int = 2000
    max_text_chars_per_doc: int = 5_000_000
    max_uncompressed_mb: int = 500
    parse_timeout_s: int = 120
    parse_memory_mb: int = 2048
    parse_in_subprocess: bool = True
    max_parallel_processing: int = 2

    ocr_enabled: bool = True
    ocr_languages: str = "rus+eng"
    ocr_max_pages: int = 100
    ocr_dpi: int = 200
    ocr_timeout_s: int = 900

    max_table_cells_per_doc: int = 3_000_000
    max_total_table_cells: int = 30_000_000
    sql_timeout_s: float = 10.0
    sql_result_rows: int = 50
    sql_memory_mb: int = 256

    agent_max_reformulations: int = 2
    agent_sql_max_attempts: int = 3
    max_history_turns: int = 3
    max_inflight_upload_mb: int = 1024

    session_cookie_name: str = "docmind_session"
    session_ttl_minutes: int = 240
    session_cookie_secure: bool = True
    session_cookie_samesite: str = "lax"
    max_sessions: int = 2000
    rate_limit_new_session_per_min: int = 3

    access_code: SecretStr = SecretStr("")

    log_format: str = "text"
    enable_metrics: bool = False
    metrics_token: SecretStr = SecretStr("")
    sentry_dsn: str = ""

    cors_origins: str = "http://localhost:5173"
    enable_api_docs: bool = False
    rate_limit_query_per_min: int = 10
    rate_limit_upload_per_min: int = 10
    rate_limit_other_per_min: int = 120
    rate_limit_unlock_per_min: int = 5

    @field_validator("embedding_revision", "reranker_revision", mode="before")
    @classmethod
    def _empty_revision_is_none(cls, v):
        return v or None

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            o.strip().rstrip("/")
            for o in self.cors_origins.split(",")
            if o.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
