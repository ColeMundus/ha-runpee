"""Entry routing and stale detail publications use real HTTP and HA services."""

import asyncio

import pytest
from aiohttp import web

from tests.ha_compat import MockConfigEntry
from tests.test_ha import candidate, player, search, setup
from tests.test_playback import value


async def test_two_entry_service_routing_and_unload(hass, http, movie):
    first = await setup(hass, http, movie, active=False)
    second = MockConfigEntry(
        domain="runpee",
        version=2,
        data={"country": "CA", "media_player": "media_player.other"},
    )
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    http.add(search(candidate()))
    response = await hass.services.async_call(
        "runpee",
        "search_movies",
        {"entry_id": second.entry_id, "query": "Synthetic Movie"},
        blocking=True,
        return_response=True,
    )
    assert response["movies"][0]["year"] == 2020
    assert http.requests[-1][1]["country"] == "CA"
    http.add(movie)
    response = await hass.services.async_call(
        "runpee",
        "get_peetimes",
        {"entry_id": first.entry_id, "movie_id": 987},
        blocking=True,
        return_response=True,
    )
    assert response["movie_id"] == 987
    assert http.requests[-1][1]["country"] == "US"
    assert await hass.config_entries.async_unload(first.entry_id)
    assert hass.services.has_service("runpee", "search_movies")
    assert await hass.config_entries.async_unload(second.entry_id)
    assert not hass.services.has_service("runpee", "search_movies")


@pytest.mark.parametrize("failure", [False, True])
async def test_detail_response_cannot_publish_for_old_content(
    hass, http, movie, failure
):
    entry = await setup(hass, http, movie, active=False)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow():
        entered.set()
        await release.wait()
        return web.Response(status=503) if failure else movie

    http.add(search(candidate()))
    http.add(slow)
    player(hass)
    await entered.wait()
    http.add(search(candidate(42, "New movie")))
    http.add({**movie, "data": {**movie["data"], "movie_id": 42, "title": "New movie"}})
    player(hass, title="New movie")
    await hass.async_block_till_done()
    assert value(hass) == "matching"
    assert value(hass, "movie") == "unavailable"
    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass, "movie") == "New movie"
    assert entry.runtime_data.error is None
    assert len(http.requests) == 4
    await hass.config_entries.async_unload(entry.entry_id)


async def test_burst_content_updates_coalesce(hass, http, movie):
    entry = await setup(hass, http, movie, active=False)
    http.add(search(candidate()))
    http.add(movie)
    player(hass, title="Transient A")
    player(hass, title="Transient B")
    player(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(http.requests) == 2
    assert http.requests[0][1]["q"] == "Synthetic Movie"
    await hass.config_entries.async_unload(entry.entry_id)
