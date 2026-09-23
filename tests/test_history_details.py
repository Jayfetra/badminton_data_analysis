"""R8c: game details inside the one-call download (on by default), and in the command line. Offline."""

from __future__ import annotations

import csv
import importlib.util
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from bwf_player import BwfConfig, download_player_history, format_history
from bwf_player.exceptions import BlockedByCloudflareError, BwfClientError, BwfNotFoundError
from tests.fakes import FakeApiClient

TODAY = date(2026, 9, 21)
CHRISTIE = 73442
TABLES = ("players", "tournaments", "results", "matches", "match_players", "games", "match_stats", "game_stats", "rallies")
# Fixtures hold the details of every Christie match and of two games-only matches of Aadhya SHINE (Telangana, Nov 2025)
AADHYA_TELANGANA = {"since": date(2025, 11, 4), "until": date(2025, 11, 9)}
DEJAN_TITLE = {"since": date(2025, 9, 29), "until": date(2025, 10, 6)}  # Al Ain Masters: five matches, all tracked
DEJAN_BYE_AND_WALKOVER = {"since": date(2025, 11, 10), "until": date(2025, 11, 17)}


def _client(tmp_path: Path, cls: type[FakeApiClient] = FakeApiClient) -> FakeApiClient:
    return cls(BwfConfig(history_db_path=tmp_path / "d" / "h.sqlite", history_export_dir=tmp_path / "d" / "csv"))


def _dump(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    conn = sqlite3.connect(db)
    try:
        return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2, 3").fetchall() for t in TABLES}
    finally:
        conn.close()


def _query(db: Path, sql: str) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


@pytest.fixture(scope="module")
def christie(tmp_path_factory: pytest.TempPathFactory) -> Any:
    tmp_path = tmp_path_factory.mktemp("christie")
    client = _client(tmp_path)
    return download_player_history("Jonatan Christie", client, today=TODAY), client, tmp_path


# ---------------------------------------------------------------- the default: details are downloaded

def test_the_summary_counts_the_details(christie: Any) -> None:
    summary, _, _ = christie
    assert (summary.matches, summary.games) == (58, 138)
    assert summary.game_details == summary.game_details_tracked == 58 and summary.game_details_untracked == 0
    assert (summary.game_details_skipped, summary.game_details_not_found) == (0, 0)
    assert summary.all_details_agree is True and summary.game_details_disagreeing == []
    assert summary.rallies == sum(len(g.rallies) for d in summary.details for g in d.games) > 4000
    assert summary.all_totals_agree is True and summary.notes == []
    assert len(summary.details) == 58 and all(d.checks_ok for d in summary.details)


def test_one_details_request_per_match(christie: Any) -> None:
    _, client, _ = christie
    calls = client.calls_to("h2h/match")
    assert len(calls) == 58 and len({(c["tmt_id"], c["match_code"]) for c in calls}) == 58
    assert all(set(c) == {"tmt_id", "match_code"} for c in calls)
    assert len(client.calls_to("vue-player-tmt-matches")) == 19  # the history part is unchanged
    assert [c["tmtYear"] for c in client.calls_to("vue-player-tournaments")] == [2025, 2026]


def test_each_events_details_are_fetched_right_after_its_matches(christie: Any) -> None:
    _, client, _ = christie
    order = [endpoint for endpoint, _ in client.calls if endpoint in ("vue-player-tmt-matches", "h2h/match")]
    assert order[0] == "vue-player-tmt-matches" and order[1] == "h2h/match"  # so a failure keeps the earlier events whole
    assert order.count("vue-player-tmt-matches") == 19


def test_the_database_holds_the_details(christie: Any) -> None:
    summary, _, tmp_path = christie
    db = tmp_path / "d" / "h.sqlite"
    assert summary.database == str(db)
    counts = {t: len(rows) for t, rows in _dump(db).items()}
    assert (counts["matches"], counts["match_stats"], counts["game_stats"]) == (58, 58, 138)
    assert counts["rallies"] == summary.rallies
    assert _query(db, "SELECT DISTINCT tracked, checks_ok FROM match_stats") == [(1, 1)]
    assert _query(db, "SELECT COUNT(*) FROM matches WHERE match_code IS NULL") == [(0,)]


def test_the_six_csv_files_are_written(christie: Any) -> None:
    summary, _, tmp_path = christie
    assert set(summary.csv_files) == {"results.csv", "matches.csv", "games.csv", "match_stats.csv", "game_stats.csv", "rallies.csv"}
    for name, expected in (("match_stats.csv", 58), ("game_stats.csv", 138), ("rallies.csv", summary.rallies)):
        with Path(summary.csv_files[name]).open(encoding="utf-8-sig", newline="") as handle:
            assert len(list(csv.DictReader(handle))) == expected, name
        assert Path(summary.csv_files[name]).parent == tmp_path / "d" / "csv"


def test_the_summary_serialises_to_json(christie: Any) -> None:
    decoded = json.loads(christie[0].model_dump_json())
    assert decoded["game_details"] == 58 and decoded["all_details_agree"] is True and len(decoded["details"]) == 58


def test_running_again_changes_nothing(christie: Any) -> None:
    summary, _, tmp_path = christie
    before = _dump(tmp_path / "d" / "h.sqlite")
    again = download_player_history(CHRISTIE, _client(tmp_path), today=TODAY)
    assert again.rallies == summary.rallies and _dump(tmp_path / "d" / "h.sqlite") == before


def test_progress_names_each_event_and_each_match(tmp_path: Path) -> None:
    messages: list[str] = []
    download_player_history(CHRISTIE, _client(tmp_path), since=date(2026, 9, 1), until=date(2026, 9, 6), export=False, progress=messages.append)
    assert messages == [
        "Looking up the tournaments of player 73442",
        "[1/1] 2026-09-01 LI-NING China Masters 2026 (MS)",
        "    match 1/2: R32 (code 16), game details",
        "    match 2/2: R16 (code 8), game details",
    ]


# ---------------------------------------------------------------- the switch

def test_details_can_be_switched_off(tmp_path: Path) -> None:
    client = _client(tmp_path)
    summary = download_player_history(CHRISTIE, client, today=TODAY, game_details=False)
    assert client.calls_to("h2h/match") == []
    assert (summary.game_details, summary.game_details_skipped, summary.rallies, summary.details) == (0, 0, 0, [])
    assert summary.all_details_agree is None and summary.matches == 58
    db = tmp_path / "d" / "h.sqlite"
    assert _query(db, "SELECT COUNT(*) FROM match_stats") == [(0,)] and _query(db, "SELECT COUNT(*) FROM matches") == [(58,)]
    with Path(summary.csv_files["rallies.csv"]).open(encoding="utf-8-sig") as handle:
        assert len(handle.read().splitlines()) == 1  # header only
    assert "Game details" not in format_history(summary)


def test_details_can_be_added_to_an_existing_history_database(tmp_path: Path) -> None:
    download_player_history(CHRISTIE, _client(tmp_path), today=TODAY, game_details=False, export=False)
    before = _dump(tmp_path / "d" / "h.sqlite")
    summary = download_player_history(CHRISTIE, _client(tmp_path), today=TODAY, export=False)
    after = _dump(tmp_path / "d" / "h.sqlite")
    assert summary.game_details == 58 and after["match_stats"] and not before["match_stats"]
    assert {t: after[t] for t in ("players", "tournaments", "results", "match_players", "games")} == {
        t: before[t] for t in ("players", "tournaments", "results", "match_players", "games")
    }  # the history part is untouched


# ---------------------------------------------------------------- matches without full details

def test_games_only_matches_are_stored_as_untracked(tmp_path: Path) -> None:
    summary = download_player_history(89438, _client(tmp_path), export=False, **AADHYA_TELANGANA)  # Aadhya SHINE
    assert (summary.matches, summary.game_details, summary.game_details_tracked, summary.game_details_untracked) == (2, 2, 0, 2)
    assert summary.rallies == 0 and summary.all_details_agree is True
    assert summary.notes == ["2 match(es) have only game scores on the site (no rally-by-rally data or statistics); "
                             "their statistics are stored as NULL, not 0."]
    db = tmp_path / "d" / "h.sqlite"
    assert _query(db, "SELECT DISTINCT tracked FROM match_stats") == [(0,)]
    assert _query(db, "SELECT COUNT(*) FROM match_stats WHERE side1_rallies_won IS NOT NULL") == [(0,)]
    assert _query(db, "SELECT COUNT(*) FROM game_stats WHERE tracked = 0") == [(4,)]
    assert "2 with game scores only" in format_history(summary)


def test_byes_and_walkovers_are_not_requested(tmp_path: Path) -> None:
    client = _client(tmp_path)
    summary = download_player_history(81458, client, export=False, **DEJAN_BYE_AND_WALKOVER)  # Dejan FERDINANSYAH
    assert summary.matches_by_status == {"bye": 1, "walkover": 1}
    assert (summary.game_details, summary.game_details_skipped) == (0, 2)
    assert client.calls_to("h2h/match") == [] and summary.all_details_agree is None
    assert "2 not requested (byes, walkovers)" in format_history(summary)


def test_a_doubles_run_with_details(tmp_path: Path) -> None:
    summary = download_player_history(81458, _client(tmp_path), export=False, **DEJAN_TITLE)
    assert (summary.matches, summary.game_details, summary.game_details_tracked) == (5, 5, 5)
    assert summary.all_details_agree is True and summary.all_totals_agree is True


class _NoPageFor(FakeApiClient):
    """The site has no details page for the semi-final."""

    def get_json(self, endpoint: str, params: dict[str, Any] | None = None, *, ttl: int | None = None) -> Any:
        if endpoint == "h2h/match" and params and params.get("match_code") == "426":
            self.calls.append((endpoint, dict(params)))
            raise BwfNotFoundError("HTTP 404")
        return super().get_json(endpoint, params, ttl=ttl)


def test_a_match_without_a_details_page_is_noted_and_the_rest_carries_on(tmp_path: Path) -> None:
    summary = download_player_history(81458, _client(tmp_path, _NoPageFor), export=False, **DEJAN_TITLE)
    assert (summary.matches, summary.game_details, summary.game_details_not_found) == (5, 4, 1)
    assert summary.all_details_agree is True
    assert any("SF: the site has no details page for this match (HTTP 404); nothing was stored for it." in n for n in summary.notes)
    assert _query(tmp_path / "d" / "h.sqlite", "SELECT COUNT(*) FROM match_stats") == [(4,)]
    assert _query(tmp_path / "d" / "h.sqlite", "SELECT COUNT(*) FROM matches") == [(5,)]  # the match itself is kept
    assert "1 without a details page" in format_history(summary)


# ---------------------------------------------------------------- a response that does not add up

class _CorruptsOne(FakeApiClient):
    """One game's statistic is wrong in what the site sends."""

    def get_json(self, endpoint: str, params: dict[str, Any] | None = None, *, ttl: int | None = None) -> Any:
        payload = super().get_json(endpoint, params, ttl=ttl)
        if endpoint == "h2h/match" and params and (params["tmt_id"], params["match_code"]) == (5515, "13"):
            payload = json.loads(json.dumps(payload))
            payload["games"][0]["match_set_stats_model"]["team1_consecutive_points"] = 9
        return payload


def test_a_disagreement_is_reported_and_stored_but_does_not_stop_the_download(tmp_path: Path) -> None:
    summary = download_player_history(CHRISTIE, _client(tmp_path, _CorruptsOne), since=date(2026, 3, 3), until=date(2026, 3, 8), export=False)
    assert summary.all_details_agree is False and summary.game_details == summary.matches == 2  # All England: R32 and R16
    assert summary.game_details_disagreeing == ["All England Open Badminton Championships 2026 (MS), R16"]
    assert any("Game 1: side 1 most consecutive points: the site says 9, the rallies give 7" in n for n in summary.notes)
    rows = _query(tmp_path / "d" / "h.sqlite", "SELECT checks_ok, differences FROM match_stats WHERE checks_ok = 0")
    assert len(rows) == 1 and "the site says 9" in rows[0][1]
    text = format_history(summary)
    assert "Checked:      rallies, statistics and scores agree with each other and with the player's page: NO - see notes" in text


# ---------------------------------------------------------------- failures

class _BlocksOnDetail(FakeApiClient):
    """Cloudflare blocks the 11th details request."""

    def get_json(self, endpoint: str, params: dict[str, Any] | None = None, *, ttl: int | None = None) -> Any:
        if endpoint == "h2h/match" and len(self.calls_to(endpoint)) == 10:
            self.calls.append((endpoint, dict(params or {})))
            raise BlockedByCloudflareError("blocked")
        return super().get_json(endpoint, params, ttl=ttl)


def test_a_block_while_downloading_details_keeps_what_was_saved_and_a_rerun_completes_it(tmp_path: Path) -> None:
    with pytest.raises(BlockedByCloudflareError):
        download_player_history(CHRISTIE, _client(tmp_path, _BlocksOnDetail), today=TODAY, export=False)
    db = tmp_path / "d" / "h.sqlite"
    partial = _dump(db)
    assert len(partial["match_stats"]) == 10 and 10 < len(partial["matches"]) < 58 and len(partial["tournaments"]) == 19

    complete = download_player_history(CHRISTIE, _client(tmp_path), today=TODAY, export=False)
    reference = download_player_history(CHRISTIE, _client(tmp_path), today=TODAY, export=False, db_path=tmp_path / "ref.sqlite")
    assert complete.game_details == 58 and reference.all_details_agree is True
    assert _dump(db) == _dump(tmp_path / "ref.sqlite")  # identical to a run that was never interrupted


class _BadDetailShape(FakeApiClient):
    def get_json(self, endpoint: str, params: dict[str, Any] | None = None, *, ttl: int | None = None) -> Any:
        if endpoint == "h2h/match":
            self.calls.append((endpoint, dict(params or {})))
            return {"unexpected": True}
        return super().get_json(endpoint, params, ttl=ttl)


def test_a_malformed_details_response_stops_the_download_with_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(BwfClientError, match="unexpected response shape"):
        download_player_history(CHRISTIE, _client(tmp_path, _BadDetailShape), today=TODAY, export=False)
    db = tmp_path / "d" / "h.sqlite"
    assert _query(db, "SELECT COUNT(*) FROM match_stats") == [(0,)] and _query(db, "SELECT COUNT(*) FROM tournaments") == [(19,)]


# ---------------------------------------------------------------- the text report

def test_the_report_header_lines(christie: Any) -> None:
    summary, _, _ = christie
    lines = format_history(summary).splitlines()
    assert f"Game details: 58 match(es), 58 with rally data, 0 with game scores only, {summary.rallies} rallies" in lines
    assert "Checked:      rallies, statistics and scores agree with each other and with the player's page: yes" in lines
    assert lines.index("Checked:      the matches reproduce the site's own totals: yes (19 event(s))") < lines.index(
        f"Game details: 58 match(es), 58 with rally data, 0 with game scores only, {summary.rallies} rallies")


def test_the_report_can_show_every_game(christie: Any) -> None:
    text = format_history(christie[0], games=True)
    # All England 2026, R16: Christie (side 2) lost 19-21, 12-21 to LIN Chun-Yi
    assert "        game 1  19-21  40 rallies  longest run 5-7  game points 0-6" in text
    assert "        game 2  12-21  33 rallies  longest run 4-5  game points 0-1" in text
    # China Masters 2026, R32: Christie (side 1) won 21-17, 21-19
    assert "        game 1  21-17  38 rallies  longest run 3-3  game points 3-0" in text
    assert "        game 2  21-19  40 rallies  longest run 7-4  game points 1-0" in text
    assert text.count("        game ") == 138


def test_the_report_shows_no_game_lines_by_default(christie: Any) -> None:
    assert "        game " not in format_history(christie[0])


def test_the_report_marks_games_without_statistics(tmp_path: Path) -> None:
    summary = download_player_history(89438, _client(tmp_path), export=False, **AADHYA_TELANGANA)
    text = format_history(summary, games=True)
    assert "        game 1  19-21  (game score only)" in text and "        game 2  21-23  (game score only)" in text


# ---------------------------------------------------------------- the command line

@pytest.fixture(scope="module")
def script() -> Any:
    path = Path(__file__).resolve().parents[1] / "scripts" / "download_history.py"
    spec = importlib.util.spec_from_file_location("download_history_details", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_command_line_downloads_details_by_default(script: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    client = _client(tmp_path)
    assert script.main([str(CHRISTIE), "--since", "2026-09-01", "--until", "2026-09-06"], client) == 0
    out, err = capsys.readouterr()
    assert "Game details: 2 match(es), 2 with rally data" in out and len(client.calls_to("h2h/match")) == 2
    assert "match 1/2: R32 (code 16), game details" in err
    assert (tmp_path / "d" / "csv" / "rallies.csv").is_file()


def test_the_command_line_can_skip_the_details(script: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    client = _client(tmp_path)
    assert script.main([str(CHRISTIE), "--since", "2026-09-01", "--until", "2026-09-06", "--no-game-details"], client) == 0
    assert "Game details" not in capsys.readouterr().out and client.calls_to("h2h/match") == []


def test_the_command_line_can_show_every_game(script: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert script.main([str(CHRISTIE), "--since", "2026-09-01", "--until", "2026-09-06", "--show-games"], _client(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "        game 1  21-17  38 rallies  longest run 3-3  game points 3-0" in out
    assert "        game 2  16-21  37 rallies  longest run 4-6  game points 0-2" in out
    assert out.count("        game ") == 4
