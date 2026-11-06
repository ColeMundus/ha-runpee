"""Player-following state machine; cloud lookups are independent of local ticks."""

import asyncio
import logging
import math
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .client import ProviderError, RunPeeClient
from .const import EVENT_BREAK
from .models import Movie
from .playback import (
    content_identity,
    normalized_title,
    number,
    playback_position,
    position_discontinuity,
)

_LOGGER = logging.getLogger(__name__)
STATUSES = [
    "idle",
    "matching",
    "ready",
    "paused",
    "in_window",
    "no_match",
    "ambiguous",
    "position_unavailable",
    "error",
]


class RunPeeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Serialize/coalesce lookups and reject retired generation publications."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: RunPeeClient
    ) -> None:
        super().__init__(hass, _LOGGER, name="RunPee", config_entry=entry)
        self.client = client
        self.player: str = entry.data["media_player"]
        self.recommended_only: bool = entry.options.get(
            "recommended_windows_only",
            entry.data.get("recommended_windows_only", False),
        )
        self.offset: int = entry.options.get(
            "timing_offset_seconds", entry.data.get("timing_offset_seconds", 0)
        )
        self.identity: tuple[str, str, str] | None = None
        self.generation = 0
        self.retired = False
        self.movie: Movie | None = None
        self.override: int | None = None
        self.candidates: list[dict[str, Any]] = []
        self.phase = "idle"
        self.error: str | None = None
        self.fetched_at = 0.0
        self.retry_at = 0.0
        self.worker: asyncio.Task[None] | None = None
        self.previous: tuple[datetime, float] | None = None
        self.player_state: State | None = None
        self.fired: set[tuple[int | None, int]] = set()
        self.data = {}

    async def _async_update_data(self) -> dict[str, Any]:
        """HA's manual entity refresh recalculates locally, never bypasses pacing."""
        self.sync()
        return self.data

    @property
    def movie_id(self) -> int | None:
        return self.movie.movie_id if self.movie else None

    @callback
    def start(self) -> None:
        assert self.config_entry is not None
        self.config_entry.async_on_unload(
            async_track_state_change_event(
                self.hass, [self.player], self._state_changed
            )
        )
        self.config_entry.async_on_unload(
            async_track_time_interval(self.hass, self.tick, timedelta(seconds=1))
        )
        self.config_entry.async_on_unload(self.stop)
        self.sync()

    @callback
    def stop(self) -> None:
        self.retired = True
        self.generation += 1
        if self.worker:
            self.worker.cancel()

    @callback
    def _state_changed(self, event: Event[Any]) -> None:
        self.sync()

    def effective_identity(self) -> tuple[str, str, str] | None:
        state = self.hass.states.get(self.player)
        # Temporary transport loss is not evidence of a new playback session.
        if state is None or state.state in ("unknown", "unavailable"):
            return self.identity
        return content_identity(state)

    @callback
    def sync(self) -> None:
        if self.retired:
            return
        identity = self.effective_identity()
        if identity != self.identity:
            self.generation += 1
            self.identity = identity
            self.movie = None
            self.override = None
            self.candidates = []
            self.error = None
            self.previous = None
            self.fired.clear()
            self.phase = "matching" if identity else "idle"
            if identity:
                self._queue()
        if (
            self.identity
            and self.phase == "matching"
            and content_identity(self.hass.states.get(self.player))
        ):
            self._queue()
        self.tick(dt_util.utcnow())

    @callback
    def _queue(self) -> None:
        if self.worker is None or self.worker.done():
            self.worker = self.hass.async_create_background_task(
                self._lookup_worker(), "RunPee matching", eager_start=False
            )

    def current(self, generation: int) -> bool:
        return not self.retired and generation == self.generation

    async def _lookup_worker(self) -> None:
        while not self.retired and self.identity:
            generation = self.generation
            # Briefly coalesce bursts of title/id/year updates before any HTTP.
            await asyncio.sleep(0)
            if not self.current(generation):
                continue
            if content_identity(self.hass.states.get(self.player)) is None:
                break
            await self._lookup(generation)
            if self.current(generation):
                break

    async def _lookup(self, generation: int) -> None:
        assert self.identity is not None
        _, title, year = self.identity
        try:
            if self.override is not None:
                selected = self.override
            else:
                candidates = await self.client.search_movies(title)
                if not self.current(generation):
                    return
                self.candidates = candidates
                exact = [
                    item
                    for item in candidates
                    if normalized_title(item["title"]) == normalized_title(title)
                ]
                if year:
                    exact = [
                        item for item in exact if str(item.get("year", "")) == year
                    ]
                if len(exact) != 1:
                    self.movie = None
                    self.previous = None
                    self.phase = "ambiguous" if len(exact) > 1 else "no_match"
                    self.error = None
                    self.tick(dt_util.utcnow())
                    return
                selected = exact[0]["movie_id"]
            movie = await self.client.get_peetimes(selected)
            if not self.current(generation):
                return
            self.movie = movie
            self.phase = "ready"
            self.error = None
            self.fetched_at = dt_util.utcnow().timestamp()
        except ProviderError:
            if not self.current(generation):
                return
            self.movie = None
            self.phase = "error"
            self.error = "provider_unavailable"
            self.retry_at = dt_util.utcnow().timestamp() + 60
        self.previous = None
        self.tick(dt_util.utcnow())

    async def select_movie(self, movie_id: int | None) -> None:
        """A manual override is scoped to the exact current player identity."""
        self.sync()
        if self.retired or content_identity(self.hass.states.get(self.player)) is None:
            raise ServiceValidationError(
                "Play or pause a titled movie before selecting a match"
            )
        self.generation += 1
        generation = self.generation
        self.override = movie_id
        self.movie = None
        self.previous = None
        self.phase = "matching"
        self.tick(dt_util.utcnow())
        await self._lookup(generation)
        self.sync()
        if not self.current(generation):
            raise ServiceValidationError(
                "Playback changed while selecting a movie; select again"
            )

    @callback
    def tick(self, now: datetime) -> None:
        if self.retired:
            return
        # Read identity even on local ticks to reject a response racing a bus callback.
        if self.effective_identity() != self.identity:
            self.sync()
            return
        state = self.hass.states.get(self.player)
        # Re-anchor changed player reports before the looser tick-gap check.
        if position_discontinuity(self.player_state, state, now):
            self.previous = None
        self.player_state = state
        active_player = bool(state and state.state in ("playing", "paused"))
        if (
            active_player
            and self.identity
            and self.phase == "error"
            and now.timestamp() >= self.retry_at
        ):
            self.retry_at = now.timestamp() + 60
            self._queue()
        if active_player and self.movie and now.timestamp() - self.fetched_at >= 86400:
            self.fetched_at = now.timestamp()
            self._queue()
        status = self.phase
        position = playback_position(state, now) if state and self.movie else None
        values: dict[str, Any] = {
            "next_window": None,
            "time_until_next_window": None,
            "current_window_remaining": None,
            "upcoming_windows": None,
            "window_active": None,
        }
        windows = (
            [
                item
                for item in self.movie.peetimes
                if not self.recommended_only or item.recommended
            ]
            if self.movie
            else []
        )
        if self.movie:
            if position is None:
                status = "position_unavailable"
                self.previous = None
            else:
                # Positive offset delays windows on the player's playback timeline.
                adjusted = position - self.offset
                active = next(
                    (
                        item
                        for item in windows
                        if item.offset_seconds
                        <= adjusted
                        < item.offset_seconds + item.duration_seconds
                    ),
                    None,
                )
                upcoming = [item for item in windows if item.offset_seconds > adjusted]
                next_window = upcoming[0] if upcoming else None
                values = {
                    "next_window": next_window.offset_seconds + self.offset
                    if next_window
                    else None,
                    "time_until_next_window": max(
                        0, math.ceil(next_window.offset_seconds - adjusted)
                    )
                    if next_window
                    else None,
                    "current_window_remaining": math.ceil(
                        active.offset_seconds + active.duration_seconds - adjusted
                    )
                    if active
                    else 0,
                    "upcoming_windows": len(upcoming),
                    "window_active": active is not None,
                }
                status = (
                    "paused"
                    if state and state.state == "paused"
                    else "in_window"
                    if active
                    else "ready"
                )
                if state and state.state == "playing":
                    self._crossing(now, adjusted, windows)
                else:
                    self.previous = None
        self.async_set_updated_data(
            {
                "status": status,
                "movie": self.movie.title if self.movie else None,
                **values,
            }
        )

    def _crossing(self, now: datetime, position: float, windows: list[Any]) -> None:
        previous = self.previous
        self.previous = (now, position)
        if previous is None:
            return
        elapsed = (now - previous[0]).total_seconds()
        advance = position - previous[1]
        if not 0 < elapsed <= 5 or advance < 0 or abs(advance - elapsed) > 2:
            return
        for item in windows:
            if (
                previous[1]
                < item.offset_seconds
                <= position
                < item.offset_seconds + item.duration_seconds
                and (self.movie_id, item.pee_id) not in self.fired
            ):
                self.fired.add((self.movie_id, item.pee_id))
                self.hass.bus.async_fire(
                    EVENT_BREAK,
                    {
                        "entry_id": self.config_entry.entry_id
                        if self.config_entry
                        else None,
                        "media_player": self.player,
                        "movie_id": self.movie_id,
                        "title": self.movie.title if self.movie else None,
                        **asdict(item),
                    },
                )

    def attributes(self) -> dict[str, Any]:
        state = self.hass.states.get(self.player)
        duration = state.attributes.get("media_duration") if state else None
        return {
            "media_player": self.player,
            "country": self.client.country,
            "candidates": self.candidates,
            "movie_override": self.override,
            "error": self.error,
            "timing_offset_seconds": self.offset,
            "metadata_warning": (
                "Exact title/year matching cannot identify edits or editions; "
                "verify timer cue and runtime."
            ),
            "runtime_mismatch": bool(
                self.movie
                and number(duration)
                and abs(duration - self.movie.run_time * 60) > 300
            ),
            **(self.movie.response() if self.movie else {}),
        }
