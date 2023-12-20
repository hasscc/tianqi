from __future__ import annotations

import logging

from homeassistant.core import callback
from homeassistant.components.sensor import (
    DOMAIN as ENTITY_DOMAIN,
    SensorEntity as BaseEntity,
)

from . import TianqiClient, Converter, XEntity, async_add_setuper

_LOGGER = logging.getLogger(__name__)


def setuper(add_entities):
    def setup(client: TianqiClient, conv: Converter):
        if not (entity := client.entities.get(conv.attr)):
            entity = SensorEntity(client, conv)
        if not entity.added:
            add_entities([entity])

    return setup


async def async_setup_entry(hass, config_entry, async_add_entities):
    await async_add_setuper(hass, config_entry, ENTITY_DOMAIN, setuper(async_add_entities))


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    await async_add_setuper(hass, config or discovery_info, ENTITY_DOMAIN, setuper(async_add_entities))


class SensorEntity(XEntity, BaseEntity):
    def __init__(self, client: TianqiClient, conv: Converter):
        super().__init__(client, conv)
        self._attr_device_class = self._option.get('device_class')
        self._attr_state_class = self._option.get('state_class')
        self._attr_native_unit_of_measurement = self._option.get('unit_of_measurement')

    @callback
    def async_set_state(self, data: dict):
        super().async_set_state(data)
        self._attr_native_value = self._attr_state

    @callback
    def async_restore_last_state(self, state: str, attrs: dict):
        self._attr_native_value = attrs.get(self._name, state)
        self._attr_extra_state_attributes.update(attrs)
