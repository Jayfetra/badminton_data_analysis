"""Iteration 0 smoke tests: the package imports and its models/config behave."""

import pytest
from pydantic import ValidationError

import bwf_player
from bwf_player import BwfConfig, PlayerCandidate, PlayerRanking, SearchResult


def test_package_imports() -> None:
    assert bwf_player.__version__ == "0.1.0"


def test_config_defaults_are_conservative() -> None:
    cfg = BwfConfig()
    assert cfg.min_request_interval_seconds >= 1.0
    assert 0 <= cfg.match_threshold <= 100


def test_config_rejects_invalid_threshold() -> None:
    with pytest.raises(ValidationError):
        BwfConfig(match_threshold=150)


def test_not_found_result_needs_no_match() -> None:
    result = SearchResult(query="nobody", status="not_found")
    assert result.best_match is None
    assert result.candidates == []


def test_candidate_score_bounds() -> None:
    with pytest.raises(ValidationError):
        PlayerCandidate(
            player_id="1", slug="x", name="X", profile_url="https://example.org", score=101
        )


def test_unranked_ranking_defaults() -> None:
    ranking = PlayerRanking(player_id="1")
    assert ranking.is_ranked is False
    assert ranking.current_rank is None
