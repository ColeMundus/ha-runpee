"""Pacing regressions exercise actual HA sessions against synthetic HTTP."""

from datetime import timedelta

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.runpee.client import ProviderError, RequestGate, RunPeeClient


async def test_repeated_failures_back_off_without_inline_retries(
    hass, http, freezer, movie
):
    client = RunPeeClient(async_get_clientsession(hass), RequestGate(), "US")
    for attempt in range(2):
        http.add(status=503)
        with pytest.raises(ProviderError):
            await client.get_peetimes(987)
        assert len(http.requests) == attempt + 1
        freezer.tick(timedelta(seconds=61))
    # The second failure backs off for 120 seconds, not another 60 seconds.
    with pytest.raises(ProviderError, match="cooldown"):
        await client.get_peetimes(987)
    assert len(http.requests) == 2
    freezer.tick(timedelta(seconds=60))
    http.add(movie)
    assert (await client.get_peetimes(987)).movie_id == 987
    assert len(http.requests) == 3
