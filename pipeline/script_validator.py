"""Validate script and narration before expensive GPU steps.

Delegates duration gates to duration_policy (single owner).
"""

from __future__ import annotations

from pipeline.duration_policy import (  # noqa: F401 — re-export for callers
    CHAR_MIN_TOLERANCE,
    find_short_narrations,
    validate_before_images,
)

__all__ = [
    "CHAR_MIN_TOLERANCE",
    "find_short_narrations",
    "validate_before_images",
]
