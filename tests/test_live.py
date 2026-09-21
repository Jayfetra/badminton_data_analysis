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
