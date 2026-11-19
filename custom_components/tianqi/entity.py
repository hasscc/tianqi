"""Base entity for the tianqi integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import StateType
from homeassistant.util import slugify

from .converters.base import Converter

if TYPE_CHECKING:
    from .client import TianqiClient

_LOGGER = logging.getLogger(__name__)


class XEntity(RestoreEntity):
    """Base class for the entities of this integration."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    added = False

    def __init__(
        self,
        client: TianqiClient,
        converter: Converter,
        option: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the entity."""
        self.client = client
        self.hass = client.hass
        self.conv = converter
        self._name = converter.attr
        self._option = {**(converter.option or {}), **(option or {})}
        self._attr_unique_id = f"{client.area_id}-{converter.attr}"
        object_id = slugify(f"{client.station_code}_{converter.attr}")
        self.entity_id = f"{converter.domain}.{object_id}"
        self._attr_icon = self._option.get("icon")
        self._attr_device_class = self._option.get("device_class")
        self._attr_entity_picture = self._option.get("entity_picture")
        self._attr_entity_category = self._option.get("entity_category")
        self._attr_translation_key = self._option.get("translation_key", converter.attr)
        self._attr_device_info = client.device_info
        self._attr_entity_registry_enabled_default = converter.enabled is not False
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._vars: dict[str, Any] = {}
        self.subscribed_attrs = client.subscribe_attrs(converter)
        client.entities[converter.attr] = self

    async def async_added_to_hass(self) -> None:
        """Run when the entity has been added to Home Assistant."""
        await super().async_added_to_hass()
        self.added = True
        if (state := await self.async_get_last_state()) is not None:
            self.async_restore_last_state(state.state, state.attributes)

    @callback
    def async_restore_last_state(self, state: str, attrs: dict[str, Any]) -> None:
        """Restore the previous state."""
        self._attr_state: StateType = state

    @callback
    def async_set_state(self, data: dict[str, Any]) -> None:
        """Handle a state update coming from the client."""
        if (option := self.conv.option) is not None:
            self._option.update(option)
        if self._name in data:
            self._attr_state = data[self._name]
            self._attr_entity_picture = self._option.get("entity_picture")
        if self._option.get("payload_attrs"):
            self._attr_extra_state_attributes = dict(data)
        else:
            self._attr_extra_state_attributes.update(
                {key: data[key] for key in self.subscribed_attrs if key in data}
            )
        _LOGGER.debug("%s: State changed: %s", self.entity_id, data)
