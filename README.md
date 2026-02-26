# GoodWe Export Control

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Home Assistant integration that automatically blocks grid feed-in from your GoodWe inverter when Greek day-ahead energy prices are zero or negative.

## Features

- Fetches day-ahead prices from ENTSO-E Transparency Platform (Greek bidding zone)
- Sets `number.goodwe_grid_export_limit` to 0% when price ≤ threshold (default: 0 €/MWh)
- Restores full export when prices go positive
- Persists price cache across HA restarts (no data loss on reboot)
- Custom Lovelace card showing today & tomorrow prices as bar chart
- Manual override switch to disable automatic control

## Requirements

- GoodWe inverter with the official [GoodWe](https://www.home-assistant.io/integrations/goodwe/) HA integration installed
- Free ENTSO-E API token: https://transparency.entsoe.eu/usrm/user/createPublicUser

## Installation via HACS

1. HACS → Integrations → ⋮ → Custom repositories
2. Add your GitLab repo URL → category: **Integration**
3. Install "GoodWe Export Control"
4. Restart Home Assistant

## Setup

Settings → Integrations → Add → **GoodWe Export Control**

| Field | Value |
|---|---|
| Export entity ID | `number.goodwe_grid_export_limit` |
| ENTSO-E API Token | from transparency.entsoe.eu |
| Bidding Zone | `10YGR-HTSO-----Y` (Greece) |
| Price threshold | `0.0` €/MWh |

## Lovelace Card

Copy `www/goodwe-price-card.js` to `/config/www/` in your HA instance.

Add as a resource: Settings → Dashboards → Resources → Add → `/local/goodwe-price-card.js`

Add to your dashboard:
```yaml
type: custom:goodwe-price-card
entity: sensor.day_ahead_energy_price
```

## Entities

| Entity | Description |
|---|---|
| `sensor.day_ahead_energy_price` | Current price (€/MWh) + upcoming prices as attributes |
| `sensor.goodwe_export_status` | `allowed` / `blocked` / `manual_override` |
| `switch.goodwe_export_manual_override` | Disable automatic control |

## Price Cache

Prices are persisted to `/config/.storage/goodwe_export_control_prices` and survive restarts. The cache covers yesterday + today + tomorrow (when available). ENTSO-E publishes next-day prices around 13:00 CET.
