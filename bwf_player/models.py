"""Result models. Field names here are the package's own schema, not BWF's raw JSON."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

SearchStatus = Literal["found", "ambiguous", "not_found"]


class PlayerCandidate(BaseModel):
    """A player returned by search, with the fuzzy-match confidence (0-100)."""

    player_id: str
    slug: str
    name: str
    country: str | None = None
    profile_url: str
    score: float = Field(ge=0, le=100)


class SearchResult(BaseModel):
    """Outcome of a name search. Never raises for 'no match'; check `status`."""

    query: str
    status: SearchStatus
    best_match: PlayerCandidate | None = None
    candidates: list[PlayerCandidate] = Field(default_factory=list)
    message: str | None = None


class PlayerProfile(BaseModel):
    """Personal details (R2). Missing fields are None and listed in `missing_fields`."""

    player_id: str
    name: str | None = None
    nationality: str | None = None
    height: str | None = None
    playing_hand: Literal["Right", "Left"] | None = None
    missing_fields: list[str] = Field(default_factory=list)


class PlayerRanking(BaseModel):
    """Ranking details (R3). `is_ranked=False` means no ranking data is available."""

    player_id: str
    event: str | None = None
    is_ranked: bool = False
    current_rank: int | None = None
    weeks_at_current_rank: int | None = None
    weeks_source: Literal["site_reported", "derived_from_history"] | None = None
    note: str | None = None


class PlayerResult(BaseModel):
    """End-to-end result the notebook displays."""

    search: SearchResult
    profile: PlayerProfile | None = None
    ranking: PlayerRanking | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
