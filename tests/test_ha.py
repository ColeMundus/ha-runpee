"""Player-centric integration tested through the real HA lifecycle."""

from homeassistant.util import dt as dt_util

from tests.ha_compat import MockConfigEntry


def player(hass, title="Synthetic Movie", position=8, state="playing", **attrs):
    hass.states.async_set(
        "media_player.test",
        state,
        {
            "media_title": title,
            "media_position": position,
            "media_position_updated_at": dt_util.utcnow(),
            **attrs,
        },
    )


def search(*movies):
    return {"success": True, "data": {"movies": list(movies)}}


def candidate(movie_id=987, title="Synthetic Movie", year=2020):
    return {
        "movie_id": movie_id,
        "title": title,
        "run_time": 120,
        "release_date": f"{year}-01-01",
    }


async def setup(hass, http, movie, *, active=True, options=None):
    if active:
        player(hass)
        http.add(search(candidate()))
        http.add(movie)
    entry = MockConfigEntry(
        domain="runpee",
        version=2,
        title="Test",
        unique_id="media_player.test",
        data={"country": "US", "media_player": "media_player.test"},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


async def test_player_auto_setup(hass, http, movie):
    entry = await setup(hass, http, movie)
    assert hass.states.get("sensor.runpee_test_status").state == "ready"
    assert hass.states.get("sensor.runpee_test_movie").state == "Synthetic Movie"
    assert hass.states.get("sensor.runpee_test_time_until_next_window").state == "2"
    assert len(http.requests) == 2
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_flows_options_reconfigure_and_migration(hass, http, movie):
    import probatio
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import config_validation as cv

    form = await hass.config_entries.flow.async_init(
        "runpee", context={"source": "user"}
    )
    fields = probatio.to_field_list(
        form["data_schema"], custom_serializer=cv.custom_serializer
    )
    assert [f["name"] for f in fields] == ["media_player", "country"]
    invalid = await hass.config_entries.flow.async_configure(
        form["flow_id"], {"country": "USA", "media_player": "media_player.test"}
    )
    assert invalid["errors"] == {"base": "invalid_input"}
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {"country": " us ", "media_player": "media_player.test"}
    )
    entry = result["result"]
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == 2 and "movie_id" not in entry.data
    duplicate = await hass.config_entries.flow.async_init(
        "runpee", context={"source": "user"}, data=dict(entry.data)
    )
    assert duplicate["reason"] == "already_configured"
    options = await hass.config_entries.options.async_init(entry.entry_id)
    options = await hass.config_entries.options.async_configure(
        options["flow_id"], {"timing_offset_seconds": 1.5}
    )
    assert options["errors"] == {"base": "invalid_input"}
    options = await hass.config_entries.options.async_configure(
        options["flow_id"],
        {"timing_offset_seconds": 5, "recommended_windows_only": True},
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.offset == 5
    reconfig = await hass.config_entries.flow.async_init(
        "runpee", context={"source": "reconfigure", "entry_id": entry.entry_id}
    )
    reconfig = await hass.config_entries.flow.async_configure(
        reconfig["flow_id"], {"country": "USA", "media_player": "media_player.test"}
    )
    assert reconfig["errors"]
    reconfig = await hass.config_entries.flow.async_configure(
        reconfig["flow_id"], {"country": "CA", "media_player": "media_player.other"}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert reconfig["reason"] == "reconfigure_successful"
    assert entry.unique_id == "media_player.other"
    assert entry.runtime_data.client.country == "CA"
    await hass.config_entries.async_unload(entry.entry_id)
    legacy = MockConfigEntry(
        domain="runpee",
        version=1,
        data={"country": "US", "movie_id": 987, "media_player": "media_player.legacy"},
    )
    legacy.add_to_hass(hass)
    assert await hass.config_entries.async_setup(legacy.entry_id)
    assert legacy.version == 2 and "movie_id" not in legacy.data
    await hass.config_entries.async_unload(legacy.entry_id)
    old = MockConfigEntry(
        domain="runpee", version=1, data={"country": "US", "movie_id": 987}
    )
    old.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(old.entry_id)
    assert old.data["movie_id"] == 987
    reconfig = await hass.config_entries.flow.async_init(
        "runpee", context={"source": "reconfigure", "entry_id": old.entry_id}
    )
    await hass.config_entries.flow.async_configure(
        reconfig["flow_id"], {"country": "US", "media_player": "media_player.recovered"}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert old.state is ConfigEntryState.LOADED
    assert "movie_id" not in old.data
    await hass.config_entries.async_unload(old.entry_id)


async def test_response_actions_override_and_reload(hass, http, movie):
    from unittest.mock import AsyncMock, patch

    import pytest
    from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

    entry = await setup(hass, http, movie)

    async def action(service, **values):
        return await hass.services.async_call(
            "runpee",
            service,
            {"entry_id": entry.entry_id, **values},
            blocking=True,
            return_response=service in ("search_movies", "get_peetimes"),
        )

    assert (await action("get_peetimes"))["title"] == "Synthetic Movie"
    assert (await action("search_movies", query="Synthetic Movie"))["movies"][0][
        "year"
    ] == 2020
    for service, values in [
        ("search_movies", {"query": " "}),
        ("search_movies", {"query": "x" * 129}),
        ("get_peetimes", {"movie_id": 0}),
        ("get_peetimes", {"entry_id": "missing"}),
    ]:
        with pytest.raises(ServiceValidationError):
            await action(service, **values)
    http.add(
        {
            **movie,
            "data": {
                **movie["data"],
                "movie_id": 42,
                "title": "Manual arbitrary title",
            },
        }
    )
    await action("select_movie", movie_id=42)
    assert entry.runtime_data.movie_id == 42 and entry.runtime_data.override == 42
    await action("clear_movie_override")
    assert entry.runtime_data.movie_id == 987 and entry.runtime_data.override is None
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(http.requests) == 3
    http.add(status=503)
    with pytest.raises(HomeAssistantError):
        await action("get_peetimes", movie_id=43)
    player(hass, state="idle")
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError):
        await action("select_movie", movie_id=42)
    with pytest.raises(ServiceValidationError):
        await action("get_peetimes")
    with patch.object(
        hass.config_entries, "async_unload_platforms", AsyncMock(return_value=False)
    ):
        from custom_components.runpee import async_unload_entry

        assert not await async_unload_entry(hass, entry)
    await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service("runpee", "get_peetimes")


async def test_override_race_and_retirement(hass, http, movie):
    import asyncio

    import pytest
    from homeassistant.exceptions import ServiceValidationError

    entry = await setup(hass, http, movie)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow():
        entered.set()
        await release.wait()
        return {
            **movie,
            "data": {**movie["data"], "movie_id": 42, "title": "Old override"},
        }

    http.add(slow)
    task = asyncio.create_task(
        hass.services.async_call(
            "runpee",
            "select_movie",
            {"entry_id": entry.entry_id, "movie_id": 42},
            blocking=True,
        )
    )
    await entered.wait()
    http.add(search(candidate(43, "New")))
    http.add({**movie, "data": {**movie["data"], "movie_id": 43, "title": "New"}})
    player(hass, title="New")
    await hass.async_block_till_done()
    release.set()
    with pytest.raises(ServiceValidationError):
        await task
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.movie_id == 43
    assert entry.runtime_data.override is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_provider_error_retry_daily_and_unload_pacing(hass, http, movie, freezer):
    from tests.test_playback import tick, value

    entry = await setup(hass, http, movie, active=False)
    http.add(status=503)
    player(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass) == "error"
    assert len(http.requests) == 1
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert value(hass) == "error" and len(http.requests) == 1
    http.add(search(candidate()))
    http.add(movie)
    await tick(hass, freezer, 61)
    assert value(hass) == "in_window"
    assert len(http.requests) == 3
    http.add(search(candidate()))
    http.add(movie)
    await tick(hass, freezer, 86401)
    assert len(http.requests) == 5
    await hass.config_entries.async_unload(entry.entry_id)
    await tick(hass, freezer, 86401)
    assert len(http.requests) == 5


async def test_reconfigure_same_player_country(hass, http, movie):
    entry = await setup(hass, http, movie, active=False)
    flow = await hass.config_entries.flow.async_init(
        "runpee", context={"source": "reconfigure", "entry_id": entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"country": "CA", "media_player": "media_player.test"}
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.client.country == "CA"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_cannot_override_transport_unavailable(hass, http, movie):
    import pytest
    from homeassistant.exceptions import ServiceValidationError

    entry = await setup(hass, http, movie)
    hass.states.async_set("media_player.test", "unavailable")
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "runpee",
            "select_movie",
            {"entry_id": entry.entry_id, "movie_id": 987},
            blocking=True,
        )
    await hass.config_entries.async_unload(entry.entry_id)
