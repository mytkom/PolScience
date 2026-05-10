from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from typing import Any, Mapping, Optional, Sequence, Union

import httpx

LOG = logging.getLogger(__name__)

DEFAULT_BASE = "https://ludzie.nauka.gov.pl/api/profiles-api"

# httpx accepts a dict or a sequence of pairs (needed for repeated query keys, e.g. domains=A&domains=B).
QueryParams = Union[Mapping[str, Any], Sequence[tuple[str, Any]], None]


class RateLimiter:
    """Serialize requests + optional per-request jitter (polite crawl)."""

    def __init__(self, min_sleep: float, max_sleep: float) -> None:
        self.min_sleep = min(min_sleep, max_sleep)
        self.max_sleep = max(min_sleep, max_sleep)
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait_turn(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next_at:
                time.sleep(self._next_at - now)
                now = time.monotonic()
            jitter = random.uniform(self.min_sleep, self.max_sleep)
            self._next_at = now + jitter


class HttpClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE,
        timeout: float = 60.0,
        min_sleep: float = 0.5,
        max_sleep: float = 1.0,
        max_retries: int = 5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._limiter = RateLimiter(min_sleep, max_sleep)
        self._default_headers: dict[str, str] = {
            "Accept": "application/json",
            "Accept-Language": "en-EN",
        }
        self._client = httpx.Client(timeout=timeout, headers=dict(self._default_headers))

    def close(self) -> None:
        self._client.close()

    def get_json(
        self,
        path: str,
        params: QueryParams = None,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> Any:
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        headers = {**self._default_headers, **(extra_headers or {})}
        attempt = 0
        while True:
            self._limiter.wait_turn()
            attempt += 1
            try:
                r = self._client.get(url, params=params, headers=headers)
            except httpx.RequestError as e:
                if attempt >= self.max_retries:
                    raise
                delay = min(2 ** attempt + random.random(), 120.0)
                LOG.warning("request error %s; sleep %.1fs", e, delay)
                time.sleep(delay)
                continue

            if r.status_code in (418, 429, 502, 503, 504) or r.status_code >= 500:
                ra = r.headers.get("Retry-After")
                if ra:
                    try:
                        delay = float(ra)
                    except ValueError:
                        delay = min(2 ** attempt + random.random(), 120.0)
                else:
                    delay = min(2 ** attempt + random.random(), 120.0)
                if attempt >= self.max_retries:
                    r.raise_for_status()
                LOG.warning("HTTP %s; sleep %.1fs (%s)", r.status_code, delay, url)
                time.sleep(delay)
                continue

            if r.status_code == 404:
                return None

            r.raise_for_status()
            if not r.content:
                return None
            return r.json()


RADON_BASE = "https://radon.nauka.gov.pl"


class RadonClient:
    """Open data portal-search (same rate-limit pattern as HttpClient)."""

    def __init__(
        self,
        *,
        base_url: str = RADON_BASE,
        timeout: float = 60.0,
        min_sleep: float = 0.5,
        max_sleep: float = 1.0,
        max_retries: int = 100,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._limiter = RateLimiter(min_sleep, max_sleep)
        self._default_headers: dict[str, str] = {
            "Accept": "application/json",
            "Accept-Language": "en-EN",
        }
        self._client = httpx.Client(timeout=timeout, headers=dict(self._default_headers))

    def close(self) -> None:
        self._client.close()

    def portal_search_institution(self, institution_id: str) -> Any:
        path = f"/opendata/portal-search/{institution_id}"
        return self.get_json(path)

    def get_json(
        self,
        path: str,
        params: QueryParams = None,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> Any:
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        headers = {**self._default_headers, **(extra_headers or {})}
        attempt = 0
        while True:
            self._limiter.wait_turn()
            attempt += 1
            try:
                r = self._client.get(url, params=params, headers=headers)
            except httpx.RequestError as e:
                if attempt >= self.max_retries:
                    raise
                delay = min(2 ** attempt + random.random(), 120.0)
                LOG.warning("radon request error %s; sleep %.1fs", e, delay)
                time.sleep(delay)
                continue

            if r.status_code == 418:
                msg_text = ""
                try:
                    j = r.json()
                    if isinstance(j, dict) and j.get("message") is not None:
                        msg_text = str(j["message"])
                except Exception:
                    pass
                if "blocked" in msg_text.lower():
                    LOG.warning("radon 418 blocked; waiting 12m before retry (%s)", url)
                    time.sleep(12 * 60)
                    continue
                if attempt >= self.max_retries:
                    r.raise_for_status()
                delay = min(2 ** attempt + random.random(), 120.0)
                LOG.warning("radon HTTP 418; sleep %.1fs (%s)", delay, url)
                time.sleep(delay)
                continue

            if r.status_code in (429, 502, 503, 504) or r.status_code >= 500:
                ra = r.headers.get("Retry-After")
                if ra:
                    try:
                        delay = float(ra)
                    except ValueError:
                        delay = min(2 ** attempt + random.random(), 120.0)
                else:
                    delay = min(2 ** attempt + random.random(), 120.0)
                if attempt >= self.max_retries:
                    r.raise_for_status()
                LOG.warning("radon HTTP %s; sleep %.1fs (%s)", r.status_code, delay, url)
                time.sleep(delay)
                continue

            if r.status_code == 404:
                return None

            r.raise_for_status()
            if not r.content:
                return None
            return r.json()


def stable_org_id(name: str) -> str:
    h = hashlib.sha256(name.encode("utf-8")).hexdigest()[:32]
    return f"h_{h}"

