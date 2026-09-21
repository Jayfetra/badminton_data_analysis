"""Player profile details (R2).

All three fields come from one endpoint, ``vue-player-summary``, which is what the site's own
profile header renders:

* nationality: ``results.country_model.name`` (falls back to the ``nationality`` ISO code)
* height: ``results.bio_model.height`` (centimetres, e.g. ``"179.00"``)
* playing hand: ``results.bio_model.plays`` (the site shows 1 as right-handed, 2 as left-handed
  and anything else as "n/a")
"""

from __future__ import annotations

import logging
import math
from typing import Any

from bwf_player.exceptions import BwfClientError
from bwf_player.http_client import BwfHttpClient
from bwf_player.models import PlayerProfile
from bwf_player.names import validate_player_id

logger = logging.getLogger(__name__)

SUMMARY_ENDPOINT = "vue-player-summary"
_HANDS = {"1": "Right", "2": "Left"}
_MAX_HEIGHT_CM = 300.0
_FIELDS = ("nationality", "height", "playing_hand")


def get_profile(player_id: str | int, client: BwfHttpClient | None = None) -> PlayerProfile:
    """Fetch nationality, height and playing hand for ``player_id``.

    A field the site does not list comes back as ``None`` (named in ``missing_fields``); the
    rest of the profile is still returned. An id the site does not know returns
    ``player_found=False``.

    Raises:
        InvalidInputError: ``player_id`` is not a positive integer (at most 10 digits). This is
            checked before any request because the API answers a malformed id with an
            unrelated player.
        BwfClientError: the response was malformed or described a different player.
    """
    pid = validate_player_id(player_id)
    client = client or BwfHttpClient()
    payload = client.get_json(
        SUMMARY_ENDPOINT, {"drawCount": 1, "playerId": pid, "isPara": "false"}
    )
    return parse_profile(payload, pid)


def parse_profile(payload: Any, player_id: str) -> PlayerProfile:
    """Turn a ``vue-player-summary`` response into a ``PlayerProfile`` (no network)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), (dict, list)):
        raise BwfClientError(f"{SUMMARY_ENDPOINT}: unexpected response shape")
    results = payload["results"]

    if not results:
        return PlayerProfile(
            player_id=player_id,
            player_found=False,
            missing_fields=list(_FIELDS),
            notes=[f"No player with id {player_id} was found on bwfbadminton.com."],
        )
    if not isinstance(results, dict):
        raise BwfClientError(f"{SUMMARY_ENDPOINT}: unexpected response shape")
    if str(results.get("id")) != player_id:
        raise BwfClientError(
            f"{SUMMARY_ENDPOINT}: asked for player {player_id} but received {results.get('id')!r}"
        )

    bio = results.get("bio_model")
    bio = bio if isinstance(bio, dict) else {}
    notes: list[str] = []

    nationality = _nationality(results, notes)
    height_cm = _height_cm(bio.get("height"), notes)
    playing_hand = _playing_hand(bio.get("plays"), notes)

    values = {"nationality": nationality, "height": height_cm, "playing_hand": playing_hand}
    missing = [field for field in _FIELDS if values[field] is None]
    for field in missing:
        note = f"{field.replace('_', ' ')} is not listed on the player's profile"
        if not any(n.startswith(field.replace("_", " ")) for n in notes):
            notes.append(note + ".")

    return PlayerProfile(
        player_id=player_id,
        name=_clean_text(results.get("name_display")),
        nationality=nationality,
        height_cm=height_cm,
        playing_hand=playing_hand,
        missing_fields=missing,
        notes=notes,
    )


def _clean_text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _nationality(results: dict[str, Any], notes: list[str]) -> str | None:
    country = results.get("country_model")
    name = _clean_text(country.get("name")) if isinstance(country, dict) else None
    if name:
        return name
    code = _clean_text(results.get("nationality"))
    if code:
        notes.append(f"nationality is a country code ({code}); the site lists no country name.")
    return code


def _height_cm(raw: object, notes: list[str]) -> float | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        height = math.nan if isinstance(raw, bool) else float(raw)
    except (TypeError, ValueError):
        height = math.nan
    if not math.isfinite(height) or not 0 < height <= _MAX_HEIGHT_CM:
        notes.append(f"height has an unusable value on the site ({raw!r}).")
        return None
    return height


def _playing_hand(raw: object, notes: list[str]) -> str | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    hand = _HANDS.get(str(raw).strip())
    if hand is None:
        notes.append(f"playing hand has a value the site does not map to left/right ({raw!r}).")
    return hand
