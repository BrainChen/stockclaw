from typing import Optional

from app.core.config import get_settings
from app.common.http_client import get_http_client


class LLMService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.http_client = get_http_client()
        self._enabled = bool(self.settings.openrouter_api_key)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> Optional[str]:
        if not self._enabled:
            return None
        try:
            headers = {
                "Authorization": f"Bearer {self.settings.openrouter_api_key}",
                "Content-Type": "application/json",
            }
            if self.settings.openrouter_site_url:
                headers["HTTP-Referer"] = self.settings.openrouter_site_url
            if self.settings.openrouter_app_name:
                headers["X-Title"] = self.settings.openrouter_app_name

            payload = {
                "model": self.settings.openrouter_model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            data = self.http_client.post_json(
                f"{self.settings.openrouter_base_url.rstrip('/')}/chat/completions",
                payload=payload,
                headers=headers,
                timeout=45.0,
            )
            if not data:
                return None
            return data["choices"][0]["message"]["content"]
        except Exception:
            return None
