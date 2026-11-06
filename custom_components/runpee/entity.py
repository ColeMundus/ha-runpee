"""Shared per-player device identity."""

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import RunPeeConfigEntry
from .const import DOMAIN
from .coordinator import RunPeeCoordinator


class RunPeeEntity(CoordinatorEntity[RunPeeCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, entry: RunPeeConfigEntry, key: str) -> None:
        super().__init__(entry.runtime_data)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"RunPee {entry.data['media_player'].split('.')[1]}",
            manufacturer="RunPee (unofficial)",
            entry_type=DeviceEntryType.SERVICE,
        )
        self.key = key
