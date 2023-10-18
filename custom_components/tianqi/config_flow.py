import logging
import re
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import *

from . import TianqiClient, DOMAIN

_LOGGER = logging.getLogger(__name__)
CONF_SEARCH = 'search'


class TianqiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    @staticmethod
    @callback
    def async_get_options_flow(entry: config_entries.ConfigEntry):
        return OptionsFlowHandler(entry)

    async def async_step_user(self, user_input=None):
        self.hass.data.setdefault(DOMAIN, {})
        if user_input is None:
            user_input = {}
        schema = {}
        errors = {}
        search = user_input.get(CONF_SEARCH)
        domain = user_input.get(CONF_DOMAIN) or ''
        area_id = user_input.get('area_id', '')
        domain = re.sub(r'^\s*https?://|/+\s*$', '', domain, flags=re.IGNORECASE)
        client = TianqiClient(self.hass, {CONF_DOMAIN: domain})

        if domain:
            user_input[CONF_DOMAIN] = domain
            if not area_id:
                area_id = 'auto'
                user_input.setdefault('area_id', area_id)

        if search:
            if areas := await client.search_areas(search):
                areas = {
                    'auto': '自动获取',
                    **areas,
                }
                if area_id not in areas:
                    area_id = ''
                schema.update({
                    vol.Optional('area_id', default=area_id): vol.In(areas),
                })
            else:
                self.context['last_error'] = f'未找到与【{search}】相关的地点'

        elif area_id:
            await self.async_set_unique_id(area_id)
            self._abort_if_unique_id_configured()
            try:
                station = await client.get_station(area_id=area_id)
            except Exception as exc:
                station = None
                self.context['last_error'] = f'{exc}'
            if station:
                self.context['station'] = station
                user_input.pop(CONF_SEARCH, None)
                return self.async_create_entry(
                    title=station.area_name,
                    data=user_input,
                )

        if not self.context.get('last_error'):
            self.context['last_error'] = '输入城市/区县名称后搜索，如果留空则根据HA配置中的位置自动获取'

        latest_domain = self.hass.data[DOMAIN].get('latest_domain')
        schema = {
            vol.Required(CONF_DOMAIN, default=user_input.get(CONF_DOMAIN, latest_domain)): str,
            vol.Optional(CONF_SEARCH, default=''): str,
            **schema,
            vol.Optional('caiyun', default=user_input.get('caiyun', False)): bool,
        }
        return self.async_show_form(
            step_id='user',
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={'tip': self.context.pop('last_error', '')},
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is None:
            user_input = {}
        domain = user_input.get(CONF_DOMAIN)
        if domain:
            client = TianqiClient(self.hass, {CONF_DOMAIN: domain})
            try:
                await client.get_station()
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data={**self.config_entry.data, **user_input}
                )
                return self.async_create_entry(title='', data={})
            except Exception as exc:
                self.context['last_error'] = f'{exc}'
        if not self.context.get('last_error'):
            self.context['last_error'] = '如果想修改城市/区县，请重新添加集成'
        defaults = {
            **self.config_entry.data,
            **self.config_entry.options,
            **user_input,
        }
        return self.async_show_form(
            step_id='init',
            data_schema=vol.Schema({
                vol.Required(CONF_DOMAIN, default=defaults.get(CONF_DOMAIN)): str,
                vol.Optional('caiyun', default=defaults.get('caiyun', False)): bool,
            }),
            description_placeholders={'tip': self.context.pop('last_error', '')},
        )
