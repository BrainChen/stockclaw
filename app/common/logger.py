import logging
import sys
from typing import Any


_LOGGING_CONFIGURED = False


def setup_logging(level: str = "INFO") -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    resolved_level = _resolve_level(level)
    logging.basicConfig(
        level=resolved_level,
        stream=sys.stdout,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _LOGGING_CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def kv(**kwargs: Any) -> str:
    items: list[str] = []
    for key, value in kwargs.items():
        if value is None:
            continue
        text = str(value).replace("\n", " ").replace("\r", " ")
        items.append(f"{key}={text}")
    return " ".join(items)


def preview_text(text: str, max_len: int = 80) -> str:
    compact = " ".join(text.strip().split())
    if len(compact) <= max_len:
        return compact
    return f"{compact[:max_len]}..."


def _resolve_level(level: str) -> int:
    raw = (level or "INFO").strip().upper()
    return getattr(logging, raw, logging.INFO)
