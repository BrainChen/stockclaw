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
        enriched_query = self._build_query(query)
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(enriched_query, max_results=limit))
            normalized = []
            seen_keys: set[str] = set()
            for item in results:
                title = item.get("title", "Web Search Result")
                snippet = item.get("body", "")
                url = item.get("href", "")
                key = f"{title.strip().lower()}::{url.strip().lower()}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                normalized.append({"title": title, "snippet": snippet, "url": url})
            return normalized
        except Exception:
            return []

    def _build_query(self, query: str) -> str:
        clean = " ".join(query.strip().split())
        if not clean:
            return clean
        if "finance" in clean.lower() or "金融" in clean:
            return clean
        return f"finance {clean}"
