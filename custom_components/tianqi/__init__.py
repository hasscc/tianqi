import logging
import aiohttp
import asyncio
import time
import json
import re
import base64
import voluptuous as vol

from typing import Optional
from datetime import datetime, timedelta

from homeassistant.const import *
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import aiohttp_client
from homeassistant.exceptions import IntegrationError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


DOMAIN = 'tianqi'
_LOGGER = logging.getLogger(__name__)

SUPPORTED_PLATFORMS = [Platform.WEATHER]
HTTP_REFERER = base64.b64decode('aHR0cHM6Ly9tLndlYXRoZXIuY29tLmNuLw==').decode()
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_1) AppleWebKit/537 (KHTML, like Gecko) Chrome/116.0 Safari/537'


async def async_setup(hass: HomeAssistant, hass_config):
    config = hass_config.get(DOMAIN) or {}
    if not (domain := config.get(CONF_DOMAIN)):
        return True

    client = await TianqiClient.from_config(hass, config)
    await client.init()
    hass.data[DOMAIN]['latest_domain'] = domain

    async def get_station(call: ServiceCall):
        return await client.get_station(**call.data)
    hass.services.async_register(
        DOMAIN, 'get_station', get_station,
        schema=vol.Schema({}, extra=vol.ALLOW_EXTRA),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def update_summary(call: ServiceCall):
        return await client.update_summary(**call.data)
    hass.services.async_register(
        DOMAIN, 'update_summary', update_summary,
        schema=vol.Schema({}, extra=vol.ALLOW_EXTRA),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def update_alarms(call: ServiceCall):
        return await client.update_alarms(**call.data)
    hass.services.async_register(
        DOMAIN, 'update_alarms', update_alarms,
        schema=vol.Schema({}, extra=vol.ALLOW_EXTRA),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def update_dailies(call: ServiceCall):
        return await client.update_dailies(**call.data)
    hass.services.async_register(
        DOMAIN, 'update_dailies', update_dailies,
        schema=vol.Schema({}, extra=vol.ALLOW_EXTRA),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def update_hourlies(call: ServiceCall):
        return await client.update_hourlies(**call.data)
    hass.services.async_register(
        DOMAIN, 'update_hourlies', update_hourlies,
        schema=vol.Schema({}, extra=vol.ALLOW_EXTRA),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def update_minutely(call: ServiceCall):
        return await client.update_minutely(**call.data)
    hass.services.async_register(
        DOMAIN, 'update_minutely', update_minutely,
        schema=vol.Schema({}, extra=vol.ALLOW_EXTRA),
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def update_observe(call: ServiceCall):
        return await client.update_observe(**call.data)
    hass.services.async_register(
        DOMAIN, 'update_observe', update_observe,
        schema=vol.Schema({}, extra=vol.ALLOW_EXTRA),
        supports_response=SupportsResponse.OPTIONAL,
    )

    if 'entry_id' not in config:
        await asyncio.gather(
            *[
                hass.helpers.discovery.async_load_platform(domain, DOMAIN, config, config)
                for domain in SUPPORTED_PLATFORMS
            ]
        )

    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault('entries', {})
    hass.data[DOMAIN]['entries'][entry.entry_id] = entry
    ret = await async_setup(hass, {
        DOMAIN: {
            'entry_id': entry.entry_id,
            **(entry.data or {}),
            **(entry.options or {}),
        },
    })

    await hass.config_entries.async_forward_entry_setups(entry, SUPPORTED_PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_options))
    if client := await TianqiClient.from_config(hass, entry):
        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, client.unload)
        )
    return ret

async def async_update_options(hass: HomeAssistant, entry: ConfigEntry):
    _LOGGER.info('Update options: %s', [entry.entry_id, entry.data])
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    client = await TianqiClient.from_config(hass, entry)
    if isinstance(client, TianqiClient):
        await client.unload()
        hass.data[DOMAIN]['clients'].pop(entry.entry_id)
        _LOGGER.info('Unload client: %s', [entry.entry_id, client.station])

    await hass.config_entries.async_unload_platforms(entry, SUPPORTED_PLATFORMS)
    return True

async def async_add_setuper(hass: HomeAssistant, config, domain, setuper):
    client = await TianqiClient.from_config(hass, config)
    if not client:
        return
    if domain not in client.setups:
        client.setups[domain] = setuper
        setuper(client)


class TianqiClient:
    def __init__(self, hass: HomeAssistant, config=None):
        self.hass = hass
        self.config = config or {}
        self.entry_id = self.config.get('entry_id') or 'yaml'
        self.data = {}
        self.setups = {}
        self.entities = {}
        self.station: Optional[StationInfo] = None

        self.http = aiohttp_client.async_create_clientsession(
            hass,
            timeout=aiohttp.ClientTimeout(total=20),
            auto_cleanup=False,
        )
        self.http._default_headers = {
            'Referer': HTTP_REFERER,
            'User-Agent': USER_AGENT,
        }

        self.coordinators = [
            DataUpdateCoordinator(
                hass, _LOGGER,
                name='alarms',
                update_method=self.update_alarms,
                update_interval=timedelta(minutes=5),
            ),
            DataUpdateCoordinator(
                hass, _LOGGER,
                name='summary',
                update_method=self.update_summary_and_entities,
                update_interval=timedelta(seconds=60),
            ),
            DataUpdateCoordinator(
                hass, _LOGGER,
                name='dailies',
                update_method=self.update_dailies,
                update_interval=timedelta(minutes=60),
            ),
            DataUpdateCoordinator(
                hass, _LOGGER,
                name='observe',
                update_method=self.update_observe,
                update_interval=timedelta(minutes=30),
            ),
            DataUpdateCoordinator(
                hass, _LOGGER,
                name='hourlies',
                update_method=self.update_hourlies,
                update_interval=timedelta(minutes=30),
            ),
            DataUpdateCoordinator(
                hass, _LOGGER,
                name='minutely',
                update_method=self.update_minutely,
                update_interval=timedelta(minutes=2),
            ),
        ]
        self._remove_listeners = []

    @staticmethod
    async def from_config(hass, entry):
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN].setdefault('clients', {})

        if isinstance(entry, ConfigEntry):
            config = {
                'entry_id': entry.entry_id,
                **(entry.data or {}),
                **(entry.options or {}),
            }
        else:
            config = entry
        entry_id = config.get('entry_id') or 'yaml'
        client = hass.data[DOMAIN]['clients'].get(entry_id)
        if not client:
            client = TianqiClient(hass, config)
            hass.data[DOMAIN]['clients'][entry_id] = client
            _LOGGER.info('New client: %s', config)

        if not client.station:
            client.station = await client.get_station(area_id=config.get('area_id'))
            _LOGGER.info('New station: %s', [entry_id, client.station.data])
        return client

    async def init(self):
        if not self.station:
            self.station = await self.get_station()

        for coord in self.coordinators:
            def coordinator_handler():
                _LOGGER.debug('Coordinator %s done', coord.name)

            await coord.async_config_entry_first_refresh()
            remove_listener = coord.async_add_listener(coordinator_handler)
            self._remove_listeners.append(remove_listener)

    async def unload(self, *args):
        for rmh in self._remove_listeners:
            rmh()
        self._remove_listeners = []

    @property
    def domain(self):
        return self.config.get(CONF_DOMAIN)

    @property
    def area_id(self):
        return self.station.area_id

    async def get_station(self, area_id=None, lat=None, lng=None):
        api = self.api_url('geong/v1/api', node='d7')
        pms = {'method': 'stationinfo'}
        if area_id and area_id != 'auto':
            pms['areaid'] = area_id
        elif not lat or not lng:
            pms['lat'] = self.hass.config.latitude
            pms['lng'] = self.hass.config.longitude
        else:
            raise IntegrationError(f'Arguments invalid for {api}.')

        res = await self.http.get(api, params={
            'params': json.dumps(pms, separators=(',', ':')),
        }, allow_redirects=False)
        txt = await res.text()
        if not txt:
            _LOGGER.error('%s: %s', api, [pms, txt, res.headers])
        try:
            dat = json.loads(txt) or {}
        except Exception as exc:
            raise IntegrationError(f'{exc}:\n{txt}') from exc
        inf = dat.get('data', {}).get('station') or {}
        if not inf:
            raise IntegrationError(f'Unable to get station info: {pms} {txt}')
        return StationInfo({
            **dat.get('location', {}),
            **inf,
        })

    async def search_areas(self, name):
        api = self.api_url('search', node='toy1')
        pms = {'cityname': name}
        res = await self.http.get(api, params=pms, allow_redirects=False)
        txt = await res.text()
        if not txt:
            raise IntegrationError(f'Empty response from: {api} {pms}')
        lst = {}
        for v in json.loads(txt.strip('()')) or []:
            if not (ref := v.get('ref')):
                continue
            arr = f'{ref}'.split('~')
            area_id = arr[0]
            if len(area_id) > 9 or len(arr) < 10:
                continue
            lst[area_id] = f'{arr[9]}-{arr[2]}'
        return lst

    def api_url(self, api, node='d1'):
        if not self.domain:
            raise IntegrationError('Domain cannot be empty')
        base = f'https://{node}.{self.domain}/'
        api = api.lstrip('/')
        tim = int(time.time() * 1000)
        return f'{base}{api}?_={tim}'.replace('https://www', 'http://www')

    async def update_entities(self):
        for entity in self.entities.values():
            await entity.update_from_client()

    async def update_summary_and_entities(self, **kwargs):
        await self.update_summary(**kwargs)
        await self.update_entities()
        return self.data

    async def update_summary(self, **kwargs):
        api = self.api_url('weather_index/%s.html' % kwargs.get('area_id', self.area_id))
        res = await self.http.get(api, allow_redirects=False)
        txt = await res.text()
        if not txt:
            raise IntegrationError(f'Empty response from: {api}')
        if res.status != 200:
            self.data['summary_text'] = txt
        else:
            self.data.pop('summary_text', None)

        if match := re.search(r'dataSK\s*=\s*({.*?})\s*;', txt, re.DOTALL):
            self.data['dataSK'] = json.loads(match.group(1)) or {}

        if match := re.search(r'dataZS\s*=\s*({.*?})\s*;', txt, re.DOTALL):
            self.data['dataZS'] = (json.loads(match.group(1)) or {}).get('zs') or {}

        return self.data

    async def update_alarms(self, **kwargs):
        api = self.api_url('dingzhi/%s.html' % kwargs.get('area_id', self.area_id))
        res = await self.http.get(api, allow_redirects=False)
        txt = await res.text()
        if not txt:
            raise IntegrationError(f'Empty response from: {api}')
        if res.status != 200:
            self.data['alarms_text'] = txt
        else:
            self.data.pop('alarms_text', None)

        if match := re.search(r'var alarmDZ\w*\s*=\s*({.*})', txt, re.DOTALL):
            self.data['alarms'] = (json.loads(match.group(1)) or {}).get('w') or []

        return self.data

    async def update_dailies(self, **kwargs):
        api = self.api_url('weixinfc/%s.html' % kwargs.get('area_id', self.area_id))
        res = await self.http.get(api, allow_redirects=False)
        txt = await res.text()
        if not txt:
            raise IntegrationError(f'Empty response from: {api}')
        if res.status != 200:
            self.data['dailies_text'] = txt
        else:
            self.data.pop('dailies_text', None)

        if match := re.search(r'fc\s*=\s*({.*})', txt, re.DOTALL):
            self.data['dailies'] = (json.loads(match.group(1)) or {}).get('f') or []

        return self.data

    async def update_hourlies(self, **kwargs):
        api = self.api_url('wap_180h/%s.html' % kwargs.get('area_id', self.area_id))
        res = await self.http.get(api, allow_redirects=False)
        txt = await res.text()
        if not txt:
            raise IntegrationError(f'Empty response from: {api}')
        if res.status != 200:
            self.data['hourlies_text'] = txt
        else:
            self.data.pop('hourlies_text', None)

        if match := re.search(r'fc180\s*=\s*({.*})', txt, re.DOTALL):
            self.data['hourlies'] = (json.loads(match.group(1)) or {}).get('jh') or []

        return self.data

    async def update_minutely(self, **kwargs):
        api = self.api_url('webgis_rain_new/webgis/minute', 'd3')
        pms = {
            'lat': self.station.latitude,
            'lon': self.station.longitude,
        }
        res = await self.http.get(api, params=pms, allow_redirects=False)
        txt = await res.text()
        if not txt:
            raise IntegrationError(f'Empty response from: {api} {pms}')
        if res.status != 200:
            self.data['minutely_text'] = txt
        else:
            self.data.pop('minutely_text', None)

        self.data['minutely'] = json.loads(txt) or {}

        return self.data

    async def update_observe(self, **kwargs):
        api = self.api_url('weather/%s.shtml' % kwargs.get('area_id', self.area_id), 'www')
        res = await self.http.get(api, allow_redirects=False, verify_ssl=False)
        txt = await res.text()

        fmt = '%Y%m%d%H%M'
        dat = {}
        if match := re.search(r'observe24h_data\s*=\s*({.*?})\s*;', txt, re.DOTALL):
            rdt = (json.loads(match.group(1)) or {}).get('od') or {}
            lst = rdt.get('od2') or []
            lst.reverse()
            stm = datetime.strptime(rdt.get('od0', ''), fmt)
            for v in lst:
                tim = stm.replace(hour=int(v.get('od21', 0)))
                if tim < stm:
                    tim = tim + timedelta(days=1)
                stm = tim
                try:
                    dat[tim.strftime(fmt)] = {
                        **v,
                        'aqi': v.get('od28'),
                        'temp': float(v.get('od22')),
                        'humi': float(v.get('od27')),
                        'rain': float(v.get('od26') or 0),
                        'wind': v.get('od24'),
                        'wind_level': float(v.get('od25') or 0),
                        'wind_angel': float(v.get('od23') or 0),
                    }
                except (TypeError, ValueError):
                    pass
        if dat:
            self.data['observe'] = dat
        return dat

class StationInfo:
    def __init__(self, data: dict):
        self.data = data
        self.area_id = data.get('areaid')
        self.area_name = data.get('namecn')
        self.area_code = data.get('nameen')
        self.latitude = data.get('lat')
        self.longitude = data.get('lng')
