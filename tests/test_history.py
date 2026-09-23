"""End-to-end history download: name/id -> tournaments -> matches -> SQLite and CSV. Offline."""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from bwf_player import BwfConfig, download_player_history, format_history
from bwf_player.exceptions import BlockedByCloudflareError, InvalidInputError
from tests.fakes import FakeApiClient

TODAY = date(2026, 9, 21)


def _client(tmp_path: Path, cls: type[FakeApiClient] = FakeApiClient) -> FakeApiClient:
    return cls(BwfConfig(history_db_path=tmp_path / "data" / "h.sqlite", history_export_dir=tmp_path / "data" / "csv"))


def _dump(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    conn = sqlite3.connect(db)
    try:
        return {
            t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2, 3").fetchall()
            for t in ("players", "tournaments", "results", "matches", "match_players", "games")
        }
    finally:
        conn.close()


# ---------------------------------------------------------------- the whole download

@pytest.fixture()
def christie(tmp_path: Path) -> Any:
    client = _client(tmp_path)
    summary = download_player_history("Jonatan Christie", client, today=TODAY)
    return summary, client, tmp_path


def test_summary_of_christies_year(christie: Any) -> None:
    summary, _, _ = christie
    assert summary.search.status == "found" and summary.player_id == "73442"
    assert summary.player_name == "Jonatan CHRISTIE"
    assert (summary.since, summary.until) == (date(2025, 9, 21), date(2026, 9, 21))
    assert (summary.tournaments, summary.events, summary.matches, summary.games) == (19, 19, 58, 138)
    assert summary.matches_by_status == {"played": 58}
    assert summary.events_checked == 19 and summary.events_disagreeing == []
    assert summary.all_totals_agree is True
    assert summary.notes == []


def test_the_database_and_csv_files_are_written_where_configured(christie: Any) -> None:
    summary, _, tmp_path = christie
    assert summary.database == str(tmp_path / "data" / "h.sqlite")
    assert set(summary.csv_files) == {"results.csv", "matches.csv", "games.csv", "match_stats.csv", "game_stats.csv", "rallies.csv"}
    assert all(Path(p).is_file() and Path(p).parent == tmp_path / "data" / "csv" for p in summary.csv_files.values())
    counts = {t: len(rows) for t, rows in _dump(tmp_path / "data" / "h.sqlite").items()}
    assert counts["tournaments"] == 19 and counts["results"] == 19 and counts["matches"] == 58 and counts["games"] == 138
    with Path(summary.csv_files["matches.csv"]).open(encoding="utf-8-sig", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 58


def test_requests_made(christie: Any) -> None:
    _, client, _ = christie
    assert [c["tmtYear"] for c in client.calls_to("vue-player-tournaments")] == [2025, 2026]
    assert len(client.calls_to("vue-player-tmt-matches")) == 19  # one per event entered
    assert len(client.calls_to("vue-tournaments-search")) == 4  # categories
    assert client.calls_to("vue-player-summary") == [] and client.calls_to("vue-player-ranking-events") == []


def test_the_summary_carries_the_data_and_serialises_to_json(christie: Any) -> None:
    summary, _, _ = christie
    assert len(summary.history.entries) == 19 and sum(len(e.matches) for e in summary.event_matches) == 58
    decoded = json.loads(summary.model_dump_json())
    assert decoded["matches"] == 58 and decoded["all_totals_agree"] is True


def test_running_again_changes_nothing(christie: Any) -> None:
    summary, _, tmp_path = christie
    before = _dump(tmp_path / "data" / "h.sqlite")
    again = download_player_history("Jonatan Christie", _client(tmp_path), today=TODAY)
    assert again.matches == summary.matches and _dump(tmp_path / "data" / "h.sqlite") == before


# ---------------------------------------------------------------- input forms

@pytest.mark.parametrize("player", [73442, "73442", " 73442 "])
def test_a_player_id_skips_the_search(player: object, tmp_path: Path) -> None:
    client = _client(tmp_path)
    summary = download_player_history(player, client, today=TODAY, export=False)  # type: ignore[arg-type]
    assert summary.search is None and summary.player_id == "73442" and summary.matches == 58
    assert client.calls_to("vue-h2h-players") == [] and client.calls_to("vue-popular-players") == []
    assert summary.player_name == "Jonatan CHRISTIE"  # learned from the matches


def test_the_players_name_is_stored_even_when_only_an_id_was_given(tmp_path: Path) -> None:
    download_player_history(73442, _client(tmp_path), today=TODAY, export=False)
    conn = sqlite3.connect(tmp_path / "data" / "h.sqlite")
    assert conn.execute("SELECT name, country FROM players WHERE player_id = 73442").fetchone() == ("Jonatan CHRISTIE", "INA")
    conn.close()


@pytest.mark.parametrize("bad", [None, True, 0, -5, 1.5, [73442], "0", "1" * 11])
def test_bad_ids_are_rejected_before_any_request(bad: object, tmp_path: Path) -> None:
    client = _client(tmp_path)
    with pytest.raises(InvalidInputError):
        download_player_history(bad, client, today=TODAY)  # type: ignore[arg-type]
    assert client.calls == [] and not (tmp_path / "data").exists()


# ---------------------------------------------------------------- nothing to download

@pytest.mark.parametrize("name", ["christie", "not a real player zzz", "", "   ", "!!!"])
def test_an_ambiguous_or_unknown_name_downloads_and_creates_nothing(name: str, tmp_path: Path) -> None:
    client = _client(tmp_path)
    summary = download_player_history(name, client, today=TODAY)
    assert summary.player_id is None and summary.matches == 0 and summary.database is None
    assert summary.search.status in ("ambiguous", "not_found")
    assert summary.notes and summary.notes[0].startswith("Nothing was downloaded.")
    for endpoint in ("vue-player-tournaments", "vue-player-tmt-matches", "vue-tournaments-search"):
        assert client.calls_to(endpoint) == []
    assert not (tmp_path / "data").exists()


def test_a_player_with_no_tournaments_creates_no_database(tmp_path: Path) -> None:
    client = _client(tmp_path)
    summary = download_player_history(999999999, client, today=TODAY)
    assert summary.events == 0 and summary.database is None and summary.all_totals_agree is None
    assert any("no tournaments in the window" in n for n in summary.notes)
    assert client.calls_to("vue-player-tmt-matches") == [] and not (tmp_path / "data").exists()


def test_a_narrower_window_downloads_less(tmp_path: Path) -> None:
    client = _client(tmp_path)
    summary = download_player_history(
        73442, client, since=date(2026, 1, 1), until=date(2026, 1, 31), export=False,
    )
    assert (summary.tournaments, summary.matches) == (2, 9)  # Malaysia Open (4 matches) and India Open (5)
    assert len(client.calls_to("vue-player-tmt-matches")) == 2


# ---------------------------------------------------------------- doubles and unusual matches

# Dejan FERDINANSYAH (81458) has match fixtures for only two of his events, so these windows hold just those.
_DEJAN_TITLE = {"since": date(2025, 9, 29), "until": date(2025, 10, 6)}  # Al Ain Masters, mixed doubles, won
_DEJAN_WALKOVER = {"since": date(2025, 11, 10), "until": date(2025, 11, 17)}  # Indonesia International Challenge


def test_a_doubles_title_run(tmp_path: Path) -> None:
    summary = download_player_history(81458, _client(tmp_path), export=False, **_DEJAN_TITLE)
    assert (summary.events, summary.matches, summary.matches_by_status) == (1, 5, {"played": 5})
    assert summary.all_totals_agree is True and summary.player_name == "Dejan FERDINANSYAH"


def test_a_bye_and_a_walkover(tmp_path: Path) -> None:
    summary = download_player_history(81458, _client(tmp_path), export=False, **_DEJAN_WALKOVER)
    assert summary.matches_by_status == {"bye": 1, "walkover": 1}
    assert summary.all_totals_agree is True  # the site counts the bye as a match won, the walkover as lost


def test_export_can_be_switched_off_and_redirected(tmp_path: Path) -> None:
    client = _client(tmp_path)
    off = download_player_history(73442, client, today=TODAY, export=False)
    assert off.csv_files == {} and not (tmp_path / "data" / "csv").exists()
    elsewhere = download_player_history(73442, client, today=TODAY, db_path=tmp_path / "other.sqlite", export_dir=tmp_path / "out")
    assert (tmp_path / "other.sqlite").is_file() and (tmp_path / "out" / "matches.csv").is_file()
    assert elsewhere.database == str(tmp_path / "other.sqlite")


def test_progress_messages_name_each_event(tmp_path: Path) -> None:
    messages: list[str] = []
    download_player_history(73442, _client(tmp_path), today=TODAY, export=False, progress=messages.append)
    assert len(messages) == 20  # the tournament lookup plus one per event
    assert messages[1].startswith("[1/19] 2025-09-16 LI-NING China Masters 2025 (MS)")
    assert messages[-1].startswith("[19/19] 2026-09-01 LI-NING China Masters 2026 (MS)")


# ---------------------------------------------------------------- checking against the site's totals

class _DropsAMatch(FakeApiClient):
    """Serves one event with its last match missing, as if a parse had lost it."""

    def get_json(self, endpoint: str, params: dict[str, Any] | None = None, *, ttl: int | None = None) -> Any:
        payload = super().get_json(endpoint, params, ttl=ttl)
        if endpoint == "vue-player-tmt-matches" and params and params.get("tmtId") == 5288:
            payload = json.loads(json.dumps(payload))
            draw = next(iter(payload["results"]))
            payload["results"][draw] = payload["results"][draw][:-1]
        return payload


def test_an_event_that_does_not_add_up_is_reported(tmp_path: Path) -> None:
    summary = download_player_history(73442, _client(tmp_path, _DropsAMatch), today=TODAY, export=False)
    assert summary.all_totals_agree is False and summary.events_checked == 19
    assert summary.events_disagreeing == ["SUWON VICTOR Korea Open 2025 (MS)"]
    assert any("Korea Open" in n and "the site's totals say" in n for n in summary.notes)
    assert summary.matches == 57  # what was found is still saved


def test_the_text_report_flags_a_mismatch(tmp_path: Path) -> None:
    text = format_history(download_player_history(73442, _client(tmp_path, _DropsAMatch), today=TODAY, export=False))
    assert "NO - see notes" in text and "SUWON VICTOR Korea Open 2025 (MS): matches won" in text


# ---------------------------------------------------------------- failing half way, then resuming

class _BlocksAfter(FakeApiClient):
    """Cloudflare blocks the fifth match request."""

    def get_json(self, endpoint: str, params: dict[str, Any] | None = None, *, ttl: int | None = None) -> Any:
        if endpoint == "vue-player-tmt-matches" and len(self.calls_to(endpoint)) == 4:
            self.calls.append((endpoint, dict(params or {})))
            raise BlockedByCloudflareError("blocked")
        return super().get_json(endpoint, params, ttl=ttl)


def test_a_block_part_way_keeps_what_was_saved_and_a_rerun_completes_it(tmp_path: Path) -> None:
    with pytest.raises(BlockedByCloudflareError):
        download_player_history(73442, _client(tmp_path, _BlocksAfter), today=TODAY, export=False)
    partial = _dump(tmp_path / "data" / "h.sqlite")
    assert len(partial["tournaments"]) == 19 and len(partial["results"]) == 19  # saved before the matches
    events_saved = {m[2] for m in partial["matches"]}  # column 3 is the tournament id
    assert 0 < len(partial["matches"]) < 58 and len(events_saved) == 4

    complete = download_player_history(73442, _client(tmp_path), today=TODAY, export=False)
    reference = download_player_history(73442, _client(tmp_path), today=TODAY, export=False, db_path=tmp_path / "ref.sqlite")
    assert complete.matches == 58 and _dump(tmp_path / "data" / "h.sqlite") == _dump(tmp_path / "ref.sqlite")
    assert reference.all_totals_agree is True


# ---------------------------------------------------------------- text report

def test_the_text_report(christie: Any) -> None:
    summary, _, tmp_path = christie
    lines = format_history(summary).splitlines()
    assert lines[0] == "Search:       FOUND - Matched 'Jonatan CHRISTIE' (score 100)."
    assert lines[1:5] == [
        "Player:       Jonatan CHRISTIE (id 73442)",
        "Window:       2025-09-21 to 2026-09-21",
        "Downloaded:   19 tournament(s), 19 event(s), 58 match(es) (58 played), 138 game(s)",
        "Checked:      the matches reproduce the site's own totals: yes (19 event(s))",
    ]
    text = "\n".join(lines)
    assert "2026-09-01  LI-NING China Masters 2026  [MS]  result: R16  1-1 in matches  (HSBC BWF World Tour Super 750)" in text
    assert "R32       won              vs LEONG Jun Hao  21-17, 21-19" in text
    assert "R16       lost             vs Jason GUNAWAN  16-21, 16-21" in text
    assert "Notes" not in text


def test_the_text_report_without_matches_lists_only_events(christie: Any) -> None:
    summary, _, _ = christie
    text = format_history(summary, matches=False)
    assert "LI-NING China Masters 2026" in text and "LEONG Jun Hao" not in text


def test_the_text_report_for_doubles_shows_partner_opponents_and_special_matches(tmp_path: Path) -> None:
    title = format_history(download_player_history(81458, _client(tmp_path), export=False, **_DEJAN_TITLE))
    assert "with Bernadine Anindiya WARDANA vs Marwan FAZA / Aisyah Salsabila Putri PRANATA  21-12, 21-16" in title
    special = format_history(download_player_history(81458, _client(tmp_path), export=False, **_DEJAN_WALKOVER))
    assert " bye " in special and "lost (walkover)" in special


def test_the_text_report_for_a_name_that_matched_nobody_or_several(tmp_path: Path) -> None:
    several = format_history(download_player_history("christie", _client(tmp_path), today=TODAY))
    assert several.startswith("Search:       AMBIGUOUS") and "Jonatan CHRISTIE" in several and "Nothing was downloaded." in several
    nobody = format_history(download_player_history("zzz qqq nobody", _client(tmp_path), today=TODAY))
    assert nobody.startswith("Search:       NOT_FOUND") and "Nothing was downloaded." in nobody


def test_the_text_report_for_an_empty_window(tmp_path: Path) -> None:
    text = format_history(download_player_history(999999999, _client(tmp_path), today=TODAY))
    assert "Downloaded:   0 tournament(s)" in text and "no tournaments in the window" in text
