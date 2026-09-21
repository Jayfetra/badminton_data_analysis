"""R1 search behaviour, offline against saved real API responses."""

from __future__ import annotations

import pytest

from bwf_player.config import BwfConfig
from bwf_player.exceptions import BlockedByCloudflareError
from bwf_player.search import search_player
from fakes import FakeApiClient

CHRISTIE_URL = "https://bwfbadminton.com/player/73442/jonatan-christie"


@pytest.fixture
def client() -> FakeApiClient:
    return FakeApiClient()


def test_exact_match_uses_only_the_index(client: FakeApiClient) -> None:
    result = search_player("Jonatan CHRISTIE", client)
    assert result.status == "found"
    assert result.best_match.profile_url == CHRISTIE_URL
    assert result.best_match.score == 100
    assert client.calls_to("vue-popular-players") == []


@pytest.mark.parametrize(
    "query",
    [
        "jonatan christie",
        "  Jonatan    Christie  ",
        "JONATAN CHRISTIE",
        "Christie Jonatan",
        "jonathan cristie",
        "Jónatan Christié",
        "jonatan-christie",
    ],
)
def test_variants_resolve_to_same_player(client: FakeApiClient, query: str) -> None:
    result = search_player(query, client)
    assert result.status == "found", result.message
    assert result.best_match.player_id == "73442"
    assert result.best_match.profile_url == CHRISTIE_URL


def test_reversed_order_needs_no_server_request(client: FakeApiClient) -> None:
    assert search_player("Christie Jonatan", client).best_match.score == 100
    assert client.calls_to("vue-popular-players") == []


def test_typo_inside_a_single_word_partial_name_is_not_matched(client: FakeApiClient) -> None:
    """Known limitation (see PRD): typo tolerance applies to full names, not one-word queries."""
    assert search_player("cristie", client).status == "not_found"


def test_accented_name_in_index(client: FakeApiClient) -> None:
    result = search_player("adrian capellan", client)
    assert result.status == "found"
    assert result.best_match.name == "Adrian CAPELLÁN"


def test_partial_name_is_ambiguous_and_ranked(client: FakeApiClient) -> None:
    result = search_player("christie", client)
    assert result.status == "ambiguous"
    assert result.best_match is None
    names = [c.name for c in result.candidates]
    assert {"Jonatan CHRISTIE", "Trehan CHRISTIE", "Christie XU"} <= set(names)
    scores = [c.score for c in result.candidates]
    assert scores == sorted(scores, reverse=True)


def test_player_missing_from_index_is_found_via_server_search(client: FakeApiClient) -> None:
    result = search_player("kento momota", client)
    assert result.status == "found"
    assert result.best_match.player_id == "89785"
    assert result.best_match.country == "Japan"
    assert result.best_match.profile_url.startswith("https://bwfbadminton.com/player/89785/")


def test_reversed_name_uses_real_slug_from_server(client: FakeApiClient) -> None:
    result = search_player("Tai Tzu Ying", client)
    assert result.status == "found"
    assert result.best_match.player_id == "61427"
    assert result.best_match.profile_url == "https://bwfbadminton.com/player/61427/tzu-ying-tai"


def test_not_found_returns_result_not_exception(client: FakeApiClient) -> None:
    result = search_player("zzzzqqq xxyyww", client)
    assert result.status == "not_found"
    assert result.best_match is None
    assert result.candidates == []
    assert "No player matched" in result.message


@pytest.mark.parametrize("query", ["", "   ", "\t\n", None, 123])
def test_empty_or_non_text_input(client: FakeApiClient, query: object) -> None:
    result = search_player(query, client)  # type: ignore[arg-type]
    assert result.status == "not_found"
    assert client.calls == []


@pytest.mark.parametrize(
    "query",
    [
        "'; DROP TABLE players; --",
        "<script>alert(1)</script>",
        "%00%0d%0aHeader: x",
        "../../etc/passwd",
        "Jonatan\x00 Christie\x07",
        "!!! ???",
    ],
)
def test_special_characters_never_raise_and_are_not_forwarded_raw(client: FakeApiClient, query: str) -> None:
    result = search_player(query, client)
    assert result.status in {"found", "ambiguous", "not_found"}
    for params in client.calls_to("vue-popular-players"):
        key = params["searchKey"]
        assert key.isalnum() and key == key.lower()


def test_control_characters_are_stripped(client: FakeApiClient) -> None:
    result = search_player("Jonatan\x00 Christie\x07", client)
    assert result.status == "found"
    assert result.best_match.player_id == "73442"


def test_overlong_query_is_rejected(client: FakeApiClient) -> None:
    result = search_player("a" * 101, client)
    assert result.status == "not_found"
    assert "longer than" in result.message
    assert client.calls == []


def test_threshold_is_configurable() -> None:
    strict = FakeApiClient(BwfConfig(match_threshold=99))
    assert search_player("jonathan cristie", strict).status == "not_found"
    lenient = FakeApiClient(BwfConfig(match_threshold=50))
    assert search_player("jonathan cristie", lenient).status in {"found", "ambiguous"}


def test_cloudflare_block_propagates() -> None:
    class Blocked(FakeApiClient):
        def get_json(self, *args: object, **kwargs: object) -> object:
            raise BlockedByCloudflareError("blocked")

    with pytest.raises(BlockedByCloudflareError):
        search_player("jonatan christie", Blocked())
