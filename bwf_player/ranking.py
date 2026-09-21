"""Player ranking details (R3). Implemented in Iteration 3."""

from __future__ import annotations

from bwf_player.http_client import BwfHttpClient
from bwf_player.models import PlayerRanking


def get_ranking(player_id: str, client: BwfHttpClient | None = None) -> PlayerRanking:
    """Fetch current rank and weeks-at-rank for ``player_id``."""
    raise NotImplementedError("Implemented in Iteration 3")
