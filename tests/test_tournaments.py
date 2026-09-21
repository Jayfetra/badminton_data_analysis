"""R4: tournaments a player entered in a window, with the result per event. Offline."""

from __future__ import annotations

import copy
from datetime import date
from typing import Any

import pytest

from bwf_player.exceptions import BlockedByCloudflareError, BwfClientError, InvalidInputError
from bwf_player.tournaments import (
    get_tournaments,
    history_window,
    overlaps,
    parse_calendar,
    parse_tournaments,
)
from tests.fakes import FakeApiClient, load_fixture

TODAY = date(2026, 9, 21)
CHRISTIE = "73442"
AADHYA = "89438"


def _row(**overrides: Any) -> dict[str, Any]:
    """A minimal, valid tournament row in the site's shape."""
    row: dict[str, Any] = {
        "tournament_id": 100,
        "location": "Shenzhen, China",
        "tmt_url": "https://example.test/tournament/100/",
        "tournament_model": {
            "id": 100, "name": "Test Open", "start_date": "2026-03-03 00:00:00",
            "end_date": "2026-03-08 00:00:00", "type_id": 0, "country_model": {"name": "China"},
        },
        "draws": [{
            "name": "MS", "event_id": 555, "position": "QF", "match_win": 2, "match_lose": 1,
            "game_win": 4, "game_lose": 3, "score_player": 150, "score_opponent": 140,
        }],
    }
    row.update(overrides)
    return row


class ScriptedClient:
    """A client returning canned payloads per endpoint (callables may raise)."""

    def __init__(self, **by_endpoint: Any) -> None:
        self.by_endpoint = by_endpoint
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_json(self, endpoint: str, params: dict[str, Any] | None = None, *, ttl: int | None = None) -> Any:
        self.calls.append((endpoint, dict(params or {})))
        value = self.by_endpoint[endpoint]
        return value(params) if callable(value) else value


# ---------------------------------------------------------------- window

def test_window_is_one_year_back_from_today() -> None:
    assert history_window(TODAY) == (date(2025, 9, 21), date(2026, 9, 21))


def test_window_defaults_to_the_real_today() -> None:
    since, until = history_window()
    assert until == date.today() and since.year == until.year - 1


def test_window_on_leap_day_moves_to_28_february() -> None:
    assert history_window(date(2028, 2, 29)) == (date(2027, 2, 28), date(2028, 2, 29))
    assert history_window(date(2028, 2, 29), years=4) == (date(2024, 2, 29), date(2028, 2, 29))  # leap year again


def test_window_several_years() -> None:
    assert history_window(TODAY, years=3)[0] == date(2023, 9, 21)


@pytest.mark.parametrize("years", [0, -1, True, 1.5, "1", None])
def test_window_rejects_bad_years(years: object) -> None:
    with pytest.raises(InvalidInputError):
        history_window(TODAY, years=years)  # type: ignore[arg-type]


def test_overlap_rule_is_inclusive_at_both_edges() -> None:
    entry, _ = parse_tournaments({"results": [_row()]})
    e = entry[0]  # 2026-03-03 .. 2026-03-08
    assert overlaps(e, date(2026, 3, 8), date(2026, 3, 20))  # ends on `since`
    assert overlaps(e, date(2026, 1, 1), date(2026, 3, 3))  # starts on `until`
    assert not overlaps(e, date(2026, 3, 9), date(2026, 3, 20))
    assert not overlaps(e, date(2026, 1, 1), date(2026, 3, 2))
    assert overlaps(e, date(2026, 3, 5), date(2026, 3, 5))  # window inside the tournament


# ---------------------------------------------------------------- real data: Christie

@pytest.fixture(scope="module")
def christie() -> Any:
    client = FakeApiClient()
    history = get_tournaments(CHRISTIE, client, today=TODAY)
    return history, client


def test_christie_window_and_count(christie: Any) -> None:
    history, _ = christie
    assert (history.since, history.until) == (date(2025, 9, 21), date(2026, 9, 21))
    assert history.player_id == CHRISTIE
    assert len(history.entries) == 19  # 7 from 2025 in the window + 12 from 2026
    assert history.notes == []


def test_christie_entries_are_chronological_and_all_in_window(christie: Any) -> None:
    history, _ = christie
    starts = [e.start_date for e in history.entries]
    assert starts == sorted(starts)
    assert all(overlaps(e, history.since, history.until) for e in history.entries)
    assert history.entries[0].tournament_id == 5280 and history.entries[-1].tournament_id == 5625


def test_tournament_that_ended_on_the_first_day_is_included(christie: Any) -> None:
    """China Masters 2025 ran 16-21 Sep; the window starts on the 21st."""
    history, _ = christie
    china = next(e for e in history.entries if e.tournament_id == 5280)
    assert (china.start_date, china.end_date) == (date(2025, 9, 16), date(2025, 9, 21))


def test_tournaments_before_the_window_are_excluded(christie: Any) -> None:
    ids = {e.tournament_id for e in christie[0].entries}
    assert 5261 not in ids  # World Championships 2025, ended 31 Aug 2025
    assert 5281 not in ids and 5198 not in ids  # July 2025


def test_a_full_entry_from_real_data(christie: Any) -> None:
    entry = next(e for e in christie[0].entries if e.tournament_id == 5625)
    assert entry.model_dump() == {
        "tournament_id": 5625,
        "name": "LI-NING China Masters 2026",
        "category": "HSBC BWF World Tour Super 750",
        "start_date": date(2026, 9, 1),
        "end_date": date(2026, 9, 6),
        "location": "Shenzhen, China",
        "country": "China",
        "type_id": 0,
        "url": "https://bwfworldtour.bwfbadminton.com/tournament/5625/li-ning-china-masters-2026/",
        "event_code": "MS",
        "event_id": 28355,
        "position": "R16",
        "matches_won": 1,
        "matches_lost": 1,
        "games_won": 2,
        "games_lost": 2,
        "points_for": 74,
        "points_against": 78,
    }


def test_positions_are_the_sites_own_labels(christie: Any) -> None:
    by_id = {e.tournament_id: e.position for e in christie[0].entries}
    assert by_id[5288] == "1st"  # won Korea Open 2025
    assert by_id[5269] == "2nd" and by_id[5227] == "3rd"
    assert by_id[5622] == "QF" and by_id[5259] == "R3"  # finals group stage


def test_team_event_has_no_individual_position(christie: Any) -> None:
    thomas = next(e for e in christie[0].entries if e.tournament_id == 5600)
    assert thomas.position is None  # the site shows "N/A"
    assert (thomas.event_code, thomas.event_id, thomas.type_id) == ("Singles", 1, 1)
    assert (thomas.matches_won, thomas.matches_lost) == (1, 2)


def test_categories_come_from_the_calendar(christie: Any) -> None:
    by_id = {e.tournament_id: e.category for e in christie[0].entries}
    assert by_id[5259] == "HSBC BWF World Tour Finals"
    assert by_id[5600] == "Grade 1 – Team Tournaments"
    assert all(category for category in by_id.values())


def test_requests_are_one_per_year_plus_the_calendar(christie: Any) -> None:
    _, client = christie
    year_calls = client.calls_to("vue-player-tournaments")
    assert [c["tmtYear"] for c in year_calls] == [2025, 2026]
    assert all(
        c["playerId"] == CHRISTIE and c["activeTab"] == 3 and c["isPara"] == "false" for c in year_calls
    )
    calendar = client.calls_to("vue-tournaments-search")
    assert [c["page"] for c in calendar] == [1, 2, 3, 4]  # 5625 sits on the last page
    assert calendar[0]["startDate"] == "2025-09-21" and calendar[0]["endDate"] == "2026-09-21"
    assert {endpoint for endpoint, _ in client.calls} == {"vue-player-tournaments", "vue-tournaments-search"}


def test_categories_can_be_skipped() -> None:
    client = FakeApiClient()
    history = get_tournaments(CHRISTIE, client, today=TODAY, with_categories=False)
    assert client.calls_to("vue-tournaments-search") == []
    assert len(history.entries) == 19 and all(e.category is None for e in history.entries)


def test_calendar_paging_stops_once_every_tournament_is_known() -> None:
    client = FakeApiClient()
    history = get_tournaments(
        AADHYA, client, since=date(2025, 10, 1), until=date(2025, 11, 30)
    )
    assert {e.tournament_id for e in history.entries} == {5206, 5306}
    assert len(client.calls_to("vue-tournaments-search")) == 1  # both are on page 1
    assert {e.category for e in history.entries} == {"International Challenge"}


def test_explicit_window_ignores_today() -> None:
    history = get_tournaments(
        CHRISTIE, FakeApiClient(), since=date(2026, 1, 1), until=date(2026, 1, 31), with_categories=False
    )
    assert [e.tournament_id for e in history.entries] == [5227, 5269]
    assert [e.start_date.year for e in history.entries] == [2026, 2026]


def test_single_year_window_makes_a_single_year_request() -> None:
    client = FakeApiClient()
    get_tournaments(CHRISTIE, client, since=date(2026, 1, 1), until=date(2026, 6, 30), with_categories=False)
    assert [c["tmtYear"] for c in client.calls_to("vue-player-tournaments")] == [2026]


def test_multi_year_window_requests_each_year() -> None:
    client = FakeApiClient()
    get_tournaments(CHRISTIE, client, since=date(2024, 12, 1), until=date(2026, 1, 1), with_categories=False)
    assert [c["tmtYear"] for c in client.calls_to("vue-player-tournaments")] == [2024, 2025, 2026]


# ---------------------------------------------------------------- real data: doubles player

def test_player_with_two_events_at_one_tournament_gets_two_entries() -> None:
    history = get_tournaments(AADHYA, FakeApiClient(), today=TODAY)
    telangana = [e for e in history.entries if e.tournament_id == 5306]
    assert {(e.event_code, e.event_id, e.position) for e in telangana} == {
        ("WS", 26122, "Qual. R64"),
        ("WD", 26119, "R32"),
    }
    assert len(history.entries) == 5  # the August 2025 event is outside the window
    assert all(e.tournament_id != 5418 for e in history.entries)


# ---------------------------------------------------------------- empty / invalid

def test_player_without_tournaments_is_a_normal_result() -> None:
    client = FakeApiClient()
    history = get_tournaments("999999999", client, today=TODAY)
    assert history.entries == []
    assert len(history.notes) == 1 and "No tournaments found between 2025-09-21 and 2026-09-21" in history.notes[0]
    assert client.calls_to("vue-tournaments-search") == []  # nothing to categorise


@pytest.mark.parametrize("bad", ["abc", "0", -5, "1 2", "", None, True, 3.5, "١٢٣", "1" * 11])
def test_bad_player_id_is_rejected_before_any_request(bad: object) -> None:
    client = FakeApiClient()
    with pytest.raises(InvalidInputError):
        get_tournaments(bad, client, today=TODAY)  # type: ignore[arg-type]
    assert client.calls == []


def test_since_after_until_is_rejected() -> None:
    client = FakeApiClient()
    with pytest.raises(InvalidInputError, match="after"):
        get_tournaments(CHRISTIE, client, since=date(2026, 2, 1), until=date(2026, 1, 1))
    assert client.calls == []


def test_player_id_may_be_int_or_padded_text() -> None:
    client = FakeApiClient()
    get_tournaments(f" {CHRISTIE} ", client, today=TODAY, with_categories=False)
    assert {c["playerId"] for c in client.calls_to("vue-player-tournaments")} == {CHRISTIE}


# ---------------------------------------------------------------- categories degrade gracefully

def test_calendar_failure_keeps_the_tournaments_and_says_so() -> None:
    def boom(_: Any) -> Any:
        raise BwfClientError("calendar down")

    client = ScriptedClient(**{
        "vue-player-tournaments": {"results": [_row()]},
        "vue-tournaments-search": boom,
    })
    history = get_tournaments(CHRISTIE, client, since=date(2026, 3, 1), until=date(2026, 3, 31))
    assert len(history.entries) == 1 and history.entries[0].category is None
    assert "categories are unavailable" in history.notes[0] and "calendar down" in history.notes[0]


def test_cloudflare_block_on_the_calendar_propagates() -> None:
    def blocked(_: Any) -> Any:
        raise BlockedByCloudflareError("blocked")

    client = ScriptedClient(**{
        "vue-player-tournaments": {"results": [_row()]},
        "vue-tournaments-search": blocked,
    })
    with pytest.raises(BlockedByCloudflareError):
        get_tournaments(CHRISTIE, client, since=date(2026, 3, 1), until=date(2026, 3, 31))


def test_cloudflare_block_on_the_player_endpoint_propagates() -> None:
    def blocked(_: Any) -> Any:
        raise BlockedByCloudflareError("blocked")

    with pytest.raises(BlockedByCloudflareError):
        get_tournaments(CHRISTIE, ScriptedClient(**{"vue-player-tournaments": blocked}), today=TODAY)


def test_tournament_absent_from_the_calendar_gets_a_null_category_and_a_note() -> None:
    calendar = {"results": {"current_page": 1, "last_page": 1, "data": [{"id": 999, "category": "Other"}]}}
    client = ScriptedClient(**{"vue-player-tournaments": {"results": [_row()]}, "vue-tournaments-search": calendar})
    history = get_tournaments(CHRISTIE, client, since=date(2026, 3, 1), until=date(2026, 3, 31))
    assert history.entries[0].category is None
    assert history.notes == ["The site calendar lists no category for 1 of 1 tournament(s); category is null."]


def test_calendar_row_without_a_category_counts_as_missing() -> None:
    calendar = {"results": {"current_page": 1, "last_page": 1, "data": [{"id": 100, "name": "Test Open"}]}}
    client = ScriptedClient(**{"vue-player-tournaments": {"results": [_row()]}, "vue-tournaments-search": calendar})
    history = get_tournaments(CHRISTIE, client, since=date(2026, 3, 1), until=date(2026, 3, 31))
    assert history.entries[0].category is None and "no category" in history.notes[0]


def test_calendar_paging_is_bounded() -> None:
    """A calendar that never reports its last page must not loop forever."""
    calendar = {"results": {"current_page": 1, "last_page": 10**6, "data": [{"id": 1}]}}
    client = ScriptedClient(**{"vue-player-tournaments": {"results": [_row()]}, "vue-tournaments-search": calendar})
    get_tournaments(CHRISTIE, client, since=date(2026, 3, 1), until=date(2026, 3, 31))
    assert len([c for c in client.calls if c[0] == "vue-tournaments-search"]) == 10


# ---------------------------------------------------------------- de-duplication across years

def test_a_tournament_listed_under_two_years_is_kept_once() -> None:
    new_year = _row(tournament_model={
        "id": 100, "name": "New Year Open", "start_date": "2025-12-29 00:00:00",
        "end_date": "2026-01-03 00:00:00", "type_id": 0,
    })
    client = ScriptedClient(**{"vue-player-tournaments": {"results": [new_year]}})
    history = get_tournaments(
        CHRISTIE, client, since=date(2025, 12, 1), until=date(2026, 1, 31), with_categories=False
    )
    assert len(client.calls) == 2 and len(history.entries) == 1


# ---------------------------------------------------------------- parser robustness

def test_parse_real_year_gives_no_skipped_rows() -> None:
    entries, skipped = parse_tournaments(load_fixture("tournaments_christie_2025.json"))
    assert (len(entries), skipped) == (18, 0)
    assert all(e.matches_won is not None and e.games_lost is not None for e in entries)


@pytest.mark.parametrize("payload", [None, [], "x", 5, {}, {"results": "x"}, {"results": {"a": 1}}, {"results": 3}])
def test_unexpected_shapes_raise(payload: object) -> None:
    with pytest.raises(BwfClientError):
        parse_tournaments(payload)


@pytest.mark.parametrize("empty", [None, []])
def test_empty_results_mean_no_tournaments(empty: object) -> None:
    assert parse_tournaments({"results": empty}) == ([], 0)


def _bad_rows() -> list[Any]:
    no_model = _row()
    del no_model["tournament_model"]
    no_id = _row(tournament_id=None, tournament_model={**_row()["tournament_model"], "id": None})
    no_name = _row(tournament_model={**_row()["tournament_model"], "name": "  "})
    bad_date = _row(tournament_model={**_row()["tournament_model"], "start_date": "soon"})
    no_end = _row(tournament_model={**_row()["tournament_model"], "end_date": None})
    return ["a string", 7, None, [], no_model, no_id, no_name, bad_date, no_end]


def test_rows_without_id_name_or_dates_are_skipped_and_counted() -> None:
    entries, skipped = parse_tournaments({"results": [*_bad_rows(), _row()]})
    assert len(entries) == 1 and skipped == len(_bad_rows())


def test_skipped_rows_are_reported_in_the_history_notes() -> None:
    client = ScriptedClient(**{"vue-player-tournaments": {"results": [_bad_rows()[4], _row()]}})
    history = get_tournaments(CHRISTIE, client, since=date(2026, 3, 1), until=date(2026, 3, 31), with_categories=False)
    assert len(history.entries) == 1
    assert history.notes == ["Skipped 1 tournament row(s) the site listed without a usable id, name or dates."]


def test_tournament_id_falls_back_to_the_model_id_and_accepts_text() -> None:
    row = _row(tournament_id=None)
    assert parse_tournaments({"results": [row]})[0][0].tournament_id == 100
    assert parse_tournaments({"results": [_row(tournament_id="100")]})[0][0].tournament_id == 100


@pytest.mark.parametrize("draws", [None, [], "MS", {"name": "MS"}, [None, "x", 3]])
def test_tournament_without_usable_draws_is_kept_without_event_data(draws: object) -> None:
    entries, skipped = parse_tournaments({"results": [_row(draws=draws)]})
    assert skipped == 0 and len(entries) == 1
    e = entries[0]
    assert (e.event_code, e.event_id, e.position, e.matches_won) == (None, None, None, None)


def test_mixed_draw_list_ignores_only_the_bad_items() -> None:
    row = _row()
    row["draws"] = [None, row["draws"][0], "x"]
    entries, _ = parse_tournaments({"results": [row]})
    assert [e.event_code for e in entries] == ["MS"]


@pytest.mark.parametrize("raw", [None, "", "   ", "N/A", "n/a", " N/A ", "-"])
def test_placeholder_positions_become_none(raw: object) -> None:
    row = _row()
    row["draws"][0]["position"] = raw
    assert parse_tournaments({"results": [row]})[0][0].position is None


def test_position_text_is_kept_and_whitespace_collapsed() -> None:
    row = _row()
    row["draws"][0]["position"] = "  Qual.   R32 "
    assert parse_tournaments({"results": [row]})[0][0].position == "Qual. R32"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(3, 3), ("3", 3), (" 3 ", 3), (0, 0), (2.0, 2), (-1, None), (2.5, None), (True, None),
     (None, None), ("abc", None), ("", None), (float("nan"), None), (float("inf"), None), ([1], None), ("٣", None)],
)
def test_counts_are_coerced_defensively(raw: object, expected: int | None) -> None:
    row = _row()
    row["draws"][0].update(match_win=raw, game_lose=raw, score_player=raw)
    e = parse_tournaments({"results": [row]})[0][0]
    assert (e.matches_won, e.games_lost, e.points_for) == (expected, expected, expected)


def test_missing_country_and_location_are_null() -> None:
    row = _row(location=None)
    row["tournament_model"]["country_model"] = None
    e = parse_tournaments({"results": [row]})[0][0]
    assert e.country is None and e.location is None
    row["tournament_model"]["country_model"] = "China"
    assert parse_tournaments({"results": [row]})[0][0].country is None


def test_parser_does_not_mutate_its_input() -> None:
    payload = load_fixture("tournaments_christie_2026.json")
    before = copy.deepcopy(payload)
    parse_tournaments(payload)
    assert payload == before


def test_datetimes_and_plain_dates_both_parse() -> None:
    row = _row()
    row["tournament_model"]["start_date"] = "2026-03-03"
    row["tournament_model"]["end_date"] = " 2026-03-08T00:00:00Z"
    e = parse_tournaments({"results": [row]})[0][0]
    assert (e.start_date, e.end_date) == (date(2026, 3, 3), date(2026, 3, 8))


# ---------------------------------------------------------------- calendar parser

def test_calendar_parser_reads_real_page() -> None:
    categories, last_page = parse_calendar(load_fixture("calendar_page1.json"))
    assert last_page == 4 and len(categories) == 100
    assert categories[5280] == "HSBC BWF World Tour Super 750"
    assert None in categories.values()  # the site lists no category for some tournaments


def test_calendar_categories_are_whitespace_normalised() -> None:
    payload = {"results": {"data": [{"id": 1, "category": "BWF Para Badminton International \nLevel 2"}]}}
    assert parse_calendar(payload) == ({1: "BWF Para Badminton International Level 2"}, 1)


@pytest.mark.parametrize(
    "payload", [None, {}, {"results": None}, {"results": []}, {"results": {"data": None}}, {"results": {"data": "x"}}]
)
def test_calendar_parser_rejects_unexpected_shapes(payload: object) -> None:
    with pytest.raises(BwfClientError):
        parse_calendar(payload)


def test_calendar_parser_ignores_unusable_rows() -> None:
    payload = {"results": {"last_page": "2", "data": [None, "x", {"id": None}, {"id": "7", "category": " Super 300 "}]}}
    assert parse_calendar(payload) == ({7: "Super 300"}, 2)
