"""Conservative local metadata and timing helpers; no cloud I/O."""

import math
import unicodedata
from datetime import datetime
from typing import Any, TypeGuard

from homeassistant.core import State
from homeassistant.util import dt as dt_util


def normalized_title(title: str) -> str:
    """Normalize case, Unicode and punctuation, not words or editions."""
    return " ".join(
        "".join(
            c if c.isalnum() else " "
            for c in unicodedata.normalize("NFKC", title).casefold()
        ).split()
    )


def content_identity(state: State | None) -> tuple[str, str, str] | None:
    if not state or state.state not in ("playing", "paused"):
        return None
    attrs = state.attributes
    kind = str(attrs.get("media_content_type", "")).casefold()
    # Plex Cast can report movies as tvshow without any episodic metadata.
    # These app attributes bound a compatibility fallback, not authentication.
    plex_cast_tvshow = (
        kind == "tvshow"
        and attrs.get("app_id") == "9AC194DC"
        and attrs.get("app_name") == "Plex"
    )
    if any(
        attrs.get(key) not in (None, "")
        for key in ("media_series_title", "media_season", "media_episode")
    ) or (
        kind
        in {"episode", "tvshow", "tv_show", "music", "track", "channel", "playlist"}
        and not plex_cast_tvshow
    ):
        return None
    title = attrs.get("media_title")
    if not isinstance(title, str) or not title.strip() or len(title) > 128:
        return None
    return (
        str(attrs.get("media_content_id", ""))[:1024],
        title.strip(),
        str(attrs.get("media_year", ""))[:16],
    )


def number(value: Any) -> TypeGuard[int | float]:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def position_discontinuity(
    previous: State | None, current: State | None, now: datetime
) -> bool:
    """Compare reported anchors, allowing one second of player rounding jitter."""
    if (
        previous is None
        or current is None
        or previous.state != "playing"
        or current.state != "playing"
    ):
        return True
    expected = playback_position(previous, now)
    actual = playback_position(current, now)
    return expected is None or actual is None or abs(actual - expected) > 1


def playback_position(state: State, now: datetime) -> float | None:
    attrs = state.attributes
    if state.state not in ("playing", "paused"):
        return None
    position = attrs.get("media_position")
    if not number(position) or position < 0 or attrs.get("media_speed", 1) != 1:
        return None
    if state.state == "paused":
        return float(position)
    updated = attrs.get("media_position_updated_at")
    if isinstance(updated, str):
        updated = dt_util.parse_datetime(updated)
    if not isinstance(updated, datetime) or updated.tzinfo is None:
        return None
    elapsed = (now - updated).total_seconds()
    if elapsed < 0:
        return None
    return float(position + elapsed)
