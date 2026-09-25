"""R9: deep-dive analysis of one player's saved history. Offline.

Two kinds of test. The real Christie fixtures are analysed by the module (SQL on the saved database) and
independently recomputed here from the parsed matches, by a different route. Synthetic databases with hand-worked
numbers pin down every definition and edge case.
"""

from __future__ import annotations

import math
import sqlite3
import statistics
from collections import Counter
from datetime import date, timedelta
from typing import Any

import pytest

from bwf_player import details_targets, get_match_details, get_matches, get_tournaments
from bwf_player.analysis import (
    activity,
    count_tournaments,
    deep_dive,
    describe_correlation,
    format_activity,
    format_count,
    format_game_split,
    format_round_progress,
    format_run_correlation,
    game_split,
    partial_correlation,
    pearson,
    permutation_p_value,
    round_progress,
    run_correlation,
)
from bwf_player.models import (
    EventMatches,
    GameDetail,
    GameScore,
    MatchDetails,
    MatchPlayer,
    PlayerMatch,
    SideStats,
    TournamentEntry,
    TournamentHistory,
)
from bwf_player.store import HistoryStore
from bwf_player.tournaments import overlaps
from tests.fakes import FakeApiClient, load_fixture

TODAY = date(2026, 9, 21)
SINCE, UNTIL = date(2025, 9, 21), date(2026, 9, 21)
CHRISTIE, FAJAR = 73442, 88876


# ================================================================== real fixtures, recomputed independently

def _load(store: HistoryStore, player: int, name: str) -> None:
    client = FakeApiClient()
    history = get_tournaments(player, client, today=TODAY, with_categories=True)
    store.save_tournaments(history, player_name=name)
    for entry in history.entries:
        event = get_matches(player, entry, client)
        store.save_matches(event)
        for match in details_targets(event.matches):
            try:
                store.save_match_details(get_match_details(match.tournament_id, match.match_code, client, match=match))
            except Exception:  # noqa: BLE001 - a match without a saved response
                continue


@pytest.fixture(scope="module")
def connection() -> Any:
    with HistoryStore() as store:
        _load(store, CHRISTIE, "Jonatan CHRISTIE")
        yield store.connection


@pytest.fixture(scope="module")
def parsed() -> Any:
    """(entries, {entry key: matches}) parsed straight from the fixtures, without the database."""
    client = FakeApiClient()
    entries = get_tournaments(CHRISTIE, client, today=TODAY, with_categories=True).entries
    return entries, {(e.tournament_id, e.event_id): get_matches(CHRISTIE, e, client).matches for e in entries}


def _played(matches: list[PlayerMatch]) -> list[PlayerMatch]:
    return [m for m in matches if m.status != "bye" and m.match_date is not None]


def test_the_number_of_tournaments(connection: sqlite3.Connection, parsed: Any) -> None:
    entries, _ = parsed
    count = count_tournaments(connection, CHRISTIE, SINCE, UNTIL)
    assert (count.tournaments, count.events) == (len({e.tournament_id for e in entries}), len(entries)) == (19, 19)
    assert count.team_tournaments == len({e.tournament_id for e in entries if e.type_id == 1}) == 1  # the Thomas Cup
    assert count.individual_tournaments == 18
    assert count.by_category == dict(Counter(e.category or "(no category)" for e in entries).most_common())
    assert sum(count.by_category.values()) == 19 and count.by_category["HSBC BWF World Tour Super 750"] == 7
    assert (count.first_start, count.last_end) == (min(e.start_date for e in entries), max(e.end_date for e in entries))


def test_a_narrower_window_counts_only_overlapping_tournaments(connection: sqlite3.Connection, parsed: Any) -> None:
    entries, _ = parsed
    since, until = date(2026, 1, 1), date(2026, 3, 31)
    expected = {e.tournament_id for e in entries if overlaps(e, since, until)}
    count = count_tournaments(connection, CHRISTIE, since, until)
    assert count.tournaments == len(expected) == 3  # Malaysia Open, India Open, All England


def test_rest_and_time_on_tour_recomputed_day_by_day(connection: sqlite3.Connection, parsed: Any) -> None:
    entries, by_event = parsed
    # independent route: mark every day from a tournament's first to its last match, then look at the empty stretches
    present: set[date] = set()
    for entry in entries:
        dates = [m.match_date for m in _played(by_event[(entry.tournament_id, entry.event_id)])]
        if dates:
            day = min(dates)
            while day <= max(dates):
                present.add(day)
                day += timedelta(days=1)
    present = {d for d in present if SINCE <= d <= UNTIL}
    first, last = min(present), max(present)
    absent_runs, day = [], first
    while day <= last:
        if day not in present:
            start = day
            while day not in present:
                day += timedelta(days=1)
            absent_runs.append((start, day - timedelta(days=1), (day - start).days))
        else:
            day += timedelta(days=1)

    a = activity(connection, CHRISTIE, SINCE, UNTIL)
    assert [(r.start, r.end, r.days) for r in a.rests] == absent_runs
    assert a.days_present == len(present) and a.window_days == (UNTIL - SINCE).days + 1 == 366
    assert a.rest_days_total == a.window_days - len(present)
    assert (a.rest_before_first_days, a.rest_after_last_days) == ((first - SINCE).days, (UNTIL - last).days)
    assert a.rest_days_total == a.rest_before_first_days + sum(r.days for r in a.rests) + a.rest_after_last_days
    assert a.days_on_court == len({m.match_date for ms in by_event.values() for m in _played(ms) if SINCE <= m.match_date <= UNTIL}) == 56
    lengths = [r for _, _, r in absent_runs]
    assert a.average_rest_days == round(statistics.fmean(lengths), 1) and a.median_rest_days == statistics.median(lengths)
    assert a.longest_rest.days == max(lengths) and sum(a.buckets.values()) == len(lengths)
    def played_dates(entry: TournamentEntry) -> list[date]:
        return [m.match_date for m in _played(by_event[(entry.tournament_id, entry.event_id)])]

    in_window = [e for e in entries if any(SINCE <= d <= UNTIL for d in played_dates(e))]
    assert len(a.spans) == len(in_window) == 18 and len(a.rests) == 17 and a.back_to_back == 0 and a.overlapping == 0
    # China Masters 2025 was scheduled until 21 Sep but Christie played on 17-18 Sep, before the window
    assert any("LI-NING China Masters 2025" in n and "outside the window" in n for n in a.notes)
    assert round(a.share_present, 4) == round(len(present) / 366, 4)


def test_round_funnel_recomputed_from_the_parsed_matches(connection: sqlite3.Connection, parsed: Any) -> None:
    entries, by_event = parsed
    rounds: Counter[str] = Counter()
    won: Counter[str] = Counter()
    lost: Counter[str] = Counter()
    finals = champions = knockout = 0
    for entry in entries:
        matches = by_event[(entry.tournament_id, entry.event_id)]
        if entry.type_id == 1 or any(m.draw_name and "Group" in m.draw_name for m in matches):
            continue
        knockout += 1
        for m in matches:
            rounds[m.round] += 1
            (won if m.won else lost)[m.round] += 1
        finals += any(m.round == "Final" for m in matches)
        champions += any(m.round == "Final" and m.won for m in matches)

    p = round_progress(connection, CHRISTIE, SINCE, UNTIL)
    assert p.knockout_events == knockout == 17
    by_round = {r.round: r for r in p.rounds}
    for name in ("R64", "R32", "R16", "QF", "SF", "Final"):
        assert (by_round[name].reached, by_round[name].won, by_round[name].lost) == (rounds[name], won[name], lost[name]), name
    assert (p.finals, p.champion, p.runner_up) == (finals, champions, finals - champions) == (5, 3, 2)
    assert [r.reached for r in p.rounds] == [1, 17, 14, 9, 6, 5]
    assert champions == sum(1 for e in entries if e.position == "1st")  # the site's own "1st"


def test_the_funnel_is_consistent_with_itself(connection: sqlite3.Connection) -> None:
    p = round_progress(connection, CHRISTIE, SINCE, UNTIL)
    for r in p.rounds:
        assert r.reached == r.won + r.lost
    for earlier, later in zip(p.rounds, p.rounds[1:]):
        if later.round != "R32":  # R64 is played by only some events, so only from R32 onwards
            assert earlier.won == later.reached, (earlier.round, later.round)
    assert p.rounds[-1].won == p.champion


def test_team_events_and_group_stages_are_listed_apart(connection: sqlite3.Connection, parsed: Any) -> None:
    entries, by_event = parsed
    p = round_progress(connection, CHRISTIE, SINCE, UNTIL)
    listed = {e.tournament: (e.kind, e.matches_won, e.matches_lost) for e in p.group_or_team}
    assert listed == {
        "BWF Thomas & Uber Cup Finals 2026": ("team", 1, 2),   # Singles: won 1 tie, lost 2
        "HSBC BWF World Tour Finals 2025": ("group", 0, 3),    # lost all three group matches
    }
    assert sum(1 for e in entries if e.type_id == 1) == 1


def test_matches_by_number_of_games_recomputed(connection: sqlite3.Connection, parsed: Any) -> None:
    _, by_event = parsed
    tally: Counter[str] = Counter()
    after_win, after_loss = [0, 0], [0, 0]
    for matches in by_event.values():
        for m in matches:
            if m.status != "played":
                continue
            mine = sum(g.player_points > g.opponent_points for g in m.games)
            theirs = len(m.games) - mine
            tally[f"{mine}-{theirs}"] += 1
            bucket = after_win if m.games[0].player_points > m.games[0].opponent_points else after_loss
            bucket[0] += 1
            bucket[1] += bool(m.won)
    g = game_split(connection, CHRISTIE, SINCE, UNTIL)
    assert (g.wins_2_0, g.wins_2_1, g.losses_1_2, g.losses_0_2) == (tally["2-0"], tally["2-1"], tally["1-2"], tally["0-2"])
    assert g.matches == sum(tally.values()) == 58 and g.other == 0 and g.excluded == 0
    assert g.wins_2_0 + g.wins_2_1 == sum(1 for ms in by_event.values() for m in ms if m.won) == 39
    assert (g.matches_after_winning_game_1, g.won_after_winning_game_1) == tuple(after_win)
    assert (g.matches_after_losing_game_1, g.won_after_losing_game_1) == tuple(after_loss)
    assert g.matches_after_winning_game_1 + g.matches_after_losing_game_1 == g.matches


def _manual_pearson(xs: list[float], ys: list[float]) -> float:
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(
        sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))


def test_correlation_of_runs_and_winning_recomputed_from_the_match_details(connection: sqlite3.Connection, parsed: Any) -> None:
    _, by_event = parsed
    client = FakeApiClient()
    diffs, wins, points = [], [], []
    for matches in by_event.values():
        for m in details_targets(matches):
            d = get_match_details(m.tournament_id, m.match_code, client)
            if not d.tracked or m.status != "played":
                continue
            mine, theirs = (d.side1, d.side2) if m.side == 1 else (d.side2, d.side1)
            diffs.append(float(mine.consecutive_points - theirs.consecutive_points))
            wins.append(float(m.won))
            points.append(float(mine.rallies_won - theirs.rallies_won))
    c = run_correlation(connection, CHRISTIE, SINCE, UNTIL, level="match", trials=2000)
    assert c.n == len(diffs) == 58
    assert c.r_run_difference_and_win == round(_manual_pearson(diffs, wins), 3)
    assert c.r_run_difference_and_points_difference == round(_manual_pearson(diffs, points), 3)
    longer = [w for d, w in zip(diffs, wins) if d > 0]
    assert (c.comparison[0].n, c.comparison[0].wins) == (len(longer), int(sum(longer)))
    assert sum(row.n for row in c.comparison) == c.n and sum(row.wins for row in c.comparison) == int(sum(wins))
    assert c.p_value is not None and c.p_value < 0.01 and c.strength.startswith(("moderate", "strong"))
    assert c.partial_r == round(partial_correlation(
        _manual_pearson(diffs, wins), _manual_pearson(diffs, points), _manual_pearson(points, wins)), 3)


def test_the_game_level_correlation_is_stronger_and_mostly_the_points(connection: sqlite3.Connection) -> None:
    game = run_correlation(connection, CHRISTIE, SINCE, UNTIL, level="game", trials=2000)
    match = run_correlation(connection, CHRISTIE, SINCE, UNTIL, level="match", trials=2000)
    assert game.n >= 130 and game.r_run_difference_and_win > match.r_run_difference_and_win > 0.3
    assert abs(game.partial_r) < 0.2  # once the points balance is taken out, the run adds almost nothing


def test_the_p_value_is_reproducible(connection: sqlite3.Connection) -> None:
    a = run_correlation(connection, CHRISTIE, SINCE, UNTIL, trials=500, seed=7)
    b = run_correlation(connection, CHRISTIE, SINCE, UNTIL, trials=500, seed=7)
    assert a.p_value == b.p_value and a.model_dump() == b.model_dump()


def test_another_player_in_the_same_database_changes_nothing() -> None:
    with HistoryStore() as store:
        _load(store, CHRISTIE, "Jonatan CHRISTIE")
        alone = deep_dive(store.connection, CHRISTIE, SINCE, UNTIL, trials=200)
        _load(store, FAJAR, "Fajar ALFIAN")
        together = deep_dive(store.connection, CHRISTIE, SINCE, UNTIL, trials=200)
        other = deep_dive(store.connection, FAJAR, SINCE, UNTIL, trials=200)
    assert alone == together and alone.player_name == "Jonatan CHRISTIE"
    assert other.count.tournaments != 19 and other.player_name == "Fajar ALFIAN"


def test_the_deep_dive_bundles_all_five_answers(connection: sqlite3.Connection) -> None:
    d = deep_dive(connection, CHRISTIE, SINCE, UNTIL, trials=200)
    assert (d.count.tournaments, d.rounds.champion, d.games.matches, d.runs_by_match.n, d.runs_by_game.level) == (19, 3, 58, 58, "game")
    assert d.activity.window_days == 366


# ================================================================== synthetic databases

_ids = iter(range(1_000_000, 9_000_000))


def _add_event(
    store: HistoryStore, tid: int, name: str, start: date, end: date, matches: list[dict[str, Any]], *,
    player: int = 1, type_id: int = 0, code: str = "MS", draw: str = "MS", position: str | None = None,
    event_id: int = 1, category: str | None = "Cat A",
) -> None:
    entry = TournamentEntry(
        tournament_id=tid, name=name, category=category, start_date=start, end_date=end, type_id=type_id,
        event_code=code, event_id=event_id, position=position,
    )
    store.save_tournaments(TournamentHistory(player_id=str(player), since=start, until=end, entries=[entry]), player_name="P")
    parsed_matches = []
    for m in matches:
        match_id = next(_ids)
        games = [GameScore(game_no=i + 1, player_points=a, opponent_points=b) for i, (a, b) in enumerate(m.get("games", []))]
        won = m.get("won")
        parsed_matches.append(PlayerMatch(
            match_id=match_id, match_code=str(match_id), tournament_id=tid, draw_name=m.get("draw", draw), round=m.get("round"),
            match_date=m.get("date"), side=1, player=MatchPlayer(player_id=player, name="P"),
            opponents=[MatchPlayer(player_id=match_id + 10_000_000, name="Opp")], won=won,
            status=m.get("status", "played" if won is not None else "bye"), games=games,
        ))
        m["_id"] = match_id
    store.save_matches(EventMatches(tournament_id=tid, event_code=code, event_id=event_id, matches=parsed_matches))
    for m, saved in zip(matches, parsed_matches):
        if "runs" in m:  # rally-tracked figures: (player run, opponent run) and (player points, opponent points)
            (run_p, run_o), (pts_p, pts_o) = m["runs"], m["points"]
            game_details = []
            for i, (a, b) in enumerate(m.get("games", [])):
                gr = m.get("game_runs", [])[i] if m.get("game_runs") else (run_p, run_o)
                game_details.append(GameDetail(
                    game_no=i + 1, side1_points=a, side2_points=b, total_points_played=a + b, tracked=True,
                    side1=SideStats(consecutive_points=gr[0], rallies_played=a + b, rallies_won=a),
                    side2=SideStats(consecutive_points=gr[1], rallies_played=a + b, rallies_won=b),
                ))
            store.save_match_details(MatchDetails(
                match_id=saved.match_id, tournament_id=tid, match_code=str(saved.match_id), tracked=True,
                side1=SideStats(consecutive_points=run_p, rallies_played=pts_p + pts_o, rallies_won=pts_p),
                side2=SideStats(consecutive_points=run_o, rallies_played=pts_p + pts_o, rallies_won=pts_o),
                games=game_details,
            ))


def _win(day: date, rnd: str, **extra: Any) -> dict[str, Any]:
    return {"date": day, "round": rnd, "won": True, "games": [(21, 10), (21, 12)], **extra}


def _loss(day: date, rnd: str, **extra: Any) -> dict[str, Any]:
    return {"date": day, "round": rnd, "won": False, "games": [(10, 21), (12, 21)], **extra}


def d(month: int, day: int, year: int = 2026) -> date:
    return date(year, month, day)


@pytest.fixture()
def calendar() -> Any:
    """Hand-worked calendar for window 2026-01-01..2026-03-31 (90 days)."""
    with HistoryStore() as store:
        _add_event(store, 1, "T1", d(1, 5), d(1, 10), [_win(d(1, 6), "R32"), _loss(d(1, 8), "R16")])
        _add_event(store, 2, "T2 (back to back)", d(1, 9), d(1, 16), [_win(d(1, 9), "R32"), _loss(d(1, 12), "R16")], event_id=2)
        _add_event(store, 3, "T3 team (overlaps T2)", d(1, 11), d(1, 15), [_win(d(1, 11), "R1"), _loss(d(1, 14), "R2")], type_id=1, code="Singles", event_id=3)
        _add_event(store, 4, "T4", d(1, 30), d(2, 2), [_win(d(1, 30), "R32"), _win(d(1, 31), "R16")], event_id=4)
        _add_event(store, 5, "T5 (no dated match)", d(2, 20), d(2, 22), [], event_id=5)
        _add_event(store, 6, "T6 (outside the window)", d(2, 1) + timedelta(days=200), d(2, 5) + timedelta(days=200), [_win(d(8, 20), "R32")], event_id=6)
        yield store.connection


def test_hand_worked_calendar(calendar: sqlite3.Connection) -> None:
    a = activity(calendar, 1, d(1, 1), d(3, 31))
    assert a.window_days == 90
    assert [s.name for s in a.spans] == ["T1", "T2 (back to back)", "T3 team (overlaps T2)", "T4", "T5 (no dated match)"]
    # present: 6-8 Jan, 9-12 (T2), 11-14 (team, overlaps), 30-31 Jan, and 20-22 Feb from the scheduled dates
    assert a.days_present == 3 + 4 + 2 + 2 + 3 == 14
    assert a.days_on_court == 8  # eight distinct match dates
    assert (a.rest_before_first_days, a.rest_after_last_days) == (5, 37)  # 1-5 Jan; 23 Feb-31 Mar
    assert [(r.days, r.start, r.end) for r in a.rests] == [(15, d(1, 15), d(1, 29)), (19, d(2, 1), d(2, 19))]
    assert (a.rests[0].after, a.rests[0].before) == ("T3 team (overlaps T2)", "T4")
    assert (a.back_to_back, a.overlapping) == (1, 1)
    assert a.rest_days_total == 76 == 5 + 15 + 19 + 37
    assert (a.longest_rest.days, a.average_rest_days, a.median_rest_days) == (19, 17.0, 17.0)
    assert a.buckets == {"1-6 days": 0, "7-13 days": 0, "14-27 days": 2, "28 days or more": 0}
    assert a.share_present == round(14 / 90, 4)
    assert any("T5 (no dated match): no dated match" in n for n in a.notes) and any(n.startswith("Rest =") for n in a.notes)
    assert a.average_stay_days == round((3 + 4 + 4 + 2 + 3) / 5, 1)


def test_scheduled_days_count_each_calendar_day_once(calendar: sqlite3.Connection) -> None:
    a = activity(calendar, 1, d(1, 1), d(3, 31))
    # 5-16 Jan is one block of 12 days (T1, T2 and the team event overlap), then 30 Jan-2 Feb (4) and 20-22 Feb (3)
    assert a.scheduled_days == 12 + 4 + 3 == 19


def test_the_window_clips_the_days(calendar: sqlite3.Connection) -> None:
    a = activity(calendar, 1, d(1, 8), d(2, 5))
    assert a.window_days == 29
    assert [s.name for s in a.spans] == ["T1", "T2 (back to back)", "T3 team (overlaps T2)", "T4"]  # T5 starts after the window
    assert a.days_present == 1 + 4 + 2 + 2 == 9  # T1 counted from 8 Jan only
    assert (a.rest_before_first_days, a.rest_after_last_days) == (0, 5)
    assert [r.days for r in a.rests] == [15]


def test_no_tournaments_means_all_rest() -> None:
    with HistoryStore() as store:
        a = activity(store.connection, 99, d(1, 1), d(1, 31))
        assert (a.days_present, a.rest_days_total, a.rests, a.spans, a.longest_rest) == (0, 31, [], [], None)
        assert count_tournaments(store.connection, 99, d(1, 1), d(1, 31)).tournaments == 0
        assert round_progress(store.connection, 99, d(1, 1), d(1, 31)).knockout_events == 0
        assert game_split(store.connection, 99, d(1, 1), d(1, 31)).matches == 0
        assert run_correlation(store.connection, 99, d(1, 1), d(1, 31)).n == 0


def test_a_single_tournament_has_no_rest_between() -> None:
    with HistoryStore() as store:
        _add_event(store, 1, "Only", d(1, 10), d(1, 14), [_win(d(1, 11), "R32")])
        a = activity(store.connection, 1, d(1, 1), d(1, 31))
        assert a.rests == [] and a.average_rest_days is None and a.days_present == 1 and (a.rest_before_first_days, a.rest_after_last_days) == (10, 20)
        assert format_activity(a).count("Rests between tournaments: 0") == 1


def test_categories_and_counts_of_the_calendar(calendar: sqlite3.Connection) -> None:
    c = count_tournaments(calendar, 1, d(1, 1), d(3, 31))
    assert (c.tournaments, c.events, c.individual_tournaments, c.team_tournaments) == (5, 5, 4, 1)
    assert c.by_category == {"Cat A": 5} and (c.first_start, c.last_end) == (d(1, 5), d(2, 22))


def test_tournaments_without_a_category_are_counted_as_such() -> None:
    with HistoryStore() as store:
        _add_event(store, 1, "A", d(1, 5), d(1, 6), [_win(d(1, 5), "R32")], category=None)
        assert count_tournaments(store.connection, 1, d(1, 1), d(1, 31)).by_category == {"(no category)": 1}


# ---------------------------------------------------------------- rounds

@pytest.fixture()
def rounds() -> Any:
    with HistoryStore() as store:
        k = 0
        def day() -> date:
            nonlocal k
            k += 1
            return d(1, 1) + timedelta(days=k)
        _add_event(store, 1, "E1 bye then out in QF", d(1, 1), d(1, 9),
                   [{"date": None, "round": "R64", "won": None, "status": "bye"}, _win(day(), "R32"), _win(day(), "R16"), _loss(day(), "QF")], event_id=1)
        _add_event(store, 2, "E2 champion", d(2, 1), d(2, 9),
                   [_win(day(), r) for r in ("R32", "R16", "QF", "SF", "Final")], event_id=2, position="1st")
        _add_event(store, 3, "E3 runner-up", d(3, 1), d(3, 9),
                   [_win(day(), r) for r in ("R32", "R16", "QF", "SF")] + [_loss(day(), "Final"), _win(day(), "Play-off")], event_id=3, position="2nd")
        _add_event(store, 4, "E4 qualified", d(4, 1), d(4, 9),
                   [_win(day(), "Qual. R32"), _win(day(), "Qual. QF"), _loss(day(), "R32")], event_id=4)
        _add_event(store, 5, "E5 group stage", d(5, 1), d(5, 9),
                   [_loss(day(), "R1", draw="MS - Group A"), _win(day(), "R2", draw="MS - Group A"), _loss(day(), "R3", draw="MS - Group A")], event_id=5)
        _add_event(store, 6, "E6 team", d(6, 1), d(6, 9), [_win(day(), "R1"), _loss(day(), "R2")], type_id=1, code="Singles", event_id=6)
        _add_event(store, 7, "E7 walkover", d(7, 1), d(7, 9), [{"date": day(), "round": "R32", "won": False, "status": "walkover"}], event_id=7)
        yield store.connection


def test_hand_worked_round_funnel(rounds: sqlite3.Connection) -> None:
    p = round_progress(rounds, 1, d(1, 1), d(12, 31))
    table = {r.round: (r.reached, r.won, r.lost) for r in p.rounds}
    assert table == {
        "R64": (1, 1, 0),   # the bye counts as reaching and winning the round
        "R32": (5, 3, 2),   # E1, E2, E3 won; E4 lost; E7 lost by walkover
        "R16": (3, 3, 0),
        "QF": (3, 2, 1),
        "SF": (2, 2, 0),
        "Final": (2, 1, 1),
    }
    assert (p.knockout_events, p.finals, p.champion, p.runner_up, p.qualifying_events) == (5, 2, 1, 1, 1)
    assert [(e.tournament, e.kind, e.matches_won, e.matches_lost) for e in p.group_or_team] == [
        ("E5 group stage", "group", 1, 2), ("E6 team", "team", 1, 1)]
    assert any("Play-off" in n for n in p.notes)  # a round outside the funnel is mentioned, not counted
    for r in p.rounds:
        assert r.reached == r.won + r.lost


def test_the_round_window_filters_events(rounds: sqlite3.Connection) -> None:
    p = round_progress(rounds, 1, d(2, 1), d(3, 31))
    assert p.knockout_events == 2 and p.champion == 1 and p.runner_up == 1


def test_r128_only_appears_when_played() -> None:
    with HistoryStore() as store:
        _add_event(store, 1, "Big draw", d(1, 5), d(1, 9), [_win(d(1, 5), "R128"), _win(d(1, 6), "R64"), _loss(d(1, 7), "R32")])
        p = round_progress(store.connection, 1, d(1, 1), d(1, 31))
        assert [r.round for r in p.rounds] == ["R128", "R64", "R32", "R16", "QF", "SF", "Final"]
        assert (p.rounds[0].reached, p.rounds[1].reached, p.rounds[2].lost) == (1, 1, 1)


# ---------------------------------------------------------------- game split

def test_hand_worked_game_split() -> None:
    with HistoryStore() as store:
        rows = (
            [_win(d(1, 2), "R32", games=[(21, 10), (21, 12)])] * 2
            + [{"date": d(1, 3), "round": "R16", "won": True, "games": [(21, 15), (18, 21), (21, 19)]}] * 2  # 2-1, won game 1
            + [{"date": d(1, 4), "round": "QF", "won": True, "games": [(18, 21), (21, 15), (21, 19)]}]      # 2-1, lost game 1
            + [{"date": d(1, 5), "round": "SF", "won": False, "games": [(21, 19), (17, 21), (15, 21)]}]      # 1-2, won game 1
            + [{"date": d(1, 6), "round": "Final", "won": False, "games": [(15, 21), (12, 21)]}] * 2         # 0-2
            + [{"date": d(1, 7), "round": "X", "won": True, "status": "retired", "games": [(21, 10), (5, 3)]}]  # retired: left out
            + [{"date": d(1, 8), "round": "Y", "won": True, "games": [(10, 21), (21, 10)]}]                  # inconsistent: other
        )
        for i, m in enumerate(rows):  # one event per match so the copies of a dict stay distinct
            _add_event(store, 100 + i, f"E{i}", d(1, 1), d(1, 20), [dict(m)], event_id=100 + i)
        g = game_split(store.connection, 1, d(1, 1), d(1, 31))
    assert (g.wins_2_0, g.wins_2_1, g.losses_1_2, g.losses_0_2) == (2, 3, 1, 2)
    assert g.matches == 8 and g.other == 1 and g.excluded == 1
    assert (g.matches_after_winning_game_1, g.won_after_winning_game_1) == (5, 4)   # 2x 2-0, 2x 2-1 (won g1), 1-2
    assert (g.matches_after_losing_game_1, g.won_after_losing_game_1) == (3, 1)     # 2-1 comeback, 2x 0-2
    assert any("did not fit best-of-three" in n for n in g.notes) and any("left out" in n for n in g.notes)


# ---------------------------------------------------------------- run correlation

_SAMPLE = [  # (player run, opponent run, won, points balance)
    (7, 4, 1, 10), (6, 3, 1, 8), (8, 5, 1, 12), (5, 5, 1, 4), (6, 2, 1, 9), (4, 6, 1, 2),
    (3, 7, 0, -8), (4, 6, 0, -3), (2, 5, 0, -10), (5, 5, 0, -5), (3, 3, 0, -1), (6, 4, 0, -2),
]


def _store_with_sample(sample: list[tuple[int, int, int, int]]) -> HistoryStore:
    store = HistoryStore()
    matches = []
    for i, (mine, theirs, won, balance) in enumerate(sample):
        pts_p, pts_o = (60 + balance // 2, 60 - balance // 2) if balance >= 0 else (60 + (balance - 1) // 2, 60 - (balance - 1) // 2)
        games = [(21, 15), (21, 19)] if won else [(15, 21), (19, 21)]
        matches.append({"date": d(1, 1) + timedelta(days=i), "round": "R32", "won": bool(won), "games": games,
                        "runs": (mine, theirs), "points": (pts_p, pts_o), "game_runs": [(mine, theirs), (theirs, mine)]})
    _add_event(store, 1, "Sample", d(1, 1), d(1, 31), matches)
    return store


def test_hand_worked_match_level_correlation() -> None:
    with _store_with_sample([(a, b, w, p) for a, b, w, p in _SAMPLE]) as store:
        c = run_correlation(store.connection, 1, d(1, 1), d(1, 31), trials=500)
    assert c.n == 12
    assert [(r.label, r.n, r.wins, r.win_pct) for r in c.comparison] == [
        ("player's run longer", 5, 4, 80.0), ("runs equal", 3, 1, 33.3), ("opponent's run longer", 4, 1, 25.0)]
    diffs = [float(a - b) for a, b, _, _ in _SAMPLE]
    assert c.r_run_difference_and_win == round(_manual_pearson(diffs, [float(w) for _, _, w, _ in _SAMPLE]), 3)
    assert c.avg_player_run_when_won == round(statistics.fmean([7, 6, 8, 5, 6, 4]), 2) == 6.0
    assert c.avg_player_run_when_lost == round(statistics.fmean([3, 4, 2, 5, 3, 6]), 2) == 3.83
    assert c.avg_opponent_run_when_won == round(statistics.fmean([4, 3, 5, 5, 2, 6]), 2) == 4.17
    # only 12 matches: a large correlation that a permutation test still cannot separate from chance (p about 0.1)
    assert c.strength.startswith("strong") and 0.05 < c.p_value < 0.2


def test_the_game_level_uses_the_games_own_runs() -> None:
    with _store_with_sample(_SAMPLE) as store:
        c = run_correlation(store.connection, 1, d(1, 1), d(1, 31), level="game", trials=200)
    assert c.n == 24 and c.level == "game"
    # each match has game 1 with runs (mine, theirs) and game 2 with them swapped; the player wins both games or loses both
    assert sum(row.n for row in c.comparison) == 24


def test_all_wins_have_nothing_to_correlate() -> None:
    with _store_with_sample([(a, b, 1, 5) for a, b, _, _ in _SAMPLE]) as store:
        c = run_correlation(store.connection, 1, d(1, 1), d(1, 31), trials=100)
    assert c.n == 12 and c.r_run_difference_and_win is None and c.p_value is None and c.strength == "not enough data"
    assert any("nothing to correlate" in n for n in c.notes) and c.comparison[0].wins == c.comparison[0].n


def test_two_matches_are_too_few() -> None:
    with _store_with_sample(_SAMPLE[:2]) as store:
        c = run_correlation(store.connection, 1, d(1, 1), d(1, 31), trials=100)
    assert c.n == 2 and c.r_run_difference_and_win is None and c.strength == "not enough data"


def test_a_perfect_relationship_gives_r_one() -> None:
    sample = [(k + 1, 0, 1, 10) for k in range(6)] + [(0, k + 1, 0, -10) for k in range(6)]
    with _store_with_sample(sample) as store:
        c = run_correlation(store.connection, 1, d(1, 1), d(1, 31), trials=300)
    assert c.r_run_difference_and_win > 0.8 and c.p_value < 0.05


def test_retirements_and_untracked_matches_are_left_out() -> None:
    with _store_with_sample(_SAMPLE) as store:
        store.connection.execute("UPDATE matches SET status = 'retired' WHERE match_id IN (SELECT match_id FROM matches LIMIT 2)")
        store.connection.execute("UPDATE match_stats SET tracked = 0 WHERE match_id IN (SELECT match_id FROM matches ORDER BY match_id DESC LIMIT 1)")
        c = run_correlation(store.connection, 1, d(1, 1), d(1, 31), trials=100)
    assert c.n == 9


# ---------------------------------------------------------------- statistics helpers

def test_pearson() -> None:
    assert pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
    assert pearson([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)
    assert pearson([1, 2, 3, 4], [1, 3, 2, 4]) == pytest.approx(0.8)
    assert pearson([1, 1, 1, 1], [1, 2, 3, 4]) is None      # a constant series has no correlation
    assert pearson([1, 2], [1, 2]) is None                  # too few points
    assert pearson([1, 2, 3], [1, 2]) is None               # different lengths


def test_permutation_p_value() -> None:
    xs = list(range(1, 11))
    assert permutation_p_value(xs, xs, trials=2000, seed=3) <= 0.001   # perfect: essentially never matched by chance
    alternating = [1, 0] * 5
    assert permutation_p_value(xs, alternating, trials=2000, seed=3) > 0.3   # unrelated
    assert permutation_p_value(xs, xs, trials=500, seed=9) == permutation_p_value(xs, xs, trials=500, seed=9)
    assert permutation_p_value([1, 1, 1], [1, 2, 3]) is None
    p = permutation_p_value(xs, [10 - x for x in xs], trials=500, seed=1)
    assert p == permutation_p_value(xs, xs, trials=500, seed=1)          # two-sided: a perfect negative counts the same


def test_partial_correlation() -> None:
    assert partial_correlation(0.5, 0.6, 0.7) == pytest.approx((0.5 - 0.6 * 0.7) / math.sqrt((1 - 0.36) * (1 - 0.49)))
    assert partial_correlation(None, 0.6, 0.7) is None and partial_correlation(0.5, None, 0.7) is None
    assert partial_correlation(0.5, 1.0, 0.7) is None   # z explains x completely


@pytest.mark.parametrize(("r", "expected"), [
    (None, "not enough data"), (0.0, "negligible"), (0.05, "negligible"), (-0.09, "negligible"),
    (0.2, "weak (positive)"), (-0.2, "weak (negative)"), (0.4, "moderate (positive)"), (-0.45, "moderate (negative)"),
    (0.5, "strong (positive)"), (0.9, "strong (positive)"), (-0.7, "strong (negative)"),
])
def test_describe_correlation(r: float | None, expected: str) -> None:
    assert describe_correlation(r) == expected


# ---------------------------------------------------------------- text

def test_the_text_reports(connection: sqlite3.Connection) -> None:
    count = format_count(count_tournaments(connection, CHRISTIE, SINCE, UNTIL))
    assert "Tournaments entered:  19  (18 individual, 1 team)" in count and "HSBC BWF World Tour Super 750" in count
    act = format_activity(activity(connection, CHRISTIE, SINCE, UNTIL))
    assert "Rests between tournaments: 17" in act and "Average rest:" in act and "Rests by length:" in act
    assert act.count("\n  20") == 18  # one line per tournament (they all start with a year)
    rounds_text = format_round_progress(round_progress(connection, CHRISTIE, SINCE, UNTIL))
    assert "Reached the final: 5 time(s)  ->  champion 3 time(s), runner-up 2 time(s)" in rounds_text
    assert "R32          17   14     3" in rounds_text and "[group] 0-3 in matches" in rounds_text
    split = format_game_split(game_split(connection, CHRISTIE, SINCE, UNTIL))
    assert "Played matches (best of three): 58   won 39, lost 19" in split and "Won in 2 games (2-0):" in split
    corr = format_run_correlation(run_correlation(connection, CHRISTIE, SINCE, UNTIL, trials=200))
    assert "58 matches with rally-by-rally data" in corr and "permutation p-value:" in corr and "Partial correlation" in corr


def test_the_text_for_no_data() -> None:
    with HistoryStore() as store:
        args = (store.connection, 5, d(1, 1), d(1, 31))
        assert "Tournaments entered:  0" in format_count(count_tournaments(*args))
        assert "Rests between tournaments: 0" in format_activity(activity(*args))
        assert "Individual knockout events: 0" in format_round_progress(round_progress(*args))
        assert "Played matches (best of three): 0" in format_game_split(game_split(*args))
        assert "0 matches with rally-by-rally data" in format_run_correlation(run_correlation(*args))


# ---------------------------------------------------------------- matches that are not finished yet (real: an ongoing event)

def test_the_funnel_counts_a_pending_match_as_pending() -> None:
    with HistoryStore() as store:
        _add_event(store, 1, "Ongoing", d(9, 25), d(9, 29), [
            {"date": None, "round": "R64", "won": None, "status": "bye"},
            {"date": d(9, 26), "round": "R32", "won": None, "status": "scheduled"},
        ])
        _add_event(store, 2, "Finished", d(8, 1), d(8, 6), [_win(d(8, 2), "R64"), _win(d(8, 3), "R32"), _loss(d(8, 4), "R16")], event_id=2)
        p = round_progress(store.connection, 1, d(1, 1), d(12, 31))
        table = {r.round: (r.reached, r.won, r.lost, r.pending) for r in p.rounds}
        assert table["R64"] == (2, 2, 0, 0)          # the bye and a played win
        assert table["R32"] == (2, 1, 0, 1)          # one win and one match still to play
        assert table["R16"] == (1, 0, 1, 0)
        for r in p.rounds:
            assert r.reached == r.won + r.lost + r.pending
        text = format_round_progress(p)
        assert "not played yet" in text and "scheduled or under way" in text


def test_the_funnel_text_has_no_pending_column_when_nothing_is_pending(connection: sqlite3.Connection) -> None:
    assert "not played yet" not in format_round_progress(round_progress(connection, CHRISTIE, SINCE, UNTIL))


def test_a_tournament_with_no_match_played_yet_is_left_out_of_the_calendar() -> None:
    with HistoryStore() as store:
        _add_event(store, 1, "Started", d(9, 1), d(9, 5), [_win(d(9, 2), "R32")])
        _add_event(store, 2, "Ongoing, only a bye so far", d(9, 25), d(9, 29), [
            {"date": None, "round": "R64", "won": None, "status": "bye"},
            {"date": d(9, 26), "round": "R32", "won": None, "status": "scheduled"},
        ], event_id=2)
        a = activity(store.connection, 1, d(9, 1), d(9, 25))
    assert [s.name for s in a.spans] == ["Started"]
    assert any("Ongoing, only a bye so far: entered, but no match has been played yet" in n for n in a.notes)
    assert a.days_on_court == 1 and a.days_present == 1


def test_a_match_scheduled_after_a_played_one_does_not_extend_the_stay() -> None:
    with HistoryStore() as store:
        _add_event(store, 1, "Ongoing", d(9, 20), d(9, 29), [
            _win(d(9, 21), "R32"), {"date": d(9, 27), "round": "R16", "won": None, "status": "scheduled"}])
        a = activity(store.connection, 1, d(9, 1), d(9, 30))
    assert (a.spans[0].first_match, a.spans[0].last_match, a.days_present) == (d(9, 21), d(9, 21), 1)


def test_days_on_tour_are_counted_inside_the_window_only(calendar: sqlite3.Connection) -> None:
    a = activity(calendar, 1, d(1, 8), d(2, 5))
    t1 = next(s for s in a.spans if s.name == "T1")
    assert (t1.first_match, t1.last_match, t1.days_present) == (d(1, 6), d(1, 8), 1)  # 6-7 Jan are before the window
    assert sum(min(s.days_present, 99) for s in a.spans) >= a.days_present


def test_the_real_ongoing_event_is_seen_as_pending() -> None:
    """Asian Games 2026 (individual): a bye in R64 and an R32 match planned for 26 Sep, from the real response."""
    from bwf_player.matches import parse_matches

    matches, _ = parse_matches(load_fixture("matches_73442_5874_29880.json"), CHRISTIE, 5874)
    with HistoryStore() as store:
        entry = TournamentEntry(tournament_id=5874, name="Asian Games (Individual)", start_date=date(2026, 9, 25),
                                end_date=date(2026, 9, 29), type_id=0, event_code="MS", event_id=29880, position="R32",
                                matches_won=1, matches_lost=0)
        store.save_tournaments(TournamentHistory(player_id=str(CHRISTIE), since=date(2026, 9, 1), until=date(2026, 9, 25), entries=[entry]),
                               player_name="Jonatan CHRISTIE")
        store.save_matches(EventMatches(tournament_id=5874, event_code="MS", event_id=29880, matches=matches))
        p = round_progress(store.connection, CHRISTIE, date(2026, 9, 1), date(2026, 9, 25))
        table = {r.round: (r.reached, r.won, r.lost, r.pending) for r in p.rounds}
        assert table["R64"] == (1, 1, 0, 0) and table["R32"] == (1, 0, 0, 1)
        assert game_split(store.connection, CHRISTIE, date(2026, 9, 1), date(2026, 9, 25)).matches == 0
        assert activity(store.connection, CHRISTIE, date(2026, 9, 1), date(2026, 9, 25)).spans == []
