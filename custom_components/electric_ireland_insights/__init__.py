"""Electric Ireland Insights integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import ElectricIrelandCoordinator

_LOGGER = logging.getLogger(DOMAIN)

type ElectricIrelandConfigEntry = ConfigEntry[ElectricIrelandCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = ElectricIrelandCoordinator(hass, entry)

    entry.runtime_data = coordinator

    await coordinator.async_config_entry_first_refresh()

    entry.async_on_unload(coordinator.async_add_listener(lambda: None))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True
