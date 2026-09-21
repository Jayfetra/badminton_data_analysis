"""End-to-end lookup: name -> search -> personal details -> ranking."""

from __future__ import annotations

from bwf_player.http_client import BwfHttpClient
from bwf_player.models import PlayerResult
from bwf_player.profile import get_profile
from bwf_player.ranking import get_ranking
from bwf_player.search import search_player


def lookup_player(
    name: str, client: BwfHttpClient | None = None, *, event_id: str | None = None
) -> PlayerResult:
    """Look up a player by name and return search, profile and ranking together.

    ``profile`` and ``ranking`` are only fetched when the search finds exactly one player
    (``search.status == "found"``); for an ambiguous or unknown name they stay ``None`` and no
    further requests are made.

    Args:
        name: the player's name, in any reasonable form (see ``search_player``).
        client: HTTP client to reuse (defaults to a new polite client).
        event_id: ranking event to report, e.g. ``"9-90070"``; defaults to the first the site
            lists. Ignored when no single player is found.

    Raises:
        BlockedByCloudflareError, BwfClientError: a request failed (see ``BwfHttpClient``).
        InvalidInputError: ``event_id`` is malformed or not one of the player's events.
    """
    client = client or BwfHttpClient()
    search = search_player(name, client)
    if search.best_match is None:
        return PlayerResult(search=search)
    player_id = search.best_match.player_id
    return PlayerResult(
        search=search,
        profile=get_profile(player_id, client),
        ranking=get_ranking(player_id, client, event_id=event_id),
    )


def format_result(result: PlayerResult) -> str:
    """Render a ``PlayerResult`` as readable text (missing values are shown as ``null``)."""
    search = result.search
    lines = [f"Search:         {search.status.upper()} - {search.message}"]

    if search.best_match is None:
        lines += [
            f"  {c.score:5.1f}  {c.name} ({c.country or 'country unknown'})  {c.profile_url}"
            for c in search.candidates
        ]
        if search.candidates:
            lines.append("Several players match; re-run with a fuller name to pick one.")
        return "\n".join(lines)

    lines.append(f"Profile URL:    {search.best_match.profile_url}")
    notes: list[str] = []

    profile = result.profile
    if profile is not None:
        lines += [
            "",
            "Personal details",
            f"  Name:          {_show(profile.name)}",
            f"  Nationality:   {_show(profile.nationality)}",
            f"  Height:        {_show(profile.height_cm, ' cm')}",
            f"  Playing hand:  {_show(profile.playing_hand)}",
        ]
        notes += profile.notes

    ranking = result.ranking
    if ranking is not None:
        event = ranking.event.name if ranking.event else None
        lines += ["", f"Ranking ({_show(event)})", f"  Current rank:  {_show(ranking.current_rank)}"]
        if ranking.weeks_at_current_rank is not None:
            lines.append(
                f"  At this rank:  {ranking.weeks_at_current_rank} week(s), since "
                f"{ranking.at_rank_since} (latest ranking list {ranking.as_of})"
            )
        else:
            lines.append("  At this rank:  null")
        lines += [f"  Other event:   {e.name} [{e.id}]" for e in ranking.other_events]
        notes += ranking.notes

    if notes:
        lines += ["", "Notes"] + [f"  - {note}" for note in notes]
    return "\n".join(lines)


def _show(value: object, unit: str = "") -> str:
    return "null" if value is None else f"{value}{unit}"
