"""Offline test doubles built from saved real API responses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bwf_player.config import BwfConfig

FIXTURES = Path(__file__).parent / "fixtures"

# (playerId, rankingEvent) -> fixture suffix; the events fixture is per player.
_RANKING_EVENTS = {
    "73442": "christie", "39881": "christie",
    "89438": "aadhya_two_events", "50152": "lee_chong_wei",
}
_RANKING_DATA = {
    ("73442", "6-0"): "christie", ("89438", "7-0"): "aadhya_ws", ("89438", "9-90070"): "aadhya_wd",
    ("50152", "6-0"): "lee_chong_wei", ("39881", "6-0"): "molis",
}

_SUMMARY_FIXTURES = {
    "73442": "summary_christie.json",
    "18228": "summary_marin.json",
    "89438": "summary_no_details.json",
}


# (playerId, tmtYear) -> fixture; any other player/year has no tournaments.
_TOURNAMENT_FIXTURES = {
    ("73442", "2026"): "tournaments_christie_2026.json",
    ("73442", "2025"): "tournaments_christie_2025.json",
    ("89438", "2026"): "tournaments_aadhya_2026.json",
    ("89438", "2025"): "tournaments_aadhya_2025.json",
    ("88876", "2026"): "tournaments_fajar_2026.json",
    ("88876", "2025"): "tournaments_fajar_2025.json",
    ("81458", "2026"): "tournaments_dejan_2026.json",
    ("81458", "2025"): "tournaments_dejan_2025.json",
    ("81462", "2026"): "tournaments_apriyani_2026.json",
    ("81462", "2025"): "tournaments_apriyani_2025.json",
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
        for name in ("popular_christie.json", "popular_momota.json", "popular_tzu_ying.json", "popular_chong_wei.json"):
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
        if endpoint == "vue-player-ranking-events":
            name = _RANKING_EVENTS.get(str(params.get("playerId")))
            return load_fixture(f"ranking_events_{name}.json" if name else "ranking_events_none.json")
        if endpoint in ("vue-player-ranking-current", "vue-player-ranking-history"):
            key = (str(params.get("playerId")), str(params.get("rankingEvent")))
            if key not in _RANKING_DATA:
                raise AssertionError(f"unexpected ranking request {endpoint} {key}")
            kind = "current" if endpoint.endswith("current") else "history"
            return load_fixture(f"ranking_{kind}_{_RANKING_DATA[key]}.json")
        if endpoint == "vue-player-tournaments":
            key = (str(params.get("playerId")), str(params.get("tmtYear")))
            fixture = _TOURNAMENT_FIXTURES.get(key)
            return load_fixture(fixture) if fixture else {"results": [], "drawCount": 1}
        if endpoint == "vue-player-tmt-matches":
            name = f"matches_{params.get('playerId')}_{params.get('tmtId')}_{params.get('eventId')}.json"
            return load_fixture(name) if (FIXTURES / name).exists() else {"results": [], "drawCount": 1}
        if endpoint == "vue-tournaments-search":
            return load_fixture(f"calendar_page{int(params.get('page', 1))}.json")
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
