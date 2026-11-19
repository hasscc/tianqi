"""Config flow for the tianqi integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.config_entries import ConfigFlow as BaseConfigFlow
from homeassistant.const import CONF_DOMAIN
from homeassistant.core import callback

from .api import StationInfo, TianqiApi
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CONF_SEARCH = "search"
CONF_AREA_ID = "area_id"
CONF_CAIYUN = "caiyun"

AUTO_AREA = "auto"
DEFAULT_TIP = "输入城市/区县名称后搜索，如果留空则根据HA配置中的位置自动获取"
OPTIONS_TIP = "如果想修改城市/区县，请重新添加集成"

RE_DOMAIN = re.compile(r"^\s*https?://|/+\s*$", re.IGNORECASE)


def _clean_domain(value: str | None) -> str:
    """Strip the scheme and trailing slashes from a server domain."""
    return RE_DOMAIN.sub("", value or "").strip()


class TianqiConfigFlow(BaseConfigFlow, domain=DOMAIN):
    """Handle the config flow of the tianqi integration."""

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._station: StationInfo | None = None
        self._tip: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return TianqiOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        user_input = dict(user_input or {})
        self._tip = None
        domain = _clean_domain(user_input.get(CONF_DOMAIN))
        area_id = user_input.get(CONF_AREA_ID, "")
        search = user_input.get(CONF_SEARCH)
        api = TianqiApi(self.hass, domain)
        area_schema: dict[Any, Any] = {}

        if domain:
            user_input[CONF_DOMAIN] = domain
            if not area_id:
                area_id = AUTO_AREA
                user_input.setdefault(CONF_AREA_ID, area_id)

        if search and not domain:
            self._tip = "请先填写服务器域，再搜索地点"
        elif search:
            if areas := await api.async_search_areas(search):
                areas = {AUTO_AREA: "自动获取", **areas}
                if area_id not in areas:
                    area_id = ""
                area_schema[vol.Optional(CONF_AREA_ID, default=area_id)] = vol.In(areas)
            else:
                self._tip = f"未找到与【{search}】相关的地点"
        elif area_id:
            await self.async_set_unique_id(area_id)
            self._abort_if_unique_id_configured()
            try:
                self._station = await api.async_get_station(area_id=area_id)
            except Exception as exc:  # noqa: BLE001 - reported to the user in the form
                self._tip = f"{exc}"
            if self._station:
                user_input.pop(CONF_SEARCH, None)
                return self.async_create_entry(
                    title=self._station.area_name or area_id,
                    data=user_input,
                )

        latest_domain = self.hass.data.get(DOMAIN, {}).get("latest_domain")
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DOMAIN, default=user_input.get(CONF_DOMAIN, latest_domain)
                ): str,
                vol.Optional(CONF_SEARCH, default=""): str,
                **area_schema,
                vol.Optional(
                    CONF_CAIYUN, default=user_input.get(CONF_CAIYUN, False)
                ): bool,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            description_placeholders={"tip": self._tip or DEFAULT_TIP},
        )


class TianqiOptionsFlow(OptionsFlow):
    """Handle the options flow of the tianqi integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        tip = OPTIONS_TIP

        if user_input is not None:
            domain = _clean_domain(user_input.get(CONF_DOMAIN))
            if not domain:
                tip = "服务器域不能为空"
            else:
                api = TianqiApi(self.hass, domain)
                try:
                    await api.async_get_station(
                        area_id=self.config_entry.data.get(CONF_AREA_ID)
                    )
                except Exception as exc:  # noqa: BLE001 - reported to the user in the form
                    tip = f"{exc}"
                else:
                    return self.async_create_entry(
                        data={**user_input, CONF_DOMAIN: domain}
                    )

        defaults = {
            **self.config_entry.data,
            **self.config_entry.options,
            **(user_input or {}),
        }
        schema = vol.Schema(
            {
                vol.Required(CONF_DOMAIN, default=defaults.get(CONF_DOMAIN)): str,
                vol.Optional(
                    CONF_CAIYUN, default=defaults.get(CONF_CAIYUN, False)
                ): bool,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={"tip": tip},
        )
