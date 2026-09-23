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


MatchStatus = Literal["played", "bye", "walkover", "retired", "disqualified", "unknown"]


class MatchPlayer(BaseModel):
    """A player in a match (the subject, a partner or an opponent). `country` is the ISO code."""

    player_id: int | None = None
    name: str
    country: str | None = None


class GameScore(BaseModel):
    """One game, from the subject's side: `player_points` are the subject's team's points."""

    game_no: int = Field(ge=1)
    player_points: int = Field(ge=0)
    opponent_points: int = Field(ge=0)


class PlayerMatch(BaseModel):
    """One match seen from the subject player's side (R5, R6).

    `partner` is None in singles; `opponents` has one player in singles and two in doubles (empty
    only if the site names none). `side` (1 or 2) is the subject's side in the site's own match
    record, which is what the database keeps. `won` is None for a bye (nobody was played) and if
    the site's winner is unusable. `games` is empty for a bye and a walkover; a retirement keeps the
    points of the game in progress. Filter `status == "played"` for matches that were really played.
    `match_code` is the site's number of the match within its tournament (the `match/13` of the
    match page URL); with the tournament id it addresses the match's game details.
    `notes` holds anything odd about this one match.
    """

    match_id: int
    match_code: str | None = None
    tournament_id: int
    draw_id: int | None = None
    draw_name: str | None = None
    round: str | None = None
    match_date: date | None = None
    duration_min: int | None = None
    side: Literal[1, 2]
    player: MatchPlayer
    partner: MatchPlayer | None = None
    opponents: list[MatchPlayer] = Field(default_factory=list)
    won: bool | None = None
    status: MatchStatus = "played"
    games: list[GameScore] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class EventMatches(BaseModel):
    """Every match of one event entry, and whether it agrees with the site's own totals.

    `totals_agree` is True when matches, games and points won/lost equal the totals on the
    tournament entry, False when they differ (`notes` lists which), None when the entry has no
    totals to compare with.
    """

    tournament_id: int
    event_code: str | None = None
    event_id: int | None = None
    matches: list[PlayerMatch] = Field(default_factory=list)
    totals_agree: bool | None = None
    notes: list[str] = Field(default_factory=list)


class SideStats(BaseModel):
    """One side's statistics for a game or a whole match, as the site lists them.

    `consecutive_points` is the longest run of points in a row, `game_points` the number of rallies
    played while the side was one point from winning the game, `rallies_played` the rallies of the
    game (or match) and `rallies_won` the side's points. The tracking fields (`smash_winner`,
    `net_winner`, `clear_winner`, `other`, `challenge_*`) are on the site's payload but empty in
    every match seen; they are kept as sent.
    """

    consecutive_points: int | None = None
    game_points: int | None = None
    rallies_played: int | None = None
    rallies_won: int | None = None
    smash_winner: int | None = None
    net_winner: int | None = None
    clear_winner: int | None = None
    other: int | None = None
    challenge_used: int | None = None
    challenge_won: int | None = None
    challenge_lost: int | None = None
    challenge_nodecision: int | None = None


class Rally(BaseModel):
    """The score after one rally, in the site's side orientation. `winner_side` is None if the step is not one point."""

    rally_no: int = Field(ge=1)
    side1_points: int = Field(ge=0)
    side2_points: int = Field(ge=0)
    winner_side: Literal[1, 2] | None = None


class GameDetail(BaseModel):
    """One game's tab on the match page. Side 1 and side 2 are the site's own (team 1 and team 2).

    `tracked` is False for tournaments where the site gives only the score: there is then no rally
    sequence and `side1`/`side2` are None (the site sends zeros there, which mean "not tracked").
    """

    game_no: int = Field(ge=1)
    side1_points: int = Field(ge=0)
    side2_points: int = Field(ge=0)
    total_points_played: int | None = None
    tracked: bool = False
    side1: SideStats | None = None
    side2: SideStats | None = None
    rallies: list[Rally] = Field(default_factory=list)


class DetailPlayer(BaseModel):
    """A player on the match page. `country` is the country name as the page shows it."""

    player_id: int | None = None
    name: str
    slug: str | None = None
    country: str | None = None


class MatchDetails(BaseModel):
    """Everything on the site's match page: the Match tab and one tab per game (R8).

    Sides follow the site (side 1 = team 1). `side1`/`side2` are the Match tab's statistics (None
    when the site does not track the match). `differences` lists every check that failed (the
    rally sequence, the statistics and, if a `PlayerMatch` was given, the data we already hold);
    `checks_ok` is True when there is none, False when there is one, None when nothing could be
    checked. `notes` explains anything else, for example that a game is untracked.
    """

    match_id: int | None = None
    tournament_id: int
    match_code: str
    tournament_name: str | None = None
    draw_name: str | None = None
    round: str | None = None
    start_local: datetime | None = None
    venue: str | None = None
    duration_min: int | None = None
    winner_side: Literal[1, 2] | None = None
    score_status: int | None = None
    side1_players: list[DetailPlayer] = Field(default_factory=list)
    side2_players: list[DetailPlayer] = Field(default_factory=list)
    side1_result: int | None = None
    side2_result: int | None = None
    side1: SideStats | None = None
    side2: SideStats | None = None
    games: list[GameDetail] = Field(default_factory=list)
    tracked: bool = False
    checks_ok: bool | None = None
    differences: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class HistorySummary(BaseModel):
    """What one `download_player_history` call found and saved.

    `search` is None when a player id was given instead of a name. If the name matched no single
    player, or the player entered no tournament in the window, nothing is saved (`database` is
    None) and `notes` says why. `all_totals_agree` is True when every event's parsed matches
    reproduce the site's own totals, False if any event differs (listed in `events_disagreeing`),
    None when no event had totals to compare. `history` and `event_matches` hold the data itself.

    Game details (R8): `game_details` matches had their details downloaded (`game_details_tracked`
    with rally data, `game_details_untracked` with only game scores), `game_details_skipped` were not
    requested (byes, walkovers) and `game_details_not_found` had no page on the site. `all_details_agree`
    is True when every downloaded match passed all checks, False if any did not (listed in
    `game_details_disagreeing`), None when none was downloaded. `details` holds them.
    """

    search: SearchResult | None = None
    player_id: str | None = None
    player_name: str | None = None
    since: date | None = None
    until: date | None = None
    tournaments: int = 0
    events: int = 0
    matches: int = 0
    matches_by_status: dict[str, int] = Field(default_factory=dict)
    games: int = 0
    events_checked: int = 0
    events_disagreeing: list[str] = Field(default_factory=list)
    all_totals_agree: bool | None = None
    game_details: int = 0
    game_details_tracked: int = 0
    game_details_untracked: int = 0
    game_details_skipped: int = 0
    game_details_not_found: int = 0
    game_details_disagreeing: list[str] = Field(default_factory=list)
    all_details_agree: bool | None = None
    rallies: int = 0
    database: str | None = None
    csv_files: dict[str, str] = Field(default_factory=dict)
    history: TournamentHistory | None = None
    event_matches: list[EventMatches] = Field(default_factory=list)
    details: list[MatchDetails] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PlayerResult(BaseModel):
    """End-to-end result the notebook displays."""

    search: SearchResult
    profile: PlayerProfile | None = None
    ranking: PlayerRanking | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
