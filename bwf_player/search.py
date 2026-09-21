"""Player search (R1).

Two sources are combined because neither is sufficient alone:

1. **Index** (``vue-h2h-players``): every player's id and name in one request, cached for days.
   Fuzzy-matched locally, so typos, accents and reversed order are handled. It omits some
   players (e.g. Kento MOMOTA).
2. **Server search** (``vue-popular-players``): a strict substring match on the display name,
   so it cannot absorb typos, but it covers players the index lacks and returns real slugs.

The index runs first. The server is queried only when the index has no single match scoring
100 (the same words in any order), so repeat lookups of known players cost no requests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from rapidfuzz import fuzz

from bwf_player.exceptions import InvalidInputError
from bwf_player.http_client import BwfHttpClient
from bwf_player.models import PlayerCandidate, SearchResult
from bwf_player.names import derive_slug, normalize_name, sanitize_query

logger = logging.getLogger(__name__)

INDEX_ENDPOINT = "vue-h2h-players"
SEARCH_ENDPOINT = "vue-popular-players"
_EXACT = 100.0


@dataclass
class _Hit:
    player_id: str
    name: str
    score: float
    slug: str | None = None
    country: str | None = None


def search_player(name: str, client: BwfHttpClient | None = None) -> SearchResult:
    """Find a player by (possibly imprecise) name.

    Never raises for "no match" or bad input; inspect ``SearchResult.status``.
    Network failures still raise ``BwfClientError`` / ``BlockedByCloudflareError``.
    """
    client = client or BwfHttpClient()
    cfg = client.config

    try:
        query = sanitize_query(name, cfg.max_query_length)
    except InvalidInputError as exc:
        shown = name[: cfg.max_query_length] if isinstance(name, str) else ""
        return SearchResult(query=shown, status="not_found", message=str(exc))

    q_norm = normalize_name(query)
    hits: dict[str, _Hit] = {}

    for hit in _index_hits(client, q_norm):
        hits[hit.player_id] = hit

    if not _has_exact_match(hits):
        for phrase in _server_queries(q_norm, cfg.search_max_queries):
            for hit in _server_hits(client, phrase, q_norm):
                known = hits.get(hit.player_id)
                hit.score = max(hit.score, known.score) if known else hit.score
                hits[hit.player_id] = hit
            if _decide(list(hits.values()), cfg.match_threshold, cfg.ambiguity_margin)[0] == "found":
                break

    status, ranked = _decide(list(hits.values()), cfg.match_threshold, cfg.ambiguity_margin)
    candidates = [_to_candidate(h, client.config.site_url) for h in ranked[: cfg.max_candidates]]

    if status == "not_found":
        closest = max(hits.values(), key=lambda h: h.score, default=None)
        hint = f" Closest was '{closest.name}' ({closest.score:.0f})." if closest else ""
        return SearchResult(
            query=query,
            status="not_found",
            message=f"No player matched '{query}' at or above {cfg.match_threshold:.0f}.{hint}",
        )
    if status == "ambiguous":
        return SearchResult(
            query=query,
            status="ambiguous",
            candidates=candidates,
            message="Several players match closely; choose one of the candidates.",
        )
    best = candidates[0]
    return SearchResult(
        query=query,
        status="found",
        best_match=best,
        candidates=candidates,
        message=f"Matched '{best.name}' (score {best.score:.0f}).",
    )


def _score(query_norm: str, name: str) -> float:
    """0-100. Order-independent (reversed names score like exact ones); typos in full names
    lose a few points; a partial name scores a flat 90 whatever the length of the other name."""
    candidate = normalize_name(name)
    return float(
        max(
            fuzz.token_sort_ratio(query_norm, candidate),
            0.9 * fuzz.token_set_ratio(query_norm, candidate),
        )
    )


def _index_hits(client: BwfHttpClient, q_norm: str) -> list[_Hit]:
    payload = client.get_json(
        INDEX_ENDPOINT,
        {"searchKey": "", "drawCount": 1, "drawTab": 0},
        ttl=client.config.index_cache_ttl_seconds,
    )
    hits: list[_Hit] = []
    for item in _results(payload):
        player_id, name = item.get("value"), item.get("text")
        if player_id is None or not isinstance(name, str):
            continue
        hits.append(_Hit(str(player_id), name, _score(q_norm, name)))
    return hits


def _server_hits(client: BwfHttpClient, phrase: str, q_norm: str) -> list[_Hit]:
    hits: list[_Hit] = []
    for page in range(1, client.config.search_max_pages + 1):
        payload = client.get_json(SEARCH_ENDPOINT, {"searchKey": phrase, "activeTab": 1, "page": page})
        for item in _results(payload):
            player_id, name = item.get("id"), item.get("name_display")
            if player_id is None or not isinstance(name, str):
                continue
            country = (item.get("country_model") or {}).get("name")
            hits.append(_Hit(str(player_id), name, _score(q_norm, name), item.get("slug"), country))
        if not _has_next_page(payload):
            break
    return hits


def _results(payload: Any) -> list[dict[str, Any]]:
    results = payload.get("results") if isinstance(payload, dict) else None
    return [r for r in results if isinstance(r, dict)] if isinstance(results, list) else []


def _has_next_page(payload: Any) -> bool:
    pagination = payload.get("pagination") if isinstance(payload, dict) else None
    return isinstance(pagination, dict) and bool(pagination.get("next_page_url"))


def _server_queries(q_norm: str, limit: int) -> list[str]:
    """Contiguous word sequences of the query, longest first.

    The server matches a contiguous substring of the display name, whose word order differs
    from the user's ("Tzu Ying TAI" vs "Tai Tzu Ying"). Long phrases are selective; single
    common words ("ying") return more players than we page through.
    """
    words = q_norm.split()
    phrases = (
        " ".join(words[i : i + size])
        for size in range(len(words), 0, -1)
        for i in range(len(words) - size + 1)
    )
    unique = dict.fromkeys(p for p in phrases if len(p) >= 2)
    return sorted(unique, key=len, reverse=True)[:limit]


def _has_exact_match(hits: dict[str, _Hit]) -> bool:
    return sum(h.score >= _EXACT for h in hits.values()) == 1


def _decide(hits: list[_Hit], threshold: float, margin: float) -> tuple[str, list[_Hit]]:
    ranked = sorted((h for h in hits if h.score >= threshold), key=lambda h: (-h.score, h.name))
    if not ranked:
        return "not_found", []
    if len(ranked) == 1 or ranked[0].score - ranked[1].score >= margin:
        return "found", ranked
    return "ambiguous", ranked


def _to_candidate(hit: _Hit, site_url: str) -> PlayerCandidate:
    slug = hit.slug or derive_slug(hit.name)
    return PlayerCandidate(
        player_id=hit.player_id,
        slug=slug,
        name=hit.name,
        country=hit.country,
        profile_url=f"{site_url.rstrip('/')}/player/{quote(hit.player_id, safe='')}/{quote(slug, safe='-')}",
        score=round(hit.score, 1),
    )
