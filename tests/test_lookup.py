"""End-to-end lookup and its text rendering, offline against saved real API responses."""

from __future__ import annotations

import pytest

from bwf_player import BlockedByCloudflareError, InvalidInputError, format_result, lookup_player
from fakes import FakeApiClient

SUMMARY, EVENTS, CURRENT, HISTORY = (
    "vue-player-summary", "vue-player-ranking-events", "vue-player-ranking-current", "vue-player-ranking-history",
)

CHRISTIE_TEXT = """\
Search:         FOUND - Matched 'Jonatan CHRISTIE' (score 94).
Profile URL:    https://bwfbadminton.com/player/73442/jonatan-christie

Personal details
  Name:          Jonatan CHRISTIE
  Nationality:   Indonesia
  Height:        179.0 cm
  Playing hand:  Right

Ranking (MEN'S SINGLES)
  Current rank:  1
  At this rank:  4 week(s), since 2026-08-25 (latest ranking list 2026-09-15)"""


@pytest.fixture
def client() -> FakeApiClient:
    return FakeApiClient()


def endpoints(client: FakeApiClient) -> set[str]:
    return {endpoint for endpoint, _ in client.calls}


def test_found_player_gets_search_profile_and_ranking(client: FakeApiClient) -> None:
    result = lookup_player("jonathan cristie", client)
    assert result.search.status == "found"
    assert result.profile.nationality == "Indonesia"
    assert result.ranking.current_rank == 1 and result.ranking.weeks_at_current_rank == 4
    assert result.fetched_at.tzinfo is not None


def test_text_report_for_a_ranked_player(client: FakeApiClient) -> None:
    assert format_result(lookup_player("jonathan cristie", client)) == CHRISTIE_TEXT


def test_text_report_shows_nulls_and_notes_for_a_player_with_nothing_listed(client: FakeApiClient) -> None:
    text = format_result(lookup_player("Aadhya Shine", client))
    for line in ("Nationality:   null", "Height:        null", "Playing hand:  null"):
        assert line in text
    assert "Current rank:  423" in text
    assert "Other event:   WOMEN'S DOUBLES (Nanda GHOSH) [9-90070]" in text
    assert text.count("is not listed on the player's profile.") == 3
    assert "\nNotes\n" in text


def test_text_report_for_an_unranked_player(client: FakeApiClient) -> None:
    text = format_result(lookup_player("Chong Wei Lee", client))
    assert "Ranking (MEN'S SINGLES)" in text
    assert "Current rank:  null" in text and "At this rank:  null" in text
    assert "Not currently ranked in MEN'S SINGLES" in text


def test_ambiguous_name_makes_no_profile_or_ranking_requests(client: FakeApiClient) -> None:
    result = lookup_player("christie", client)
    assert result.search.status == "ambiguous"
    assert result.profile is None and result.ranking is None
    assert endpoints(client).isdisjoint({SUMMARY, EVENTS, CURRENT, HISTORY})
    text = format_result(result)
    assert "AMBIGUOUS" in text and "Trehan CHRISTIE (England)" in text and "Christie XU (Canada)" in text
    assert "re-run with a fuller name" in text
    assert "Personal details" not in text and "Ranking" not in text


@pytest.mark.parametrize("name", ["zzzzqqq xxyyww", "", None, "'; DROP TABLE players; --"])
def test_unknown_or_invalid_names_return_a_not_found_report(client: FakeApiClient, name: object) -> None:
    result = lookup_player(name, client)  # type: ignore[arg-type]
    assert result.search.status == "not_found"
    assert result.profile is None and result.ranking is None
    assert format_result(result).startswith("Search:         NOT_FOUND - ")
    assert endpoints(client).isdisjoint({SUMMARY, EVENTS, CURRENT, HISTORY})


def test_event_id_selects_the_ranking_event(client: FakeApiClient) -> None:
    result = lookup_player("Aadhya Shine", client, event_id="9-90070")
    assert result.ranking.event.id == "9-90070" and result.ranking.current_rank == 764
    assert "Ranking (WOMEN'S DOUBLES (Nanda GHOSH))" in format_result(result)


def test_unknown_event_id_is_rejected(client: FakeApiClient) -> None:
    with pytest.raises(InvalidInputError):
        lookup_player("jonathan cristie", client, event_id="8-0")


def test_event_id_is_ignored_when_no_single_player_is_found(client: FakeApiClient) -> None:
    assert lookup_player("christie", client, event_id="not-an-event").ranking is None


def test_result_serialises_to_json(client: FakeApiClient) -> None:
    payload = lookup_player("jonathan cristie", client).model_dump_json()
    assert '"current_rank":1' in payload and '"at_rank_since":"2026-08-25"' in payload


def test_cloudflare_block_propagates() -> None:
    class Blocked(FakeApiClient):
        def get_json(self, *args: object, **kwargs: object) -> object:
            raise BlockedByCloudflareError("blocked")

    with pytest.raises(BlockedByCloudflareError):
        lookup_player("jonathan cristie", Blocked())
