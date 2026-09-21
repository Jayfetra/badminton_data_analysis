"""Polite HTTP client for bwfbadminton.com.

Behaviour (implemented in Iteration 1, when the first live endpoint is consumed):

* Bootstraps a session cookie by requesting a normal site page once.
* Sends a custom User-Agent and a Referer header on API calls.
* Enforces a minimum interval between requests and per-request timeouts.
* Retries transient failures (timeouts, 5xx) with exponential backoff.
* Never retries a Cloudflare block; raises ``BlockedByCloudflareError`` instead.
* Caches successful JSON responses on disk (TTL from ``BwfConfig``).
"""

from __future__ import annotations

from typing import Any

from bwf_player.config import BwfConfig


class BwfHttpClient:
    """Thin wrapper around ``requests.Session`` with rate limiting, retry and caching."""

    def __init__(self, config: BwfConfig | None = None) -> None:
        self.config = config or BwfConfig()

    def get_json(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """GET ``{api_url}/{endpoint}`` and return the decoded JSON body."""
        raise NotImplementedError("Implemented in Iteration 1")
