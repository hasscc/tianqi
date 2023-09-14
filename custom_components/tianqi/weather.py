from __future__ import annotations

import logging
import enum

from datetime import datetime

from homeassistant.components.weather import *
from homeassistant.components.weather import (
    DOMAIN as ENTITY_DOMAIN,
    WeatherEntity as BaseEntity,
)
from homeassistant.util import dt
from homeassistant.const import *

try:
    # hass 2023.9
    from homeassistant.components.weather import WeatherEntityFeature
except (ModuleNotFoundError, ImportError):
    WeatherEntityFeature = None

from . import TianqiClient, async_add_setuper, HTTP_REFERER

_LOGGER = logging.getLogger(__name__)


def setuper(add_entities):
    def setup(client: TianqiClient):
        if not (entity := client.entities.get(ENTITY_DOMAIN)):
            entity = WeatherEntity(client)
        if not entity.added:
            add_entities([entity])
    return setup


async def async_setup_entry(hass, config_entry, async_add_entities):
    await async_add_setuper(hass, config_entry, ENTITY_DOMAIN, setuper(async_add_entities))


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    await async_add_setuper(hass, config or discovery_info, ENTITY_DOMAIN, setuper(async_add_entities))


class WeatherEntity(BaseEntity):
    added = False
    _attr_should_poll = False

    def __init__(self, client: TianqiClient):
        self.client = client
        self.hass = client.hass

        station = client.station
        code = station.area_code or station.area_name or self.hass.config.location_name
        self.entity_id = f'{ENTITY_DOMAIN}.{code}'
        self._attr_name = station.area_name or code
        self._attr_unique_id = f'{client.entry_id}-{ENTITY_DOMAIN}'
        self._attr_attribution = None
        self._attr_supported_features = 0
        if WeatherEntityFeature:
            self._attr_supported_features |= WeatherEntityFeature.FORECAST_DAILY
            self._attr_supported_features |= WeatherEntityFeature.FORECAST_HOURLY
        self.support_caiyun = client.config.get('caiyun')

    async def async_added_to_hass(self):
        self.added = True
        self.client.entities[ENTITY_DOMAIN] = self

        await super().async_added_to_hass()
        await self.update_from_client()

    async def update_from_client(self):
        dat = self.client.data
        dataZS = dat.get('dataZS') or {}
        dataSK = dat.get('dataSK') or {}
        code = dataSK.get('weathercode', '')
        if code not in ConditionCodes.__members__:
            return
        self._attr_condition = ConditionCodes[code].value[0]
        self._attr_humidity = float(dataSK.get('sd', '').replace('%', ''))
        self._attr_native_pressure = float(dataSK.get('qy', ''))
        self._attr_native_pressure_unit = UnitOfPressure.HPA
        self._attr_native_temperature = float(dataSK.get('temp', ''))
        self._attr_native_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_native_wind_speed = float(dataSK.get('wse', '').replace('km/h', ''))
        self._attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
        self._attr_native_visibility = float(dataSK.get('njd', '').replace('km', ''))
        self._attr_native_visibility_unit = UnitOfLength.KILOMETERS
        self._attr_wind_bearing = dataSK.get('WD') or dataSK.get('wde')
        self._attr_native_precipitation_unit = UnitOfLength.MILLIMETERS
        self._attr_extra_state_attributes = {
            'condition_desc': dataSK.get('weather'),
            'skycon': ConditionCodes[code].value[1],
            'aqi': dataSK.get('aqi'),
            'limit_number': dataSK.get('limitnumber'),
            'area_id': self.client.area_id,
            'forecast_minutely': self.client.data.get('minutely', {}).get('msg'),
            'forecast_hourly': dataZS.get('ct_des_s'),
            'forecast_keypoint': dataZS.get('ys_des_s'),
            'forecast_alert': {'status': '', 'content': []},
            'updated_time': dataSK.get('time'),
        }

        if alarms := dat.get('alarms') or []:
            self._attr_extra_state_attributes['forecast_alert'] = {'status': 'ok', 'content': [
                {
                    'province': v.get('w1'),
                    'city': v.get('w2'),
                    'code': f'{v.get("w4")}{v.get("w6")}',
                    'title': v.get('w13', ''),
                    'description': v.get('w9', ''),
                    'alertld': v.get('w16'),
                    'link': f'{HTTP_REFERER}warning/publish_area.shtml?code={self.client.area_id}',
                }
                for v in alarms
            ]}

        indexes = {}
        for k, v in dataZS.items():
            if '_name' not in k:
                continue
            key = f'{k}'.replace('_name', '')
            if not (des := dataZS.get(f'{key}_des_s')):
                continue
            indexes[v] = des
        if indexes:
            self._attr_extra_state_attributes['indexes'] = indexes

        if not WeatherEntityFeature or 1:
            self._attr_forecast = await self.async_forecast_daily()
        await self.async_forecast_hourly()

        self.async_write_ha_state()

    async def async_forecast_daily(self) -> list[Forecast] | None:
        """Return the daily forecast in native units.
        Only implement this method if `WeatherEntityFeature.FORECAST_DAILY` is set
        """
        lst = []
        for item in self.client.data.get('dailies', []):
            code = f'd{item.get("fa")}'
            if code not in ConditionCodes.__members__:
                continue
            row = {
                'condition': ConditionCodes[code].value[0],
                'skycon': ConditionCodes[code].value[1],
                'native_precipitation': ConditionCodes[code].value[2],
            }
            try:
                day = datetime.strptime(item.get('fi', ''), '%m/%d')
                tim = dt.now().replace(
                    month=day.month, day=day.day, hour=0,
                    minute=0, second=0, microsecond=0,
                )
                row['datetime'] = tim
            except (TypeError, ValueError):
                continue
            try:
                precipitation = self.client.data.get('dataSK', {}).get('rain')
                if precipitation and tim.date() == dt.now().date():
                    row['native_precipitation'] = float(precipitation)
            except (TypeError, ValueError):
                pass
            try:
                row['humidity'] = float(item.get('fn'))
            except (TypeError, ValueError):
                pass
            try:
                row['native_temperature'] = float(item.get('fc'))
            except (TypeError, ValueError):
                pass
            try:
                row['native_templow'] = float(item.get('fd'))
            except (TypeError, ValueError):
                pass
            row['wind_bearing'] = item.get('fe')
            lst.append(row)
        return lst

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        """Return the hourly forecast in native units.
        Only implement this method if `WeatherEntityFeature.FORECAST_HOURLY` is set
        """
        if self.support_caiyun:
            self._attr_extra_state_attributes.setdefault('hourly_temperature', [])
            self._attr_extra_state_attributes.setdefault('hourly_skycon', [])
            self._attr_extra_state_attributes.setdefault('hourly_cloudrate', [])
            self._attr_extra_state_attributes.setdefault('hourly_precipitation', [])
        lst = []
        for item in self.client.data.get('hourlies', []):
            if len(lst) > 48:
                break
            code = f'd{item.get("ja")}'
            if code not in ConditionCodes.__members__:
                continue
            row = {
                'condition': ConditionCodes[code].value[0],
                'skycon': ConditionCodes[code].value[1],
                'native_precipitation': ConditionCodes[code].value[2],
            }
            ymd = item.get('jf', '')
            observe = self.client.data.get('observe', {}).get(ymd) or {}
            if observe:
                row['native_precipitation'] = observe.get('rain')
            try:
                day = datetime.strptime(ymd, '%Y%m%d%H%M')
                tim = dt.now().replace(
                    month=day.month, day=day.day, hour=day.hour,
                    minute=0, second=0, microsecond=0,
                )
                row['datetime'] = tim
            except (TypeError, ValueError):
                continue
            if dt.now() - tim > timedelta(hours=1.5):
                continue
            try:
                row['humidity'] = float(item.get('je'))
            except (TypeError, ValueError):
                pass
            try:
                row['native_temperature'] = float(item.get('jb'))
            except (TypeError, ValueError):
                pass
            try:
                row['native_pressure'] = float(item.get('jj'))
            except (TypeError, ValueError):
                pass
            try:
                row['native_wind_speed'] = float(item.get('jg'))
            except (TypeError, ValueError):
                pass
            row['wind_bearing'] = observe.get('wind')
            lst.append(row)

            if self.support_caiyun:
                self._attr_extra_state_attributes['hourly_temperature'].append({
                    'datetime': tim,
                    'value': row.get('native_temperature'),
                })
                self._attr_extra_state_attributes['hourly_precipitation'].append({
                    'datetime': tim,
                    'value': row.get('native_precipitation'),
                })
                self._attr_extra_state_attributes['hourly_skycon'].append({
                    'datetime': tim,
                    'value': ConditionCodes[code].value[1],
                })
                self._attr_extra_state_attributes['hourly_cloudrate'].append({
                    'datetime': tim,
                    'value': ConditionCodes[code].value[3] / 100,
                })
        return lst

class ConditionCodes(enum.Enum):
    # [state, skycon, precipitation(mm/h), cloud_coverage(%), name]
    d00 = [ATTR_CONDITION_SUNNY, 'CLEAR_DAY', 0, 10, '晴']
    d01 = [ATTR_CONDITION_PARTLYCLOUDY, 'PARTLY_CLOUDY_DAY', 0, 50, '多云']
    d02 = [ATTR_CONDITION_CLOUDY, 'CLOUDY', 0, 80, '阴']
    d03 = [ATTR_CONDITION_RAINY, 'MODERATE_RAIN', 0.1, 70, '阵雨']
    d04 = [ATTR_CONDITION_LIGHTNING_RAINY, 'LIGHT_RAIN', 0.1, 80, '雷阵雨']
    d05 = [ATTR_CONDITION_HAIL, 'LIGHT_RAIN', 0.2, 80, '雷阵雨伴有冰雹']
    d06 = [ATTR_CONDITION_SNOWY_RAINY, 'LIGHT_SNOW', 0.5, 90, '雨夹雪']
    d07 = [ATTR_CONDITION_RAINY, 'LIGHT_RAIN', 0.5, 90, '小雨']
    d08 = [ATTR_CONDITION_RAINY, 'MODERATE_RAIN', 1.0, 100, '中雨']
    d09 = [ATTR_CONDITION_RAINY, 'HEAVY_RAIN', 2.0, 100, '大雨']
    d10 = [ATTR_CONDITION_POURING, 'STORM_RAIN', 4.0, 100, '暴雨']
    d11 = [ATTR_CONDITION_POURING, 'STORM_RAIN', 10.0, 100, '大暴雨']
    d12 = [ATTR_CONDITION_POURING, 'STORM_RAIN', 20.0, 100, '特大暴雨']
    d13 = [ATTR_CONDITION_SNOWY, 'LIGHT_SNOW', 0.1, 90, '阵雪']
    d14 = [ATTR_CONDITION_SNOWY, 'LIGHT_SNOW', 0.25, 90, '小雪']
    d15 = [ATTR_CONDITION_SNOWY, 'MODERATE_SNOW', 0.5, 100, '中雪']
    d16 = [ATTR_CONDITION_SNOWY, 'HEAVY_SNOW', 1.0, 100, '大雪']
    d17 = [ATTR_CONDITION_SNOWY, 'STORM_SNOW', 2.0, 100, '暴雪']
    d18 = [ATTR_CONDITION_FOG, 'LIGHT_HAZE', 0, 80, '雾']
    d19 = [ATTR_CONDITION_HAIL, 'LIGHT_RAIN', 0.5, 100, '冻雨']
    d20 = [ATTR_CONDITION_EXCEPTIONAL, 'SAND', 0, 70, '沙尘暴']
    d21 = [ATTR_CONDITION_RAINY, 'MODERATE_RAIN', 0.8, 90, '小到中雨']
    d22 = [ATTR_CONDITION_RAINY, 'HEAVY_RAIN', 1.5, 100, '中到大雨']
    d23 = [ATTR_CONDITION_POURING, 'STORM_RAIN', 3.0, 100, '大到暴雨']
    d24 = [ATTR_CONDITION_POURING, 'STORM_RAIN', 7.0, 100, '暴雨到大暴雨']
    d25 = [ATTR_CONDITION_POURING, 'STORM_RAIN', 15.0, 100, '大暴雨到特大暴雨']
    d26 = [ATTR_CONDITION_SNOWY, 'MODERATE_SNOW', 0.35, 90, '小到中雪']
    d27 = [ATTR_CONDITION_SNOWY, 'HEAVY_SNOW', 0.75, 100, '中到大雪']
    d28 = [ATTR_CONDITION_SNOWY, 'STORM_SNOW', 1.5, 100, '大到暴雪']
    d29 = [ATTR_CONDITION_WINDY, 'DUST', 0, 60, '浮尘']
    d30 = [ATTR_CONDITION_WINDY, 'DUST', 0, 60, '扬沙']
    d31 = [ATTR_CONDITION_EXCEPTIONAL, 'SAND', 0, 80, '强沙尘暴']
    d32 = [ATTR_CONDITION_FOG, 'FOG', 0, 90, '浓雾']
    d49 = [ATTR_CONDITION_FOG, 'FOG', 0, 100, '强浓雾']
    d53 = [ATTR_CONDITION_FOG, 'LIGHT_HAZE', 0, 90, '霾']
    d54 = [ATTR_CONDITION_FOG, 'MODERATE_HAZE', 90, 0, '中度霾']
    d55 = [ATTR_CONDITION_FOG, 'HEAVY_HAZE', 0, 100, '重度霾']
    d56 = [ATTR_CONDITION_FOG, 'HEAVY_HAZE', 0, 100, '严重霾']
    d57 = [ATTR_CONDITION_FOG, 'FOG', 0, 100, '大雾']
    d58 = [ATTR_CONDITION_FOG, 'FOG', 0, 100, '特强浓雾']
    d301 = [ATTR_CONDITION_RAINY, 'MODERATE_RAIN', 1.0, 100, '雨']
    d302 = [ATTR_CONDITION_SNOWY, 'MODERATE_SNOW', 0.5, 100, '雪']
