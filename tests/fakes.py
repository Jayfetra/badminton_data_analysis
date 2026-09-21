"""Offline test doubles built from saved real API responses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bwf_player.config import BwfConfig

FIXTURES = Path(__file__).parent / "fixtures"

_SUMMARY_FIXTURES = {
    "73442": "summary_christie.json",
    "18228": "summary_marin.json",
    "89438": "summary_no_details.json",
}


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeApiClient:
    """Stands in for BwfHttpClient. Mimics the site: the index ignores searchKey, the
    search endpoint does a case-insensitive substring match on name_display."""

    def __init__(self, config: BwfConfig | None = None) -> None:
        self.config = config or BwfConfig()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._index = load_fixture("h2h_players_index.json")
        self._players: dict[str, dict[str, Any]] = {}
        # Common name parts return many unrelated players on the real site (30 per page), and
        # the player we want is not necessarily on the first pages. Decoys therefore come first.
        for word in ("Ying", "Tai"):
            for i in range(80):
                pid = f"9{word}{i}"
                self._players[pid] = {"id": pid, "slug": f"{word.lower()}-decoy-{i}",
                                      "name_display": f"{word} Decoy{i}", "country_model": None}
        for name in ("popular_christie.json", "popular_momota.json", "popular_tzu_ying.json"):
            for item in load_fixture(name)["results"]:
                self._players[item["id"]] = item

    def get_json(self, endpoint: str, params: dict[str, Any] | None = None, *, ttl: int | None = None) -> Any:
        params = params or {}
        self.calls.append((endpoint, dict(params)))
        if endpoint == "vue-h2h-players":
            return self._index
        if endpoint == "vue-popular-players":
            key = str(params.get("searchKey", "")).lower()
            matches = [p for p in self._players.values() if key in p["name_display"].lower()]
            page, size = int(params.get("page", 1)), 30
            chunk = matches[(page - 1) * size : page * size]
            more = len(matches) > page * size
            return {"results": chunk, "pagination": {"next_page_url": "next" if more else None}}
        if endpoint == "vue-player-summary":
            fixture = _SUMMARY_FIXTURES.get(str(params.get("playerId")), "summary_unknown_player.json")
            return load_fixture(fixture)
        raise AssertionError(f"unexpected endpoint {endpoint}")

    def calls_to(self, endpoint: str) -> list[dict[str, Any]]:
        return [p for e, p in self.calls if e == endpoint]


class FakeResponse:
    def __init__(self, status_code: int = 200, body: Any = None, text: str | None = None,
                 headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else (json.dumps(body) if body is not None else "")
        self.headers = headers or {}

    def json(self) -> Any:
        if self._body is None:
            raise ValueError("not json")
        return self._body


class FakeSession:
    """Returns queued responses (or raises queued exceptions) and records requests."""

    def __init__(self, *responses: FakeResponse | Exception) -> None:
        self._queue = list(responses)
        self.requests: list[dict[str, Any]] = []

    def get(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None,
            timeout: float | None = None) -> FakeResponse:
        self.requests.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
