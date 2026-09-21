"""Player profile details (R2). Implemented in Iteration 2."""

from __future__ import annotations

from bwf_player.http_client import BwfHttpClient
from bwf_player.models import PlayerProfile


def get_profile(player_id: str, client: BwfHttpClient | None = None) -> PlayerProfile:
    """Fetch nationality, height and playing hand for ``player_id``."""
    raise NotImplementedError("Implemented in Iteration 2")
