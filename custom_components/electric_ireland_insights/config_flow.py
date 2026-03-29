"""Config flow for Electric Ireland Insights integration."""
from __future__ import annotations

import aiohttp
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import ElectricIrelandAPI
from .const import DOMAIN, NAME
from .exceptions import AccountNotFound, CannotConnect, InvalidAuth

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): str,
        vol.Required("account_number"): str,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("password"): str,
    }
)


class ElectricIrelandInsightsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Electric Ireland Insights."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                session = async_create_clientsession(
                    self.hass, cookie_jar=aiohttp.CookieJar()
                )
                api = ElectricIrelandAPI(
                    user_input["username"],
                    user_input["password"],
                    user_input["account_number"],
                )
                await api.validate_credentials(session)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except AccountNotFound:
                errors["base"] = "account_not_found"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(user_input["account_number"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"{NAME} ({user_input['account_number']})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle re-authentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle re-authentication confirmation."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            new_data = {**reauth_entry.data, "password": user_input["password"]}
            try:
                session = async_create_clientsession(
                    self.hass, cookie_jar=aiohttp.CookieJar()
                )
                api = ElectricIrelandAPI(
                    new_data["username"],
                    new_data["password"],
                    new_data["account_number"],
                )
                await api.validate_credentials(session)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except AccountNotFound:
                errors["base"] = "account_not_found"
            except Exception:
                _LOGGER.exception("Unexpected exception during reauth")
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(new_data["account_number"])
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data=new_data,
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
        )
