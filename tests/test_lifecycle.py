"""Retirement and metadata edge cases through actual HA state/services."""

import asyncio
from datetime import timedelta

from homeassistant.util import dt as dt_util

from tests.test_ha import candidate, player, search, setup
from tests.test_playback import tick, value


async def test_normalized_title_year_and_empty_results(hass, http, movie):
    entry = await setup(hass, http, movie, active=False)
    http.add(search(candidate(title="SYNTHETIC—Movie")))
    http.add(movie)
    player(hass, title="Synthetic Movie", media_year=2020)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass, "movie") == "Synthetic Movie"
    http.add(search())
    player(hass, title="Unlisted")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass) == "no_match"
    assert hass.states.get("sensor.runpee_test_status").attributes["error"] is None
    assert value(hass, "upcoming_windows") == "unavailable"
    player(hass, title=None)
    await hass.async_block_till_done()
    assert value(hass) == "idle"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_attach_future_timestamp_and_pause_resume_no_event(
    hass, http, movie, freezer
):
    entry = await setup(hass, http, movie)
    events = []
    hass.bus.async_listen("runpee_break", events.append)
    player(hass, position=11, media_position_updated_at=dt_util.utcnow().isoformat())
    await tick(hass, freezer)
    assert not events
    player(
        hass,
        position=8,
        media_position_updated_at=dt_util.utcnow() + timedelta(seconds=10),
    )
    await tick(hass, freezer)
    assert value(hass) == "position_unavailable"
    player(hass, position=9, state="paused", media_position_updated_at=None)
    await tick(hass, freezer, 2)
    assert value(hass) == "paused"
    assert value(hass, "time_until_next_window") == "1"
    player(hass, position=11)
    await tick(hass, freezer)
    assert not events
    retired = entry.runtime_data
    await hass.config_entries.async_unload(entry.entry_id)
    retired.sync()
    retired.tick(dt_util.utcnow())


async def test_unload_inflight_lookup_reserves_pacing(hass, http, movie, freezer):
    entry = await setup(hass, http, movie, active=False)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow():
        entered.set()
        await release.wait()
        return search(candidate())

    http.add(slow)
    player(hass)
    await entered.wait()
    retired = entry.runtime_data
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert retired.retired
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass) == "error"
    assert len(http.requests) == 1
    release.set()
    http.add(search(candidate()))
    http.add(movie)
    await tick(hass, freezer, 61)
    assert entry.runtime_data.movie_id == 987
    assert retired.movie is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_native_manual_refresh_is_local(hass, http, movie):
    entry = await setup(hass, http, movie)
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.last_update_success
    assert len(http.requests) == 2
    await hass.config_entries.async_unload(entry.entry_id)


async def test_no_retry_cloud_reads_while_player_unavailable(
    hass, http, movie, freezer
):
    entry = await setup(hass, http, movie, active=False)
    http.add(status=503)
    player(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    hass.states.async_set("media_player.test", "unavailable")
    await tick(hass, freezer, 61)
    assert len(http.requests) == 1
    http.add(search(candidate()))
    http.add(movie)
    player(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.movie_id == 987
    await hass.config_entries.async_unload(entry.entry_id)
