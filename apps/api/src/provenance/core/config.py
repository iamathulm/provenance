"""Application settings, validated at startup from environment variables and `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[5]
DEV_SESSION_SECRET = "dev-only-insecure-session-secret-change-me"  # noqa: S105 - placeholder, rejected in production


class Settings(BaseSettings):
    """Runtime configuration. Unknown variables are ignored; invalid values fail fast."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "test", "production"] = "local"
    database_url: str = (
        "postgresql+psycopg://provenance:provenance@127.0.0.1:5432/provenance?connect_timeout=5"
    )
    qdrant_url: str = "http://127.0.0.1:6333"
    groq_api_key: SecretStr | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    # Answer models in preference order; the next one is used when the first has no quota left.
    answer_models: list[str] = ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"]
    sql_model: str = "openai/gpt-oss-20b"
    model_requests_per_minute: int = 30  # Groq free plan, per model
    model_tokens_per_minute: int = 8_000
    llm_timeout_s: float = 30.0
    llm_max_wait_s: float = 8.0  # queue this long for free-tier quota before giving up
    # off: call Groq; replay: answer only from recorded cassettes; record: call Groq and save.
    llm_cassettes: Literal["off", "replay", "record"] = "off"
    llm_cassette_dir: Path = REPO_ROOT / "eval" / "cassettes"
    answer_max_tokens: int = 450
    # Per user, so one person cannot spend the shared free quota for everyone.
    questions_per_minute: int = 5
    questions_per_hour: int = 60
    context_max_sources: int = 6
    context_max_words: int = 1_800  # ~2.4K tokens: one answer must fit the free 8K tokens/minute
    citation_support_min: float = 0.5  # FlashRank score a cited sentence needs
    citation_lexical_min: float = 0.6  # word-overlap fallback when the reranker is unavailable
    # Below this top rerank score the workspace has nothing on the question: abstain, no LLM call.
    relevance_floor: float = 0.05  # every answerable golden question scored >= 0.08
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    demo_mode: bool = True

    session_secret: SecretStr = SecretStr(DEV_SESSION_SECRET)
    session_ttl_hours: int = 12
    session_idle_minutes: int = 120
    allowed_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    max_file_bytes: int = 10 * 1024 * 1024
    qdrant_collection: str = "chunks"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimension: int = 384
    # BGE v1.5 retrieval instruction, prepended to queries only (documents are embedded as-is).
    embedding_query_prefix: str = "Represent this sentence for searching relevant passages: "
    sparse_model: str = "Qdrant/bm25"
    fastembed_cache_dir: Path | None = REPO_ROOT / ".cache" / "fastembed"
    reranker_model: str = "ms-marco-MiniLM-L-12-v2"
    flashrank_cache_dir: Path = REPO_ROOT / ".cache" / "flashrank"
    search_candidates: int = 40
    rerank_candidates: int = 20
    rerank_max_tokens: int = 256  # truncation per passage; latency grows faster than linearly
    rerank_timeout_s: float = 3.0
    sql_max_rows: int = 200
    sql_timeout_s: float = 5.0
    max_pages: int = 200
    max_table_rows: int = 50_000
    file_link_ttl_s: int = 300
    # Peers whose X-Forwarded-For is trusted for client IPs (e.g. the web app proxy).
    trusted_proxies: list[str] = []
    profiles_dir: Path = REPO_ROOT / "profiles"

    @model_validator(mode="after")
    def _require_real_secret_in_production(self) -> Self:
        secret = self.session_secret.get_secret_value()
        if self.app_env == "production" and (secret == DEV_SESSION_SECRET or len(secret) < 32):
            msg = "SESSION_SECRET must be set to a random value of at least 32 characters"
            raise ValueError(msg)
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
