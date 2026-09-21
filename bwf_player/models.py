"""Result models. Field names here are the package's own schema, not BWF's raw JSON."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

SearchStatus = Literal["found", "ambiguous", "not_found"]


class PlayerCandidate(BaseModel):
    """A player returned by search, with the fuzzy-match confidence (0-100)."""

    player_id: str
    slug: str
    name: str
    country: str | None = None
    profile_url: str
    score: float = Field(ge=0, le=100)


class SearchResult(BaseModel):
    """Outcome of a name search. Never raises for 'no match'; check `status`."""

    query: str
    status: SearchStatus
    best_match: PlayerCandidate | None = None
    candidates: list[PlayerCandidate] = Field(default_factory=list)
    message: str | None = None


class PlayerProfile(BaseModel):
    """Personal details (R2).

    A field the site does not list is None, named in `missing_fields`, and explained in
    `notes`. `player_found` is False only when the site has no player with this id.
    """

    player_id: str
    player_found: bool = True
    name: str | None = None
    nationality: str | None = None
    height_cm: float | None = None
    playing_hand: Literal["Right", "Left"] | None = None
    missing_fields: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class RankingEvent(BaseModel):
    """A ranking a player appears in, e.g. id "6-0" = "MEN'S SINGLES"."""

    id: str
    name: str


class PlayerRanking(BaseModel):
    """Ranking details (R3) for one event.

    `is_ranked=False` means the site lists no current rank; `notes` says why.
    `weeks_at_current_rank` counts consecutive weekly ranking lists, ending with the latest one
    (`as_of`), in which the player held `current_rank`; `at_rank_since` is the first of them.
    """

    player_id: str
    event: RankingEvent | None = None
    other_events: list[RankingEvent] = Field(default_factory=list)
    is_ranked: bool = False
    current_rank: int | None = None
    weeks_at_current_rank: int | None = None
    at_rank_since: date | None = None
    as_of: date | None = None
    weeks_source: Literal["derived_from_history"] | None = None
    notes: list[str] = Field(default_factory=list)


class TournamentEntry(BaseModel):
    """One player's entry in one event of one tournament (R4): the tournament and the result.

    A player who enters two events (e.g. women's singles and doubles) has two entries for the
    tournament. `position` is the site's own label ("1st", "2nd", "3rd", "QF", "R16", "Qual. R32");
    None means the site gives no individual position (team events show "N/A"). The counts are the
    site's summary for this event, and are what the parsed matches are checked against.
    `event_code` and `event_id` are None for a tournament the site lists with no event.
    """

    tournament_id: int
    name: str
    category: str | None = None
    start_date: date
    end_date: date
    location: str | None = None
    country: str | None = None
    type_id: int | None = None
    url: str | None = None
    event_code: str | None = None
    event_id: int | None = None
    position: str | None = None
    matches_won: int | None = None
    matches_lost: int | None = None
    games_won: int | None = None
    games_lost: int | None = None
    points_for: int | None = None
    points_against: int | None = None


class TournamentHistory(BaseModel):
    """Tournaments a player entered between `since` and `until` (inclusive; overlap counts)."""

    player_id: str
    since: date
    until: date
    entries: list[TournamentEntry] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PlayerResult(BaseModel):
    """End-to-end result the notebook displays."""

    search: SearchResult
    profile: PlayerProfile | None = None
    ranking: PlayerRanking | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
