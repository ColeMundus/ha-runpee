"""Real HA harness and loopback-only synthetic HTTP provider."""

from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_socket
from aiohttp import web

import custom_components

# Extend the harness test package with this checkout for normal HA discovery.
custom_components.__path__.append(
    str(Path(__file__).resolve().parents[1] / "custom_components")
)


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield


@pytest.hookimpl(trylast=True)
def pytest_runtest_setup():
    pytest_socket.socket_allow_hosts(["127.0.0.1"], allow_unix_socket=True)


@pytest.fixture
async def http(aiohttp_server, socket_enabled):
    pytest_socket.socket_allow_hosts(["127.0.0.1"], allow_unix_socket=True)
    replies = deque()
    requests = []

    async def handler(request):
        requests.append((request.path, dict(request.query)))
        payload, status, headers = replies.popleft()
        if callable(payload):
            payload = await payload()
        if isinstance(payload, web.StreamResponse):
            return payload
        return web.json_response(payload, status=status, headers=headers)

    app = web.Application()
    app.router.add_get("/api/{tail:.*}", handler)
    server = await aiohttp_server(app, host="127.0.0.1", access_log=None)

    def add(payload=None, status=200, headers=None):
        replies.append((payload, status, headers))

    with patch("custom_components.runpee.client.BASE", str(server.make_url("/api"))):
        yield SimpleNamespace(add=add, requests=requests, replies=replies)


@pytest.fixture
def movie():
    return {
        "success": True,
        "data": {
            "movie_id": 987,
            "title": "Synthetic Movie",
            "run_time": 120,
            "timer_cue": "Start at the synthetic logo",
            "peetimes": [
                {
                    "pee_id": 1,
                    "pt_start": 10,
                    "len": 60,
                    "cue": "A synthetic cue",
                    "is_recommended": True,
                    "synopsis": "PRIVATE_PLOT_CANARY",
                },
                {
                    "pee_id": 2,
                    "pt_start": 100,
                    "len": 90,
                    "cue": "Second cue",
                    "is_recommended": False,
                },
            ],
            "credits_length": 300,
            "has_extras": False,
        },
    }
