"""Native playback status and timing sensors."""

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RunPeeConfigEntry
from .coordinator import STATUSES
from .entity import RunPeeEntity

KEYS = (
    "status",
    "movie",
    "next_window",
    "time_until_next_window",
    "current_window_remaining",
    "upcoming_windows",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RunPeeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([RunPeeSensor(entry, key) for key in KEYS])


class RunPeeSensor(RunPeeEntity, SensorEntity):
    def __init__(self, entry: RunPeeConfigEntry, key: str) -> None:
        super().__init__(entry, key)
        if key == "status":
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = STATUSES
        elif key in (
            "next_window",
            "time_until_next_window",
            "current_window_remaining",
        ):
            self._attr_device_class = SensorDeviceClass.DURATION
            self._attr_native_unit_of_measurement = UnitOfTime.SECONDS

    @property
    def available(self) -> bool:
        return self.key == "status" or self.coordinator.data.get(self.key) is not None

    @property
    def native_value(self) -> Any:
        return self.coordinator.data.get(self.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return (
            self.coordinator.attributes() if self.key in ("status", "movie") else None
        )
