"""Synthetic provider schema, pacing, privacy, and transport failures."""

import asyncio
import copy
import logging
from datetime import timedelta

import pytest
from aiohttp import web
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from custom_components.runpee.client import (
    ProviderError,
    RateLimited,
    RequestGate,
    RunPeeClient,
)
from custom_components.runpee.models import (
    InvalidData,
    integer,
    parse_movie,
    parse_search,
    text,
)


@pytest.fixture
async def client(hass):
    return RunPeeClient(async_get_clientsession(hass), RequestGate(), "US")


async def test_coalesce_cache_expiry_and_search(client, http, movie, freezer):
    http.add(movie)
    results = await asyncio.gather(*(client.get_peetimes(987) for _ in range(4)))
    assert all(result == results[0] for result in results)
    assert len(http.requests) == 1
    assert http.requests[0][1] == {"movie_id": "987", "country": "US", "lang": "EN"}
    http.add({"success": True, "data": {"movies": []}})
    assert await client.search_movies("Synthetic") == []
    assert await client.search_movies("Synthetic") == []
    freezer.tick(timedelta(seconds=301))
    http.add({"success": True, "data": {"movies": []}})
    await client.search_movies("Synthetic")
    assert len(http.requests) == 3
    freezer.tick(timedelta(days=1))
    http.add(movie)
    await client.get_peetimes(987)
    assert len(http.requests) == 4


@pytest.mark.parametrize("header", ["600", "bad", "1e999", "nan", "-1"])
async def test_429_shared_bounded_cooldown(client, http, movie, freezer, header):
    http.add(status=429, headers={"Retry-After": header})
    with pytest.raises(RateLimited):
        await client.get_peetimes(987)
    with pytest.raises(RateLimited):
        await client.search_movies("Other")
    assert len(http.requests) == 1
    freezer.tick(timedelta(days=1, seconds=1))
    http.add(movie)
    assert (await client.get_peetimes(987)).title == "Synthetic Movie"


@pytest.mark.parametrize(
    "reply",
    [
        {"success": False},
        [],
        {"success": True, "data": None},
        web.Response(text="not-json PRIVATE_PLOT_CANARY", content_type="text/plain"),
        web.Response(body=b"x" * (1024 * 1024 + 1)),
        web.Response(
            status=302,
            headers={"Location": "https://example.invalid/PRIVATE_PLOT_CANARY"},
        ),
    ],
)
async def test_errors_sanitized_and_no_immediate_retry(client, http, reply, caplog):
    caplog.set_level(logging.DEBUG)
    http.add(reply)
    with pytest.raises(ProviderError) as raised:
        await client.get_peetimes(987)
    assert "PRIVATE_PLOT_CANARY" not in str(raised.value)
    assert raised.value.__suppress_context__ or raised.value.__context__ is None
    with pytest.raises(ProviderError):
        await client.get_peetimes(987)
    assert len(http.requests) == 1
    assert "PRIVATE_PLOT_CANARY" not in caplog.text


@pytest.mark.parametrize(
    "changes",
    [
        {"movie_id": 1},
        {"movie_id": True},
        {"title": None},
        {"title": "x" * 256},
        {"peetimes": None},
        {"peetimes": [None]},
        {"peetimes": [{}]},
        {"peetimes": [], "has_extras": "yes"},
        {"peetimes": [{"pee_id": 1, "pt_start": -1, "len": 30, "cue": "x"}]},
        {"peetimes": [{"pee_id": 1, "pt_start": 1, "len": 0, "cue": "x"}]},
        {
            "peetimes": [
                {"pee_id": 1, "pt_start": 1, "len": 30, "cue": "x", "is_recommended": 1}
            ]
        },
        {"peetimes": [{}] * 101},
        {"run_time": 0},
    ],
)
def test_malformed_movies(movie, changes):
    data = copy.deepcopy(movie["data"])
    data.update(changes)
    with pytest.raises(InvalidData):
        parse_movie(data, 987)


def test_models_optional_and_helpers(movie):
    data = movie["data"]
    data.pop("credits_length")
    data.pop("has_extras")
    parsed = parse_movie(data, 987)
    assert parsed.credits_length is None
    assert parsed.has_extras is None
    assert "PRIVATE_PLOT_CANARY" not in str(parsed.response())
    for value in [True, None, -1, 86401, 1.5]:
        with pytest.raises(InvalidData):
            integer(value)
    with pytest.raises(InvalidData):
        text(1)
    for data in [None, {}, {"movies": None}, {"movies": [{}]}, {"movies": [{}] * 501}]:
        with pytest.raises(InvalidData):
            parse_search(data)


async def test_bounded_cache(client, http, movie, freezer):
    for index in range(128):
        http.add(movie)
        await client._get(
            "peetimes.php",
            {"movie_id": "987", "country": "US", "cache_test": str(index)},
        )
    assert len(client.gate.cache) == 128
    with pytest.raises(ProviderError, match="capacity"):
        await client.search_movies("full")
    freezer.tick(timedelta(days=1, seconds=1))
    http.add({"success": True, "data": {"movies": []}})
    await client.search_movies("last")
    assert len(client.gate.cache) == 1
    now = dt_util.utcnow().timestamp()
    client.gate.retry_at.update({str(index): now + 60 for index in range(256)})
    with pytest.raises(ProviderError, match="capacity"):
        await client.search_movies("over capacity")


def test_search_release_dates():
    result = parse_search(
        {
            "movies": [
                {
                    "movie_id": 1,
                    "title": "One",
                    "run_time": 120,
                    "release_date": "2020-03-01",
                    "effective_release_date": "2021-01-01",
                    "synopsis": "NEVER",
                }
            ]
        }
    )
    assert result == [
        {
            "movie_id": 1,
            "title": "One",
            "run_time": 120,
            "release_date": "2020-03-01",
            "year": 2020,
        }
    ]
    assert (
        "year"
        not in parse_search(
            {"movies": [{"movie_id": 1, "title": "One", "run_time": 120}]}
        )[0]
    )
    with pytest.raises(InvalidData):
        parse_search(
            {
                "movies": [
                    {
                        "movie_id": 1,
                        "title": "One",
                        "run_time": 120,
                        "release_date": "bad",
                    }
                ]
            }
        )


def test_external_socket_is_blocked_even_with_http_fixture(http):
    import socket

    import pytest_socket

    with socket.socket() as connection:
        with (
            pytest.warns(UserWarning, match="203.0.113.1"),
            pytest.raises(pytest_socket.SocketConnectBlockedError),
        ):
            connection.connect(("203.0.113.1", 443))
