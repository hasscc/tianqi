"""Sensor platform for the tianqi integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity as BaseEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

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
    """Set up the sensor platform from a config entry."""
    await async_add_setuper(
        hass, config_entry, Platform.SENSOR, _setuper(async_add_entities)
    )


async def async_setup_platform(
    hass: HomeAssistant,
    config: dict[str, Any],
    async_add_entities: AddEntitiesCallback,
    discovery_info: dict[str, Any] | None = None,
) -> None:
    """Set up the sensor platform from YAML."""
    await async_add_setuper(
        hass,
        config or discovery_info or {},
        Platform.SENSOR,
        _setuper(async_add_entities),
    )


def _setuper(add_entities: AddEntitiesCallback) -> Any:
    """Return the setuper of this platform."""

    def setup(client: TianqiClient, converter: Converter) -> None:
        entity = client.entities.get(converter.attr) or SensorEntity(client, converter)
        if not entity.added:
            add_entities([entity])

    return setup


class SensorEntity(XEntity, BaseEntity):
    """Sensor entity driven by a converter."""

    def __init__(self, client: TianqiClient, converter: Converter) -> None:
        """Initialize the sensor."""
        super().__init__(client, converter)
        self._attr_state_class = self._option.get("state_class")
        self._attr_native_unit_of_measurement = self._option.get("unit_of_measurement")

    @callback
    def async_set_state(self, data: dict[str, Any]) -> None:
        """Handle a state update coming from the client."""
        super().async_set_state(data)
        self._attr_native_value: StateType = self._attr_state

    @callback
    def async_restore_last_state(self, state: str, attrs: dict[str, Any]) -> None:
        """Restore the previous state."""
        self._attr_native_value = attrs.get(self._name, state)
        self._attr_extra_state_attributes.update(attrs)
