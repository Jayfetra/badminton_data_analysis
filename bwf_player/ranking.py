"""Player ranking (R3).

Three endpoints, for one ranking event (default: the first the site lists, which is what the
site's own ranking tab selects):

* ``vue-player-ranking-events``: the events the player is ranked in, ``{"6-0": {"id", "name"}}``.
* ``vue-player-ranking-current``: ``{"results": 1}``, or ``"-"`` when there is no current rank.
* ``vue-player-ranking-history``: weekly ``{"date", "value_1"}`` rows (``value_1`` is the world
  rank); ``results`` is itself a JSON *string*.

**Weeks at the current rank is derived from the history.** The history response also carries a
``consecutive`` block, but that describes the player's *best* rank, not the current one (it says
"rank 1, 138 weeks" for the retired Lee Chong Wei), so it is deliberately not used. The weeks are
the number of consecutive weekly ranking lists, ending with the latest, that show the current rank.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from bwf_player.exceptions import BwfClientError, InvalidInputError
from bwf_player.http_client import BwfHttpClient
from bwf_player.models import PlayerRanking, RankingEvent
from bwf_player.names import validate_player_id

logger = logging.getLogger(__name__)

EVENTS_ENDPOINT = "vue-player-ranking-events"
CURRENT_ENDPOINT = "vue-player-ranking-current"
HISTORY_ENDPOINT = "vue-player-ranking-history"
_EVENT_ID = re.compile(r"[0-9]{1,3}-[0-9]{1,10}")
_NO_RANK_PLACEHOLDERS = frozenset({"", "-", "0"})


def get_ranking(
    player_id: str | int,
    client: BwfHttpClient | None = None,
    *,
    event_id: str | None = None,
) -> PlayerRanking:
    """Fetch the current rank and weeks-at-rank for ``player_id`` in one ranking event.

    Args:
        player_id: positive integer id from the search result.
        client: HTTP client (defaults to a new polite client).
        event_id: e.g. ``"6-0"`` (men's singles). Defaults to the first event the site lists;
            the others are returned in ``other_events``.

    An unranked player is a normal result (``is_ranked=False`` plus a note), not an error. The
    site answers an unknown id with an empty events list, so that case looks the same.

    Raises:
        InvalidInputError: malformed ``player_id``/``event_id``, or an event the player lacks.
        BwfClientError: a response was malformed.
    """
    pid = validate_player_id(player_id)
    client = client or BwfHttpClient()

    events = parse_events(client.get_json(EVENTS_ENDPOINT, _params(pid, activeTab=4)))
    if not events:
        return PlayerRanking(
            player_id=pid,
            notes=["The site lists no ranking events for this player (never ranked, or no such id)."],
        )

    event = _select_event(events, event_id)
    others = [e for e in events if e.id != event.id]

    rank, note = parse_current_rank(
        client.get_json(CURRENT_ENDPOINT, _params(pid, rankingEvent=event.id))
    )
    if rank is None:
        return PlayerRanking(
            player_id=pid,
            event=event,
            other_events=others,
            notes=[f"Not currently ranked in {event.name}: {note}"],
        )

    history = parse_history(
        client.get_json(HISTORY_ENDPOINT, _params(pid, activeTab=4, rankingEvent=event.id))
    )
    weeks, since, as_of, history_note = trailing_run(history, rank)
    return PlayerRanking(
        player_id=pid,
        event=event,
        other_events=others,
        is_ranked=True,
        current_rank=rank,
        weeks_at_current_rank=weeks,
        at_rank_since=since,
        as_of=as_of,
        weeks_source="derived_from_history" if weeks is not None else None,
        notes=[history_note] if history_note else [],
    )


def parse_events(payload: Any) -> list[RankingEvent]:
    """Events from a ``vue-player-ranking-events`` response ([] when the player has none)."""
    results = _results(payload, EVENTS_ENDPOINT)
    if not results:
        return []
    items = results.values() if isinstance(results, dict) else results
    events = [
        RankingEvent(id=item["id"], name=item["name"].strip())
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and _EVENT_ID.fullmatch(item["id"])
        and isinstance(item.get("name"), str)
        and item["name"].strip()
    ]
    if not events:
        raise BwfClientError(f"{EVENTS_ENDPOINT}: no usable events in response")
    return events


def parse_current_rank(payload: Any) -> tuple[int | None, str | None]:
    """(rank, None) or (None, reason) from a ``vue-player-ranking-current`` response."""
    if not isinstance(payload, dict) or "results" not in payload:
        raise BwfClientError(f"{CURRENT_ENDPOINT}: unexpected response shape")
    raw = payload["results"]
    if raw is None or (isinstance(raw, str) and raw.strip() in _NO_RANK_PLACEHOLDERS) or raw == 0:
        return None, "the site lists no current rank."
    rank = _positive_int(raw)
    if rank is None:
        return None, f"the site gave an unrecognised current rank ({raw!r})."
    return rank, None


def parse_history(payload: Any) -> list[tuple[date, int | None]] | None:
    """Chronological (date, world rank) rows, or None if the history cannot be read.

    A row without a usable rank is kept with rank None, because a week the player was not
    ranked must end a run at the current rank.
    """
    results = payload.get("results") if isinstance(payload, dict) else None
    if isinstance(results, str):
        try:
            results = json.loads(results)
        except ValueError:
            return None
    if not isinstance(results, list):
        return None

    by_date: dict[date, int | None] = {}
    for row in results:
        if not isinstance(row, dict) or not isinstance(row.get("date"), str):
            continue
        try:
            week = date.fromisoformat(row["date"][:10])
        except ValueError:
            continue
        by_date[week] = _positive_int(row.get("value_1"))
    return sorted(by_date.items())


def trailing_run(
    history: list[tuple[date, int | None]] | None, rank: int
) -> tuple[int | None, date | None, date | None, str | None]:
    """(weeks, since, as_of, note): the run of ``rank`` at the end of ``history``."""
    if history is None:
        return None, None, None, "The ranking history could not be read, so weeks at rank are unknown."
    if not history:
        return None, None, None, "The site lists no ranking history, so weeks at rank are unknown."

    as_of, latest = history[-1]
    if latest != rank:
        return None, None, as_of, (
            f"The latest ranking list ({as_of}) shows rank {latest}, not the current rank {rank}; "
            "weeks at rank are unknown."
        )
    weeks = 0
    since = as_of
    for week, value in reversed(history):
        if value != rank:
            break
        weeks += 1
        since = week
    return weeks, since, as_of, None


def _params(player_id: str, **extra: Any) -> dict[str, Any]:
    return {**extra, "playerId": player_id, "isPara": "false"}


def _results(payload: Any, endpoint: str) -> Any:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), (dict, list)):
        raise BwfClientError(f"{endpoint}: unexpected response shape")
    return payload["results"]


def _select_event(events: list[RankingEvent], event_id: str | None) -> RankingEvent:
    if event_id is None:
        return events[0]
    wanted = event_id.strip() if isinstance(event_id, str) else ""
    for event in events:
        if event.id == wanted:
            return event
    available = ", ".join(f"{e.id} ({e.name})" for e in events)
    raise InvalidInputError(f"Player has no ranking event {event_id!r}. Available: {available}.")


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
        number = int(value.strip())
        return number if number > 0 else None
    return None
