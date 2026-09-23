"""HTTP client behaviour: bootstrap, retry/backoff, block detection, caching, throttling."""

from __future__ import annotations

from pathlib import Path

import pytest
import requests

from bwf_player.config import BwfConfig
from bwf_player.exceptions import BlockedByCloudflareError, BwfClientError, BwfNotFoundError
from bwf_player.http_client import BwfHttpClient
from fakes import FakeResponse, FakeSession

BLOCK_PAGE = "<title>Attention Required! | Cloudflare</title><h1>Sorry, you have been blocked</h1>"
PAGE = FakeResponse(200, text="<html>players</html>")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


def make_client(tmp_path: Path, session: FakeSession, clock: Clock | None = None, **cfg: object) -> BwfHttpClient:
    clock = clock or Clock()
    config = BwfConfig(cache_dir=tmp_path / "cache", min_request_interval_seconds=2.5, **cfg)
    return BwfHttpClient(config, session=session, sleep=clock.sleep, monotonic=clock.monotonic,
                         wall_clock=clock.monotonic)  # type: ignore[arg-type]


def test_bootstraps_once_then_calls_api_with_headers(tmp_path: Path) -> None:
    session = FakeSession(PAGE, FakeResponse(body={"a": 1}), FakeResponse(body={"b": 2}))
    client = make_client(tmp_path, session)
    assert client.get_json("ep", {"q": "x"}) == {"a": 1}
    assert client.get_json("ep", {"q": "y"}) == {"b": 2}
    urls = [r["url"] for r in session.requests]
    assert urls == [
        "https://bwfbadminton.com/players/",
        "https://extranet-lv.bwfbadminton.com/api/ep",
        "https://extranet-lv.bwfbadminton.com/api/ep",
    ]
    api_call = session.requests[1]
    assert api_call["params"] == {"q": "x"}
    assert api_call["headers"]["Referer"] == "https://bwfbadminton.com/players/"
    assert "bwf-player-lookup" in api_call["headers"]["User-Agent"]
    assert api_call["timeout"] == client.config.timeout_seconds


def test_cache_hit_makes_no_network_request(tmp_path: Path) -> None:
    session = FakeSession(PAGE, FakeResponse(body={"a": 1}))
    client = make_client(tmp_path, session)
    client.get_json("ep", {"q": "x"})
    assert client.get_json("ep", {"q": "x"}) == {"a": 1}
    assert len(session.requests) == 2

    fresh = make_client(tmp_path, FakeSession())  # new client, empty session: must not need it
    assert fresh.get_json("ep", {"q": "x"}) == {"a": 1}


def test_cache_expires_after_ttl(tmp_path: Path) -> None:
    clock = Clock()
    session = FakeSession(PAGE, FakeResponse(body={"v": 1}), FakeResponse(body={"v": 2}))
    client = make_client(tmp_path, session, clock, cache_ttl_seconds=60)
    assert client.get_json("ep") == {"v": 1}
    clock.now += 61
    assert client.get_json("ep") == {"v": 2}


def test_zero_ttl_disables_cache(tmp_path: Path) -> None:
    session = FakeSession(PAGE, FakeResponse(body={"v": 1}), FakeResponse(body={"v": 2}))
    client = make_client(tmp_path, session, cache_ttl_seconds=0)
    assert client.get_json("ep") == {"v": 1}
    assert client.get_json("ep") == {"v": 2}


def test_corrupt_cache_file_is_ignored(tmp_path: Path) -> None:
    session = FakeSession(PAGE, FakeResponse(body={"a": 1}))
    client = make_client(tmp_path, session)
    path = client._cache_file("ep", {})
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert client.get_json("ep") == {"a": 1}


def test_rate_limit_spaces_network_requests(tmp_path: Path) -> None:
    clock = Clock()
    session = FakeSession(PAGE, FakeResponse(body=1), FakeResponse(body=2))
    client = make_client(tmp_path, session, clock)
    client.get_json("ep", {"n": 1})
    client.get_json("ep", {"n": 2})
    assert clock.sleeps == [2.5, 2.5]


def test_transient_errors_are_retried_with_backoff(tmp_path: Path) -> None:
    clock = Clock()
    session = FakeSession(
        PAGE,
        FakeResponse(500, text="boom"),
        requests.Timeout("slow"),
        FakeResponse(body={"ok": True}),
    )
    client = make_client(tmp_path, session, clock, backoff_factor=2.0)
    assert client.get_json("ep") == {"ok": True}
    assert 2.0 in clock.sleeps and 4.0 in clock.sleeps


def test_retry_after_header_is_respected(tmp_path: Path) -> None:
    clock = Clock()
    session = FakeSession(PAGE, FakeResponse(429, text="slow down", headers={"Retry-After": "7"}),
                          FakeResponse(body=1))
    client = make_client(tmp_path, session, clock)
    client.get_json("ep")
    assert 7.0 in clock.sleeps


def test_gives_up_after_max_retries(tmp_path: Path) -> None:
    session = FakeSession(PAGE, *[FakeResponse(500, text="boom")] * 3)
    client = make_client(tmp_path, session, max_retries=2)
    with pytest.raises(BwfClientError, match="giving up"):
        client.get_json("ep")
    assert len(session.requests) == 1 + 3


def test_cloudflare_block_is_not_retried(tmp_path: Path) -> None:
    session = FakeSession(PAGE, FakeResponse(403, text=BLOCK_PAGE))
    client = make_client(tmp_path, session)
    with pytest.raises(BlockedByCloudflareError):
        client.get_json("ep")
    assert len(session.requests) == 2


def test_block_during_bootstrap_is_detected(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse(403, text=BLOCK_PAGE))
    with pytest.raises(BlockedByCloudflareError):
        make_client(tmp_path, session).get_json("ep")
    assert len(session.requests) == 1


def test_plain_403_is_a_client_error_not_a_block(tmp_path: Path) -> None:
    session = FakeSession(PAGE, FakeResponse(403, text="forbidden"))
    with pytest.raises(BwfClientError) as info:
        make_client(tmp_path, session).get_json("ep")
    assert not isinstance(info.value, BlockedByCloudflareError)


def test_404_is_a_not_found_error_and_is_not_retried(tmp_path: Path) -> None:
    session = FakeSession(PAGE, FakeResponse(404, body={"stats": None, "games": []}))
    with pytest.raises(BwfNotFoundError, match="HTTP 404"):
        make_client(tmp_path, session).get_json("h2h/match", {"tmt_id": 1, "match_code": 2})
    assert len(session.requests) == 2  # bootstrap + one attempt, no retry


def test_not_found_is_a_client_error_but_other_statuses_are_not_not_found(tmp_path: Path) -> None:
    assert issubclass(BwfNotFoundError, BwfClientError)
    for status in (400, 401, 403, 410):
        session = FakeSession(PAGE, FakeResponse(status, text="no"))
        with pytest.raises(BwfClientError) as info:
            make_client(tmp_path, session).get_json("ep")
        assert not isinstance(info.value, BwfNotFoundError), status


def test_a_404_is_not_cached(tmp_path: Path) -> None:
    session = FakeSession(PAGE, FakeResponse(404, text="gone"), FakeResponse(body={"ok": True}))
    client = make_client(tmp_path, session)
    with pytest.raises(BwfNotFoundError):
        client.get_json("ep", {"q": "x"})
    assert client.get_json("ep", {"q": "x"}) == {"ok": True}  # asked again, not served from a cached failure


def test_non_json_response_raises(tmp_path: Path) -> None:
    session = FakeSession(PAGE, FakeResponse(200, text="<html>oops</html>"))
    with pytest.raises(BwfClientError, match="not valid JSON"):
        make_client(tmp_path, session).get_json("ep")


def test_params_are_passed_separately_never_in_url(tmp_path: Path) -> None:
    session = FakeSession(PAGE, FakeResponse(body={}))
    make_client(tmp_path, session).get_json("vue-popular-players", {"searchKey": "a&b=c/../d"})
    api_call = session.requests[1]
    assert "&" not in api_call["url"] and api_call["params"] == {"searchKey": "a&b=c/../d"}
