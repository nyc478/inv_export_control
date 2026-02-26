"""Config flow for GoodWe Export Control."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN, CONF_ENTSOE_TOKEN, CONF_BIDDING_ZONE,
    CONF_EXPORT_ENTITY_ID, CONF_PRICE_THRESHOLD, GREEK_BIDDING_ZONE,
)

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_EXPORT_ENTITY_ID, default="number.goodwe_grid_export_limit"): str,
    vol.Required(CONF_ENTSOE_TOKEN): str,
    vol.Optional(CONF_BIDDING_ZONE, default=GREEK_BIDDING_ZONE): str,
    vol.Optional(CONF_PRICE_THRESHOLD, default=0.0): vol.Coerce(float),
})


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GoodWe Export Control."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            return self.async_create_entry(
                title="GoodWe Export Control",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
