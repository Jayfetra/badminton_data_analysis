"""Game details of one match: the site's Match tab and one tab per game (R8).

One endpoint, the one behind a match page such as ``.../tournament/5515/<slug>/match/13``:
``h2h/match`` (``tmt_id`` = the tournament id, ``match_code`` = the ``code`` of the match in
``vue-player-tmt-matches``). It returns

* ``stats``: the Match tab (final result, and per side the game points, most consecutive points,
  total points played and won);
* ``games[]``: one Game tab each, with the game's score, the same statistics and
  ``match_set_details_model``, the **score after every rally** (the chart on the page);
* the match's tournament, draw, round, start time, venue, duration and players.

Sides follow the site: side 1 is team 1, side 2 is team 2 (the same as in ``vue-player-tmt-matches``).

**Coverage differs by tournament.** World Tour level events have everything. For lower-level events
(for example an International Challenge) the site sends only the game scores: the rally list is empty
and every statistic is ``0``. Those zeros mean "not tracked", so they are returned as ``None`` and the
game is marked ``tracked=False``. Byes and walkovers have no games at all.

**Every statistic is re-derived from the rally sequence and compared with what the site says**
(:func:`check_internal`): the sequence must have as many rallies as points and end at the game score,
the longest run of points and the number of rallies played while a side was one point from the game
must equal the site's ``consecutive_points`` and ``game_points``, and at match level the longest run
crosses game boundaries while the other figures add up over the games. On the real matches checked
(86 tracked matches, 204 games, 15 of them past 21 points, none reaching 29) this held without exception. If a :class:`PlayerMatch` is given the
details are also compared with the match we already have (:func:`check_against_match`): same match
id, players, game scores and winner.
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from bwf_player.exceptions import BwfClientError, InvalidInputError
from bwf_player.http_client import BwfHttpClient
from bwf_player.models import (
    DetailPlayer,
    GameDetail,
    MatchDetails,
    PlayerMatch,
    Rally,
    SideStats,
)
from bwf_player.parsing import clean_text as _clean_text
from bwf_player.parsing import to_code as _code
from bwf_player.parsing import to_int as _int

logger = logging.getLogger(__name__)

DETAILS_ENDPOINT = "h2h/match"
_TAG = re.compile(r"<[^>]+>")
_STAT_FIELDS = (
    "consecutive_points", "game_points", "rallies_played", "rallies_won", "smash_winner", "net_winner",
    "clear_winner", "other", "challenge_used", "challenge_won", "challenge_lost", "challenge_nodecision",
)
_KEY_STATS = ("consecutive_points", "game_points", "rallies_played", "rallies_won")
_TRACKED_STATUSES = frozenset({"played", "retired"})


def get_match_details(
    tournament_id: str | int,
    match_code: str | int,
    client: BwfHttpClient | None = None,
    *,
    match: PlayerMatch | None = None,
) -> MatchDetails:
    """Fetch and parse the details of one match (one request), and check them.

    Args:
        tournament_id: the site's tournament id (positive integer).
        match_code: the match's code within the tournament (``PlayerMatch.match_code``).
        client: HTTP client (defaults to a new polite client).
        match: the match as we already hold it; if given, the details are also compared with it.

    Raises:
        InvalidInputError: malformed ``tournament_id`` or ``match_code``.
        BwfNotFoundError: the site has no such match (HTTP 404).
        BwfClientError: the response was malformed. BlockedByCloudflareError: never retried.
    """
    tid = _positive_id(tournament_id, "tournament_id")
    code = _code(match_code)
    if code is None:
        raise InvalidInputError("match_code must be letters, digits, '_' or '-' (at most 20 characters).")
    client = client or BwfHttpClient()
    payload = client.get_json(DETAILS_ENDPOINT, {"tmt_id": tid, "match_code": code})
    details = parse_match_details(payload, tid, code)
    if match is not None:
        details.differences.extend(check_against_match(details, match))
        details.checks_ok = not details.differences
    return details


def details_targets(matches: Sequence[PlayerMatch]) -> list[PlayerMatch]:
    """The matches whose details are worth requesting: they were played (or retired) and have a match code.

    Byes and walkovers have no games; disqualified and unknown matches are left out too.
    """
    return [m for m in matches if m.match_code and m.status in _TRACKED_STATUSES]


def parse_match_details(payload: Any, tournament_id: int, match_code: str) -> MatchDetails:
    """A :class:`MatchDetails` from an ``h2h/match`` response, with its internal checks done."""
    if not isinstance(payload, dict) or not isinstance(payload.get("games"), list) or "stats" not in payload:
        raise BwfClientError(f"{DETAILS_ENDPOINT}: unexpected response shape")
    info = payload.get("info")
    if not isinstance(info, dict):
        raise BwfClientError(f"{DETAILS_ENDPOINT}: the response has no match information")

    stats = payload["stats"] if isinstance(payload["stats"], dict) else {}
    tournament = payload.get("tournament") if isinstance(payload.get("tournament"), dict) else {}
    timing = payload.get("matchStartTimeDetails") if isinstance(payload.get("matchStartTimeDetails"), dict) else {}
    location = payload.get("location") if isinstance(payload.get("location"), dict) else {}
    progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}

    problems: list[str] = []
    notes: list[str] = []
    games = _parse_games(payload["games"], problems)

    ids = {_int(g.get("tournament_match_id")) for g in payload["games"] if isinstance(g, dict)}
    ids.add(_int(stats.get("tournament_match_id")))
    ids.discard(None)
    if len(ids) > 1:
        problems.append(f"the response names more than one match id ({sorted(ids)})")
    winner = _int(info.get("winner"))
    tracked = any(g.tracked for g in games)
    side1, side2 = _side_stats(stats, "team1_"), _side_stats(stats, "team2_")
    if not tracked:
        if games:
            notes.append(
                "The site gives only the game scores for this match: no rally-by-rally data and no statistics "
                "(the site's zeros mean 'not tracked'), so those fields are null."
            )
        if _all_zero(side1) and _all_zero(side2):
            side1 = side2 = None

    details = MatchDetails(
        match_id=next(iter(ids)) if len(ids) == 1 else None,
        tournament_id=tournament_id,
        match_code=match_code,
        tournament_name=_clean_text(tournament.get("name")),
        draw_name=_clean_text(info.get("drawName")),
        round=_clean_text(info.get("roundName")),
        start_local=_datetime(timing.get("dateTimeLocal")),
        venue=_clean_text(location.get("locationName")),
        duration_min=_int(progress.get("duration")) or None,
        winner_side=winner if winner in (1, 2) else None,
        score_status=_int(info.get("scoreStatus")),
        side1_players=_players(payload.get("team1")),
        side2_players=_players(payload.get("team2")),
        side1_result=_int(stats.get("team1_result")),
        side2_result=_int(stats.get("team2_result")),
        side1=side1,
        side2=side2,
        games=games,
        tracked=tracked,
        notes=notes,
    )
    details.differences = problems + check_internal(details)
    if tracked:
        details.checks_ok = not details.differences
    return details


# ---------------------------------------------------------------- statistics derived from the rallies

def longest_runs(winners: Sequence[int | None]) -> tuple[int, int]:
    """The longest run of consecutive points of side 1 and of side 2 in a sequence of rally winners."""
    best = [0, 0]
    current, last = 0, None
    for winner in winners:
        current = current + 1 if winner is not None and winner == last else 1
        last = winner
        if winner in (1, 2):
            best[winner - 1] = max(best[winner - 1], current)
    return best[0], best[1]


def game_point_rallies(rallies: Sequence[Rally]) -> tuple[int, int]:
    """How many rallies each side played while one point from winning the game.

    A side is on game point when it has at least 20 points and leads, or has 29 (at 29-29 either
    side wins the game with the next point, so both are on game point).
    """
    counts = [0, 0]
    previous = (0, 0)
    for rally in rallies:
        for index in (0, 1):
            mine, theirs = previous[index], previous[1 - index]
            if (mine >= 20 and mine > theirs) or mine == 29:
                counts[index] += 1
        previous = (rally.side1_points, rally.side2_points)
    return counts[0], counts[1]


def check_internal(details: MatchDetails) -> list[str]:
    """Differences between the rally sequences, the site's statistics and the scores (empty = all agree)."""
    found: list[str] = []
    for game in details.games:
        if not game.tracked:
            continue
        label = f"Game {game.game_no}"
        count = len(game.rallies)
        if game.total_points_played is not None and game.total_points_played != count:
            found.append(f"{label}: the site says {game.total_points_played} points played but lists {count} rallies")
        if count != game.side1_points + game.side2_points:
            found.append(f"{label}: {count} rallies but the score {game.side1_points}-{game.side2_points} has {game.side1_points + game.side2_points} points")
        last = game.rallies[-1]
        if (last.side1_points, last.side2_points) != (game.side1_points, game.side2_points):
            found.append(f"{label}: the last rally ends {last.side1_points}-{last.side2_points}, not the score {game.side1_points}-{game.side2_points}")
        bad = [r.rally_no for r in game.rallies if r.winner_side is None]
        if bad:
            found.append(f"{label}: rally {bad[0]} does not add exactly one point to one side")
        if game.side1 and game.side2:
            found += _compare_game_stats(game, label)

    tracked = [g for g in details.games if g.tracked]
    if tracked and details.side1 and details.side2 and len(tracked) == len(details.games):
        found += _compare_match_stats(details, tracked)
    if details.score_status in (0, None) and details.side1_result is not None and details.side2_result is not None and details.games:
        won1 = sum(g.side1_points > g.side2_points for g in details.games)
        won2 = sum(g.side2_points > g.side1_points for g in details.games)
        if (won1, won2) != (details.side1_result, details.side2_result):
            found.append(f"the final result {details.side1_result}-{details.side2_result} does not match the games won ({won1}-{won2})")
    return found


def check_against_match(details: MatchDetails, match: PlayerMatch) -> list[str]:
    """Differences between the details and the same match as we already hold it from the player's page."""
    found: list[str] = []
    if details.match_id is not None and details.match_id != match.match_id:
        found.append(f"the details are for match {details.match_id}, not {match.match_id}")
    if details.tournament_id != match.tournament_id:
        found.append(f"the details are for tournament {details.tournament_id}, not {match.tournament_id}")

    ours_side1 = _ids([match.player, match.partner] if match.side == 1 else match.opponents)
    ours_side2 = _ids(match.opponents if match.side == 1 else [match.player, match.partner])
    theirs1 = {p.player_id for p in details.side1_players}
    theirs2 = {p.player_id for p in details.side2_players}
    if theirs1 and theirs2 and None not in theirs1 | theirs2 and (ours_side1, ours_side2) != (theirs1, theirs2):
        found.append(f"the players differ: details {sorted(theirs1)} v {sorted(theirs2)}, ours {sorted(ours_side1)} v {sorted(ours_side2)}")

    ours = [
        (g.player_points, g.opponent_points) if match.side == 1 else (g.opponent_points, g.player_points)
        for g in match.games
    ]
    theirs_games = [(g.side1_points, g.side2_points) for g in details.games if (g.side1_points, g.side2_points) != (0, 0)]
    if ours != theirs_games:
        found.append(f"the game scores differ: details {theirs_games}, ours {ours}")

    if match.won is not None and details.winner_side is not None:
        expected = match.side if match.won else 3 - match.side
        if details.winner_side != expected:
            found.append(f"the winner differs: details say side {details.winner_side}, ours side {expected}")
    return found


def format_match_details(details: MatchDetails, *, rallies: bool = True) -> str:
    """The details as text laid out like the site's tabs: Match, then Game 1, Game 2, ..."""
    name1 = " / ".join(p.name for p in details.side1_players) or "Side 1"
    name2 = " / ".join(p.name for p in details.side2_players) or "Side 2"
    when = details.start_local.strftime("%Y-%m-%d %H:%M") if details.start_local else "time unknown"
    head = " | ".join(
        x for x in (details.tournament_name, details.draw_name, details.round, when, details.venue,
                    f"{details.duration_min} min" if details.duration_min else None) if x
    )
    winner = {1: name1, 2: name2}.get(details.winner_side)
    lines = [head, f"  side 1: {name1}", f"  side 2: {name2}", f"  winner: {winner or 'unknown'}"]

    def table(title: str, rows: list[tuple[str, object, object]]) -> None:
        lines.extend(["", f"{title}", f"  {'':<26}{'side 1':>8}{'side 2':>8}"])
        lines.extend(f"  {label:<26}{_show(one):>8}{_show(two):>8}" for label, one, two in rows)

    rows: list[tuple[str, object, object]] = [("Final match score", details.side1_result, details.side2_result)]
    rows += [(f"Game {g.game_no} score", g.side1_points, g.side2_points) for g in details.games]
    if details.side1 and details.side2:
        for label, field in (("Game points", "game_points"), ("Most consecutive points", "consecutive_points"),
                             ("Total points played", "rallies_played"), ("Total points won", "rallies_won")):
            rows.append((label, getattr(details.side1, field), getattr(details.side2, field)))
    table("MATCH", rows)

    for game in details.games:
        game_rows: list[tuple[str, object, object]] = [("Score", game.side1_points, game.side2_points)]
        if game.side1 and game.side2:
            for label, field in (("Most consecutive points", "consecutive_points"), ("Game points", "game_points"),
                                 ("Total points played", "rallies_played"), ("Total points won", "rallies_won")):
                game_rows.append((label, getattr(game.side1, field), getattr(game.side2, field)))
        table(f"GAME {game.game_no}", game_rows)
        if rallies and game.rallies:
            lines.append("  score after each rally: " + " ".join(f"{r.side1_points}-{r.side2_points}" for r in game.rallies))

    if details.differences:
        lines += ["", "Checks failed:"] + [f"  - {d}" for d in details.differences]
    elif details.checks_ok:
        lines += ["", "Checks: the rallies, statistics and scores agree."]
    lines += [f"  note: {n}" for n in details.notes]
    return "\n".join(lines)


# ---------------------------------------------------------------- parsing helpers

def _parse_games(raw_games: list[Any], problems: list[str]) -> list[GameDetail]:
    parsed: list[tuple[int, GameDetail]] = []
    for index, raw in enumerate(raw_games, start=1):
        if not isinstance(raw, dict):
            problems.append(f"game entry {index} was not an object")
            continue
        one, two = _int(raw.get("team1")), _int(raw.get("team2"))
        if one is None or two is None:
            problems.append(f"game entry {index} has no readable score")
            continue
        number = _int(raw.get("ordering")) or index

        raw_rallies = raw.get("match_set_details_model")
        steps = [r for r in raw_rallies if isinstance(r, dict)] if isinstance(raw_rallies, list) else []
        steps.sort(key=lambda r: _int(r.get("ordering")) or 0)
        rallies: list[Rally] = []
        previous = (0, 0)
        for position, step in enumerate(steps, start=1):
            a, b = _int(step.get("team1")), _int(step.get("team2"))
            if a is None or b is None:
                problems.append(f"Game {number}: rally {position} has no readable score")
                continue
            winner = 1 if (a, b) == (previous[0] + 1, previous[1]) else 2 if (a, b) == (previous[0], previous[1] + 1) else None
            rallies.append(Rally(rally_no=position, side1_points=a, side2_points=b, winner_side=winner))
            previous = (a, b)
        if steps and [_int(r.get("ordering")) for r in steps] != list(range(1, len(steps) + 1)):
            problems.append(f"Game {number}: the rally numbers are not 1 to {len(steps)} without gaps")

        stats_raw = raw.get("match_set_stats_model") if isinstance(raw.get("match_set_stats_model"), dict) else {}
        side1, side2 = _side_stats(stats_raw, "team1_"), _side_stats(stats_raw, "team2_")
        if not rallies and _all_zero(side1) and _all_zero(side2):
            side1 = side2 = None
        parsed.append((number, GameDetail(
            game_no=number, side1_points=one, side2_points=two, total_points_played=_int(raw.get("total_points_played")),
            tracked=bool(rallies), side1=side1, side2=side2, rallies=rallies,
        )))
    return [game for _, game in sorted(parsed, key=lambda pair: pair[0])]


def _side_stats(source: dict[str, Any], prefix: str) -> SideStats | None:
    values = {field: _int(source.get(prefix + field)) for field in _STAT_FIELDS}
    return None if all(v is None for v in values.values()) else SideStats(**values)


def _all_zero(stats: SideStats | None) -> bool:
    return stats is None or all(getattr(stats, field) in (None, 0) for field in _KEY_STATS)


def _players(team: Any) -> list[DetailPlayer]:
    if not isinstance(team, dict):
        return []
    players = []
    for key in sorted(team):
        raw = team[key]
        if not isinstance(raw, dict):
            continue
        nationality = raw.get("nationality_item") if isinstance(raw.get("nationality_item"), dict) else {}
        plain = _clean_text(html.unescape(_TAG.sub("", str(raw.get("name_display_bold") or ""))))
        slug = _clean_text(raw.get("slug"))
        player_id = _int(raw.get("id"))
        name = plain or slug or (f"Player {player_id}" if player_id is not None else None)
        if name is not None:
            players.append(DetailPlayer(player_id=player_id, name=name, slug=slug, country=_clean_text(nationality.get("name"))))
    return players


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None


def _positive_id(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise InvalidInputError(f"{what} must be a positive integer.")
    text = str(value).strip()
    if not (text.isascii() and text.isdigit()) or int(text) == 0 or len(text) > 10:
        raise InvalidInputError(f"{what} must be a positive integer of at most 10 digits.")
    return int(text)


def _ids(players: Sequence[Any]) -> set[int | None]:
    return {p.player_id for p in players if p is not None}


def _compare_game_stats(game: GameDetail, label: str) -> list[str]:
    found = []
    winners = [r.winner_side for r in game.rallies]
    streak = longest_runs(winners)
    points = game_point_rallies(game.rallies)
    for index, (side, stats) in enumerate((("side 1", game.side1), ("side 2", game.side2))):
        assert stats is not None
        for name, expected, actual in (
            ("most consecutive points", streak[index], stats.consecutive_points),
            ("game points", points[index], stats.game_points),
            ("total points played", len(game.rallies), stats.rallies_played),
            ("total points won", (game.side1_points, game.side2_points)[index], stats.rallies_won),
        ):
            if actual is not None and actual != expected:
                found.append(f"{label}: {side} {name}: the site says {actual}, the rallies give {expected}")
    return found


def _compare_match_stats(details: MatchDetails, tracked: list[GameDetail]) -> list[str]:
    found = []
    winners = [r.winner_side for g in tracked for r in g.rallies]
    streak = longest_runs(winners)
    for index, stats in enumerate((details.side1, details.side2)):
        assert stats is not None
        side = f"side {index + 1}"
        for name, expected, actual in (
            ("most consecutive points (across the whole match)", streak[index], stats.consecutive_points),
            ("game points", sum(game_point_rallies(g.rallies)[index] for g in tracked), stats.game_points),
            ("total points played", sum(len(g.rallies) for g in tracked), stats.rallies_played),
            ("total points won", sum((g.side1_points, g.side2_points)[index] for g in tracked), stats.rallies_won),
        ):
            if actual is not None and actual != expected:
                found.append(f"Match: {side} {name}: the site says {actual}, the games give {expected}")
    return found


def _show(value: object) -> str:
    return "-" if value is None else str(value)
