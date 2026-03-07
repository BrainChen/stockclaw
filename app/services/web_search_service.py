from typing import Dict, List

from app.core.config import get_settings

try:
    from duckduckgo_search import DDGS
except Exception:
    DDGS = None


class WebSearchService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def search(self, query: str, max_results: int | None = None) -> List[Dict]:
        if not self.settings.web_search_enabled or DDGS is None:
            return []

        limit = max_results or self.settings.web_search_max_results
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=limit))
            normalized = []
            for item in results:
                normalized.append(
                    {
                        "title": item.get("title", "Web Search Result"),
                        "snippet": item.get("body", ""),
                        "url": item.get("href", ""),
                    }
                )
            return normalized
        except Exception:
            return []
