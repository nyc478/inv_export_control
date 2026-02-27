"""Fetch day-ahead prices from ENTSO-E with HENEX fallback.

HENEX parsing uses only Python builtins (zipfile + xml.etree) — no openpyxl needed.
"""
from __future__ import annotations

import io
import logging
import xml.etree.ElementTree as ET
import zipfile
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

_XLSX_NS = {"ns": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _parse_henex_xlsx(content: bytes, target_date) -> pd.Series | None:
    """Parse HENEX Excel using only stdlib — no openpyxl required."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            # Shared strings table
            with zf.open("xl/sharedStrings.xml") as f:
                ss_tree = ET.parse(f)
            shared_strings = [
                "".join(t.text or "" for t in si.findall(".//ns:t", _XLSX_NS))
                for si in ss_tree.findall(".//ns:si", _XLSX_NS)
            ]

            # MKT_Coupling is always sheet3
            with zf.open("xl/worksheets/sheet3.xml") as f:
                ws_tree = ET.parse(f)

        prices = None
        for row in ws_tree.findall(".//ns:row", _XLSX_NS):
            cells = row.findall("ns:c", _XLSX_NS)
            if not cells:
                continue
            # Read first cell to identify row label
            first = cells[0]
            v_el = first.find("ns:v", _XLSX_NS)
            if first.get("t") == "s" and v_el is not None:
                label = shared_strings[int(v_el.text)]
            else:
                continue  # not a string label row

            if label != "Greece Mainland  (15min MCP)":
                continue

            # Extract numeric values from remaining cells (skip formula/empty)
            prices = []
            for cell in cells[1:]:
                cv = cell.find("ns:v", _XLSX_NS)
                # Skip formula cells and non-numeric types
                if cv is None or cell.get("t") == "s":
                    continue
                try:
                    prices.append(float(cv.text))
                except (ValueError, TypeError):
                    continue
            break

        if not prices or len(prices) < 96:
            _LOGGER.warning("HENEX: only %d prices parsed for %s", len(prices) if prices else 0, target_date)
            return None

        prices = prices[:96]  # ensure exactly 96 slots

        delivery_start = pd.Timestamp(target_date, tz="Europe/Athens").tz_convert("UTC")
        index = pd.date_range(start=delivery_start, periods=96, freq="15min", tz="UTC")
        series = pd.Series(prices, index=index, dtype=float)
        _LOGGER.info("HENEX: parsed %d slots for %s (first=%.2f)", len(series), target_date, series.iloc[0])
        return series

    except Exception as exc:
        _LOGGER.error("HENEX: parse error for %s: %s", target_date, exc)
        return None


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
        # Always refresh if no future slots
        if self._cache[self._cache.index > now].empty:
            return True
        # Refresh if tomorrow's data is missing and it's past 13:00 CET (HENEX publishes ~13:00)
        tomorrow = (now + timedelta(days=1)).date()
        tomorrow_start = pd.Timestamp(tomorrow, tz="Europe/Athens").tz_convert("UTC")
        has_tomorrow = not self._cache[self._cache.index >= tomorrow_start].empty
        if not has_tomorrow:
            now_cet = now.astimezone(__import__('zoneinfo').ZoneInfo("Europe/Athens"))
            if now_cet.hour >= 13:
                return True
        return False

    def get_current_price(self, now: datetime) -> float | None:
        if self._needs_refresh(now):
            self._cache = self._fetch_prices(now)
        if self._cache is None:
            return None
        try:
            slot = self._cache.index[self._cache.index <= now]
            if slot.empty:
                return None
            return float(self._cache[slot[-1]])
        except Exception as exc:
            _LOGGER.error("Error reading price: %s", exc)
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
            _LOGGER.info("ENTSO-E: fetched %d slots", len(prices))
            return prices
        except NoMatchingDataError:
            _LOGGER.warning("ENTSO-E: no data for %s", now.date())
            return None
        except Exception as exc:
            _LOGGER.error("ENTSO-E fetch failed: %s", exc)
            return None

    def _fetch_henex(self, now: datetime) -> pd.Series | None:
        all_series = []
        for delta in [0, 1, -1]:  # today first, then tomorrow, then yesterday
            target_date = now.date() + timedelta(days=delta)
            series = self._fetch_henex_for_date(target_date)
            if series is not None:
                all_series.append(series)

        if not all_series:
            _LOGGER.error("HENEX: no data available around %s", now.date())
            return self._cache

        combined = pd.concat(all_series).sort_index()
        combined = combined[~combined.index.duplicated(keep="last")]
        _LOGGER.info("HENEX: combined %d total price slots", len(combined))
        return combined

    def _fetch_henex_for_date(self, target_date) -> pd.Series | None:
        date_str = target_date.strftime("%Y%m%d")
        for version in range(1, 6):
            url = HENEX_URL.format(date=date_str, version=version)
            try:
                resp = requests.get(url, timeout=15)
                if resp.status_code == 200:
                    _LOGGER.info("HENEX: downloaded %s v%02d (%d bytes)", date_str, version, len(resp.content))
                    return _parse_henex_xlsx(resp.content, target_date)
                _LOGGER.debug("HENEX: %s v%02d → HTTP %d", date_str, version, resp.status_code)
            except requests.RequestException as exc:
                _LOGGER.error("HENEX: network error for %s: %s", date_str, exc)
                break  # no point retrying on network failure
        return None
