"""Tournaments a player entered in a date window, with the result per event (R4).

Two endpoints, the ones the site's own player "Tournaments" tab uses:

* ``vue-player-tournaments``: one request per calendar year. Each item is a tournament with one
  ``draws[]`` row per event the player entered: the event code (MS, WD, ...), the result
  (``position``) and the match/game/point record.
* ``vue-tournaments-search``: the site's calendar for a date range, used only to add the
  tournament category ("HSBC BWF World Tour Super 750"), which the player endpoint lacks.

A tournament belongs to the window when its dates overlap it, so an event that started before
``since`` but ended on or after it is included.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from bwf_player.exceptions import BlockedByCloudflareError, BwfClientError, InvalidInputError
from bwf_player.http_client import BwfHttpClient
from bwf_player.models import TournamentEntry, TournamentHistory
from bwf_player.names import validate_player_id
from bwf_player.parsing import clean_text as _clean_text
from bwf_player.parsing import to_date as _date
from bwf_player.parsing import to_int as _int

logger = logging.getLogger(__name__)

TOURNAMENTS_ENDPOINT = "vue-player-tournaments"
CALENDAR_ENDPOINT = "vue-tournaments-search"
_CALENDAR_PER_PAGE = 100
_CALENDAR_MAX_PAGES = 10
_NO_POSITION = frozenset({"", "n/a", "-"})


def history_window(today: date | None = None, years: int = 1) -> tuple[date, date]:
    """(since, until): ``years`` back from ``today`` (default: today) to ``today``.

    29 February moves to 28 February in a year without one.
    """
    if isinstance(years, bool) or not isinstance(years, int) or years < 1:
        raise InvalidInputError("years must be a positive integer.")
    until = today or date.today()
    try:
        since = until.replace(year=until.year - years)
    except ValueError:
        since = until.replace(year=until.year - years, day=28)
    return since, until


def get_tournaments(
    player_id: str | int,
    client: BwfHttpClient | None = None,
    *,
    since: date | None = None,
    until: date | None = None,
    today: date | None = None,
    with_categories: bool = True,
) -> TournamentHistory:
    """Every event ``player_id`` entered in the window, oldest first.

    Args:
        player_id: positive integer id from the search result.
        client: HTTP client (defaults to a new polite client).
        since, until: window (inclusive). Default: one year back from ``today`` to ``today``.
        today: only used to derive the default window (tests pass a fixed date).
        with_categories: add the tournament category from the site calendar (extra requests).

    A player with no tournaments in the window is a normal result (empty ``entries`` plus a note);
    the site answers an unknown id the same way. A missing category is ``None`` and noted.

    Raises:
        InvalidInputError: malformed ``player_id``, or ``since`` after ``until``.
        BwfClientError: a response was malformed. BlockedByCloudflareError: never retried.
    """
    pid = validate_player_id(player_id)
    default_since, default_until = history_window(today)
    since = since or default_since
    until = until or default_until
    if since > until:
        raise InvalidInputError(f"since ({since}) is after until ({until}).")
    client = client or BwfHttpClient()

    notes: list[str] = []
    entries: list[TournamentEntry] = []
    skipped = 0
    for year in range(since.year, until.year + 1):
        parsed, bad = parse_tournaments(client.get_json(TOURNAMENTS_ENDPOINT, _params(pid, year)))
        entries.extend(e for e in parsed if overlaps(e, since, until))
        skipped += bad
    entries = _dedupe(entries)
    if skipped:
        notes.append(f"Skipped {skipped} tournament row(s) the site listed without a usable id, name or dates.")
    if not entries:
        notes.append(
            f"No tournaments found between {since} and {until} (none entered, or no player with this id)."
        )
    elif with_categories:
        notes.extend(_add_categories(entries, client, since, until))

    entries.sort(key=lambda e: (e.start_date, e.tournament_id, e.event_code or ""))
    return TournamentHistory(player_id=pid, since=since, until=until, entries=entries, notes=notes)


def overlaps(entry: TournamentEntry, since: date, until: date) -> bool:
    """True if the tournament's dates overlap ``since``..``until`` (inclusive)."""
    return entry.end_date >= since and entry.start_date <= until


def parse_tournaments(payload: Any) -> tuple[list[TournamentEntry], int]:
    """(entries, skipped) from a ``vue-player-tournaments`` response.

    One entry per event; a tournament listed with no event yields one entry without event data.
    A tournament row without a usable id, name or dates is skipped and counted.
    """
    if not isinstance(payload, dict) or "results" not in payload:
        raise BwfClientError(f"{TOURNAMENTS_ENDPOINT}: unexpected response shape")
    results = payload["results"]
    if results is None:
        return [], 0
    if not isinstance(results, list):
        raise BwfClientError(f"{TOURNAMENTS_ENDPOINT}: unexpected response shape")

    entries: list[TournamentEntry] = []
    skipped = 0
    for item in results:
        base = _tournament_fields(item)
        if base is None:
            skipped += 1
            continue
        raw_draws = item.get("draws")
        draws = [d for d in raw_draws if isinstance(d, dict)] if isinstance(raw_draws, list) else []
        if not draws:
            entries.append(TournamentEntry(**base))
        for draw in draws:
            entries.append(TournamentEntry(**base, **_draw_fields(draw)))
    return entries, skipped


def parse_calendar(payload: Any) -> tuple[dict[int, str | None], int]:
    """({tournament id: category or None}, last page) from a ``vue-tournaments-search`` page."""
    results = payload.get("results") if isinstance(payload, dict) else None
    rows = results.get("data") if isinstance(results, dict) else None
    if not isinstance(rows, list):
        raise BwfClientError(f"{CALENDAR_ENDPOINT}: unexpected response shape")
    categories: dict[int, str | None] = {}
    for row in rows:
        tid = _int(row.get("id")) if isinstance(row, dict) else None
        if tid is not None:
            categories[tid] = _clean_text(row.get("category"))
    return categories, _int(results.get("last_page")) or 1


def _tournament_fields(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict) or not isinstance(item.get("tournament_model"), dict):
        return None
    model = item["tournament_model"]
    tid = _int(item.get("tournament_id"))
    if tid is None:
        tid = _int(model.get("id"))
    name = _clean_text(model.get("name"))
    start, end = _date(model.get("start_date")), _date(model.get("end_date"))
    if tid is None or name is None or start is None or end is None:
        return None
    country = model.get("country_model")
    return {
        "tournament_id": tid,
        "name": name,
        "start_date": start,
        "end_date": end,
        "location": _clean_text(item.get("location")),
        "country": _clean_text(country.get("name")) if isinstance(country, dict) else None,
        "type_id": _int(model.get("type_id")),
        "url": _clean_text(item.get("tmt_url")),
    }


def _draw_fields(draw: dict[str, Any]) -> dict[str, Any]:
    position = _clean_text(draw.get("position"))
    return {
        "event_code": _clean_text(draw.get("name")),
        "event_id": _int(draw.get("event_id")),
        "position": None if position is None or position.casefold() in _NO_POSITION else position,
        "matches_won": _int(draw.get("match_win")),
        "matches_lost": _int(draw.get("match_lose")),
        "games_won": _int(draw.get("game_win")),
        "games_lost": _int(draw.get("game_lose")),
        "points_for": _int(draw.get("score_player")),
        "points_against": _int(draw.get("score_opponent")),
    }


def _add_categories(
    entries: list[TournamentEntry], client: BwfHttpClient, since: date, until: date
) -> list[str]:
    """Fill ``category`` in place from the site calendar; return notes about what is missing."""
    wanted = {e.tournament_id for e in entries}
    try:
        categories = _fetch_categories(client, since, until, wanted)
    except BlockedByCloudflareError:
        raise
    except BwfClientError as exc:
        return [f"Tournament categories are unavailable ({exc}); category is null."]

    missing = sum(1 for tid in wanted if categories.get(tid) is None)
    for entry in entries:
        entry.category = categories.get(entry.tournament_id)
    if missing:
        return [f"The site calendar lists no category for {missing} of {len(wanted)} tournament(s); category is null."]
    return []


def _fetch_categories(
    client: BwfHttpClient, since: date, until: date, wanted: set[int]
) -> dict[int, str | None]:
    """Page through the calendar (oldest first) until every wanted tournament has been seen."""
    found: dict[int, str | None] = {}
    page = 1
    while page <= _CALENDAR_MAX_PAGES:
        categories, last_page = parse_calendar(
            client.get_json(
                CALENDAR_ENDPOINT,
                {
                    "startDate": since.isoformat(),
                    "endDate": until.isoformat(),
                    "page": page,
                    "perPage": _CALENDAR_PER_PAGE,
                    "drawCount": 1,
                    "activeTab": 1,
                },
            )
        )
        found.update(categories)
        if wanted <= found.keys() or page >= last_page:
            break
        page += 1
    return found


def _params(player_id: str, year: int) -> dict[str, Any]:
    return {
        "playerId": player_id,
        "tmtYear": year,
        "activeTab": 3,
        "isPara": "false",
        "drawCount": 1,
        "searchKey": "",
        "locale": "en",
    }


def _dedupe(entries: list[TournamentEntry]) -> list[TournamentEntry]:
    seen: set[tuple[int, int | None, str | None]] = set()
    unique = []
    for entry in entries:
        key = (entry.tournament_id, entry.event_id, entry.event_code)
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    return unique
