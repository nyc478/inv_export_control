"""Fetch day-ahead prices from ENTSO-E, persist via HA Store."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
from entsoe import EntsoePandasClient
from entsoe.exceptions import NoMatchingDataError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "goodwe_export_control_prices"
STORAGE_VERSION = 1


class PriceFetcher:
    def __init__(self, hass: HomeAssistant, api_key: str, bidding_zone: str = "10YGR-HTSO-----Y") -> None:
        self.client = EntsoePandasClient(api_key=api_key)
        self.bidding_zone = bidding_zone
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._cache: pd.Series | None = None

    async def async_load(self) -> None:
        """Load cached prices from .storage/ on startup."""
        data = await self._store.async_load()
        if data and "prices" in data:
            try:
                self._cache = pd.Series(
                    data["prices"]["values"],
                    index=pd.to_datetime(data["prices"]["index"], utc=True),
                    dtype=float,
                )
                _LOGGER.info("Loaded %d cached price slots from storage", len(self._cache))
            except Exception as exc:
                _LOGGER.warning("Could not restore price cache: %s", exc)
                self._cache = None

    async def async_save(self) -> None:
        """Persist current prices to .storage/."""
        if self._cache is None:
            return
        await self._store.async_save({
            "prices": {
                "index": [str(ts) for ts in self._cache.index],
                "values": list(self._cache.values),
            }
        })

    def _needs_refresh(self, now: datetime) -> bool:
        if self._cache is None:
            return True
        future = self._cache[self._cache.index > now]
        return future.empty

    def get_current_price(self, now: datetime) -> float | None:
        """Return current hour's price in EUR/MWh. Refreshes cache if stale."""
        if self._needs_refresh(now):
            self._cache = self._fetch_prices(now)

        if self._cache is None:
            return None

        try:
            slot = self._cache.index[self._cache.index <= now]
            if slot.empty:
                return None
            price = float(self._cache[slot[-1]])
            _LOGGER.debug("Current price: %.2f EUR/MWh at %s", price, slot[-1])
            return price
        except Exception as exc:
            _LOGGER.error("Error reading price from cache: %s", exc)
            return None

    def get_upcoming_prices(self, hours: int = 36) -> list[dict]:
        """Return next N hours of prices for sensor attributes."""
        if self._cache is None:
            return []
        now = datetime.now(tz=timezone.utc)
        future = self._cache[self._cache.index >= now].head(hours)
        return [
            {"time": ts.isoformat(), "price_eur_mwh": round(float(val), 2)}
            for ts, val in future.items()
        ]

    def _fetch_prices(self, now: datetime) -> pd.Series | None:
        start = pd.Timestamp(now.date() - pd.Timedelta(days=1), tz="UTC")
        end = pd.Timestamp(now.date() + pd.Timedelta(days=2), tz="UTC")
        try:
            prices = self.client.query_day_ahead_prices(self.bidding_zone, start=start, end=end)
            _LOGGER.info("Fetched %d price slots from ENTSO-E", len(prices))
            return prices
        except NoMatchingDataError:
            _LOGGER.warning("No day-ahead price data available for %s", now.date())
            return self._cache
        except Exception as exc:
            _LOGGER.error("ENTSO-E fetch failed: %s", exc)
            return self._cache
