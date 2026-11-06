"""Content warnings must never become bathroom-break notifications."""

import pytest

from custom_components.runpee.models import InvalidData, parse_movie
from tests.test_ha import setup
from tests.test_playback import player, tick


def test_alerts_omitted_and_bad_flags_rejected(movie):
    movie["data"]["peetimes"][0]["is_alert"] = True
    parsed = parse_movie(movie["data"], 987)
    assert [item.pee_id for item in parsed.peetimes] == [2]
    movie["data"]["peetimes"][0]["is_alert"] = "true"
    with pytest.raises(InvalidData, match="alert"):
        parse_movie(movie["data"], 987)


async def test_alert_does_not_emit_break(hass, http, movie, freezer):
    movie["data"]["peetimes"][0]["is_alert"] = True
    entry = await setup(hass, http, movie)
    events = []
    hass.bus.async_listen("runpee_break", events.append)
    player(hass, position=7)
    for _ in range(3):
        await tick(hass, freezer)
    assert not events
    player(hass, position=97)
    for _ in range(3):
        await tick(hass, freezer)
    assert len(events) == 1
    assert events[0].data["pee_id"] == 2
    assert await hass.config_entries.async_unload(entry.entry_id)
