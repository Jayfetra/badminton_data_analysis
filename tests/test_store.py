"""R7: SQLite storage and CSV export. Offline, on real fixtures."""

from __future__ import annotations

import csv
import logging
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from bwf_player import get_matches, get_tournaments
from bwf_player.exceptions import BwfClientError, InvalidInputError
from bwf_player.matches import parse_matches
from bwf_player.models import EventMatches, MatchPlayer, TournamentHistory
from bwf_player.store import SCHEMA_VERSION, HistoryStore
from tests.fakes import FakeApiClient, load_fixture

TODAY = date(2026, 9, 21)
CHRISTIE, FAJAR, DEJAN, APRIYANI = 73442, 88876, 81458, 81462


def _load(store: HistoryStore, player_id: int, name: str | None = None, *, categories: bool = False) -> TournamentHistory:
    """Download (from fixtures) and save one player's whole history."""
    client = FakeApiClient()
    history = get_tournaments(player_id, client, today=TODAY, with_categories=categories)
    store.save_tournaments(history, player_name=name)
    for entry in history.entries:
        store.save_matches(get_matches(player_id, entry, client))
    return history


def _rows(store: HistoryStore, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    return store.connection.execute(sql, params).fetchall()


def _dump(store: HistoryStore) -> dict[str, list[tuple[Any, ...]]]:
    return {
        table: _rows(store, f"SELECT * FROM {table} ORDER BY 1, 2, 3")
        for table in ("players", "tournaments", "results", "matches", "match_players", "games")
    }


@pytest.fixture()
def store() -> Any:
    with HistoryStore() as opened:
        yield opened


@pytest.fixture()
def christie(store: HistoryStore) -> HistoryStore:
    _load(store, CHRISTIE, "Jonatan CHRISTIE", categories=True)
    return store


# ---------------------------------------------------------------- opening the database

def test_a_new_database_has_the_tables_the_view_and_the_version(store: HistoryStore) -> None:
    names = {r[0] for r in _rows(store, "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
    assert {"players", "tournaments", "results", "matches", "match_players", "games", "player_match_view"} <= names
    assert _rows(store, "PRAGMA user_version") == [(SCHEMA_VERSION,)]
    assert _rows(store, "PRAGMA foreign_keys") == [(1,)]
    assert set(store.counts().values()) == {0}


def test_the_database_file_and_its_folders_are_created(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "history.sqlite"
    with HistoryStore(path):
        pass
    assert path.is_file()


def test_data_survives_closing_and_reopening(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite"
    with HistoryStore(path) as first:
        _load(first, CHRISTIE, "Jonatan CHRISTIE")
        counts = first.counts()
    with HistoryStore(path) as second:
        assert second.counts() == counts
        assert counts["matches"] == 58


def test_a_database_from_a_newer_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(BwfClientError, match="schema version"):
        HistoryStore(path)


def test_a_file_that_is_not_a_database_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "notes.sqlite"
    path.write_text("this is not a database " * 50, encoding="utf-8")
    with pytest.raises(BwfClientError, match="Cannot open"):
        HistoryStore(path)


def test_a_path_that_cannot_be_created_is_refused(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(BwfClientError, match="Cannot open"):
        HistoryStore(blocker / "history.sqlite")


# ---------------------------------------------------------------- what is stored

def test_counts_for_christies_year(christie: HistoryStore) -> None:
    counts = christie.counts()
    assert counts["tournaments"] == 19 and counts["results"] == 19
    assert counts["matches"] == 58
    assert counts["match_players"] == 116  # singles: two players per match
    assert counts["games"] == sum(  # every played game of every match
        len(m.games) for e in get_tournaments(CHRISTIE, FakeApiClient(), today=TODAY, with_categories=False).entries
        for m in get_matches(CHRISTIE, e, FakeApiClient()).matches
    ) == 138


def test_a_result_row(christie: HistoryStore) -> None:
    row = _rows(christie, "SELECT * FROM results WHERE tournament_id = 5625")[0]
    assert row == (73442, 5625, 28355, "MS", "R16", 1, 1, 2, 2, 74, 78)


def test_a_tournament_row_with_its_category(christie: HistoryStore) -> None:
    assert _rows(christie, "SELECT * FROM tournaments WHERE tournament_id = 5625") == [(
        5625, "LI-NING China Masters 2026", "HSBC BWF World Tour Super 750", "2026-09-01", "2026-09-06",
        "Shenzhen, China", "China", 0,
        "https://bwfworldtour.bwfbadminton.com/tournament/5625/li-ning-china-masters-2026/",
    )]


def test_the_subject_and_opponents_are_players(christie: HistoryStore) -> None:
    assert _rows(christie, "SELECT * FROM players WHERE player_id IN (73442, 84838) ORDER BY 1") == [
        (73442, "Jonatan CHRISTIE", "INA"), (84838, "LEONG Jun Hao", "MAS"),
    ]


def test_games_are_stored_in_the_sites_own_side_orientation(christie: HistoryStore) -> None:
    """Christie is side 1 in the China Masters match and side 2 in the Korea Open one."""
    side_one = get_matches(CHRISTIE, _entry(CHRISTIE, 5625), FakeApiClient()).matches[0]
    assert _rows(christie, "SELECT game_no, side1_points, side2_points FROM games WHERE match_id = ? ORDER BY 1",
                 side_one.match_id) == [(1, 21, 17), (2, 21, 19)]
    side_two = get_matches(CHRISTIE, _entry(CHRISTIE, 5288), FakeApiClient()).matches[0]
    assert (side_two.side, side_two.won) == (2, True)
    assert _rows(christie, "SELECT game_no, side1_points, side2_points FROM games WHERE match_id = ? ORDER BY 1",
                 side_two.match_id) == [(1, 11, 21), (2, 17, 21)]
    assert _rows(christie, "SELECT winner_side FROM matches WHERE match_id = ?", side_two.match_id) == [(2,)]


def _entry(player_id: int, tournament_id: int) -> Any:
    entries = get_tournaments(player_id, FakeApiClient(), today=TODAY, with_categories=False).entries
    return next(e for e in entries if e.tournament_id == tournament_id)


def test_sides_of_the_participants(christie: HistoryStore) -> None:
    match = get_matches(CHRISTIE, _entry(CHRISTIE, 5288), FakeApiClient()).matches[0]
    sides = dict(_rows(christie, "SELECT player_id, side FROM match_players WHERE match_id = ?", match.match_id))
    assert sides == {73442: 2, match.opponents[0].player_id: 1}


def test_winner_side_follows_the_subjects_result_on_either_side(christie: HistoryStore) -> None:
    rows = _rows(
        christie,
        """SELECT m.winner_side, mp.side, v.won FROM matches m
           JOIN match_players mp ON mp.match_id = m.match_id AND mp.player_id = 73442
           JOIN player_match_view v ON v.match_id = m.match_id AND v.player_id = 73442""",
    )
    assert len(rows) == 58
    assert all((winner == side) == bool(won) for winner, side, won in rows)


def test_matches_keep_their_playing_order(christie: HistoryStore) -> None:
    rounds = [r[0] for r in _rows(christie, "SELECT round FROM matches WHERE tournament_id = 5288 ORDER BY seq")]
    assert rounds == ["R32", "R16", "QF", "SF", "Final"]


# ---------------------------------------------------------------- the per-player view

def test_view_singles_rows(christie: HistoryStore) -> None:
    rows = _rows(
        christie,
        """SELECT round, won, partner, opponent_1, opponent_2, games, status, event_code, category
           FROM player_match_view WHERE tournament_id = 5625 ORDER BY seq""",
    )
    assert rows == [
        ("R32", 1, None, "LEONG Jun Hao", None, "21-17, 21-19", "played", "MS", "HSBC BWF World Tour Super 750"),
        ("R16", 0, None, "Jason GUNAWAN", None, "16-21, 16-21", "played", "MS", "HSBC BWF World Tour Super 750"),
    ]


def test_view_games_are_from_the_subjects_side_even_when_they_are_side_two(christie: HistoryStore) -> None:
    rows = _rows(christie, "SELECT round, games FROM player_match_view WHERE tournament_id = 5288 ORDER BY seq")
    assert rows[0] == ("R32", "21-11, 21-17") and rows[-1] == ("Final", "21-10, 15-21, 21-17")


def test_view_doubles_have_a_partner_and_two_opponents(store: HistoryStore) -> None:
    _load(store, FAJAR, "Fajar ALFIAN")
    rows = _rows(
        store,
        """SELECT round, won, partner, opponent_1, opponent_2, games FROM player_match_view
           WHERE player_id = 88876 AND tournament_id = 5288 ORDER BY seq""",
    )
    assert rows[-1] == ("Final", 0, "Muhammad Shohibul FIKRI", "KIM Won Ho", "SEO Seung Jae", "16-21, 21-23")
    assert {r[2] for r in rows} == {"Muhammad Shohibul FIKRI"}


def test_view_bye_walkover_and_retirement(store: HistoryStore) -> None:
    _load(store, FAJAR, "Fajar ALFIAN")
    _load(store, DEJAN, "Dejan FERDINANSYAH")
    bye = _rows(store, "SELECT won, opponent_1, games, status, partner FROM player_match_view "
                       "WHERE player_id = 88876 AND tournament_id = 5601 AND round = 'R64'")
    assert bye == [(None, None, None, "bye", "Muhammad Shohibul FIKRI")]
    walkover = _rows(store, "SELECT won, games, status FROM player_match_view "
                            "WHERE player_id = 81458 AND tournament_id = 5378 AND round = 'R16'")
    assert walkover == [(0, None, "walkover")]
    retired = _rows(store, "SELECT won, games, status FROM player_match_view "
                           "WHERE player_id = 88876 AND tournament_id = 5257 AND round = 'R32'")
    assert retired == [(1, "21-16", "retired")]
    assert _rows(store, "SELECT winner_side FROM matches WHERE status = 'bye' LIMIT 1") == [(None,)]


def test_view_only_lists_players_who_have_a_result_in_the_tournament(christie: HistoryStore) -> None:
    assert {r[0] for r in _rows(christie, "SELECT DISTINCT player_id FROM player_match_view")} == {73442}
    assert len(_rows(christie, "SELECT * FROM player_match_view")) == 58


def test_a_team_event_partner_changes_per_tie(store: HistoryStore) -> None:
    _load(store, FAJAR, "Fajar ALFIAN")
    partners = [r[0] for r in _rows(store, "SELECT partner FROM player_match_view "
                                           "WHERE player_id = 88876 AND tournament_id = 5600 ORDER BY seq")]
    assert partners == ["Muhammad Shohibul FIKRI", "Nikolaus JOAQUIN", "Muhammad Shohibul FIKRI"]


def test_two_events_at_one_tournament_are_kept_apart(store: HistoryStore) -> None:
    _load(store, APRIYANI, "Apriyani RAHAYU")
    events = _rows(store, "SELECT event_code, COUNT(*) FROM player_match_view "
                          "WHERE player_id = 81462 AND tournament_id = 5623 GROUP BY event_code ORDER BY 1")
    assert events == [("WD", 4), ("XD", 3)]
    assert len(_rows(store, "SELECT * FROM results WHERE player_id = 81462 AND tournament_id = 5623")) == 2


# ---------------------------------------------------------------- saving again

def test_saving_twice_changes_nothing(store: HistoryStore) -> None:
    _load(store, CHRISTIE, "Jonatan CHRISTIE", categories=True)
    first = _dump(store)
    _load(store, CHRISTIE, "Jonatan CHRISTIE", categories=True)
    assert _dump(store) == first


def test_a_corrected_match_replaces_its_games_and_players(christie: HistoryStore) -> None:
    event = get_matches(CHRISTIE, _entry(CHRISTIE, 5625), FakeApiClient())
    changed = event.model_copy(deep=True)
    match = changed.matches[0]
    match.games = match.games[:1]
    match.opponents = [MatchPlayer(player_id=999, name="Somebody ELSE", country="XXX")]
    christie.save_matches(changed)
    assert _rows(christie, "SELECT COUNT(*) FROM games WHERE match_id = ?", match.match_id) == [(1,)]
    assert _rows(christie, "SELECT player_id FROM match_players WHERE match_id = ? ORDER BY 1", match.match_id) == [(999,), (73442,)]
    assert christie.counts()["matches"] == 58


def test_the_same_match_from_both_players_views_is_one_consistent_match(christie: HistoryStore) -> None:
    """Christie beat LEONG Jun Hao 21-17 21-19; saving the match from Leong's side changes nothing."""
    before = _dump(christie)
    leong_view, notes = parse_matches(load_fixture("matches_73442_5625_28355.json"), 84838, 5625)
    assert [(m.side, m.won) for m in leong_view] == [(2, False)]  # the event's second match is not his
    assert len(notes) == 1 and "does not name the player" in notes[0]
    christie.save_matches(EventMatches(tournament_id=5625, event_code="MS", event_id=28355, matches=leong_view))
    after = _dump(christie)
    assert after["matches"] == before["matches"] and after["games"] == before["games"]
    assert after["match_players"] == before["match_players"]


def test_a_later_save_without_a_category_or_name_does_not_erase_them(christie: HistoryStore) -> None:
    history = get_tournaments(CHRISTIE, FakeApiClient(), today=TODAY, with_categories=False)
    assert all(e.category is None for e in history.entries)
    christie.save_tournaments(history)  # no categories, no player name
    assert _rows(christie, "SELECT category FROM tournaments WHERE tournament_id = 5625") == [("HSBC BWF World Tour Super 750",)]
    assert _rows(christie, "SELECT name, country FROM players WHERE player_id = 73442") == [("Jonatan CHRISTIE", "INA")]


def test_a_changed_result_is_updated(christie: HistoryStore) -> None:
    history = get_tournaments(CHRISTIE, FakeApiClient(), today=TODAY, with_categories=False)
    history.entries[-1].position = "QF"
    christie.save_tournaments(history)
    assert _rows(christie, "SELECT position FROM results WHERE tournament_id = 5625") == [("QF",)]
    assert christie.counts()["results"] == 19


def test_two_subjects_share_tournaments_and_opponents(store: HistoryStore) -> None:
    _load(store, FAJAR, "Fajar ALFIAN")
    _load(store, DEJAN, "Dejan FERDINANSYAH")
    assert {r[0] for r in _rows(store, "SELECT DISTINCT player_id FROM player_match_view")} == {FAJAR, DEJAN}
    both = _rows(store, "SELECT COUNT(*) FROM tournaments")[0][0]
    assert both == len({e.tournament_id for p in (FAJAR, DEJAN)
                        for e in get_tournaments(p, FakeApiClient(), today=TODAY, with_categories=False).entries})


# ---------------------------------------------------------------- errors and edge cases

def test_matches_of_an_unsaved_tournament_are_refused(store: HistoryStore) -> None:
    event = get_matches(CHRISTIE, _entry(CHRISTIE, 5625), FakeApiClient())
    with pytest.raises(InvalidInputError, match="save the tournament list first"):
        store.save_matches(event)
    assert store.counts()["matches"] == 0


def test_a_failed_save_leaves_nothing_behind(christie: HistoryStore, monkeypatch: pytest.MonkeyPatch) -> None:
    before = _dump(christie)
    event = get_matches(CHRISTIE, _entry(CHRISTIE, 5288), FakeApiClient())
    changed = event.model_copy(deep=True)
    changed.matches[0].games = []  # the first match would be rewritten before the failure
    original = HistoryStore._save_match
    calls = {"n": 0}

    def flaky(self: HistoryStore, *args: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 3:
            raise sqlite3.OperationalError("disk full")
        original(self, *args)

    monkeypatch.setattr(HistoryStore, "_save_match", flaky)
    with pytest.raises(sqlite3.OperationalError):
        christie.save_matches(changed)
    assert _dump(christie) == before


def test_a_player_without_an_id_is_skipped_with_a_warning(christie: HistoryStore, caplog: pytest.LogCaptureFixture) -> None:
    event = get_matches(CHRISTIE, _entry(CHRISTIE, 5625), FakeApiClient())
    changed = event.model_copy(deep=True)
    changed.matches[0].opponents = [MatchPlayer(player_id=None, name="No Id")]
    with caplog.at_level(logging.WARNING, logger="bwf_player.store"):
        christie.save_matches(changed)
    assert "No Id" in caplog.text
    assert _rows(christie, "SELECT COUNT(*) FROM match_players WHERE match_id = ?", changed.matches[0].match_id) == [(1,)]


def test_an_entry_without_an_event_is_stored_with_event_id_zero(store: HistoryStore) -> None:
    history = get_tournaments(CHRISTIE, FakeApiClient(), today=TODAY, with_categories=False)
    history.entries[0].event_id = None
    history.entries[0].event_code = None
    store.save_tournaments(history)
    assert _rows(store, "SELECT event_id, event_code FROM results WHERE tournament_id = ?", history.entries[0].tournament_id) == [(0, None)]
    store.save_tournaments(history)  # and it is still one row after a re-save
    assert store.counts()["results"] == 19


def test_an_empty_history_saves_only_the_player(store: HistoryStore) -> None:
    empty = get_tournaments("999999999", FakeApiClient(), today=TODAY)
    assert store.save_tournaments(empty, player_name="Nobody") == 0
    assert store.counts()["players"] == 1 and store.counts()["tournaments"] == 0


def test_awkward_text_is_stored_literally(store: HistoryStore) -> None:
    history = get_tournaments(CHRISTIE, FakeApiClient(), today=TODAY, with_categories=False)
    history.entries[0].name = "O'Brien Open\"; DROP TABLE players; --"
    store.save_tournaments(history, player_name="Émile 'Ünal' \"X\"")
    assert _rows(store, "SELECT name FROM tournaments WHERE tournament_id = ?", history.entries[0].tournament_id) == [
        ("O'Brien Open\"; DROP TABLE players; --",)
    ]
    assert _rows(store, "SELECT name FROM players WHERE player_id = 73442") == [("Émile 'Ünal' \"X\"",)]
    assert store.counts()["players"] == 1


def test_foreign_keys_are_enforced(store: HistoryStore) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("INSERT INTO results (player_id, tournament_id, event_id) VALUES (1, 2, 3)")


# ---------------------------------------------------------------- CSV export

def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_export_writes_the_history_files_and_the_game_detail_files(christie: HistoryStore, tmp_path: Path) -> None:
    written = christie.export_csv(tmp_path / "out")
    assert set(written) == {"results.csv", "matches.csv", "games.csv", "match_stats.csv", "game_stats.csv", "rallies.csv"}
    assert all(p.is_file() for p in written.values())
    assert len(_read(written["results.csv"])) == 19
    assert len(_read(written["matches.csv"])) == 58
    assert len(_read(written["games.csv"])) == 138


def test_results_csv_content(christie: HistoryStore, tmp_path: Path) -> None:
    rows = _read(christie.export_csv(tmp_path)["results.csv"])
    assert list(rows[0]) == [
        "player_id", "player_name", "tournament_id", "tournament", "category", "start_date", "end_date", "location",
        "country", "event_code", "event_id", "position", "matches_won", "matches_lost", "games_won", "games_lost",
        "points_for", "points_against", "url",
    ]
    assert [r["start_date"] for r in rows] == sorted(r["start_date"] for r in rows)
    last = rows[-1]
    assert (last["player_name"], last["tournament"], last["position"], last["event_id"]) == (
        "Jonatan CHRISTIE", "LI-NING China Masters 2026", "R16", "28355")
    thomas = next(r for r in rows if r["tournament_id"] == "5600")
    assert thomas["position"] == "" and thomas["category"] == "Grade 1 – Team Tournaments"


def test_matches_csv_content(store: HistoryStore, tmp_path: Path) -> None:
    _load(store, FAJAR, "Fajar ALFIAN")
    rows = _read(store.export_csv(tmp_path)["matches.csv"])
    final = next(r for r in rows if r["tournament_id"] == "5288" and r["round"] == "Final")
    assert final == {
        "player_id": "88876", "player_name": "Fajar ALFIAN", "tournament_id": "5288",
        "tournament": "SUWON VICTOR Korea Open 2025", "category": "", "event_code": "MD", "draw_name": "MD",
        "round": "Final", "match_date": "2025-09-28", "status": "played", "won": "0", "partner_id": "91440",
        "partner": "Muhammad Shohibul FIKRI", "opponent_1": "KIM Won Ho", "opponent_2": "SEO Seung Jae",
        "games": "16-21, 21-23", "duration_min": "50", "match_id": "1462807", "match_code": "317",
    }
    bye = next(r for r in rows if r["status"] == "bye")
    assert (bye["won"], bye["opponent_1"], bye["games"]) == ("", "", "")


def test_games_csv_content(christie: HistoryStore, tmp_path: Path) -> None:
    rows = _read(christie.export_csv(tmp_path)["games.csv"])
    first = next(r for r in rows if r["tournament_id"] == "5625" and r["round"] == "R32")
    second = next(r for r in rows if r["tournament_id"] == "5625" and r["round"] == "R32" and r["game_no"] == "2")
    assert (first["player_points"], first["opponent_points"], first["game_no"]) == ("21", "17", "1")
    assert (second["player_points"], second["opponent_points"]) == ("21", "19")
    # a game from a side-2 match is written from the subject's side
    korea = next(r for r in rows if r["tournament_id"] == "5288" and r["round"] == "R32" and r["game_no"] == "1")
    assert (korea["player_points"], korea["opponent_points"]) == ("21", "11")


def test_export_is_utf8_with_a_byte_order_mark_and_keeps_accents(store: HistoryStore, tmp_path: Path) -> None:
    history = get_tournaments(CHRISTIE, FakeApiClient(), today=TODAY, with_categories=False)
    store.save_tournaments(history, player_name="Émile Ünal, \"the\" player")
    path = store.export_csv(tmp_path)["results.csv"]
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert _read(path)[0]["player_name"] == "Émile Ünal, \"the\" player"


def test_export_replaces_existing_files_and_is_repeatable(christie: HistoryStore, tmp_path: Path) -> None:
    first = christie.export_csv(tmp_path)
    contents = {name: path.read_bytes() for name, path in first.items()}
    (tmp_path / "results.csv").write_text("stale", encoding="utf-8")
    second = christie.export_csv(tmp_path)
    assert {name: path.read_bytes() for name, path in second.items()} == contents


def test_export_of_an_empty_database_has_only_headers(store: HistoryStore, tmp_path: Path) -> None:
    for path in store.export_csv(tmp_path).values():
        assert len(path.read_text(encoding="utf-8-sig").splitlines()) == 1


def test_a_scheduled_match_is_stored_without_a_winner(store: HistoryStore) -> None:
    from bwf_player.matches import parse_matches
    from bwf_player.models import TournamentEntry

    matches, _ = parse_matches(load_fixture("matches_73442_5874_29880.json"), CHRISTIE, 5874)
    entry = TournamentEntry(tournament_id=5874, name="Asian Games (Individual)", start_date=date(2026, 9, 25),
                            end_date=date(2026, 9, 29), event_code="MS", event_id=29880, position="R32")
    store.save_tournaments(TournamentHistory(player_id=str(CHRISTIE), since=entry.start_date, until=entry.end_date, entries=[entry]),
                           player_name="Jonatan CHRISTIE")
    store.save_matches(EventMatches(tournament_id=5874, event_code="MS", event_id=29880, matches=matches))
    assert _rows(store, "SELECT round, status, winner_side, match_date, match_code FROM matches ORDER BY round") == [
        ("R32", "scheduled", None, "2026-09-26", "16"), ("R64", "bye", None, None, "32")]
    assert _rows(store, "SELECT round, won, games, status FROM player_match_view ORDER BY round") == [
        ("R32", None, None, "scheduled"), ("R64", None, None, "bye")]
    assert store.counts()["games"] == 0
