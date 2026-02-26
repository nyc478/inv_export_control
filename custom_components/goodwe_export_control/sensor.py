"""Sensors: current price, export status."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
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
    async_add_entities([
        DayAheadPriceSensor(coordinator, entry),
        ExportStatusSensor(coordinator, entry),
    ])


class DayAheadPriceSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "Day-Ahead Energy Price"
    _attr_native_unit_of_measurement = "EUR/MWh"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:currency-eur"

    def __init__(self, coordinator: ExportControlCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_price"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get("price_eur_mwh")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "block_export": data.get("block_export"),
            "last_updated": data.get("last_updated"),
            "upcoming_prices": data.get("upcoming_prices", []),
        }


class ExportStatusSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "GoodWe Export Status"
    _attr_icon = "mdi:transmission-tower-export"

    def __init__(self, coordinator: ExportControlCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_export_status"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        if data.get("manual_override"):
            return "manual_override"
        return "blocked" if data.get("block_export") else "allowed"

    @property
    def extra_state_attributes(self) -> dict:
        return self.coordinator.data or {}
