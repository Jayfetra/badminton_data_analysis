"""Matches of one event entry: partner, opponents and the points of every game (R5, R6).

One endpoint, the one behind the "View Match Breakdown" link of the site's player page:
``vue-player-tmt-matches`` (``playerId``, ``tmtId``, ``tmtType``, ``eventId``). ``results`` is
``{draw_id: matches}`` (one draw for a knockout event; a qualification draw and a main draw, or
group stage and knockout, give several). A draw's matches are usually a list but can also be an
object with gapped keys (``{"2": {...}}``), so both are accepted.

Each match is stored by the site as side 1 versus side 2, and the subject can be on either side.
The side is found from the player ids, then partner, opponents and game points are read from the
subject's point of view. Game points come from ``match_set_model`` (``{ordering, team1, team2}``);
the ``team1Score``/``team2Score`` HTML (``<span>21</span>...``) is only a fallback.

The result of every event is checked against the totals the tournament list gives for it
(:func:`check_totals`), so a parsing mistake shows up instead of passing silently.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from bwf_player.exceptions import BwfClientError
from bwf_player.http_client import BwfHttpClient
from bwf_player.models import (
    EventMatches,
    GameScore,
    MatchPlayer,
    MatchStatus,
    PlayerMatch,
    TournamentEntry,
)
from bwf_player.names import validate_player_id
from bwf_player.parsing import clean_text as _clean_text
from bwf_player.parsing import to_code as _code
from bwf_player.parsing import to_date as _date
from bwf_player.parsing import to_int as _int

logger = logging.getLogger(__name__)

MATCHES_ENDPOINT = "vue-player-tmt-matches"
_SPAN = re.compile(r"<span[^>]*>\s*([0-9]+)\s*</span>")
# The site's own reading of `score_status` (its match template: WO / RET / DSQ).
_STATUS_BY_CODE: dict[int, MatchStatus] = {0: "played", 1: "walkover", 2: "retired", 3: "disqualified"}
_BYE = re.compile(r"\bBYE\b", re.IGNORECASE)


def get_matches(
    player_id: str | int, entry: TournamentEntry, client: BwfHttpClient | None = None
) -> EventMatches:
    """Fetch and parse every match ``player_id`` played in the event of ``entry`` (one request).

    An entry without an event id (the site lists a tournament with no event) makes no request
    and returns no matches, with a note.

    Raises:
        InvalidInputError: malformed ``player_id``.
        BwfClientError: the response was malformed. BlockedByCloudflareError: never retried.
    """
    pid = validate_player_id(player_id)
    result = EventMatches(
        tournament_id=entry.tournament_id, event_code=entry.event_code, event_id=entry.event_id
    )
    if entry.event_id is None:
        result.notes.append("The site lists no event for this tournament, so there are no matches to fetch.")
        return result

    client = client or BwfHttpClient()
    payload = client.get_json(MATCHES_ENDPOINT, _params(pid, entry))
    result.matches, result.notes = parse_matches(payload, int(pid), entry.tournament_id)
    result.totals_agree, differences = check_totals(entry, result.matches)
    result.notes.extend(differences)
    return result


def parse_matches(
    payload: Any, player_id: int, tournament_id: int
) -> tuple[list[PlayerMatch], list[str]]:
    """(matches oldest first, notes) from a ``vue-player-tmt-matches`` response.

    A match that cannot be read (no id, or the subject is not in it) is skipped and counted in
    the notes rather than failing the whole event.
    """
    if not isinstance(payload, dict) or "results" not in payload:
        raise BwfClientError(f"{MATCHES_ENDPOINT}: unexpected response shape")
    results = payload["results"]
    if results is None or results == []:
        return [], []
    if not isinstance(results, dict):
        raise BwfClientError(f"{MATCHES_ENDPOINT}: unexpected response shape")

    matches: dict[int, tuple[str, PlayerMatch]] = {}
    problems: list[str] = []
    for draw_key, draw in results.items():
        raw_matches = list(draw.values()) if isinstance(draw, dict) else draw
        if not isinstance(raw_matches, list):
            problems.append(f"draw {draw_key} has an unreadable list of matches")
            continue
        for raw in raw_matches:
            parsed, problem = _parse_match(raw, player_id, tournament_id, draw_key)
            if parsed is None:
                problems.append(problem or "unreadable match")
            else:
                sort_key, match = parsed
                matches.setdefault(match.match_id, (sort_key, match))

    ordered = [m for _, m in sorted(matches.values(), key=lambda pair: (pair[0], pair[1].match_id))]
    notes = []
    if problems:
        notes.append(f"Skipped {len(problems)} match(es) that could not be read: " + "; ".join(sorted(set(problems))) + ".")
    return ordered, notes


def check_totals(entry: TournamentEntry, matches: list[PlayerMatch]) -> tuple[bool | None, list[str]]:
    """Compare the parsed matches with the totals on ``entry``.

    Returns (True, []) if every total the entry has is reproduced, (False, differences) if not,
    and (None, []) if the entry has no totals. Games and points are counted by the points of
    each game, matches by ``won``. The site counts a bye as a match won (checked on real events),
    so byes are added to the wins here even though ``won`` is None for them.
    """
    actual = {
        "matches won": sum(1 for m in matches if m.won or m.status == "bye"),
        "matches lost": sum(1 for m in matches if m.won is False),
        "games won": sum(g.player_points > g.opponent_points for m in matches for g in m.games),
        "games lost": sum(g.player_points < g.opponent_points for m in matches for g in m.games),
        "points for": sum(g.player_points for m in matches for g in m.games),
        "points against": sum(g.opponent_points for m in matches for g in m.games),
    }
    expected = {
        "matches won": entry.matches_won,
        "matches lost": entry.matches_lost,
        "games won": entry.games_won,
        "games lost": entry.games_lost,
        "points for": entry.points_for,
        "points against": entry.points_against,
    }
    comparable = {k: v for k, v in expected.items() if v is not None}
    if not comparable:
        return None, []
    differences = [
        f"{name}: the site's totals say {value}, the parsed matches give {actual[name]}"
        for name, value in comparable.items()
        if actual[name] != value
    ]
    return (not differences), differences


def _parse_match(
    raw: Any, player_id: int, tournament_id: int, draw_key: str
) -> tuple[tuple[str, PlayerMatch] | None, str | None]:
    if not isinstance(raw, dict):
        return None, "a match entry was not an object"
    match_id = _int(raw.get("id"))
    if match_id is None:
        return None, "a match without an id"

    team1 = [p for p in (_player(raw, 1, 1), _player(raw, 1, 2)) if p is not None]
    team2 = [p for p in (_player(raw, 2, 1), _player(raw, 2, 2)) if p is not None]
    on1 = any(p.player_id == player_id for p in team1)
    on2 = any(p.player_id == player_id for p in team2)
    if on1 == on2:
        return None, f"match {match_id} does not name the player on exactly one side"
    side = 1 if on1 else 2
    mine, theirs = (team1, team2) if side == 1 else (team2, team1)
    subject = next(p for p in mine if p.player_id == player_id)
    partner = next((p for p in mine if p is not subject), None)

    notes: list[str] = []
    status = _status(raw)
    if status == "played" and not theirs and _is_bye(raw):
        status = "bye"
    games, game_notes = _games(raw, side)
    if status == "played" and not _is_finished(raw):  # a match that has not been played to the end
        status = "in_progress" if games else "scheduled"
    winner = _int(raw.get("winner"))
    no_result_expected = status in ("bye", "scheduled", "in_progress")
    won: bool | None = (winner == side) if winner in (1, 2) and not no_result_expected else None
    if won is None and not no_result_expected:
        notes.append("The site gives no usable winner for this match.")
    elif won is not None and isinstance(raw.get("player_win"), bool) and raw["player_win"] != won:
        notes.append("The site's own player_win flag disagrees with its winner; the winner is used.")

    notes.extend(game_notes)
    if status == "played" and not games:
        notes.append("No game scores were listed for a match marked as played.")
    if status == "played" and not theirs:
        notes.append("The site names no opponent for this match.")

    started, sort_key = _start(raw)
    duration = _int(raw.get("duration")) or None
    match = PlayerMatch(
        match_id=match_id,
        match_code=_code(raw.get("code")),
        tournament_id=tournament_id,
        draw_id=_int(raw.get("tournament_draw_id")) or _int(draw_key),
        draw_name=_clean_text(raw.get("draw_name")),
        round=_clean_text(raw.get("round_name")),
        match_date=started,
        duration_min=duration,
        side=side,
        player=subject,
        partner=partner,
        opponents=theirs,
        won=won,
        status=status,
        games=games,
        notes=notes,
    )
    return (sort_key, match), None


def _player(raw: dict[str, Any], team: int, slot: int) -> MatchPlayer | None:
    prefix = f"t{team}p{slot}"
    model = raw.get(f"{prefix}_player_model")
    model = model if isinstance(model, dict) else {}
    player_id = _int(model.get("id"))
    if player_id is None:
        player_id = _int(raw.get(f"team{team}_player{slot}_id"))
    name = _clean_text(model.get("name_display"))
    if name is None:
        name = _clean_text(
            " ".join(str(raw.get(f"{prefix}_{part}") or "") for part in ("firstname", "lastname"))
        )
    if player_id is None and name is None:
        return None
    return MatchPlayer(
        player_id=player_id, name=name or f"Player {player_id}", country=_clean_text(raw.get(f"{prefix}_country"))
    )


def _games(raw: dict[str, Any], side: int) -> tuple[list[GameScore], list[str]]:
    """Game points from the subject's side; 0-0 games (never played) are dropped."""
    pairs: list[tuple[int, int]] | None = None
    notes: list[str] = []
    sets = raw.get("match_set_model")
    if isinstance(sets, list) and sets:
        rows = []
        for index, item in enumerate(sets):
            one = _int(item.get("team1")) if isinstance(item, dict) else None
            two = _int(item.get("team2")) if isinstance(item, dict) else None
            if one is None or two is None:
                notes.append("A game score could not be read and was left out.")
                continue
            order = _int(item.get("ordering"))
            rows.append((order if order is not None else index + 1, one, two))
        pairs = [(one, two) for _, one, two in sorted(rows, key=lambda row: row[0])]
    else:
        first = [int(n) for n in _SPAN.findall(str(raw.get("team1Score") or ""))]
        second = [int(n) for n in _SPAN.findall(str(raw.get("team2Score") or ""))]
        if first and len(first) == len(second):
            pairs = list(zip(first, second))
            notes.append("Game scores were read from the score text (no structured game list).")

    games = []
    for one, two in pairs or []:
        if one == 0 and two == 0:
            continue
        mine, theirs = (one, two) if side == 1 else (two, one)
        games.append(GameScore(game_no=len(games) + 1, player_points=mine, opponent_points=theirs))

    recorded = (_int(raw.get("result_team1")), _int(raw.get("result_team2")))
    if games and None not in recorded and _status(raw) == "played":
        won_by_1 = sum(1 for one, two in (pairs or []) if one > two)
        won_by_2 = sum(1 for one, two in (pairs or []) if two > one)
        if (won_by_1, won_by_2) != recorded:
            notes.append("The game scores do not add up to the game result the site records for this match.")
    return games, notes


def _status(raw: dict[str, Any]) -> MatchStatus:
    code = _int(raw.get("score_status"))
    if code in _STATUS_BY_CODE:
        return _STATUS_BY_CODE[code]
    name = (_clean_text(raw.get("status_name")) or "").casefold()
    if not name and code is None:
        return "played"
    return {"walkover": "walkover", "retired": "retired", "disqualified": "disqualified"}.get(name, "unknown")


def _is_finished(raw: dict[str, Any]) -> bool:
    """The site's ``match_state`` is "F" for a finished match ("N" for one not started); no state counts as finished."""
    state = _clean_text(raw.get("match_state"))
    return state is None or state.upper() == "F"


def _is_bye(raw: dict[str, Any]) -> bool:
    """The site shows a bye as the text "BYE" in place of a score."""
    return any(_BYE.search(str(raw.get(key) or "")) for key in ("team1Score", "team2Score"))


def _start(raw: dict[str, Any]) -> tuple[date | None, str]:
    """(local match date, sort key) from the start-time details, falling back to ``match_time``.

    ``match_time_utc`` is only the day (midnight), so two matches on one day tie on it; the
    details carry the real start (``actualTimeUTC``, else the scheduled ``timeUTC``), which
    keeps a day's rounds in playing order.
    """
    details = raw.get("match_start_time_details")
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except ValueError:
            details = None
    if not isinstance(details, dict):
        details = {}
    local = _date(details.get("dateLocal")) or _date(raw.get("match_time"))

    day, clock = _date(details.get("dateUTC")), details.get("actualTimeUTC") or details.get("timeUTC")
    if day is not None and isinstance(clock, str) and clock.strip():
        return local, f"{day} {clock.strip()}"
    return local, str(raw.get("match_time_utc") or local or "")


def _params(player_id: str, entry: TournamentEntry) -> dict[str, Any]:
    return {
        "playerId": player_id,
        "tmtId": entry.tournament_id,
        "tmtType": entry.type_id if entry.type_id is not None else 0,
        "eventId": entry.event_id,
        "activeTab": 3,
        "isPara": "false",
        "drawCount": 1,
        "locale": "en",
    }
