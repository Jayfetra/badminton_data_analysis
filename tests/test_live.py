"""Live smoke tests against bwfbadminton.com. Excluded by default: run with `pytest -m live`.

These make a handful of real requests (cached in a temp dir). If Cloudflare blocks you, the
tests fail with BlockedByCloudflareError; wait before retrying.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bwf_player.config import BwfConfig
from bwf_player.http_client import BwfHttpClient
from bwf_player.search import search_player

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> BwfHttpClient:
    cache: Path = tmp_path_factory.mktemp("bwf_cache")
    return BwfHttpClient(BwfConfig(cache_dir=cache))


def test_live_exact_name(client: BwfHttpClient) -> None:
    result = search_player("Jonatan Christie", client)
    assert result.status == "found"
    assert result.best_match.profile_url == "https://bwfbadminton.com/player/73442/jonatan-christie"


def test_live_typo_and_reversed_order(client: BwfHttpClient) -> None:
    assert search_player("jonathan cristie", client).best_match.player_id == "73442"
    assert search_player("Christie Jonatan", client).best_match.player_id == "73442"


def test_live_player_missing_from_index(client: BwfHttpClient) -> None:
    result = search_player("Kento Momota", client)
    assert result.status == "found"
    assert result.best_match.player_id == "89785"


def test_live_reversed_name_and_common_word(client: BwfHttpClient) -> None:
    """'ying' alone returns too many players to page through; phrases must be used."""
    result = search_player("Tai Tzu Ying", client)
    assert result.status == "found"
    assert result.best_match.player_id == "61427"


def test_live_profile_right_and_left_handed(client: BwfHttpClient) -> None:
    from bwf_player.profile import get_profile

    christie = get_profile("73442", client)
    assert (christie.nationality, christie.height_cm, christie.playing_hand) == ("Indonesia", 179.0, "Right")
    marin = get_profile("18228", client)
    assert (marin.nationality, marin.height_cm, marin.playing_hand) == ("Spain", 172.0, "Left")


def test_live_profile_with_unlisted_details_and_unknown_id(client: BwfHttpClient) -> None:
    from bwf_player.profile import get_profile

    sparse = get_profile("89438", client)
    assert sparse.player_found and sparse.missing_fields == ["nationality", "height", "playing_hand"]
    assert get_profile("999999999", client).player_found is False


def test_live_ranking_of_an_active_player(client: BwfHttpClient) -> None:
    from datetime import date, timedelta

    from bwf_player.ranking import get_ranking

    ranking = get_ranking("73442", client)
    assert ranking.is_ranked and ranking.event.name == "MEN'S SINGLES"
    assert isinstance(ranking.current_rank, int) and ranking.current_rank >= 1
    assert ranking.weeks_at_current_rank >= 1 and ranking.weeks_source == "derived_from_history"
    assert ranking.at_rank_since <= ranking.as_of
    assert (ranking.as_of - ranking.at_rank_since).days >= 6 * (ranking.weeks_at_current_rank - 1)
    assert date.today() - ranking.as_of < timedelta(days=45), "ranking history looks stale"


def test_live_ranking_of_a_retired_and_an_unknown_player(client: BwfHttpClient) -> None:
    from bwf_player.ranking import get_ranking

    retired = get_ranking("50152", client)  # Lee Chong Wei
    assert retired.is_ranked is False and retired.current_rank is None
    assert retired.notes and retired.event is not None
    unknown = get_ranking("999999999", client)
    assert unknown.is_ranked is False and unknown.event is None and unknown.notes
