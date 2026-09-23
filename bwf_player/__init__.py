"""Look up a badminton player's profile and ranking data from bwfbadminton.com."""

from bwf_player.config import BwfConfig
from bwf_player.exceptions import (
    BlockedByCloudflareError,
    BwfClientError,
    BwfNotFoundError,
    InvalidInputError,
)
from bwf_player.http_client import BwfHttpClient
from bwf_player.game_details import (
    check_against_match,
    check_internal,
    details_targets,
    format_match_details,
    get_match_details,
)
from bwf_player.history import download_player_history, format_history
from bwf_player.lookup import format_result, lookup_player
from bwf_player.matches import check_totals, get_matches
from bwf_player.models import (
    DetailPlayer,
    EventMatches,
    GameDetail,
    GameScore,
    HistorySummary,
    MatchDetails,
    MatchPlayer,
    PlayerCandidate,
    PlayerMatch,
    PlayerProfile,
    PlayerRanking,
    PlayerResult,
    RankingEvent,
    Rally,
    SearchResult,
    SideStats,
    TournamentEntry,
    TournamentHistory,
)
from bwf_player.store import HistoryStore
from bwf_player.tournaments import get_tournaments, history_window

__version__ = "0.1.0"

__all__ = [
    "BlockedByCloudflareError",
    "BwfClientError",
    "BwfNotFoundError",
    "BwfConfig",
    "BwfHttpClient",
    "DetailPlayer",
    "EventMatches",
    "GameDetail",
    "GameScore",
    "HistoryStore",
    "HistorySummary",
    "InvalidInputError",
    "MatchDetails",
    "MatchPlayer",
    "PlayerCandidate",
    "PlayerMatch",
    "PlayerProfile",
    "PlayerRanking",
    "PlayerResult",
    "RankingEvent",
    "Rally",
    "SearchResult",
    "SideStats",
    "TournamentEntry",
    "TournamentHistory",
    "check_against_match",
    "check_internal",
    "check_totals",
    "details_targets",
    "download_player_history",
    "format_history",
    "format_match_details",
    "format_result",
    "get_match_details",
    "get_matches",
    "get_tournaments",
    "history_window",
    "lookup_player",
]
