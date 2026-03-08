import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

# 先加载 .env 默认值，再用 .env.local 覆盖（若存在）
load_dotenv(".env", override=False)
load_dotenv(".env.local", override=True)


@dataclass
class Settings:
    app_name: str = "Financial Asset QA System"
    app_env: str = os.getenv("APP_ENV", "dev")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))

    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "openrouter/auto")
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_site_url: str = os.getenv("OPENROUTER_SITE_URL", "")
    openrouter_app_name: str = os.getenv("OPENROUTER_APP_NAME", "Financial Asset QA System")

    web_search_enabled: bool = os.getenv("WEB_SEARCH_ENABLED", "true").lower() == "true"
    web_search_max_results: int = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "3"))
    kb_dir: str = os.getenv("KB_DIR", "app/data/knowledge_base")
    kb_index_dir: str = os.getenv("KB_INDEX_DIR", "app/data/.kb_index")
    kb_chunk_size: int = int(os.getenv("KB_CHUNK_SIZE", "500"))
    kb_chunk_overlap: int = int(os.getenv("KB_CHUNK_OVERLAP", "80"))
    kb_max_chunks: int = int(os.getenv("KB_MAX_CHUNKS", "20000"))
    external_api_max_attempts: int = int(os.getenv("EXTERNAL_API_MAX_ATTEMPTS", "3"))
    external_api_backoff_ms: int = int(os.getenv("EXTERNAL_API_BACKOFF_MS", "250"))
    event_large_move_threshold_pct: float = float(os.getenv("EVENT_LARGE_MOVE_THRESHOLD_PCT", "3.0"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
