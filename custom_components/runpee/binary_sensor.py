"""Native bathroom-window binary sensor."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RunPeeConfigEntry
from .entity import RunPeeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RunPeeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([WindowSensor(entry, "window_active")])


class WindowSensor(RunPeeEntity, BinarySensorEntity):
    @property
    def available(self) -> bool:
        return self.coordinator.data.get("window_active") is not None

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.get("window_active")
