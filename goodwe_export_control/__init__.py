"""GoodWe Export Control based on real-time energy exchange prices."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, CONF_ENTSOE_TOKEN, CONF_BIDDING_ZONE, CONF_EXPORT_ENTITY_ID, CONF_PRICE_THRESHOLD
from .price_fetcher import PriceFetcher

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.SWITCH]
SCAN_INTERVAL = timedelta(minutes=5)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    fetcher = PriceFetcher(
        hass=hass,
        api_key=entry.data[CONF_ENTSOE_TOKEN],
        bidding_zone=entry.data.get(CONF_BIDDING_ZONE, "10YGR-HTSO-----Y"),
    )
    await fetcher.async_load()  # restore cached prices from .storage/

    coordinator = ExportControlCoordinator(hass, fetcher, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


class ExportControlCoordinator(DataUpdateCoordinator):
    """Fetches prices, decides export policy, calls HA number entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        fetcher: PriceFetcher,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.fetcher = fetcher
        self.export_entity_id: str = entry.data.get(CONF_EXPORT_ENTITY_ID, "number.goodwe_grid_export_limit")
        self.price_threshold: float = entry.data.get(CONF_PRICE_THRESHOLD, 0.0)
        self._manual_override: bool = False

    async def _async_update_data(self) -> dict[str, Any]:
        now = datetime.now(tz=timezone.utc)

        try:
            price = await self.hass.async_add_executor_job(
                self.fetcher.get_current_price, now
            )
            await self.fetcher.async_save()  # persist to .storage/
        except Exception as exc:
            raise UpdateFailed(f"Failed to fetch price: {exc}") from exc

        block_export = price is not None and price <= self.price_threshold

        if not self._manual_override:
            limit = 0 if block_export else 100  # percent: 0% or 100%
            await self.hass.services.async_call(
                "number", "set_value",
                {"entity_id": self.export_entity_id, "value": limit},
                blocking=False,
            )
            _LOGGER.info(
                "Price=%.2f EUR/MWh → export %s (limit=%d%%)",
                price if price is not None else float("nan"),
                "BLOCKED" if block_export else "ALLOWED",
                limit,
            )

        return {
            "price_eur_mwh": price,
            "block_export": block_export,
            "manual_override": self._manual_override,
            "last_updated": now.isoformat(),
            "upcoming_prices": self.fetcher.get_upcoming_prices(),
        }

    def set_manual_override(self, enabled: bool) -> None:
        self._manual_override = enabled
