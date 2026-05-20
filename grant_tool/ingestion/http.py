from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class HttpResponse:
    url: str
    status_code: int
    content_type: str | None
    text: str
    json_data: Any | None = None


class HttpClient:
    def __init__(
        self,
        *,
        user_agent: str,
        timeout_seconds: float = 20,
        retries: int = 2,
        rate_limit_seconds: float = 0,
    ) -> None:
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.rate_limit_seconds = rate_limit_seconds
        self._last_request_at: float | None = None
        self._client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept": "*/*"},
        )

    def close(self) -> None:
        self._client.close()

    def get(self, url: str, *, params: dict[str, Any] | None = None) -> HttpResponse:
        response = self._request("GET", url, params=params)
        return self._to_response(response)

    def post(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: Any | None = None,
        files: Any | None = None,
        json: Any | None = None,
    ) -> HttpResponse:
        response = self._request("POST", url, params=params, data=data, files=files, json=json)
        return self._to_response(response)

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait_for_rate_limit()
            try:
                response = self._client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                if attempt >= self.retries:
                    raise
                time.sleep(min(2**attempt, 5))
        raise RuntimeError("HTTP request failed") from last_exc

    def _wait_for_rate_limit(self) -> None:
        if self.rate_limit_seconds <= 0:
            return
        now = time.monotonic()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            if elapsed < self.rate_limit_seconds:
                time.sleep(self.rate_limit_seconds - elapsed)
        self._last_request_at = time.monotonic()

    @staticmethod
    def _to_response(response: httpx.Response) -> HttpResponse:
        json_data: Any | None = None
        content_type = response.headers.get("content-type")
        if content_type and "json" in content_type.lower():
            try:
                json_data = response.json()
            except ValueError:
                json_data = None
        return HttpResponse(
            url=str(response.url),
            status_code=response.status_code,
            content_type=content_type,
            text=response.text,
            json_data=json_data,
        )
