"""Manual override switch — disables automatic export control."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from . import ExportControlCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: ExportControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ManualOverrideSwitch(coordinator, entry)])


class ManualOverrideSwitch(CoordinatorEntity, SwitchEntity):
    _attr_name = "GoodWe Export Manual Override"
    _attr_icon = "mdi:hand-back-right"

    def __init__(self, coordinator: ExportControlCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_manual_override"
        self._is_on = False

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        self.coordinator.set_manual_override(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._is_on = False
        self.coordinator.set_manual_override(False)
        # Force immediate re-evaluation
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()
