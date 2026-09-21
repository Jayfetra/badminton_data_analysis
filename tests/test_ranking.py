"""R3 ranking, offline against saved real API responses plus targeted synthetic cases."""

from __future__ import annotations

import json
from datetime import date

import pytest

from bwf_player.exceptions import BlockedByCloudflareError, BwfClientError, InvalidInputError
from bwf_player.ranking import (
    get_ranking,
    parse_current_rank,
    parse_events,
    parse_history,
    trailing_run,
)
from fakes import FakeApiClient, load_fixture

EVENTS, CURRENT, HISTORY = "vue-player-ranking-events", "vue-player-ranking-current", "vue-player-ranking-history"


@pytest.fixture
def client() -> FakeApiClient:
    return FakeApiClient()


def d(text: str) -> date:
    return date.fromisoformat(text)


# ---------------------------------------------------------------- real fixtures, end to end


def test_ranked_player_rank_and_weeks(client: FakeApiClient) -> None:
    ranking = get_ranking("73442", client)
    assert ranking.is_ranked is True
    assert ranking.event.id == "6-0" and ranking.event.name == "MEN'S SINGLES"
    assert ranking.other_events == []
    assert ranking.current_rank == 1
    assert ranking.weeks_at_current_rank == 4
    assert ranking.at_rank_since == d("2026-08-25")
    assert ranking.as_of == d("2026-09-15")
    assert ranking.weeks_source == "derived_from_history"
    assert ranking.notes == []


def test_derived_weeks_agree_with_the_site_streak_when_current_rank_is_the_best_rank() -> None:
    """Christie is at his best rank, so the site's `consecutive` block coincides with our value."""
    block = load_fixture("ranking_history_christie.json")["consecutive"]
    assert (block["rank"], block["streak"], block["start_date"]) == (1, 4, "2026-08-25")


def test_site_streak_is_not_the_weeks_at_current_rank() -> None:
    """Why `consecutive` is not used: for Aadhya it describes rank 364, not her current 423."""
    block = load_fixture("ranking_history_aadhya_ws.json")["consecutive"]
    assert block["rank"] == 364 and block["streak"] == 3
    ranking = get_ranking("89438", FakeApiClient())
    assert (ranking.current_rank, ranking.weeks_at_current_rank) == (423, 1)


def test_player_with_several_events_defaults_to_the_first(client: FakeApiClient) -> None:
    ranking = get_ranking("89438", client)
    assert ranking.event.id == "7-0" and ranking.current_rank == 423
    assert [(e.id, e.name) for e in ranking.other_events] == [("9-90070", "WOMEN'S DOUBLES (Nanda GHOSH)")]


def test_another_event_can_be_selected(client: FakeApiClient) -> None:
    ranking = get_ranking("89438", client, event_id="9-90070")
    assert ranking.event.name == "WOMEN'S DOUBLES (Nanda GHOSH)"
    assert ranking.current_rank == 764
    assert ranking.weeks_at_current_rank == 1
    assert [e.id for e in ranking.other_events] == ["7-0"]


def test_unknown_event_is_rejected_and_lists_the_valid_ones(client: FakeApiClient) -> None:
    with pytest.raises(InvalidInputError, match=r"6-0 \(MEN'S SINGLES\)"):
        get_ranking("73442", client, event_id="8-0")
    assert [e for e, _ in client.calls] == [EVENTS]


@pytest.mark.parametrize("event_id", ["", "../x", "6-0&isPara=true", "abc"])
def test_malformed_event_id_never_reaches_the_api(client: FakeApiClient, event_id: str) -> None:
    with pytest.raises(InvalidInputError):
        get_ranking("73442", client, event_id=event_id)
    assert [e for e, _ in client.calls] == [EVENTS]


def test_unranked_player_returns_null_rank_and_a_note(client: FakeApiClient) -> None:
    ranking = get_ranking("50152", client)  # retired: current rank is "-"
    assert ranking.is_ranked is False
    assert ranking.current_rank is None
    assert ranking.weeks_at_current_rank is None and ranking.at_rank_since is None
    assert ranking.event.name == "MEN'S SINGLES"
    assert ranking.notes == ["Not currently ranked in MEN'S SINGLES: the site lists no current rank."]
    assert [e for e, _ in client.calls] == [EVENTS, CURRENT]


def test_player_with_no_ranking_events(client: FakeApiClient) -> None:
    ranking = get_ranking("999999999", client)
    assert ranking.is_ranked is False and ranking.event is None
    assert "no ranking events" in ranking.notes[0]
    assert [e for e, _ in client.calls] == [EVENTS]


def test_single_history_row(client: FakeApiClient) -> None:
    ranking = get_ranking("39881", client)
    assert (ranking.current_rank, ranking.weeks_at_current_rank) == (1996, 1)
    assert ranking.at_rank_since == ranking.as_of == d("2026-09-15")


def test_three_requests_with_validated_params(client: FakeApiClient) -> None:
    get_ranking(73442, client)
    base = {"playerId": "73442", "isPara": "false"}
    assert client.calls == [
        (EVENTS, {"activeTab": 4, **base}),
        (CURRENT, {"rankingEvent": "6-0", **base}),
        (HISTORY, {"activeTab": 4, "rankingEvent": "6-0", **base}),
    ]


@pytest.mark.parametrize("bad_id", ["abc", "", "12a", "-1", "0", None, True, 1.5, "73442&isPara=true", "../1"])
def test_malformed_player_ids_are_rejected_before_any_request(client: FakeApiClient, bad_id: object) -> None:
    with pytest.raises(InvalidInputError):
        get_ranking(bad_id, client)  # type: ignore[arg-type]
    assert client.calls == []


def test_unreadable_history_keeps_the_rank_and_says_weeks_are_unknown() -> None:
    class BrokenHistory(FakeApiClient):
        def get_json(self, endpoint: str, params: dict | None = None, *, ttl: int | None = None) -> object:
            if endpoint == HISTORY:
                return {"results": "not json"}
            return super().get_json(endpoint, params, ttl=ttl)

    ranking = get_ranking("73442", BrokenHistory())
    assert ranking.is_ranked and ranking.current_rank == 1
    assert ranking.weeks_at_current_rank is None and ranking.weeks_source is None
    assert "could not be read" in ranking.notes[0]


def test_cloudflare_block_propagates() -> None:
    class Blocked(FakeApiClient):
        def get_json(self, *args: object, **kwargs: object) -> object:
            raise BlockedByCloudflareError("blocked")

    with pytest.raises(BlockedByCloudflareError):
        get_ranking("73442", Blocked())


# ---------------------------------------------------------------- trailing_run


def rows(*pairs: tuple[str, int | None]) -> list[tuple[date, int | None]]:
    return [(d(day), rank) for day, rank in pairs]


def test_run_stops_at_the_last_different_rank() -> None:
    history = rows(("2026-08-04", 3), ("2026-08-11", 3), ("2026-08-18", 1), ("2026-08-25", 1), ("2026-09-01", 1))
    assert trailing_run(history, 1) == (3, d("2026-08-18"), d("2026-09-01"), None)


def test_whole_history_at_one_rank() -> None:
    history = rows(("2026-08-25", 7), ("2026-09-01", 7))
    assert trailing_run(history, 7) == (2, d("2026-08-25"), d("2026-09-01"), None)


def test_earlier_run_of_the_same_rank_is_not_counted() -> None:
    history = rows(("2026-08-04", 5), ("2026-08-11", 5), ("2026-08-18", 9), ("2026-08-25", 5))
    assert trailing_run(history, 5)[0] == 1


def test_latest_rank_differing_from_current_gives_no_weeks() -> None:
    weeks, since, as_of, note = trailing_run(rows(("2026-09-08", 3), ("2026-09-15", 3)), 2)
    assert weeks is None and since is None and as_of == d("2026-09-15")
    assert "shows rank 3, not the current rank 2" in note


def test_week_without_a_rank_ends_the_run() -> None:
    history = rows(("2026-09-01", 4), ("2026-09-08", None), ("2026-09-15", 4))
    assert trailing_run(history, 4)[0] == 1


@pytest.mark.parametrize("history", [None, []])
def test_no_usable_history(history: object) -> None:
    weeks, since, as_of, note = trailing_run(history, 1)  # type: ignore[arg-type]
    assert (weeks, since, as_of) == (None, None, None) and "unknown" in note


# ---------------------------------------------------------------- parse_history


def history_payload(rows_: object, encode: bool = True) -> dict:
    return {"results": json.dumps(rows_) if encode else rows_}


def test_history_is_decoded_from_a_json_string_and_sorted() -> None:
    payload = history_payload([{"date": "2026-09-15", "value_1": 2}, {"date": "2026-09-08", "value_1": 3}])
    assert parse_history(payload) == [(d("2026-09-08"), 3), (d("2026-09-15"), 2)]


def test_history_accepts_an_already_decoded_list() -> None:
    assert parse_history(history_payload([{"date": "2026-09-15", "value_1": "12"}], encode=False)) == [
        (d("2026-09-15"), 12)]


def test_history_tolerates_datetimes_duplicates_and_bad_rows() -> None:
    payload = history_payload([
        {"date": "2026-09-15T00:00:00", "value_1": 2},
        {"date": "2026-09-15", "value_1": 4},
        {"date": "not a date", "value_1": 1},
        {"value_1": 1},
        "junk",
        {"date": "2026-09-08", "value_2": 10},
        {"date": "2026-09-01", "value_1": 0},
        {"date": "2026-08-25", "value_1": "abc"},
    ])
    assert parse_history(payload) == [
        (d("2026-08-25"), None), (d("2026-09-01"), None), (d("2026-09-08"), None), (d("2026-09-15"), 4)]


@pytest.mark.parametrize("payload", [None, [], "x", {}, {"results": None}, {"results": "not json"},
                                     {"results": '{"a": 1}'}, {"results": 5}])
def test_unreadable_history_is_none(payload: object) -> None:
    assert parse_history(payload) is None


def test_empty_history_is_an_empty_list() -> None:
    assert parse_history({"results": "[]"}) == []


def test_real_history_fixtures_parse() -> None:
    christie = parse_history(load_fixture("ranking_history_christie.json"))
    assert len(christie) == 643 and christie[0] == (d("2013-06-13"), 501) and christie[-1] == (d("2026-09-15"), 1)
    lee = parse_history(load_fixture("ranking_history_lee_chong_wei.json"))
    assert lee[-1] == (d("2019-06-11"), 191)


# ---------------------------------------------------------------- parse_current_rank


@pytest.mark.parametrize(("raw", "rank"), [(1, 1), ("12", 12), (" 7 ", 7), (1996, 1996)])
def test_current_rank_values(raw: object, rank: int) -> None:
    assert parse_current_rank({"results": raw}) == (rank, None)


@pytest.mark.parametrize("raw", [None, "-", "", "  ", 0, "0", False])
def test_no_current_rank_placeholders(raw: object) -> None:
    rank, note = parse_current_rank({"results": raw})
    assert rank is None and note == "the site lists no current rank."


@pytest.mark.parametrize("raw", ["N/A", 3.5, -2, "-3", [], {}, "1e3", "٣", True])
def test_unrecognised_current_rank_is_null_with_a_note(raw: object) -> None:
    rank, note = parse_current_rank({"results": raw})
    assert rank is None and "unrecognised" in note


@pytest.mark.parametrize("payload", [None, [], "x", {}, {"result": 1}])
def test_malformed_current_payload_raises(payload: object) -> None:
    with pytest.raises(BwfClientError):
        parse_current_rank(payload)


# ---------------------------------------------------------------- parse_events


def test_events_from_keyed_dict_and_from_list() -> None:
    keyed = {"results": {"6-0": {"id": "6-0", "name": "MEN'S SINGLES", "partner_id": 0}}}
    listed = {"results": [{"id": "6-0", "name": " MEN'S SINGLES "}]}
    assert parse_events(keyed) == parse_events(listed)
    assert parse_events(keyed)[0].name == "MEN'S SINGLES"


@pytest.mark.parametrize("payload", [{"results": []}, {"results": {}}])
def test_no_events(payload: dict) -> None:
    assert parse_events(payload) == []


def test_events_with_unsafe_ids_are_dropped() -> None:
    payload = {"results": {"a": {"id": "6-0&x=1", "name": "BAD"}, "b": {"id": "7-0", "name": "WOMEN'S SINGLES"}}}
    assert [e.id for e in parse_events(payload)] == ["7-0"]


@pytest.mark.parametrize("payload", [None, [], "x", {}, {"results": None}, {"results": "x"},
                                     {"results": {"a": {"id": "../x", "name": "BAD"}}},
                                     {"results": [{"id": "6-0"}]}])
def test_malformed_events_payload_raises(payload: object) -> None:
    with pytest.raises(BwfClientError):
        parse_events(payload)
