"""Read-only RunPee actions and player entry lifecycle."""

from typing import Any, cast

import probatio as p
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import (
    ConfigEntryError,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import ProviderError, RequestGate, RunPeeClient
from .const import DOMAIN
from .coordinator import RunPeeCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
SERVICES = ("search_movies", "get_peetimes", "select_movie", "clear_movie_override")
type RunPeeConfigEntry = ConfigEntry[RunPeeCoordinator]


async def async_migrate_entry(hass: HomeAssistant, entry: RunPeeConfigEntry) -> bool:
    if entry.version > 2:
        return False
    if entry.version == 1:
        # Preserve no-player legacy data until reconfigure supplies a player.
        data = dict(entry.data)
        if data.get("media_player"):
            data.pop("movie_id", None)
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            version=2,
            unique_id=data.get("media_player", entry.unique_id),
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: RunPeeConfigEntry) -> bool:
    if not entry.data.get("media_player"):
        raise ConfigEntryError(
            "Reconfigure this RunPee entry and choose a media player"
        )
    shared = hass.data.setdefault(DOMAIN, {})
    gate = shared.setdefault("gate", RequestGate())
    coordinator = RunPeeCoordinator(
        hass,
        entry,
        RunPeeClient(async_get_clientsession(hass), gate, entry.data["country"]),
    )
    entry.runtime_data = coordinator
    coordinator.start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    loaded: dict[str, RunPeeCoordinator] = shared.setdefault("entries", {})
    loaded[entry.entry_id] = coordinator
    if len(loaded) == 1:
        _register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def _options_updated(hass: HomeAssistant, entry: RunPeeConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: RunPeeConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    entry.runtime_data.stop()
    entries = hass.data[DOMAIN]["entries"]
    entries.pop(entry.entry_id, None)
    if not entries:
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)
    return True


def _register_services(hass: HomeAssistant) -> None:
    async def handle(call: ServiceCall) -> ServiceResponse:
        entries: dict[str, RunPeeCoordinator] = hass.data[DOMAIN]["entries"]
        coordinator = entries.get(call.data["entry_id"])
        if coordinator is None:
            raise ServiceValidationError("RunPee entry is not loaded")
        try:
            if call.service == "search_movies":
                query = call.data["query"].strip()
                if not 1 <= len(query) <= 128:
                    raise ServiceValidationError(
                        "Query must contain 1 to 128 characters"
                    )
                return cast(
                    ServiceResponse,
                    {"movies": await coordinator.client.search_movies(query)},
                )
            if call.service == "clear_movie_override":
                await coordinator.select_movie(None)
                return None
            movie_id = call.data.get("movie_id", coordinator.movie_id)
            if (
                isinstance(movie_id, bool)
                or not isinstance(movie_id, int)
                or not 1 <= movie_id <= 2**31 - 1
            ):
                raise ServiceValidationError(
                    "Supply a positive movie ID or match current playback first"
                )
            if call.service == "select_movie":
                await coordinator.select_movie(movie_id)
                return None
            return (await coordinator.client.get_peetimes(movie_id)).response()
        except ProviderError:
            raise HomeAssistantError("RunPee request failed; try again later") from None

    schemas: dict[str, Any] = {
        "search_movies": p.Schema(
            {p.Required("entry_id"): str, p.Required("query"): str}
        ),
        "get_peetimes": p.Schema(
            {p.Required("entry_id"): str, p.Optional("movie_id"): int}
        ),
        "select_movie": p.Schema(
            {p.Required("entry_id"): str, p.Required("movie_id"): int}
        ),
        "clear_movie_override": p.Schema({p.Required("entry_id"): str}),
    }
    for name, service_schema in schemas.items():
        hass.services.async_register(
            DOMAIN,
            name,
            handle,
            schema=service_schema,
            supports_response=SupportsResponse.ONLY
            if name in ("search_movies", "get_peetimes")
            else SupportsResponse.NONE,
        )
