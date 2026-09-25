"""Deep-dive analysis of one player's saved history (R9).

Reads the SQLite database written by :class:`bwf_player.store.HistoryStore` (the tables and the
views ``player_match_view``, ``player_match_stats_view`` and ``player_game_view``) and answers five
questions about one player over a date window:

1. **How many tournaments** did the player enter (:func:`count_tournaments`).
2. **Rest and time on tour**: how long the player was competing, and the rests between tournaments
   (:func:`activity`).
3. **How far in each round**: how often the player reached R64, R32, R16, QF, SF, the final, and won
   (:func:`round_progress`).
4. **Two-game and three-game matches**: wins and losses by number of games (:func:`game_split`).
5. **Consecutive points and winning**: is the player with the longer run of points more likely to win
   (:func:`run_correlation`).

Definitions worth knowing (they are repeated in each result's notes where they matter):

* A tournament belongs to the window when its dates overlap it (the same rule as the download).
* The player is *on tour* from the first to the last day the player played a match at a tournament; a *rest*
  is a stretch of full days between two tournaments without a match. Only tournaments in the BWF
  data are known: matches in other competitions (club leagues, exhibitions) are not, so a "rest" can
  contain other play.
* Team events (Thomas/Uber/Sudirman Cup, Asian Games team event) and group stages (the World Tour
  Finals) have no knockout rounds and are reported separately from the round funnel.
* Byes, walkovers and retirements: a bye counts as reaching and winning that round; a walkover counts
  by its result; a retirement counts by its result; matches with a retirement are left out of the
  game-split and correlation questions.
* A correlation is not causation. The player with the longer run of points usually also won more
  points overall, which makes winning likelier by itself; :func:`run_correlation` shows how much the
  run adds beyond the points balance (the partial correlation).
"""

from __future__ import annotations

import random
import sqlite3
import statistics
from collections import Counter
from datetime import date, timedelta
from typing import Literal, Sequence

from pydantic import BaseModel, Field

_KNOCKOUT_ROUNDS = ("R128", "R64", "R32", "R16", "QF", "SF", "Final")
_ALWAYS_SHOWN = ("R64", "R32", "R16", "QF", "SF", "Final")
_OPEN = ("scheduled", "in_progress")  # matches that are not finished yet
_BUCKETS = (("1-6 days", 1, 6), ("7-13 days", 7, 13), ("14-27 days", 14, 27), ("28 days or more", 28, 10**6))


# ------------------------------------------------------------------ result models

class TournamentCount(BaseModel):
    """How many tournaments and events the player entered in the window."""

    since: date
    until: date
    tournaments: int = 0
    events: int = 0
    individual_tournaments: int = 0
    team_tournaments: int = 0
    by_category: dict[str, int] = Field(default_factory=dict)
    first_start: date | None = None
    last_end: date | None = None


class TournamentSpan(BaseModel):
    """One tournament: its scheduled dates and the days the player was actually competing."""

    tournament_id: int
    name: str
    category: str | None = None
    team_event: bool = False
    start_date: date
    end_date: date
    first_match: date
    last_match: date
    matches: int
    days_on_court: int
    days_present: int


class RestPeriod(BaseModel):
    """Full days without a match between two tournaments (days >= 1)."""

    after: str
    before: str
    start: date
    end: date
    days: int


class Activity(BaseModel):
    """Time on tour and rests over the window."""

    since: date
    until: date
    window_days: int
    spans: list[TournamentSpan] = Field(default_factory=list)
    days_present: int = 0
    days_on_court: int = 0
    scheduled_days: int = 0
    average_stay_days: float | None = None
    share_present: float = 0.0
    rest_days_total: int = 0
    rest_before_first_days: int = 0
    rest_after_last_days: int = 0
    rests: list[RestPeriod] = Field(default_factory=list)
    back_to_back: int = 0
    overlapping: int = 0
    longest_rest: RestPeriod | None = None
    average_rest_days: float | None = None
    median_rest_days: float | None = None
    buckets: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class RoundCount(BaseModel):
    """How often the player reached a round of a knockout event, and what happened there.

    ``reached == won + lost + pending``; ``pending`` is a match scheduled or under way but not finished.
    """

    round: str
    reached: int = 0
    won: int = 0
    lost: int = 0
    pending: int = 0


class GroupOrTeamEvent(BaseModel):
    tournament: str
    event_code: str | None = None
    kind: Literal["team", "group"]
    matches_won: int = 0
    matches_lost: int = 0
    position: str | None = None


class RoundProgress(BaseModel):
    """The round funnel over the player's individual knockout events."""

    since: date
    until: date
    knockout_events: int = 0
    rounds: list[RoundCount] = Field(default_factory=list)
    finals: int = 0
    champion: int = 0
    runner_up: int = 0
    qualifying_events: int = 0
    group_or_team: list[GroupOrTeamEvent] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class GameSplit(BaseModel):
    """Matches by number of games (best of three), for played matches only."""

    since: date
    until: date
    matches: int = 0
    wins_2_0: int = 0
    wins_2_1: int = 0
    losses_1_2: int = 0
    losses_0_2: int = 0
    other: int = 0
    excluded: int = 0
    won_after_winning_game_1: int = 0
    matches_after_winning_game_1: int = 0
    won_after_losing_game_1: int = 0
    matches_after_losing_game_1: int = 0
    notes: list[str] = Field(default_factory=list)


class RunComparison(BaseModel):
    label: str
    n: int
    wins: int
    win_pct: float | None = None


class RunCorrelation(BaseModel):
    """Does the longer run of consecutive points go with winning? (match level or game level)"""

    since: date
    until: date
    level: Literal["match", "game"]
    n: int = 0
    comparison: list[RunComparison] = Field(default_factory=list)
    avg_player_run_when_won: float | None = None
    avg_player_run_when_lost: float | None = None
    avg_opponent_run_when_won: float | None = None
    avg_opponent_run_when_lost: float | None = None
    r_run_difference_and_win: float | None = None
    p_value: float | None = None
    r_run_difference_and_points_difference: float | None = None
    partial_r: float | None = None
    strength: str = "not enough data"
    notes: list[str] = Field(default_factory=list)


class DeepDive(BaseModel):
    player_id: int
    player_name: str | None = None
    count: TournamentCount
    activity: Activity
    rounds: RoundProgress
    games: GameSplit
    runs_by_match: RunCorrelation
    runs_by_game: RunCorrelation


# ------------------------------------------------------------------ 1. how many tournaments

def count_tournaments(connection: sqlite3.Connection, player_id: int, since: date, until: date) -> TournamentCount:
    """Tournaments and events the player entered whose dates overlap ``since``..``until``."""
    rows = connection.execute(
        """SELECT t.tournament_id, t.category, t.type_id, t.start_date, t.end_date
           FROM results r JOIN tournaments t ON t.tournament_id = r.tournament_id
           WHERE r.player_id = ? AND t.end_date >= ? AND t.start_date <= ?""",
        (player_id, since.isoformat(), until.isoformat()),
    ).fetchall()
    tournaments = {}
    for tournament_id, category, type_id, start, end in rows:
        tournaments[tournament_id] = (category, type_id, start, end)
    categories = Counter((c or "(no category)") for c, _, _, _ in tournaments.values())
    team = sum(1 for _, type_id, _, _ in tournaments.values() if type_id == 1)
    return TournamentCount(
        since=since,
        until=until,
        tournaments=len(tournaments),
        events=len(rows),
        individual_tournaments=len(tournaments) - team,
        team_tournaments=team,
        by_category=dict(categories.most_common()),
        first_start=min((date.fromisoformat(v[2]) for v in tournaments.values()), default=None),
        last_end=max((date.fromisoformat(v[3]) for v in tournaments.values()), default=None),
    )


# ------------------------------------------------------------------ 2. rest and time on tour

def activity(connection: sqlite3.Connection, player_id: int, since: date, until: date) -> Activity:
    """When the player was competing and how long the rests between tournaments were.

    The player is present from the first to the last day of the player's matches at a tournament (a
    tournament with no dated match falls back to its scheduled dates). Only tournaments where the player
    played inside the window count (one whose scheduled dates overlap the window but where all of the player's
    matches were before or after it is left out, and named in the notes). Overlapping tournaments
    (a team event alongside another) are merged, so days are never counted twice.
    """
    window_days = (until - since).days + 1
    result = Activity(since=since, until=until, window_days=window_days)

    tournaments = connection.execute(
        """SELECT DISTINCT t.tournament_id, t.name, t.category, t.type_id, t.start_date, t.end_date
           FROM results r JOIN tournaments t ON t.tournament_id = r.tournament_id
           WHERE r.player_id = ? AND t.end_date >= ? AND t.start_date <= ? ORDER BY t.start_date, t.tournament_id""",
        (player_id, since.isoformat(), until.isoformat()),
    ).fetchall()
    played = {
        row[0]: row[1:]
        for row in connection.execute(
            """SELECT tournament_id, MIN(match_date), MAX(match_date), COUNT(*), COUNT(DISTINCT match_date)
               FROM player_match_view
               WHERE player_id = ? AND status NOT IN ('bye', 'scheduled', 'in_progress') AND match_date IS NOT NULL
               GROUP BY tournament_id""",
            (player_id,),
        )
    }
    not_started = {
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT tournament_id FROM player_match_view WHERE player_id = ? AND status IN ('scheduled', 'in_progress')",
            (player_id,),
        )
    }
    spans: list[TournamentSpan] = []
    for tournament_id, name, category, type_id, start, end in tournaments:
        first, last, matches, days = played.get(tournament_id, (None, None, 0, 0))
        if first is None and tournament_id in not_started:
            result.notes.append(f"{name}: entered, but no match has been played yet, so it is not counted here.")
            continue
        fallback = first is None
        first_day = date.fromisoformat(first or start)
        last_day = date.fromisoformat(last or end)
        spans.append(TournamentSpan(
            tournament_id=tournament_id, name=name, category=category, team_event=type_id == 1,
            start_date=date.fromisoformat(start), end_date=date.fromisoformat(end),
            first_match=first_day, last_match=last_day, matches=matches, days_on_court=days,
            days_present=max((min(last_day, until) - max(first_day, since)).days + 1, 0),
        ))
        if fallback:
            result.notes.append(f"{name}: no dated match, so its scheduled dates are used.")
    spans.sort(key=lambda s: (s.first_match, s.tournament_id))
    outside = [s for s in spans if s.last_match < since or s.first_match > until]
    spans = [s for s in spans if s not in outside]
    if outside:
        result.notes.append(
            "Not counted here, because all of the player's matches there were outside the window (only the scheduled dates overlap it): "
            + ", ".join(s.name for s in outside) + "."
        )
    result.spans = spans
    if not spans:
        result.rest_days_total = window_days
        return result

    # union of the present days, clipped to the window
    present: set[date] = set()
    for span in spans:
        day = max(span.first_match, since)
        while day <= min(span.last_match, until):
            present.add(day)
            day += timedelta(days=1)
    result.days_present = len(present)
    scheduled: set[date] = set()
    for span in spans:
        day = max(span.start_date, since)
        while day <= min(span.end_date, until):
            scheduled.add(day)
            day += timedelta(days=1)
    result.scheduled_days = len(scheduled)
    result.average_stay_days = round(statistics.fmean(s.days_present for s in spans), 1)
    result.days_on_court = len({d for d in _match_dates(connection, player_id, since, until)})
    result.share_present = round(len(present) / window_days, 4)
    result.rest_days_total = window_days - len(present)
    result.rest_before_first_days = (min(present) - since).days if present else window_days
    result.rest_after_last_days = (until - max(present)).days if present else 0

    # rests between tournaments: walk the tournaments in order
    latest_end, latest_name = spans[0].last_match, spans[0].name
    for span in spans[1:]:
        gap = (span.first_match - latest_end).days - 1
        if gap >= 1:
            result.rests.append(RestPeriod(
                after=latest_name, before=span.name, start=latest_end + timedelta(days=1),
                end=span.first_match - timedelta(days=1), days=gap,
            ))
        elif gap == 0:
            result.back_to_back += 1
        else:
            result.overlapping += 1
        if span.last_match > latest_end:
            latest_end, latest_name = span.last_match, span.name

    days = [r.days for r in result.rests]
    if days:
        result.longest_rest = max(result.rests, key=lambda r: r.days)
        result.average_rest_days = round(statistics.fmean(days), 1)
        result.median_rest_days = float(statistics.median(days))
    result.buckets = {label: sum(1 for d in days if low <= d <= high) for label, low, high in _BUCKETS}
    result.notes.append(
        "Rest = full days between the last match of one tournament and the first of the next. Only BWF tournaments are "
        "known, so other competitions inside a rest are not seen."
    )
    return result


def _match_dates(connection: sqlite3.Connection, player_id: int, since: date, until: date) -> list[str]:
    return [r[0] for r in connection.execute(
        "SELECT DISTINCT match_date FROM player_match_view WHERE player_id = ? "
        "AND status NOT IN ('bye', 'scheduled', 'in_progress') AND match_date BETWEEN ? AND ?", (player_id, since.isoformat(), until.isoformat()))]


# ------------------------------------------------------------------ 3. how far in each round

def round_progress(connection: sqlite3.Connection, player_id: int, since: date, until: date) -> RoundProgress:
    """How often the player reached each round of individual knockout events, and won the title.

    Team events and group stages are listed separately (they have no such rounds). "Reached" counts
    the events with a match (or a bye) in that round; ``reached == won + lost + pending`` in every round,
    where ``pending`` is a match that is scheduled or under way.
    """
    result = RoundProgress(since=since, until=until)
    rows = connection.execute(
        """SELECT v.tournament_id, v.tournament, v.event_id, v.event_code, v.draw_name, v.round, v.status, v.won,
                  t.type_id, r.position
           FROM player_match_view v
           JOIN tournaments t ON t.tournament_id = v.tournament_id
           LEFT JOIN results r ON r.player_id = v.player_id AND r.tournament_id = v.tournament_id
                                AND r.event_id = COALESCE(v.event_id, 0)
           WHERE v.player_id = ? AND t.end_date >= ? AND t.start_date <= ?""",
        (player_id, since.isoformat(), until.isoformat()),
    ).fetchall()

    events: dict[tuple, dict] = {}
    for tournament_id, tournament, event_id, code, draw, round_name, status, won, type_id, position in rows:
        event = events.setdefault((tournament_id, event_id), {
            "tournament": tournament, "code": code, "team": type_id == 1, "group": False, "position": position,
            "matches": [], "qualifying": False,
        })
        if draw and "group" in draw.casefold():
            event["group"] = True
        event["matches"].append((round_name, status, won))

    counts: dict[str, RoundCount] = {name: RoundCount(round=name) for name in _ALWAYS_SHOWN}
    extra_rounds: set[str] = set()
    for event in events.values():
        if event["team"] or event["group"]:
            wins = sum(1 for _, status, won in event["matches"] if won == 1 or status == "bye")
            losses = sum(1 for _, _, won in event["matches"] if won == 0)
            result.group_or_team.append(GroupOrTeamEvent(
                tournament=event["tournament"], event_code=event["code"], kind="team" if event["team"] else "group",
                matches_won=wins, matches_lost=losses, position=event["position"],
            ))
            continue
        main = [(r, s, w) for r, s, w in event["matches"] if r and not r.casefold().startswith("qual")]
        if any(r and r.casefold().startswith("qual") for r, _, _ in event["matches"]):
            result.qualifying_events += 1
        if not main:
            continue
        result.knockout_events += 1
        for round_name, status, won in main:
            if round_name in _KNOCKOUT_ROUNDS:
                entry = counts.setdefault(round_name, RoundCount(round=round_name))
            else:
                extra_rounds.add(round_name)
                continue
            entry.reached += 1
            if won == 1 or status == "bye":  # the store gives 1 / 0 (NULL for a bye)
                entry.won += 1
            elif won == 0:
                entry.lost += 1
            elif status in _OPEN:
                entry.pending += 1
        final = next(((s, w) for r, s, w in main if r == "Final"), None)
        if final is not None:
            result.finals += 1
            if final[1] == 1:
                result.champion += 1
            elif final[1] == 0:
                result.runner_up += 1
    ordered = [counts[r] for r in _KNOCKOUT_ROUNDS if r in counts and (r in _ALWAYS_SHOWN or counts[r].reached)]
    result.rounds = ordered
    result.group_or_team.sort(key=lambda e: e.tournament)
    if extra_rounds:
        result.notes.append("Rounds not in the R64-Final funnel were left out: " + ", ".join(sorted(extra_rounds)) + ".")
    result.notes.append(
        "Team events and group stages are listed separately. A bye counts as reaching and winning that round."
    )
    return result


# ------------------------------------------------------------------ 4. two-game and three-game matches

def game_split(connection: sqlite3.Connection, player_id: int, since: date, until: date) -> GameSplit:
    """Played matches by number of games: won 2-0 and 2-1, lost 1-2 and 0-2 (retirements are left out)."""
    result = GameSplit(since=since, until=until)
    rows = connection.execute(
        """SELECT v.match_id, v.status, v.won, g.game_no, g.player_points, g.opponent_points
           FROM player_match_view v
           JOIN tournaments t ON t.tournament_id = v.tournament_id
           JOIN player_game_view g ON g.match_id = v.match_id AND g.player_id = v.player_id
           WHERE v.player_id = ? AND t.end_date >= ? AND t.start_date <= ? ORDER BY v.match_id, g.game_no""",
        (player_id, since.isoformat(), until.isoformat()),
    ).fetchall()
    matches: dict[int, dict] = {}
    for match_id, status, won, game_no, mine, theirs in rows:
        entry = matches.setdefault(match_id, {"status": status, "won": won, "games": []})
        entry["games"].append((game_no, mine, theirs))
    for entry in matches.values():
        if entry["status"] != "played" or entry["won"] is None:
            result.excluded += 1
            continue
        games = sorted(entry["games"])
        mine_won = sum(1 for _, mine, theirs in games if mine > theirs)
        theirs_won = len(games) - mine_won
        if entry["won"] and (mine_won, theirs_won) == (2, 0):
            result.wins_2_0 += 1
        elif entry["won"] and (mine_won, theirs_won) == (2, 1):
            result.wins_2_1 += 1
        elif not entry["won"] and (mine_won, theirs_won) == (1, 2):
            result.losses_1_2 += 1
        elif not entry["won"] and (mine_won, theirs_won) == (0, 2):
            result.losses_0_2 += 1
        else:
            result.other += 1
            continue
        first = games[0]
        if first[1] > first[2]:
            result.matches_after_winning_game_1 += 1
            result.won_after_winning_game_1 += int(entry["won"])
        else:
            result.matches_after_losing_game_1 += 1
            result.won_after_losing_game_1 += int(entry["won"])
    result.matches = result.wins_2_0 + result.wins_2_1 + result.losses_1_2 + result.losses_0_2
    if result.other:
        result.notes.append(f"{result.other} match(es) did not fit best-of-three and are left out.")
    if result.excluded:
        result.notes.append(f"{result.excluded} match(es) left out (retirements, walkovers, byes or unknown result).")
    return result


# ------------------------------------------------------------------ 5. consecutive points and winning

def run_correlation(
    connection: sqlite3.Connection,
    player_id: int,
    since: date,
    until: date,
    *,
    level: Literal["match", "game"] = "match",
    trials: int = 10_000,
    seed: int = 20260925,
) -> RunCorrelation:
    """Is the longer run of consecutive points associated with winning the match (or the game)?

    Uses only matches (games) the site tracks rally-by-rally. For each one the run difference is
    (the player's longest run - the opponent's longest run). Reported: the win rate when the player's
    run was longer, equal or shorter; the correlation ``r`` between the run difference and winning;
    a permutation p-value for that ``r`` (shuffling the outcomes ``trials`` times, seeded, so the
    result is reproducible); the correlation of the run difference with the points balance; and the
    partial correlation of run difference and winning once the points balance is taken out.
    """
    result = RunCorrelation(since=since, until=until, level=level)
    if level == "match":
        sql = """SELECT s.player_consecutive_points, s.opponent_consecutive_points, v.won,
                        s.player_rallies_won - s.opponent_rallies_won
                 FROM player_match_stats_view s
                 JOIN player_match_view v ON v.match_id = s.match_id AND v.player_id = s.player_id
                 JOIN tournaments t ON t.tournament_id = v.tournament_id
                 WHERE s.player_id = ? AND t.end_date >= ? AND t.start_date <= ? AND s.tracked = 1
                       AND v.status = 'played' AND v.won IS NOT NULL
                       AND s.player_consecutive_points IS NOT NULL AND s.opponent_consecutive_points IS NOT NULL"""
    else:
        sql = """SELECT g.player_consecutive_points, g.opponent_consecutive_points,
                        CASE WHEN g.player_points > g.opponent_points THEN 1 ELSE 0 END,
                        g.player_points - g.opponent_points
                 FROM player_game_view g
                 JOIN player_match_view v ON v.match_id = g.match_id AND v.player_id = g.player_id
                 JOIN tournaments t ON t.tournament_id = v.tournament_id
                 WHERE g.player_id = ? AND t.end_date >= ? AND t.start_date <= ? AND g.tracked = 1
                       AND v.status = 'played'
                       AND g.player_consecutive_points IS NOT NULL AND g.opponent_consecutive_points IS NOT NULL"""
    rows = connection.execute(sql, (player_id, since.isoformat(), until.isoformat())).fetchall()
    result.n = len(rows)
    if not rows:
        result.notes.append("No matches with rally-by-rally data in the window.")
        return result

    mine = [float(r[0]) for r in rows]
    theirs = [float(r[1]) for r in rows]
    won = [float(r[2]) for r in rows]
    points = [float(r[3]) for r in rows]
    difference = [m - t for m, t in zip(mine, theirs)]

    for label, keep in (
        ("player's run longer", lambda d: d > 0),
        ("runs equal", lambda d: d == 0),
        ("opponent's run longer", lambda d: d < 0),
    ):
        outcomes = [w for d, w in zip(difference, won) if keep(d)]
        result.comparison.append(RunComparison(
            label=label, n=len(outcomes), wins=int(sum(outcomes)),
            win_pct=round(100 * sum(outcomes) / len(outcomes), 1) if outcomes else None,
        ))

    def mean_where(values: list[float], outcome: float) -> float | None:
        picked = [v for v, w in zip(values, won) if w == outcome]
        return round(statistics.fmean(picked), 2) if picked else None

    result.avg_player_run_when_won, result.avg_player_run_when_lost = mean_where(mine, 1.0), mean_where(mine, 0.0)
    result.avg_opponent_run_when_won, result.avg_opponent_run_when_lost = mean_where(theirs, 1.0), mean_where(theirs, 0.0)

    r_win = pearson(difference, won)
    r_points = pearson(difference, points)
    result.r_run_difference_and_win = _round(r_win)
    result.r_run_difference_and_points_difference = _round(r_points)
    result.p_value = permutation_p_value(difference, won, trials=trials, seed=seed) if r_win is not None else None
    r_win_points = pearson(points, won)
    result.partial_r = _round(partial_correlation(r_win, r_points, r_win_points))
    result.strength = describe_correlation(r_win)
    if len(set(won)) < 2:
        result.notes.append("The player won (or lost) every one of these, so there is nothing to correlate.")
    result.notes.append(
        "A correlation is not causation: a longer run usually comes with more points overall, which helps winning by itself. "
        "The partial correlation shows what the run adds once the points balance is taken out: near 0 means the run adds little "
        "beyond the points, and a small negative value should not be over-read, especially with few matches."
    )
    return result


def deep_dive(connection: sqlite3.Connection, player_id: int, since: date, until: date, **kwargs: object) -> DeepDive:
    """All five analyses for one player."""
    name = connection.execute("SELECT name FROM players WHERE player_id = ?", (player_id,)).fetchone()
    return DeepDive(
        player_id=player_id,
        player_name=name[0] if name else None,
        count=count_tournaments(connection, player_id, since, until),
        activity=activity(connection, player_id, since, until),
        rounds=round_progress(connection, player_id, since, until),
        games=game_split(connection, player_id, since, until),
        runs_by_match=run_correlation(connection, player_id, since, until, level="match", **kwargs),  # type: ignore[arg-type]
        runs_by_game=run_correlation(connection, player_id, since, until, level="game", **kwargs),  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------ statistics helpers

def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson correlation, or None when it is undefined (fewer than 3 points or a constant series)."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    try:
        return statistics.correlation(xs, ys)
    except statistics.StatisticsError:
        return None


def permutation_p_value(xs: Sequence[float], ys: Sequence[float], *, trials: int = 10_000, seed: int = 1) -> float | None:
    """Two-sided permutation p-value of the correlation between ``xs`` and ``ys`` (reproducible for a seed)."""
    observed = pearson(xs, ys)
    if observed is None:
        return None
    rng = random.Random(seed)
    shuffled = list(ys)
    at_least = 0
    for _ in range(trials):
        rng.shuffle(shuffled)
        r = pearson(xs, shuffled)
        if r is not None and abs(r) >= abs(observed) - 1e-12:
            at_least += 1
    return (at_least + 1) / (trials + 1)


def partial_correlation(r_xy: float | None, r_xz: float | None, r_yz: float | None) -> float | None:
    """Correlation of x and y with z taken out; None if any input is missing or z explains everything."""
    if r_xy is None or r_xz is None or r_yz is None:
        return None
    denominator = ((1 - r_xz**2) * (1 - r_yz**2)) ** 0.5
    if denominator < 1e-9:
        return None
    return (r_xy - r_xz * r_yz) / denominator


def describe_correlation(r: float | None) -> str:
    """A plain word for the size of a correlation (Cohen's rule of thumb)."""
    if r is None:
        return "not enough data"
    size = abs(r)
    word = "negligible" if size < 0.1 else "weak" if size < 0.3 else "moderate" if size < 0.5 else "strong"
    return f"{word} ({'positive' if r > 0 else 'negative' if r < 0 else 'none'})" if word != "negligible" else "negligible"


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


# ------------------------------------------------------------------ text

def _bar(value: int, maximum: int, width: int = 28) -> str:
    return "#" * (round(width * value / maximum) if maximum else 0)


def _p(value: float | None) -> str:
    if value is None:
        return "-"
    return "< 0.0001" if value < 0.0001 else f"{value:.4f}"


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "-"


def format_count(count: TournamentCount) -> str:
    lines = [
        f"Window: {count.since} to {count.until}",
        f"Tournaments entered:  {count.tournaments}  ({count.individual_tournaments} individual, {count.team_tournaments} team)",
        f"Events entered:       {count.events}",
    ]
    if count.first_start and count.last_end:
        lines.append(f"First start / last end: {count.first_start} / {count.last_end}")
    lines.append("By category:")
    width = max((len(c) for c in count.by_category), default=0)
    lines += [f"  {category:<{width}}  {n:>2}  {_bar(n, max(count.by_category.values()))}" for category, n in count.by_category.items()]
    return "\n".join(lines)


def format_activity(activity_: Activity) -> str:
    a = activity_
    lines = [
        f"Window: {a.since} to {a.until}  ({a.window_days} days)",
        f"On tour (first to last match of each tournament): {a.days_present} days = {100 * a.share_present:.0f}% of the window",
        f"Scheduled tournament days on the calendar: {a.scheduled_days}; the player stayed on average {a.average_stay_days} days per tournament (the player leaves when knocked out)",
        f"Days with at least one match: {a.days_on_court}",
        f"Days without being on tour: {a.rest_days_total} (of which {a.rest_before_first_days} before the first and {a.rest_after_last_days} after the last tournament)",
        "",
        "Tournaments in order (first match to last match):",
    ]
    for s in a.spans:
        kind = " [team]" if s.team_event else ""
        lines.append(f"  {s.first_match} to {s.last_match}  {s.days_present:>2} day(s), {s.matches:>2} match(es)  {s.name[:46]}{kind}")
    lines += ["", f"Rests between tournaments: {len(a.rests)}   (back-to-back with no rest day: {a.back_to_back}; overlapping: {a.overlapping})"]
    for r in a.rests:
        lines.append(f"  {r.days:>3} day(s)  {r.start} to {r.end}   after {r.after[:30]} / before {r.before[:30]}")
    if a.rests:
        lines += [
            "",
            f"Average rest: {a.average_rest_days} days, median {a.median_rest_days}; longest {a.longest_rest.days} days "
            f"({a.longest_rest.start} to {a.longest_rest.end}).",
            "Rests by length: " + ", ".join(f"{label}: {n}" for label, n in a.buckets.items()),
        ]
    lines += [f"Note: {note}" for note in a.notes if not note.endswith("scheduled dates are used.")]
    return "\n".join(lines)


def format_round_progress(progress: RoundProgress) -> str:
    p = progress
    top = max((r.reached for r in p.rounds), default=0)
    pending = any(r.pending for r in p.rounds)
    lines = [f"Individual knockout events: {p.knockout_events}", "", "Round    reached  won  lost" + ("  not played yet" if pending else "")]
    for r in p.rounds:
        extra = f"  {r.pending:>14}" if pending else ""
        lines.append(f"{r.round:<8} {r.reached:>6}  {r.won:>3}  {r.lost:>4}{extra}   {_bar(r.reached, top)}")
    lines += [
        "",
        f"Reached the final: {p.finals} time(s)  ->  champion {p.champion} time(s), runner-up {p.runner_up} time(s)",
    ]
    if p.qualifying_events:
        lines.append(f"Played qualifying in {p.qualifying_events} event(s).")
    if p.group_or_team:
        lines += ["", "Team events and group stages (no knockout rounds to count):"]
        for e in p.group_or_team:
            lines.append(f"  {e.tournament[:48]:<48} [{e.kind}] {e.matches_won}-{e.matches_lost} in matches")
    if pending:
        lines.append("A match \"not played yet\" is scheduled or under way: the player has reached that round but it has no result yet.")
    lines += [f"Note: {n}" for n in p.notes[:1]]
    return "\n".join(lines)


def format_game_split(split: GameSplit) -> str:
    g = split
    wins, losses = g.wins_2_0 + g.wins_2_1, g.losses_1_2 + g.losses_0_2
    lines = [
        f"Played matches (best of three): {g.matches}   won {wins}, lost {losses}",
        "",
        f"  Won in 2 games (2-0):   {g.wins_2_0:>3}  ({_pct(g.wins_2_0, wins)} of the wins)   {_bar(g.wins_2_0, max(g.wins_2_0, g.wins_2_1, 1), 20)}",
        f"  Won in 3 games (2-1):   {g.wins_2_1:>3}  ({_pct(g.wins_2_1, wins)} of the wins)   {_bar(g.wins_2_1, max(g.wins_2_0, g.wins_2_1, 1), 20)}",
        f"  Lost in 3 games (1-2):  {g.losses_1_2:>3}  ({_pct(g.losses_1_2, losses)} of the losses)",
        f"  Lost in 2 games (0-2):  {g.losses_0_2:>3}  ({_pct(g.losses_0_2, losses)} of the losses)",
        "",
        f"Three-game matches: {g.wins_2_1 + g.losses_1_2}, won {g.wins_2_1} ({_pct(g.wins_2_1, g.wins_2_1 + g.losses_1_2)}).",
        f"After winning game 1 the player won the match {g.won_after_winning_game_1} of {g.matches_after_winning_game_1} times ({_pct(g.won_after_winning_game_1, g.matches_after_winning_game_1)}).",
        f"After losing game 1 the player won the match {g.won_after_losing_game_1} of {g.matches_after_losing_game_1} times ({_pct(g.won_after_losing_game_1, g.matches_after_losing_game_1)}).",
    ]
    lines += [f"Note: {n}" for n in g.notes]
    return "\n".join(lines)


def format_run_correlation(c: RunCorrelation) -> str:
    unit = "matches" if c.level == "match" else "games"
    lines = [f"{c.n} {unit} with rally-by-rally data (retirements left out)"]
    if not c.n:
        return "\n".join(lines + [f"Note: {n}" for n in c.notes])
    lines += ["", f"{'when ...':<24} {unit:>8}  won  win rate"]
    for row in c.comparison:
        rate = "-" if row.win_pct is None else f"{row.win_pct:.1f}%"
        lines.append(f"{row.label:<24} {row.n:>8}  {row.wins:>3}  {rate:>8}")
    lines += [
        "",
        f"The player's longest run, averaged: {c.avg_player_run_when_won} when the player won, {c.avg_player_run_when_lost} when the player lost",
        f"The opponent's longest run:        {c.avg_opponent_run_when_won} when the player won, {c.avg_opponent_run_when_lost} when the player lost",
        "",
        f"Correlation of (the player's run - the opponent's run) with winning:  r = {c.r_run_difference_and_win}   {c.strength}",
        f"  permutation p-value: {_p(c.p_value)}   (small = unlikely to be chance)",
        f"Correlation of the run difference with the points balance: r = {c.r_run_difference_and_points_difference}",
        f"Partial correlation with winning once the points balance is taken out: r = {c.partial_r}",
    ]
    lines += [f"Note: {n}" for n in c.notes[-1:]]
    return "\n".join(lines)
