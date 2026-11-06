"""Read-only public web-client transport; no application keys or credentials."""

import asyncio
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, cast

from aiohttp import ClientError, ClientSession, ClientTimeout
from homeassistant.util import dt as dt_util

from .models import InvalidData, Movie, parse_movie, parse_search

BASE = "https://runpee.net/app/api/v1"
DAY = 86400
MAX_BODY = 1024 * 1024


class ProviderError(Exception):
    """Sanitized provider failure."""


class RateLimited(ProviderError):
    """The shared provider cooldown is active."""


@dataclass
class RequestGate:
    """HA-lifetime cache and pacing survive entry unload/reload."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    cache: OrderedDict[str, tuple[float, Any]] = field(default_factory=OrderedDict)
    retry_at: dict[str, float] = field(default_factory=dict)
    failure_delay: dict[str, int] = field(default_factory=dict)
    blocked_until: float = 0


class RunPeeClient:
    def __init__(self, session: ClientSession, gate: RequestGate, country: str) -> None:
        self.session = session
        self.gate = gate
        self.country = country

    async def _get(
        self, path: str, params: dict[str, str], *, search: bool = False
    ) -> Any:
        key = path + repr(sorted(params.items()))
        async with self.gate.lock:
            now = dt_util.utcnow().timestamp()
            cached = self.gate.cache.get(key)
            if cached and now < cached[0]:
                return cached[1]
            if now < self.gate.blocked_until:
                raise RateLimited("Provider cooldown active")
            if now < self.gate.retry_at.get(key, 0):
                raise ProviderError("Request cooldown active")
            # Never evict a fresh response: eviction must not bypass daily pacing.
            self.gate.cache = OrderedDict(
                (item_key, value)
                for item_key, value in self.gate.cache.items()
                if value[0] > now
            )
            self.gate.retry_at = {
                item_key: deadline
                for item_key, deadline in self.gate.retry_at.items()
                if deadline > now - DAY
            }
            self.gate.failure_delay = {
                item_key: delay
                for item_key, delay in self.gate.failure_delay.items()
                if item_key in self.gate.retry_at
            }
            if len(self.gate.cache) >= 128 or (
                key not in self.gate.retry_at and len(self.gate.retry_at) >= 256
            ):
                raise ProviderError("Local request capacity reached; try again later")
            # Reserve before I/O so a failed request cannot create a retry storm.
            backoff_delay = min(self.gate.failure_delay.get(key, 30) * 2, 3600)
            self.gate.failure_delay[key] = backoff_delay
            self.gate.retry_at[key] = now + backoff_delay
            try:
                async with (
                    asyncio.timeout(20),
                    self.session.get(
                        f"{BASE}/{path}",
                        params=params,
                        timeout=ClientTimeout(total=15),
                        allow_redirects=False,
                    ) as response,
                ):
                    if response.status == 429:
                        try:
                            delay = float(response.headers.get("Retry-After", "3600"))
                            delay = min(max(delay, 60), DAY) if delay == delay else 3600
                        except ValueError:
                            delay = 3600
                        self.gate.blocked_until = now + delay
                        raise RateLimited("Provider rate limited")
                    if response.status != 200:
                        raise ProviderError("Provider request failed")
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        body.extend(chunk)
                        if len(body) > MAX_BODY:
                            raise ProviderError("Provider response too large")
                    payload = json.loads(body)
                    if (
                        not isinstance(payload, dict)
                        or payload.get("success") is not True
                    ):
                        raise ProviderError("Provider rejected request")
                    data = (
                        parse_search(payload.get("data"))
                        if search
                        else parse_movie(payload.get("data"), int(params["movie_id"]))
                    )
            except ClientError, TimeoutError, ValueError, InvalidData:
                raise ProviderError(
                    "Provider response unavailable or invalid"
                ) from None
            self.gate.retry_at.pop(key, None)
            self.gate.failure_delay.pop(key, None)
            self.gate.cache[key] = (now + (300 if search else DAY), data)
            self.gate.cache.move_to_end(key)
            return data

    async def get_peetimes(self, movie_id: int) -> Movie:
        return cast(
            Movie,
            await self._get(
                "peetimes.php",
                {"movie_id": str(movie_id), "country": self.country, "lang": "EN"},
            ),
        )

    async def search_movies(self, query: str) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            await self._get(
                "movies.php",
                {"action": "search", "q": query, "country": self.country},
                search=True,
            ),
        )
