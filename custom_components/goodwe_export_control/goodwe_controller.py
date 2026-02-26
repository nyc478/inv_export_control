"""Control GoodWe inverter export limit via local UDP."""
from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)

try:
    import goodwe
    HAS_GOODWE = True
except ImportError:
    HAS_GOODWE = False
    _LOGGER.warning("goodwe library not installed; export control disabled")

# Known register names across GoodWe models — tried in order until one works
EXPORT_LIMIT_SETTING_NAMES = [
    "export_limit_power",   # ET/BT series
    "max_export_power",     # some ES series
    "feed_in_power_limit",  # older firmware
]


class GoodWeController:
    """
    Controls GoodWe export power limit.
    limit_w = 0  → block all export
    limit_w = -1 → restore full export
    """

    def __init__(self, host: str) -> None:
        self.host = host
        self._inverter = None
        self._export_setting_name: str | None = None  # cached after discovery

    async def _get_inverter(self):
        if self._inverter is None:
            self._inverter = await goodwe.connect(self.host)
            _LOGGER.info(
                "Connected to GoodWe %s (S/N: %s)",
                self._inverter.model_name,
                self._inverter.serial_number,
            )
        return self._inverter

    async def discover_export_setting(self) -> str | None:
        """Find which export limit setting name this inverter supports."""
        inv = await self._get_inverter()
        available = {s.id_ for s in inv.settings()}
        _LOGGER.info("Available inverter settings: %s", available)

        for name in EXPORT_LIMIT_SETTING_NAMES:
            if name in available:
                _LOGGER.info("Using export limit setting: '%s'", name)
                return name

        _LOGGER.error(
            "No known export limit setting found. "
            "Available settings: %s — please report this with your inverter model.", available
        )
        return None

    async def set_export_limit(self, limit_w: int) -> None:
        if not HAS_GOODWE:
            _LOGGER.error("goodwe library missing; cannot set export limit")
            return

        inv = await self._get_inverter()

        if self._export_setting_name is None:
            self._export_setting_name = await self.discover_export_setting()

        if self._export_setting_name is None:
            return  # error already logged in discover

        value = inv.rated_power if limit_w < 0 else limit_w
        await inv.write_setting(self._export_setting_name, value)
        _LOGGER.info("Export limit → %dW (setting: '%s')", value, self._export_setting_name)

    async def read_runtime_data(self) -> dict:
        if not HAS_GOODWE:
            return {}
        inv = await self._get_inverter()
        data = await inv.read_runtime_data()
        return {k: v.value for k, v in data.items() if hasattr(v, "value")}
