"""Plex Cast-shaped synthetic metadata through the real HA matching pipeline."""

import pytest
from homeassistant.core import State
from homeassistant.util import dt as dt_util

from custom_components.runpee.playback import content_identity
from tests.test_ha import candidate, search, setup
from tests.test_playback import value


@pytest.fixture
def cast_attrs():
    """Use observed attribute shape, not personal playback/provider records."""
    return {
        "app_id": "9AC194DC",
        "app_name": "Plex",
        "media_content_id": "/library/metadata/12345",
        "media_content_type": "tvshow",
        "media_duration": 7200,
        "media_position": 0,
        "media_position_updated_at": dt_util.utcnow(),
        "media_title": "Synthetic Movie",
    }


async def test_plex_cast_movie_matches_through_ha(hass, http, movie, cast_attrs):
    entry = await setup(hass, http, movie, active=False)
    http.add(search(candidate()))
    http.add(movie)
    hass.states.async_set("media_player.test", "playing", cast_attrs)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass) == "ready"
    assert value(hass, "movie") == "Synthetic Movie"
    assert value(hass, "time_until_next_window") == "10"
    assert http.requests == [
        (
            "/api/movies.php",
            {"action": "search", "q": "Synthetic Movie", "country": "US"},
        ),
        ("/api/peetimes.php", {"movie_id": "987", "country": "US", "lang": "EN"}),
    ]
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("state", ["playing", "paused"])
@pytest.mark.parametrize(
    "empty",
    [{}, {"media_series_title": "", "media_season": None, "media_episode": None}],
)
def test_plex_cast_content_identity(cast_attrs, state, empty):
    cast_attrs.update(empty)
    cast_attrs["media_year"] = 2020
    assert content_identity(State("media_player.test", state, cast_attrs)) == (
        "/library/metadata/12345",
        "Synthetic Movie",
        "2020",
    )


EXCLUDED_METADATA = [
    {"media_series_title": "Synthetic Series"},
    {"media_season": 1},
    {"media_season": 0},
    {"media_episode": 1},
    {"media_episode": 0},
    {"media_content_type": "episode"},
    {"media_content_type": "tv_show"},
    {"media_content_type": "music"},
    {"media_content_type": "track"},
    {"media_content_type": "channel"},
    {"media_content_type": "playlist"},
    {"app_id": None},
    {"app_id": "OTHER"},
    {"app_name": None},
    {"app_name": "Other"},
]


@pytest.mark.parametrize("metadata", EXCLUDED_METADATA)
def test_plex_cast_does_not_relax_non_movie_exclusion(cast_attrs, metadata):
    cast_attrs.update(metadata)
    assert content_identity(State("media_player.test", "playing", cast_attrs)) is None


@pytest.mark.parametrize("metadata", EXCLUDED_METADATA)
async def test_excluded_cast_metadata_never_searches(
    hass, http, movie, cast_attrs, metadata
):
    entry = await setup(hass, http, movie, active=False)
    hass.states.async_set("media_player.test", "playing", {**cast_attrs, **metadata})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass) == "idle"
    assert not http.requests
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("year", "candidates", "expected", "selected"),
    [
        (None, [candidate(), candidate(42, year=1980)], "ambiguous", None),
        (None, [candidate(title="Synthetic Movie Extended")], "no_match", None),
        (1999, [candidate()], "no_match", None),
        (2020, [candidate(), candidate(42, year=1980)], "paused", 987),
    ],
)
async def test_cast_fallback_keeps_exact_unique_year_matching(
    hass, http, movie, cast_attrs, year, candidates, expected, selected
):
    entry = await setup(hass, http, movie, active=False)
    if year is not None:
        cast_attrs["media_year"] = year
    http.add(search(*candidates))
    if selected is not None:
        http.add(movie)
    hass.states.async_set("media_player.test", "paused", cast_attrs)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass) == expected
    assert len(http.requests) == (2 if selected is not None else 1)
    if selected is None:
        assert value(hass, "movie") == "unavailable"
        assert entry.runtime_data.movie is None
    else:
        assert http.requests[1][1]["movie_id"] == str(selected)
        assert value(hass, "movie") == "Synthetic Movie"
    assert await hass.config_entries.async_unload(entry.entry_id)


def test_plex_cast_without_year_content_identity(cast_attrs):
    assert content_identity(State("media_player.test", "playing", cast_attrs)) == (
        "/library/metadata/12345",
        "Synthetic Movie",
        "",
    )
