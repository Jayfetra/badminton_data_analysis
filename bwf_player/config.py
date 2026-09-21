"""Runtime configuration for bwf_player."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class BwfConfig(BaseModel):
    """Tunable settings. Defaults are deliberately conservative (polite client)."""

    model_config = ConfigDict(frozen=True)

    site_url: str = "https://bwfbadminton.com"
    api_url: str = "https://extranet-lv.bwfbadminton.com/api"

    user_agent: str = "Mozilla/5.0 (compatible; bwf-player-lookup/0.1; personal-research)"
    timeout_seconds: float = Field(default=15.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    backoff_factor: float = Field(default=2.0, ge=0)
    min_request_interval_seconds: float = Field(default=2.5, ge=0)

    cache_dir: Path = Path(".cache/bwf_player")
    cache_ttl_seconds: int = Field(default=24 * 3600, ge=0)
    index_cache_ttl_seconds: int = Field(default=7 * 24 * 3600, ge=0)

    match_threshold: float = Field(default=85.0, ge=0, le=100)
    ambiguity_margin: float = Field(default=5.0, ge=0, le=100)
    max_candidates: int = Field(default=5, ge=1)
    max_query_length: int = Field(default=100, ge=1)
    search_max_tokens: int = Field(default=2, ge=1)
    search_max_pages: int = Field(default=2, ge=1)
