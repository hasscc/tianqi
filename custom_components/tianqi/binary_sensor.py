from __future__ import annotations

import logging

from homeassistant.core import callback
from homeassistant.const import STATE_ON
from homeassistant.components.binary_sensor import (
    DOMAIN as ENTITY_DOMAIN,
    BinarySensorEntity as BaseEntity,
)

from . import TianqiClient, Converter, XEntity, async_add_setuper

_LOGGER = logging.getLogger(__name__)


def setuper(add_entities):
    def setup(client: TianqiClient, conv: Converter):
        if not (entity := client.entities.get(conv.attr)):
            entity = BinarySensorEntity(client, conv)
        if not entity.added:
            add_entities([entity])
    return setup


async def async_setup_entry(hass, config_entry, async_add_entities):
    await async_add_setuper(hass, config_entry, ENTITY_DOMAIN, setuper(async_add_entities))


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    await async_add_setuper(hass, config or discovery_info, ENTITY_DOMAIN, setuper(async_add_entities))


class BinarySensorEntity(XEntity, BaseEntity):
    def __init__(self, client: TianqiClient, conv: Converter):
        super().__init__(client, conv)
        self._attr_device_class = self._option.get('device_class')

    @callback
    def async_set_state(self, data: dict):
        super().async_set_state(data)
        if self._name in data:
            self._attr_is_on = data[self._name]

    @callback
    def async_restore_last_state(self, state: str, attrs: dict):
        self._attr_is_on = state == STATE_ON
        self._attr_extra_state_attributes.update(attrs)
