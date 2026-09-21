"""Look up a badminton player's profile and ranking data from bwfbadminton.com."""

from bwf_player.config import BwfConfig
from bwf_player.exceptions import (
    BlockedByCloudflareError,
    BwfClientError,
    InvalidInputError,
)
from bwf_player.http_client import BwfHttpClient
from bwf_player.history import download_player_history, format_history
from bwf_player.lookup import format_result, lookup_player
from bwf_player.matches import check_totals, get_matches
from bwf_player.models import (
    EventMatches,
    GameScore,
    HistorySummary,
    MatchPlayer,
    PlayerCandidate,
    PlayerMatch,
    PlayerProfile,
    PlayerRanking,
    PlayerResult,
    RankingEvent,
    SearchResult,
    TournamentEntry,
    TournamentHistory,
)
from bwf_player.store import HistoryStore
from bwf_player.tournaments import get_tournaments, history_window

__version__ = "0.1.0"

__all__ = [
    "BlockedByCloudflareError",
    "BwfClientError",
    "BwfConfig",
    "BwfHttpClient",
    "EventMatches",
    "GameScore",
    "HistoryStore",
    "HistorySummary",
    "InvalidInputError",
    "MatchPlayer",
    "PlayerCandidate",
    "PlayerMatch",
    "PlayerProfile",
    "PlayerRanking",
    "PlayerResult",
    "RankingEvent",
    "SearchResult",
    "TournamentEntry",
    "TournamentHistory",
    "check_totals",
    "download_player_history",
    "format_history",
    "format_result",
    "get_matches",
    "get_tournaments",
    "history_window",
    "lookup_player",
]
