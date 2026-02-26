"""Fetch day-ahead prices from ENTSO-E with HENEX fallback, persist via HA Store."""
from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
from entsoe import EntsoePandasClient
from entsoe.exceptions import NoMatchingDataError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "goodwe_export_control_prices"
STORAGE_VERSION = 1

HENEX_URL = (
    "https://www.enexgroup.gr/documents/20126/366820/"
    "{date}_EL-DAM_ResultsSummary_EN_v{version:02d}.xlsx"
)
HENEX_SHEET = "MKT_Coupling"


class PriceFetcher:
    def __init__(self, hass: HomeAssistant, api_key: str, bidding_zone: str = "10YGR-HTSO-----Y") -> None:
        self.client = EntsoePandasClient(api_key=api_key)
        self.bidding_zone = bidding_zone
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._cache: pd.Series | None = None

    async def async_load(self) -> None:
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
        if self._cache is None:
            return []
        now = datetime.now(tz=timezone.utc)
        future = self._cache[self._cache.index >= now]
        hourly = future.resample("1h").mean().head(hours)
        return [
            {"time": ts.isoformat(), "price_eur_mwh": round(float(val), 2)}
            for ts, val in hourly.items()
            if not pd.isna(val)
        ]

    def _fetch_prices(self, now: datetime) -> pd.Series | None:
        result = self._fetch_entsoe(now)
        if result is not None:
            return result
        _LOGGER.warning("ENTSO-E returned no data — trying HENEX fallback")
        return self._fetch_henex(now)

    def _fetch_entsoe(self, now: datetime) -> pd.Series | None:
        start = pd.Timestamp(now.date() - pd.Timedelta(days=2), tz="UTC")
        end = pd.Timestamp(now.date() + pd.Timedelta(days=2), tz="UTC")
        try:
            prices = self.client.query_day_ahead_prices(self.bidding_zone, start=start, end=end)
            _LOGGER.info("ENTSO-E: fetched %d price slots", len(prices))
            return prices
        except NoMatchingDataError:
            _LOGGER.warning("ENTSO-E: no data for %s", now.date())
            return None
        except Exception as exc:
            _LOGGER.error("ENTSO-E fetch failed: %s", exc)
            return None

    def _fetch_henex(self, now: datetime) -> pd.Series | None:
        """Fetch from HENEX for today, yesterday, and tomorrow."""
        all_series = []
        for delta in [0, -1, 1]:
            target_date = now.date() + timedelta(days=delta)
            series = self._fetch_henex_for_date(target_date)
            if series is not None:
                all_series.append(series)

        if not all_series:
            _LOGGER.error("HENEX: no data available around %s", now.date())
            return self._cache

        combined = pd.concat(all_series).sort_index()
        combined = combined[~combined.index.duplicated(keep="last")]
        _LOGGER.info("HENEX: combined %d price slots", len(combined))
        return combined

    def _fetch_henex_for_date(self, target_date) -> pd.Series | None:
        """Try versions v01..v05 and return first successful parse."""
        date_str = target_date.strftime("%Y%m%d")
        content = None

        for version in range(1, 6):
            url = HENEX_URL.format(date=date_str, version=version)
            try:
                resp = requests.get(url, timeout=15)
                if resp.status_code == 200:
                    content = resp.content
                    _LOGGER.info("HENEX: got %s (v%02d, %d bytes)", date_str, version, len(content))
                    break
                _LOGGER.debug("HENEX: %s v%02d → HTTP %d", date_str, version, resp.status_code)
            except Exception as exc:
                _LOGGER.debug("HENEX: %s v%02d → %s", date_str, version, exc)
                break  # network error, no point retrying other versions

        if content is None:
            return None

        try:
            wb = pd.read_excel(io.BytesIO(content), sheet_name=HENEX_SHEET, header=None)

            # Find MCP row dynamically
            mcp_row = None
            for i, row in wb.iterrows():
                if isinstance(row.iloc[0], str) and "15min MCP" in row.iloc[0]:
                    mcp_row = i
                    break

            if mcp_row is None:
                _LOGGER.warning("HENEX: MCP row not found in %s", date_str)
                return None

            prices_raw = wb.iloc[mcp_row, 1:97].values

            # Delivery day starts at midnight Athens time = 22:00 UTC (winter) / 21:00 UTC (summer)
            delivery_start = pd.Timestamp(target_date, tz="Europe/Athens").tz_convert("UTC")
            index = pd.date_range(start=delivery_start, periods=96, freq="15min", tz="UTC")

            series = pd.Series(prices_raw, index=index, dtype=float)
            _LOGGER.info("HENEX: parsed %d slots for %s (first=%.2f)", len(series), target_date, series.iloc[0])
            return series

        except Exception as exc:
            _LOGGER.error("HENEX: parse error for %s: %s", date_str, exc)
            return None
