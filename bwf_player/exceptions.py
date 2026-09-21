"""Exceptions raised by the bwf_player package."""

from __future__ import annotations


class BwfClientError(Exception):
    """Base class for all bwf_player errors."""


class BlockedByCloudflareError(BwfClientError):
    """Cloudflare served a block/challenge page instead of the requested content.

    This is deliberately not retried: repeating requests after a block tends to
    extend it. Callers should wait (or switch network) before trying again.
    """


class InvalidInputError(BwfClientError, ValueError):
    """The caller supplied input that failed validation."""
