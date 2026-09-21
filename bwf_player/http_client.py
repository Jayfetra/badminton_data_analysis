"""Polite HTTP client for bwfbadminton.com.

* Bootstraps a session cookie by requesting a normal site page once (lazily, only when a
  network request is actually needed, so cached runs make no requests at all).
* Sends a custom User-Agent and a Referer header on API calls.
* Enforces a minimum interval between network requests, and per-request timeouts.
* Retries transient failures (timeouts, connection errors, 429/5xx) with exponential backoff.
* Never retries a Cloudflare block; raises ``BlockedByCloudflareError`` instead.
* Caches successful JSON responses on disk (TTL from ``BwfConfig``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from bwf_player.config import BwfConfig
from bwf_player.exceptions import BlockedByCloudflareError, BwfClientError

logger = logging.getLogger(__name__)

_BLOCK_STATUSES = frozenset({403, 429, 503})
_BLOCK_MARKERS = ("Attention Required!", "Sorry, you have been blocked", "cf-error-details")
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_RETRY_AFTER_SECONDS = 60.0


class BwfHttpClient:
    """Thin wrapper around ``requests.Session`` with rate limiting, retry and caching."""

    def __init__(
        self,
        config: BwfConfig | None = None,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config or BwfConfig()
        self._session = session or requests.Session()
        self._sleep = sleep
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._last_request_at: float | None = None
        self._bootstrapped = False

    def get_json(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        *,
        ttl: int | None = None,
    ) -> Any:
        """GET ``{api_url}/{endpoint}`` and return the decoded JSON body.

        Args:
            endpoint: API path relative to ``config.api_url`` (e.g. ``"vue-popular-players"``).
            params: Query parameters; encoded by ``requests``, never string-concatenated.
            ttl: Cache lifetime in seconds; defaults to ``config.cache_ttl_seconds``.

        Raises:
            BlockedByCloudflareError: Cloudflare blocked the request (not retried).
            BwfClientError: any other failure after retries, or a non-JSON response.
        """
        params = params or {}
        ttl = self.config.cache_ttl_seconds if ttl is None else ttl
        cache_file = self._cache_file(endpoint, params)

        cached = self._read_cache(cache_file, ttl)
        if cached is not None:
            logger.debug("cache hit: %s %s", endpoint, params)
            return cached["data"]

        self._ensure_session()
        url = f"{self.config.api_url.rstrip('/')}/{endpoint.lstrip('/')}"
        response = self._request(url, params=params, referer=f"{self.config.site_url}/players/")
        try:
            data = response.json()
        except ValueError as exc:
            raise BwfClientError(f"{endpoint}: response was not valid JSON") from exc

        self._write_cache(cache_file, endpoint, data)
        return data

    def _ensure_session(self) -> None:
        if self._bootstrapped:
            return
        logger.info("Bootstrapping session cookie")
        self._request(f"{self.config.site_url}/players/", params=None, referer=None)
        self._bootstrapped = True

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            wait = self._last_request_at + self.config.min_request_interval_seconds - self._monotonic()
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._monotonic()

    def _request(
        self, url: str, *, params: dict[str, Any] | None, referer: str | None
    ) -> requests.Response:
        headers = {"User-Agent": self.config.user_agent, "Accept": "application/json, text/html"}
        if referer:
            headers["Referer"] = referer

        last_problem = "no attempt made"
        for attempt in range(self.config.max_retries + 1):
            self._throttle()
            retry_after: float | None = None
            try:
                response = self._session.get(
                    url, params=params, headers=headers, timeout=self.config.timeout_seconds
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_problem = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code in _BLOCK_STATUSES and _looks_blocked(response):
                    raise BlockedByCloudflareError(
                        f"Cloudflare blocked the request to {url} (HTTP {response.status_code}). "
                        "Stop and wait before retrying; repeated requests can extend the block."
                    )
                if response.status_code < 400:
                    return response
                last_problem = f"HTTP {response.status_code}"
                if response.status_code not in _RETRYABLE_STATUSES:
                    raise BwfClientError(f"{url}: {last_problem}")
                retry_after = _parse_retry_after(response)

            if attempt < self.config.max_retries:
                delay = retry_after if retry_after is not None else self.config.backoff_factor * 2**attempt
                logger.warning("%s failed (%s); retrying in %.1fs", url, last_problem, delay)
                self._sleep(delay)

        raise BwfClientError(f"{url}: giving up after {self.config.max_retries + 1} attempts ({last_problem})")

    def _cache_file(self, endpoint: str, params: dict[str, Any]) -> Path:
        key = f"{endpoint}?{urlencode(sorted(params.items()))}"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return Path(self.config.cache_dir) / f"{digest}.json"

    def _read_cache(self, path: Path, ttl: int) -> dict[str, Any] | None:
        if ttl <= 0:
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            if self._wall_clock() - float(entry["fetched_at"]) > ttl:
                return None
            return entry if "data" in entry else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _write_cache(self, path: Path, endpoint: str, data: Any) -> None:
        entry = {"fetched_at": self._wall_clock(), "endpoint": endpoint, "data": data}
        tmp = path.with_suffix(".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            logger.warning("could not write cache file %s: %s", path, exc)


def _looks_blocked(response: requests.Response) -> bool:
    body = (response.text or "")[:8000]
    return any(marker in body for marker in _BLOCK_MARKERS)


def _parse_retry_after(response: requests.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    try:
        return min(max(float(raw), 0.0), _MAX_RETRY_AFTER_SECONDS) if raw is not None else None
    except ValueError:
        return None
