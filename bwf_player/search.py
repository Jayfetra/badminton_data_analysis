"""Player search (R1). Implemented in Iteration 1."""

from __future__ import annotations

from bwf_player.http_client import BwfHttpClient
from bwf_player.models import SearchResult


def search_player(name: str, client: BwfHttpClient | None = None) -> SearchResult:
    """Find a player by (possibly imprecise) name and return a ``SearchResult``."""
    raise NotImplementedError("Implemented in Iteration 1")
