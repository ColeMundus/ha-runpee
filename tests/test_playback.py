"""Local playback timing, matching and lifecycle regressions."""

import asyncio
from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_util

from tests.ha_compat import async_fire_time_changed
from tests.test_ha import candidate, player, search, setup


def value(hass, key="status", domain="sensor"):
    return hass.states.get(
        f"{domain}.runpee_test_{'pee_window_active' if key == 'window_active' else key}"
    ).state


async def tick(hass, freezer, seconds=1):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_timing_crossing_pause_seek_and_session(hass, http, movie, freezer):
    entry = await setup(hass, http, movie)
    events = []
    hass.bus.async_listen("runpee_break", events.append)
    await tick(hass, freezer)
    await tick(hass, freezer)
    assert value(hass) == "in_window"
    assert value(hass, "current_window_remaining") == "60"
    assert value(hass, "upcoming_windows") == "1"
    assert value(hass, "window_active", "binary_sensor") == "on"
    assert len(events) == 1
    player(hass, position=10, state="paused")
    await tick(hass, freezer, 5)
    assert value(hass) == "paused"
    assert value(hass, "current_window_remaining") == "60"
    player(hass, position=9)
    await tick(hass, freezer)
    assert len(events) == 1
    player(hass, position=101)
    await tick(hass, freezer)
    assert len(events) == 1
    player(hass, position=200)
    await tick(hass, freezer)
    assert value(hass, "upcoming_windows") == "0"
    assert value(hass, "next_window") == "unavailable"
    assert value(hass, "current_window_remaining") == "0"
    player(hass, state="idle", title=None)
    await tick(hass, freezer)
    assert value(hass) == "idle"
    player(hass, position=8)
    await hass.async_block_till_done(wait_background_tasks=True)
    await tick(hass, freezer)
    await tick(hass, freezer)
    assert len(events) == 2
    assert len(http.requests) == 2
    assert await hass.config_entries.async_unload(entry.entry_id)
    await tick(hass, freezer)
    assert value(hass) == "unavailable"


async def test_small_explicit_seek_reanchors_before_crossing(
    hass, http, movie, freezer
):
    entry = await setup(hass, http, movie)
    events = []
    hass.bus.async_listen("runpee_break", events.append)
    await tick(hass, freezer)
    assert entry.runtime_data.previous[1] == 9
    freezer.tick(0.1)
    player(hass, position=10.5)
    await hass.async_block_till_done()
    assert value(hass) == "in_window"
    assert not events
    assert not entry.runtime_data.fired
    await tick(hass, freezer)
    assert not events
    # Seeking did not consume the event; genuine later progress still fires.
    player(hass, position=8)
    await hass.async_block_till_done()
    await tick(hass, freezer, 2)
    assert len(events) == 1
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("rounding", [0, -0.5, 0.5])
async def test_refreshed_position_preserves_normal_crossing(
    hass, http, movie, freezer, rounding
):
    entry = await setup(hass, http, movie)
    events = []
    hass.bus.async_listen("runpee_break", events.append)
    await tick(hass, freezer)
    freezer.tick(1.5)
    player(hass, position=10.5 + rounding)
    await hass.async_block_till_done()
    assert value(hass) == "in_window"
    assert len(events) == 1
    await tick(hass, freezer)
    assert len(events) == 1
    await hass.config_entries.async_unload(entry.entry_id)


async def test_resume_at_window_does_not_fire(hass, http, movie, freezer):
    entry = await setup(hass, http, movie)
    events = []
    hass.bus.async_listen("runpee_break", events.append)
    await tick(hass, freezer)
    player(hass, position=9, state="paused")
    await hass.async_block_till_done()
    await tick(hass, freezer, 5)
    assert value(hass) == "paused"
    assert value(hass, "time_until_next_window") == "1"
    player(hass, position=10)
    await hass.async_block_till_done()
    await tick(hass, freezer)
    assert value(hass) == "in_window"
    assert not events
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "attrs",
    [
        {"media_position": None},
        {"media_position": True},
        {"media_position": -1},
        {"media_position": float("nan")},
        {"media_position_updated_at": None},
        {"media_position_updated_at": "bad"},
        {"media_position_updated_at": "2026-01-01"},
        {"media_speed": 1.5},
    ],
)
async def test_position_unavailable(hass, http, movie, attrs):
    entry = await setup(hass, http, movie)
    player(hass, **attrs)
    await hass.async_block_till_done()
    assert value(hass) == "position_unavailable"
    assert value(hass, "time_until_next_window") == "unavailable"
    assert value(hass, "current_window_remaining") == "unavailable"
    assert value(hass, "upcoming_windows") == "unavailable"
    assert value(hass, "movie") == "Synthetic Movie"
    assert len(http.requests) == 2
    await hass.config_entries.async_unload(entry.entry_id)


async def test_offset_recommended_runtime_warning(hass, http, movie, freezer):
    entry = await setup(
        hass,
        http,
        movie,
        options={"timing_offset_seconds": 5, "recommended_windows_only": True},
    )
    assert value(hass, "next_window") == "15"
    assert value(hass, "time_until_next_window") == "7"
    assert value(hass, "upcoming_windows") == "1"
    player(hass, position=15, media_duration=9000)
    await tick(hass, freezer)
    assert value(hass) == "in_window"
    assert value(hass, "upcoming_windows") == "0"
    assert hass.states.get("sensor.runpee_test_movie").attributes["runtime_mismatch"]
    assert "PRIVATE_PLOT_CANARY" not in str(hass.states.async_all())
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("kind", ["episode", "tvshow", "music"])
async def test_explicit_non_movie_is_idle(hass, http, movie, kind):
    entry = await setup(hass, http, movie, active=False)
    player(hass, media_content_type=kind)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass) == "idle"
    assert not http.requests
    await hass.config_entries.async_unload(entry.entry_id)


async def test_ambiguous_year_no_match_and_paused_content(hass, http, movie):
    entry = await setup(hass, http, movie, active=False)
    http.add(search(candidate(year=2020), candidate(42, year=1980)))
    player(hass, state="paused")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass) == "ambiguous"
    attrs = hass.states.get("sensor.runpee_test_status").attributes
    assert len(attrs["candidates"]) == 2
    assert attrs["candidates"][0]["year"] == 2020
    http.add(movie)
    player(hass, state="paused", media_year=2020)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass) == "paused"
    player(hass, media_year=1999)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass) == "no_match"
    assert value(hass, "movie") == "unavailable"
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("ambiguous", [False, True], ids=["no_match", "ambiguous"])
async def test_daily_refresh_loses_match(hass, http, movie, freezer, ambiguous):
    entry = await setup(hass, http, movie)
    coordinator = entry.runtime_data
    events = []
    hass.bus.async_listen("runpee_break", events.append)
    await tick(hass, freezer)
    assert coordinator.previous is not None
    candidates = [candidate(), candidate(42, year=1980)] if ambiguous else []
    http.add(search(*candidates))
    await tick(hass, freezer, 86401)
    expected = "ambiguous" if ambiguous else "no_match"
    assert value(hass) == expected
    assert coordinator.movie is None
    assert coordinator.previous is None
    assert value(hass, "movie") == "unavailable"
    assert "movie_id" not in coordinator.attributes()
    assert len(coordinator.candidates) == len(candidates)
    for key in (
        "next_window",
        "time_until_next_window",
        "current_window_remaining",
        "upcoming_windows",
    ):
        assert value(hass, key) == "unavailable"
    assert value(hass, "window_active", "binary_sensor") == "unavailable"
    player(hass, position=8)
    await hass.async_block_till_done()
    await tick(hass, freezer, 2)
    assert value(hass) == expected
    assert not events
    assert len(http.requests) == 3
    await hass.config_entries.async_unload(entry.entry_id)


async def test_slow_a_to_b_discards_old_and_coalesces(hass, http, movie):
    entry = await setup(hass, http, movie, active=False)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow():
        entered.set()
        await release.wait()
        return search(candidate())

    http.add(slow)
    player(hass)
    await entered.wait()
    http.add(search(candidate(42, "B")))
    http.add({**movie, "data": {**movie["data"], "movie_id": 42, "title": "B"}})
    player(hass, title="B", media_content_id="B")
    await hass.async_block_till_done()
    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass, "movie") == "B"
    assert [q.get("movie_id") for _, q in http.requests] == [None, None, "42"]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_unknown_does_not_rearm_break(hass, http, movie, freezer):
    entry = await setup(hass, http, movie)
    events = []
    hass.bus.async_listen("runpee_break", events.append)
    await tick(hass, freezer, 2)
    assert len(events) == 1
    hass.states.async_set("media_player.test", "unavailable")
    await tick(hass, freezer)
    player(hass, position=8)
    await hass.async_block_till_done(wait_background_tasks=True)
    await tick(hass, freezer, 2)
    assert len(events) == 1
    await hass.services.async_call(
        "runpee",
        "select_movie",
        {"entry_id": entry.entry_id, "movie_id": 987},
        blocking=True,
    )
    player(hass, position=8)
    await hass.async_block_till_done(wait_background_tasks=True)
    await tick(hass, freezer, 2)
    assert len(events) == 1
    await hass.config_entries.async_unload(entry.entry_id)
