"""Look up a badminton player's profile and ranking data from bwfbadminton.com."""

from bwf_player.config import BwfConfig
from bwf_player.exceptions import (
    BlockedByCloudflareError,
    BwfClientError,
    InvalidInputError,
)
from bwf_player.lookup import format_result, lookup_player
from bwf_player.models import (
    PlayerCandidate,
    PlayerProfile,
    PlayerRanking,
    PlayerResult,
    RankingEvent,
    SearchResult,
    TournamentEntry,
    TournamentHistory,
)
from bwf_player.tournaments import get_tournaments, history_window

__version__ = "0.1.0"

__all__ = [
    "BlockedByCloudflareError",
    "BwfClientError",
    "BwfConfig",
    "InvalidInputError",
    "PlayerCandidate",
    "PlayerProfile",
    "PlayerRanking",
    "PlayerResult",
    "RankingEvent",
    "SearchResult",
    "TournamentEntry",
    "TournamentHistory",
    "format_result",
    "get_tournaments",
    "history_window",
    "lookup_player",
]
