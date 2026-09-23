"""R8b: storing the game details (Match tab, Game tabs, rallies), the migration to schema 2 and the CSV files. Offline."""

from __future__ import annotations

import csv
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from bwf_player import (
    BwfNotFoundError,
    details_targets,
    get_match_details,
    get_matches,
    get_tournaments,
)
from bwf_player.exceptions import BwfClientError, InvalidInputError
from bwf_player.models import Rally, SideStats
from bwf_player.store import SCHEMA_VERSION, HistoryStore
from tests.fakes import FakeApiClient

TODAY = date(2026, 9, 21)
CHRISTIE, AADHYA = 73442, 89438
EXAMPLE_MATCH_ID = 1505450  # All England 2026, R16, code 13: LIN Chun-Yi (side 1) beat Christie (side 2) 21-19, 21-12
GAME_1 = (
    "0-1 1-1 1-2 2-2 3-2 3-3 3-4 4-4 5-4 5-5 6-5 6-6 7-6 8-6 9-6 9-7 9-8 9-9 9-10 9-11 10-11 11-11 12-11 13-11 14-11 "
    "15-11 16-11 16-12 16-13 17-13 17-14 18-14 19-14 20-14 20-15 20-16 20-17 20-18 20-19 21-19"
)
STAT_FIELDS = tuple(SideStats.model_fields)


def load(store: HistoryStore, player: int, name: str, *, details: bool = True) -> None:
    """Download (from fixtures) and save a player's history, and the details of every match that has them."""
    client = FakeApiClient()
    history = get_tournaments(player, client, today=TODAY, with_categories=False)
    store.save_tournaments(history, player_name=name)
    for entry in history.entries:
        event = get_matches(player, entry, client)
        store.save_matches(event)
        for match in details_targets(event.matches) if details else []:
            try:
                store.save_match_details(get_match_details(match.tournament_id, match.match_code, client, match=match))
            except BwfNotFoundError:
                continue  # a match with no saved response


def rows(store: HistoryStore, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    return store.connection.execute(sql, params).fetchall()


def dump(store: HistoryStore, *tables: str) -> dict[str, list[tuple[Any, ...]]]:
    return {t: rows(store, f"SELECT * FROM {t} ORDER BY 1, 2, 3") for t in tables}


DETAIL_TABLES = ("match_stats", "game_stats", "rallies")


@pytest.fixture(scope="module")
def full() -> Any:
    """Christie's whole year with all details, opened once (read-only tests only)."""
    with HistoryStore() as store:
        load(store, CHRISTIE, "Jonatan CHRISTIE")
        yield store


@pytest.fixture()
def store() -> Any:
    with HistoryStore() as opened:
        yield opened


def example_details() -> Any:
    return get_match_details(5515, 13, FakeApiClient())


# ---------------------------------------------------------------- a new database

def test_a_new_database_has_the_detail_tables_and_views(store: HistoryStore) -> None:
    names = {r[0] for r in rows(store, "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
    assert {"match_stats", "game_stats", "rallies", "player_match_stats_view", "player_game_view", "player_rally_view"} <= names
    assert rows(store, "PRAGMA user_version") == [(SCHEMA_VERSION,)] == [(2,)]
    assert {"match_stats", "game_stats", "rallies"} <= set(store.counts())
    assert set(store.counts().values()) == {0}


def test_the_stat_columns_cover_every_field_of_both_sides(store: HistoryStore) -> None:
    columns = {r[1] for r in rows(store, "PRAGMA table_info(match_stats)")}
    assert {f"side{s}_{f}" for f in STAT_FIELDS for s in (1, 2)} <= columns and len(STAT_FIELDS) == 12
    assert {f"side{s}_{f}" for f in STAT_FIELDS for s in (1, 2)} <= {r[1] for r in rows(store, "PRAGMA table_info(game_stats)")}


# ---------------------------------------------------------------- what is stored

def test_counts_for_christies_year(full: HistoryStore) -> None:
    counts = full.counts()
    assert (counts["matches"], counts["match_stats"], counts["game_stats"]) == (58, 58, 138)
    total = sum(len(g.rallies) for m in _details_of_christie() for g in m.games)
    assert counts["rallies"] == total > 4000


def _details_of_christie() -> list[Any]:
    client = FakeApiClient()
    out = []
    for entry in get_tournaments(CHRISTIE, client, today=TODAY, with_categories=False).entries:
        for m in details_targets(get_matches(CHRISTIE, entry, client).matches):
            out.append(get_match_details(m.tournament_id, m.match_code, client))
    return out


def test_every_game_has_as_many_rallies_as_points(full: HistoryStore) -> None:
    bad = rows(
        full,
        """SELECT g.match_id, g.game_no FROM games g
           JOIN game_stats gs ON gs.match_id = g.match_id AND gs.game_no = g.game_no
           WHERE (SELECT COUNT(*) FROM rallies r WHERE r.match_id = g.match_id AND r.game_no = g.game_no)
                 <> g.side1_points + g.side2_points OR gs.total_points_played <> g.side1_points + g.side2_points""",
    )
    assert bad == []


def test_the_match_tab_of_the_example_match(full: HistoryStore) -> None:
    row = rows(full, "SELECT * FROM match_stats WHERE match_id = ?", EXAMPLE_MATCH_ID)[0]
    columns = [c[1] for c in rows(full, "PRAGMA table_info(match_stats)")]
    got = dict(zip(columns, row))
    assert got["start_local"] == "2026-03-05 19:15:00" and got["venue"] == "Utilita Arena Birmingham"
    assert (got["score_status"], got["tracked"], got["checks_ok"], got["differences"]) == (0, 1, 1, None)
    assert (got["side1_result"], got["side2_result"]) == (2, 0)
    assert (got["side1_consecutive_points"], got["side2_consecutive_points"]) == (7, 5)
    assert (got["side1_game_points"], got["side2_game_points"]) == (7, 0)
    assert (got["side1_rallies_played"], got["side2_rallies_played"]) == (73, 73)
    assert (got["side1_rallies_won"], got["side2_rallies_won"]) == (42, 31)
    # the tracking fields are kept as sent: 0 where the site sends 0, NULL where it sends null
    assert (got["side1_other"], got["side1_challenge_used"], got["side1_smash_winner"]) == (0, 0, None)


def test_the_game_tabs_of_the_example_match(full: HistoryStore) -> None:
    one, two = rows(
        full,
        """SELECT game_no, total_points_played, tracked, side1_consecutive_points, side2_consecutive_points,
                  side1_game_points, side2_game_points, side1_rallies_played, side2_rallies_played,
                  side1_rallies_won, side2_rallies_won FROM game_stats WHERE match_id = ? ORDER BY game_no""",
        EXAMPLE_MATCH_ID,
    )
    assert one == (1, 40, 1, 7, 5, 6, 0, 40, 40, 21, 19)
    assert two == (2, 33, 1, 5, 4, 1, 0, 33, 33, 21, 12)


def test_the_rallies_of_game_one(full: HistoryStore) -> None:
    sequence = rows(
        full,
        "SELECT group_concat(p, ' ') FROM (SELECT side1_points || '-' || side2_points AS p FROM rallies "
        "WHERE match_id = ? AND game_no = 1 ORDER BY rally_no)",
        EXAMPLE_MATCH_ID,
    )
    assert sequence == [(GAME_1,)]
    assert rows(full, "SELECT rally_no, winner_side FROM rallies WHERE match_id = ? AND game_no = 1 ORDER BY rally_no LIMIT 4", EXAMPLE_MATCH_ID) == [
        (1, 2), (2, 1), (3, 2), (4, 1)
    ]


def test_the_match_code_is_stored_on_the_match(full: HistoryStore) -> None:
    assert rows(full, "SELECT match_code FROM matches WHERE match_id = ?", EXAMPLE_MATCH_ID) == [("13",)]
    assert rows(full, "SELECT COUNT(*) FROM matches WHERE match_code IS NULL") == [(0,)]


def test_every_real_match_was_checked_and_agrees(full: HistoryStore) -> None:
    assert rows(full, "SELECT DISTINCT tracked, checks_ok, differences FROM match_stats") == [(1, 1, None)]


# ---------------------------------------------------------------- the player's point of view

def test_match_tab_from_the_players_side_when_the_player_is_side_two(full: HistoryStore) -> None:
    row = rows(
        full,
        """SELECT player_games_won, opponent_games_won, player_consecutive_points, opponent_consecutive_points,
                  player_game_points, opponent_game_points, player_rallies_played, player_rallies_won, opponent_rallies_won,
                  tracked, checks_ok, venue, match_code FROM player_match_stats_view WHERE match_id = ?""",
        EXAMPLE_MATCH_ID,
    )
    assert row == [(0, 2, 5, 7, 0, 7, 73, 31, 42, 1, 1, "Utilita Arena Birmingham", "13")]


def test_match_tab_from_the_players_side_when_the_player_is_side_one(full: HistoryStore) -> None:
    """China Masters 2026, R32 (code 16): Christie was side 1 and won 21-17, 21-19."""
    row = rows(
        full,
        """SELECT player_games_won, opponent_games_won, player_rallies_won, opponent_rallies_won, round, tournament
           FROM player_match_stats_view WHERE match_code = '16' AND tournament_id = 5625""",
    )
    assert row == [(2, 0, 42, 36, "R32", "LI-NING China Masters 2026")]  # 21+21 v 17+19 points
    # on side 1 the player's figures are the side-1 columns, unflipped
    assert rows(full, "SELECT ms.side1_rallies_won, ms.side2_rallies_won, mp.side FROM match_stats ms "
                      "JOIN matches m ON m.match_id = ms.match_id "
                      "JOIN match_players mp ON mp.match_id = m.match_id AND mp.player_id = 73442 "
                      "WHERE m.match_code = '16' AND m.tournament_id = 5625") == [(42, 36, 1)]


def test_game_tabs_from_the_players_side(full: HistoryStore) -> None:
    game1, game2 = rows(
        full,
        """SELECT game_no, player_points, opponent_points, total_points_played, player_consecutive_points,
                  opponent_consecutive_points, player_game_points, opponent_game_points, player_rallies_won, opponent_rallies_won
           FROM player_game_view WHERE match_id = ? ORDER BY game_no""",
        EXAMPLE_MATCH_ID,
    )
    assert game1 == (1, 19, 21, 40, 5, 7, 0, 6, 19, 21)
    assert game2 == (2, 12, 21, 33, 4, 5, 0, 1, 12, 21)


def test_rallies_from_the_players_side(full: HistoryStore) -> None:
    game = rows(
        full,
        "SELECT rally_no, player_points, opponent_points, rally_won_by_player FROM player_rally_view "
        "WHERE match_id = ? AND game_no = 1 ORDER BY rally_no",
        EXAMPLE_MATCH_ID,
    )
    assert game[:4] == [(1, 1, 0, 1), (2, 1, 1, 0), (3, 2, 1, 1), (4, 2, 2, 0)]  # Christie (side 2) won rallies 1 and 3
    assert game[-1] == (40, 19, 21, 0)
    assert sum(r[3] for r in game) == 19 and len(game) == 40


def test_the_views_list_only_players_whose_own_history_was_saved(full: HistoryStore) -> None:
    for view in ("player_match_stats_view", "player_game_view", "player_rally_view"):
        assert rows(full, f"SELECT DISTINCT player_id FROM {view}") == [(CHRISTIE,)]
    assert rows(full, "SELECT COUNT(*) FROM player_match_stats_view") == [(58,)]
    assert rows(full, "SELECT COUNT(*) FROM player_game_view") == [(138,)]


def test_games_without_saved_details_still_appear_with_null_statistics(store: HistoryStore) -> None:
    load(store, CHRISTIE, "Jonatan CHRISTIE", details=False)
    assert rows(store, "SELECT COUNT(*) FROM player_game_view") == [(138,)]
    assert rows(store, "SELECT DISTINCT tracked, player_rallies_won, total_points_played FROM player_game_view") == [(None, None, None)]
    assert rows(store, "SELECT COUNT(*) FROM player_match_stats_view") == [(0,)]  # a match tab needs its details


# ---------------------------------------------------------------- matches the site does not track

@pytest.fixture()
def aadhya(store: HistoryStore) -> HistoryStore:
    load(store, AADHYA, "Aadhya SHINE")
    return store


def test_an_untracked_match_has_null_statistics_and_no_rallies(aadhya: HistoryStore) -> None:
    """Telangana International Challenge, qualifying: the site gives only the scores."""
    match_id = 1479305
    row = rows(aadhya, "SELECT tracked, checks_ok, venue, side1_result, side2_result, side1_consecutive_points, "
                       "side1_rallies_won, side1_smash_winner, side1_challenge_used FROM match_stats WHERE match_id = ?", match_id)
    assert row == [(0, 1, "GMC Balayogi Sports Complex", 2, 0, None, None, None, None)]  # NULL, not 0
    games = rows(aadhya, "SELECT game_no, total_points_played, tracked, side1_rallies_played, side2_game_points "
                         "FROM game_stats WHERE match_id = ? ORDER BY game_no", match_id)
    assert games == [(1, 40, 0, None, None), (2, 44, 0, None, None)]
    assert rows(aadhya, "SELECT COUNT(*) FROM rallies WHERE match_id = ?", match_id) == [(0,)]


def test_an_untracked_match_appears_in_the_views_with_nulls(aadhya: HistoryStore) -> None:
    row = rows(aadhya, "SELECT player_games_won, opponent_games_won, tracked, player_consecutive_points, opponent_rallies_won "
                       "FROM player_match_stats_view WHERE match_id = 1479305")
    assert row == [(0, 2, 0, None, None)]  # Aadhya SHINE was side 2 and lost 0-2
    assert rows(aadhya, "SELECT COUNT(*) FROM player_rally_view WHERE match_id = 1479305") == [(0,)]
    games = rows(aadhya, "SELECT game_no, player_points, opponent_points, tracked, player_rallies_won FROM player_game_view "
                         "WHERE match_id = 1479305 ORDER BY game_no")
    assert games == [(1, 19, 21, 0, None), (2, 21, 23, 0, None)]


# ---------------------------------------------------------------- saving again

def test_saving_the_details_twice_changes_nothing() -> None:
    with HistoryStore() as store:
        load(store, CHRISTIE, "Jonatan CHRISTIE")
        before = dump(store, *DETAIL_TABLES, "matches")
        load(store, CHRISTIE, "Jonatan CHRISTIE")
        assert dump(store, *DETAIL_TABLES, "matches") == before


def test_saving_replaces_what_was_stored_for_the_match(store: HistoryStore) -> None:
    load(store, CHRISTIE, "Jonatan CHRISTIE", details=False)
    details = example_details()
    store.save_match_details(details)
    changed = details.model_copy(deep=True)
    changed.games = changed.games[:1]  # a game disappears
    changed.games[0].rallies = changed.games[0].rallies[:10]  # and rallies are lost
    changed.side1 = SideStats(consecutive_points=1)
    store.save_match_details(changed)
    assert rows(store, "SELECT game_no FROM game_stats WHERE match_id = ?", EXAMPLE_MATCH_ID) == [(1,)]
    assert rows(store, "SELECT COUNT(*) FROM rallies WHERE match_id = ?", EXAMPLE_MATCH_ID) == [(10,)]
    assert rows(store, "SELECT side1_consecutive_points, side1_game_points FROM match_stats WHERE match_id = ?", EXAMPLE_MATCH_ID) == [(1, None)]
    assert store.counts()["match_stats"] == 1


def test_a_failed_check_is_stored_with_its_differences(store: HistoryStore) -> None:
    load(store, CHRISTIE, "Jonatan CHRISTIE", details=False)
    details = example_details()
    details.differences = ["Game 1: something", "Match: something else"]
    details.checks_ok = False
    store.save_match_details(details)
    assert rows(store, "SELECT checks_ok, differences FROM match_stats WHERE match_id = ?", EXAMPLE_MATCH_ID) == [
        (0, "Game 1: something\nMatch: something else")
    ]


def test_details_for_a_match_with_unknown_checks_store_null(store: HistoryStore) -> None:
    load(store, CHRISTIE, "Jonatan CHRISTIE", details=False)
    details = example_details()
    details.checks_ok = None
    store.save_match_details(details)
    assert rows(store, "SELECT checks_ok FROM match_stats") == [(None,)]


def test_the_match_code_is_not_erased_by_a_later_save_without_one(store: HistoryStore) -> None:
    client = FakeApiClient()
    entry = next(e for e in get_tournaments(CHRISTIE, client, today=TODAY, with_categories=False).entries if e.tournament_id == 5515)
    store.save_tournaments(get_tournaments(CHRISTIE, client, today=TODAY, with_categories=False), player_name="x")
    event = get_matches(CHRISTIE, entry, client)
    store.save_matches(event)
    without = event.model_copy(deep=True)
    for match in without.matches:
        match.match_code = None
    store.save_matches(without)
    assert rows(store, "SELECT match_code FROM matches ORDER BY match_id") == [(m.match_code,) for m in sorted(event.matches, key=lambda m: m.match_id)]


def test_the_details_fill_in_a_missing_match_code(store: HistoryStore) -> None:
    load(store, CHRISTIE, "Jonatan CHRISTIE", details=False)
    store.connection.execute("UPDATE matches SET match_code = NULL")
    store.save_match_details(example_details())
    assert rows(store, "SELECT match_code FROM matches WHERE match_id = ?", EXAMPLE_MATCH_ID) == [("13",)]
    assert rows(store, "SELECT COUNT(*) FROM matches WHERE match_code IS NOT NULL") == [(1,)]


# ---------------------------------------------------------------- refusals and rollback

def test_details_of_a_match_that_is_not_stored_are_refused(store: HistoryStore) -> None:
    with pytest.raises(InvalidInputError, match="save its matches first"):
        store.save_match_details(example_details())
    assert set(store.counts().values()) == {0}


def test_details_without_a_match_id_are_refused(store: HistoryStore) -> None:
    bye = get_match_details(5378, 535, FakeApiClient())
    assert bye.match_id is None
    with pytest.raises(InvalidInputError, match="do not name a match id"):
        store.save_match_details(bye)


def test_details_for_another_tournament_are_refused(store: HistoryStore) -> None:
    load(store, CHRISTIE, "Jonatan CHRISTIE", details=False)
    wrong = example_details().model_copy(update={"tournament_id": 9999})
    with pytest.raises(InvalidInputError, match="stored under tournament 5515"):
        store.save_match_details(wrong)
    assert store.counts()["match_stats"] == 0


def test_a_failed_save_leaves_the_earlier_details_untouched(store: HistoryStore) -> None:
    load(store, CHRISTIE, "Jonatan CHRISTIE", details=False)
    store.save_match_details(example_details())
    before = dump(store, *DETAIL_TABLES)
    broken = example_details()
    broken.games[1].rallies[5] = Rally.model_construct(rally_no=6, side1_points=3, side2_points=3, winner_side=5)  # violates the CHECK
    with pytest.raises(sqlite3.IntegrityError):
        store.save_match_details(broken)
    assert dump(store, *DETAIL_TABLES) == before


def test_foreign_keys_protect_the_detail_tables(store: HistoryStore) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("INSERT INTO rallies (match_id, game_no, rally_no, side1_points, side2_points) VALUES (1, 1, 1, 1, 0)")
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("INSERT INTO match_stats (match_id, tracked) VALUES (1, 1)")


# ---------------------------------------------------------------- migration from schema version 1

def _downgrade_to_version_1(path: Path) -> None:
    """Turn a current database into what a version 1 file looked like: no match_code, no detail tables or views."""
    conn = sqlite3.connect(path)
    for view in ("player_match_stats_view", "player_game_view", "player_rally_view", "player_match_view"):
        conn.execute(f"DROP VIEW {view}")
    for table in DETAIL_TABLES:
        conn.execute(f"DROP TABLE {table}")
    conn.execute("ALTER TABLE matches DROP COLUMN match_code")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


def test_a_version_1_database_is_migrated_and_keeps_its_data(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite"
    with HistoryStore(path) as store:
        load(store, CHRISTIE, "Jonatan CHRISTIE", details=False)
    _downgrade_to_version_1(path)
    conn = sqlite3.connect(path)
    assert "match_code" not in {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    old_tables = {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2, 3").fetchall() for t in ("players", "tournaments", "results", "match_players", "games")}
    old_matches = conn.execute("SELECT match_id, tournament_id, seq, round, status, winner_side FROM matches ORDER BY match_id").fetchall()
    conn.close()

    with HistoryStore(path) as store:
        assert rows(store, "PRAGMA user_version") == [(2,)]
        assert "match_code" in {r[1] for r in rows(store, "PRAGMA table_info(matches)")}
        assert {"match_stats", "game_stats", "rallies", "player_match_stats_view", "player_match_view"} <= {
            r[0] for r in rows(store, "SELECT name FROM sqlite_master")
        }
        assert dump(store, "players", "tournaments", "results", "match_players", "games") == old_tables
        assert rows(store, "SELECT match_id, tournament_id, seq, round, status, winner_side FROM matches ORDER BY match_id") == old_matches
        assert rows(store, "SELECT COUNT(*) FROM matches WHERE match_code IS NOT NULL") == [(0,)]  # not known yet
        assert len(rows(store, "SELECT * FROM player_match_view")) == 58  # the old view works again on the new column set


def test_a_migrated_database_takes_details_and_fills_the_codes(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite"
    with HistoryStore(path) as store:
        load(store, CHRISTIE, "Jonatan CHRISTIE", details=False)
    _downgrade_to_version_1(path)
    with HistoryStore(path) as store:
        load(store, CHRISTIE, "Jonatan CHRISTIE")  # the same download again, now with details
        assert store.counts()["match_stats"] == 58 and store.counts()["matches"] == 58
        assert rows(store, "SELECT COUNT(*) FROM matches WHERE match_code IS NULL") == [(0,)]
        assert rows(store, "SELECT player_games_won FROM player_match_stats_view WHERE match_id = ?", EXAMPLE_MATCH_ID) == [(0,)]


def test_opening_a_current_database_again_is_harmless(tmp_path: Path) -> None:
    path = tmp_path / "h.sqlite"
    with HistoryStore(path) as store:
        load(store, CHRISTIE, "Jonatan CHRISTIE")
        before = dump(store, "matches", *DETAIL_TABLES)
    for _ in range(2):
        with HistoryStore(path) as again:
            assert dump(again, "matches", *DETAIL_TABLES) == before and rows(again, "PRAGMA user_version") == [(2,)]


def test_a_newer_schema_is_still_refused(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()
    with pytest.raises(BwfClientError, match="schema version 3"):
        HistoryStore(path)


# ---------------------------------------------------------------- CSV export

def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


PERSPECTIVE = [f"{who}_{field}" for field in STAT_FIELDS for who in ("player", "opponent")]
HEAD = ["player_id", "player_name", "tournament_id", "tournament", "event_code", "round", "match_date", "match_id", "match_code"]


@pytest.fixture(scope="module")
def files(full: HistoryStore, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    return full.export_csv(tmp_path_factory.mktemp("csv"))


def test_the_detail_csv_files_and_their_columns(files: dict[str, Path]) -> None:
    assert set(files) == {"results.csv", "matches.csv", "games.csv", "match_stats.csv", "game_stats.csv", "rallies.csv"}
    for name, expected in (
        ("match_stats.csv", HEAD + ["start_local", "venue", "duration_min", "tracked", "checks_ok", "player_games_won", "opponent_games_won", *PERSPECTIVE]),
        ("game_stats.csv", HEAD + ["game_no", "player_points", "opponent_points", "total_points_played", "tracked", *PERSPECTIVE]),
        ("rallies.csv", HEAD + ["game_no", "rally_no", "player_points", "opponent_points", "rally_won_by_player"]),
    ):
        with files[name].open(encoding="utf-8-sig", newline="") as handle:
            assert next(csv.reader(handle)) == expected, name


def test_the_detail_csv_row_counts(files: dict[str, Path], full: HistoryStore) -> None:
    assert len(read(files["match_stats.csv"])) == 58
    assert len(read(files["game_stats.csv"])) == 138
    assert len(read(files["rallies.csv"])) == full.counts()["rallies"]


def test_match_stats_csv_shows_the_match_tab_from_the_players_side(files: dict[str, Path]) -> None:
    row = next(r for r in read(files["match_stats.csv"]) if r["match_id"] == str(EXAMPLE_MATCH_ID))
    assert row["player_name"] == "Jonatan CHRISTIE" and row["match_code"] == "13" and row["round"] == "R16"
    assert (row["player_games_won"], row["opponent_games_won"]) == ("0", "2")
    assert (row["player_consecutive_points"], row["opponent_consecutive_points"]) == ("5", "7")
    assert (row["player_game_points"], row["opponent_game_points"]) == ("0", "7")
    assert (row["player_rallies_played"], row["player_rallies_won"], row["opponent_rallies_won"]) == ("73", "31", "42")
    assert (row["start_local"], row["venue"], row["duration_min"], row["tracked"], row["checks_ok"]) == (
        "2026-03-05 19:15:00", "Utilita Arena Birmingham", "48", "1", "1")
    assert row["player_smash_winner"] == "" and row["player_other"] == "0"  # blank = the site sends null


def test_game_stats_csv_content(files: dict[str, Path]) -> None:
    rows_ = [r for r in read(files["game_stats.csv"]) if r["match_id"] == str(EXAMPLE_MATCH_ID)]
    assert [(r["game_no"], r["player_points"], r["opponent_points"], r["total_points_played"]) for r in rows_] == [
        ("1", "19", "21", "40"), ("2", "12", "21", "33")]
    assert (rows_[0]["player_consecutive_points"], rows_[0]["opponent_game_points"], rows_[0]["player_rallies_won"]) == ("5", "6", "19")


def test_rallies_csv_content(files: dict[str, Path]) -> None:
    game = [r for r in read(files["rallies.csv"]) if r["match_id"] == str(EXAMPLE_MATCH_ID) and r["game_no"] == "1"]
    assert len(game) == 40 and [r["rally_no"] for r in game] == [str(i) for i in range(1, 41)]
    assert [(r["player_points"], r["opponent_points"], r["rally_won_by_player"]) for r in game[:3]] == [("1", "0", "1"), ("1", "1", "0"), ("2", "1", "1")]


def test_the_detail_csv_files_are_ordered_by_date_then_round_order(files: dict[str, Path]) -> None:
    rows_ = read(files["match_stats.csv"])
    dates = [r["match_date"] for r in rows_]
    assert dates == sorted(dates)
    korea = [r["round"] for r in rows_ if r["tournament_id"] == "5288"]
    assert korea == ["R32", "R16", "QF", "SF", "Final"]


def test_matches_csv_has_the_match_code_last(files: dict[str, Path]) -> None:
    with files["matches.csv"].open(encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle))
    assert header[-2:] == ["match_id", "match_code"]
    assert {r["match_code"] for r in read(files["matches.csv"])} != {""}


def test_untracked_matches_export_blanks_not_zeros(aadhya: HistoryStore, tmp_path: Path) -> None:
    out = aadhya.export_csv(tmp_path)
    row = next(r for r in read(out["match_stats.csv"]) if r["match_id"] == "1479305")
    assert (row["tracked"], row["player_consecutive_points"], row["opponent_rallies_won"], row["player_games_won"]) == ("0", "", "", "0")
    games = [r for r in read(out["game_stats.csv"]) if r["match_id"] == "1479305"]
    assert [(g["game_no"], g["player_points"], g["tracked"], g["player_rallies_played"]) for g in games] == [("1", "19", "0", ""), ("2", "21", "0", "")]
    assert [r for r in read(out["rallies.csv"]) if r["match_id"] == "1479305"] == []


def test_detail_csv_files_of_a_history_without_details_hold_only_headers(store: HistoryStore, tmp_path: Path) -> None:
    load(store, CHRISTIE, "Jonatan CHRISTIE", details=False)
    out = store.export_csv(tmp_path)
    assert read(out["match_stats.csv"]) == [] and read(out["rallies.csv"]) == []
    assert len(read(out["game_stats.csv"])) == 138  # the games are known; their statistics are blank
    assert {r["tracked"] for r in read(out["game_stats.csv"])} == {""}
