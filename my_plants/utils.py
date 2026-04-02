"""Shared helpers for the My Plants backend."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4


def iso_now(now: datetime | None = None) -> str:
    """Task: Return the current timestamp in strict ISO 8601 format without timezone suffixes.
    Input: An optional datetime value to format instead of the current time.
    Output: A string formatted as YYYY-MM-DDTHH:MM:SS.
    Failures: Raises AttributeError if a non-datetime object is passed as `now`.
    """

    active_now = now or datetime.now()
    return active_now.strftime("%Y-%m-%dT%H:%M:%S")


def make_id(prefix: str) -> str:
    """Task: Generate a compact identifier for rows written to file storage.
    Input: A short prefix describing the entity type.
    Output: A unique identifier string with the given prefix.
    Failures: No failure is expected under normal runtime conditions.
    """

    return f"{prefix}_{uuid4().hex[:10]}"

