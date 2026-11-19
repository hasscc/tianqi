"""Binary sensor platform for the tianqi integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity as BaseEntity
from homeassistant.const import STATE_ON, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import async_add_setuper
from .client import TianqiClient
from .converters.base import Converter
from .entity import XEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform from a config entry."""
    await async_add_setuper(
        hass, config_entry, Platform.BINARY_SENSOR, _setuper(async_add_entities)
    )


async def async_setup_platform(
    hass: HomeAssistant,
    config: dict[str, Any],
    async_add_entities: AddEntitiesCallback,
    discovery_info: dict[str, Any] | None = None,
) -> None:
    """Set up the binary sensor platform from YAML."""
    await async_add_setuper(
        hass,
        config or discovery_info or {},
        Platform.BINARY_SENSOR,
        _setuper(async_add_entities),
    )


def _setuper(add_entities: AddEntitiesCallback) -> Any:
    """Return the setuper of this platform."""

    def setup(client: TianqiClient, converter: Converter) -> None:
        entity = client.entities.get(converter.attr) or BinarySensorEntity(
            client, converter
        )
        if not entity.added:
            add_entities([entity])

    return setup


class BinarySensorEntity(XEntity, BaseEntity):
    """Binary sensor entity driven by a converter."""

    @callback
    def async_set_state(self, data: dict[str, Any]) -> None:
        """Handle a state update coming from the client."""
        super().async_set_state(data)
        if self._name in data:
            self._attr_is_on = data[self._name]

    @callback
    def async_restore_last_state(self, state: str, attrs: dict[str, Any]) -> None:
        """Restore the previous state."""
        self._attr_is_on = state == STATE_ON
        self._attr_extra_state_attributes.update(attrs)
