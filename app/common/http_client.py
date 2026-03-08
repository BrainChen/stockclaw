import time
from functools import lru_cache
from typing import Any, Optional

import httpx

from app.core.config import get_settings

RETRY_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


class ResilientHTTPClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.max_attempts = max(1, int(self.settings.external_api_max_attempts))
        self.base_backoff_ms = max(0, int(self.settings.external_api_backoff_ms))

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: float = 10.0,
        acceptable_statuses: tuple[int, ...] = (200,),
    ) -> Optional[httpx.Response]:
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = httpx.request(
                    method=method.upper(),
                    url=url,
                    params=params,
                    json=json,
                    headers=headers,
                    timeout=timeout,
                )
                if response.status_code in acceptable_statuses:
                    return response
                if response.status_code not in RETRY_STATUS_CODES:
                    return None
            except httpx.RequestError:
                pass

            if attempt < self.max_attempts and self.base_backoff_ms > 0:
                delay_seconds = (self.base_backoff_ms * (2 ** (attempt - 1))) / 1000
                time.sleep(delay_seconds)
        return None

    def get_json(
        self,
        url: str,
        *,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: float = 10.0,
        acceptable_statuses: tuple[int, ...] = (200,),
    ) -> Optional[dict[str, Any]]:
        response = self.request(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            acceptable_statuses=acceptable_statuses,
        )
        if response is None:
            return None
        try:
            parsed = response.json()
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def get_text(
        self,
        url: str,
        *,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: float = 10.0,
        acceptable_statuses: tuple[int, ...] = (200,),
    ) -> Optional[str]:
        response = self.request(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            acceptable_statuses=acceptable_statuses,
        )
        if response is None:
            return None
        return response.text

    def post_json(
        self,
        url: str,
        *,
        payload: dict[str, Any],
        headers: Optional[dict[str, str]] = None,
        timeout: float = 20.0,
        acceptable_statuses: tuple[int, ...] = (200,),
    ) -> Optional[dict[str, Any]]:
        response = self.request(
            "POST",
            url,
            json=payload,
            headers=headers,
            timeout=timeout,
            acceptable_statuses=acceptable_statuses,
        )
        if response is None:
            return None
        try:
            parsed = response.json()
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None


@lru_cache(maxsize=1)
def get_http_client() -> ResilientHTTPClient:
    return ResilientHTTPClient()
