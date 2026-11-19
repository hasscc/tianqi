"""The tianqi integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DOMAIN, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.typing import ConfigType

from .client import TianqiClient
from .const import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)

SERVICE_SCHEMA = vol.Schema({}, extra=vol.ALLOW_EXTRA)
SERVICES = {
    "get_station": "async_get_station",
    "update_summary": "async_update_summary",
    "update_alarms": "async_update_alarms",
    "update_dailies": "async_update_dailies",
    "update_hourlies": "async_update_hourlies",
    "update_minutely": "async_update_minutely",
    "update_observe": "async_update_observe",
}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration from YAML."""
    hass.data.setdefault(DOMAIN, {})
    if not (domain := (config.get(DOMAIN) or {}).get(CONF_DOMAIN)):
        return True

    yaml_config = dict(config.get(DOMAIN) or {})
    client = await TianqiClient.async_get(hass, yaml_config)
    hass.data[DOMAIN]["latest_domain"] = domain
    _async_register_services(hass, client)

    await asyncio.gather(
        *(
            async_load_platform(hass, platform, DOMAIN, yaml_config, config)
            for platform in PLATFORMS
        )
    )
    await client.async_init()
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("entries", {})[entry.entry_id] = entry

    client = await TianqiClient.async_get(hass, entry)
    if client.domain:
        hass.data[DOMAIN]["latest_domain"] = client.domain
    _async_register_services(hass, client)
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, client.async_unload)
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await client.async_init()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options have changed."""
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    client: TianqiClient | None = (
        hass.data.get(DOMAIN, {}).get("clients", {}).pop(entry.entry_id, None)
    )
    if client is not None:
        await client.async_unload()
        _LOGGER.info("Unload client: %s", [entry.entry_id, client.station_code])

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].get("entries", {}).pop(entry.entry_id, None)
    return unloaded


async def async_add_setuper(
    hass: HomeAssistant,
    config: ConfigEntry | dict[str, Any],
    domain: str,
    setuper: Any,
) -> None:
    """Hand a platform over to the client so it can create its entities."""
    client = await TianqiClient.async_get(hass, config)
    if domain in client.setups:
        return
    client.setups[domain] = setuper
    if domain == "weather":
        setuper(client)
    else:
        await client.setup_entities(domain)


def _async_register_services(hass: HomeAssistant, client: TianqiClient) -> None:
    """Register the services of the integration."""
    for name, method in SERVICES.items():

        async def _handle_service_call(call: ServiceCall, _method: str = method) -> Any:
            return await getattr(client, _method)(**call.data)

        hass.services.async_register(
            DOMAIN,
            name,
            _handle_service_call,
            schema=SERVICE_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
