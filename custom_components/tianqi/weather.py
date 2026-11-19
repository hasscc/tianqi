"""Weather platform for the tianqi integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from homeassistant.components.weather import (
    ATTR_CONDITION_CLOUDY,
    ATTR_CONDITION_EXCEPTIONAL,
    ATTR_CONDITION_FOG,
    ATTR_CONDITION_HAIL,
    ATTR_CONDITION_LIGHTNING_RAINY,
    ATTR_CONDITION_PARTLYCLOUDY,
    ATTR_CONDITION_POURING,
    ATTR_CONDITION_RAINY,
    ATTR_CONDITION_SNOWY,
    ATTR_CONDITION_SNOWY_RAINY,
    ATTR_CONDITION_SUNNY,
    ATTR_CONDITION_WINDY,
    Forecast,
    WeatherEntityFeature,
)
from homeassistant.components.weather import (
    WeatherEntity as BaseEntity,
)
from homeassistant.const import (
    Platform,
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from . import async_add_setuper
from .client import TianqiClient
from .const import HTTP_REFERER

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the weather platform from a config entry."""
    await async_add_setuper(
        hass, config_entry, Platform.WEATHER, _setuper(async_add_entities)
    )


async def async_setup_platform(
    hass: HomeAssistant,
    config: dict[str, Any],
    async_add_entities: AddEntitiesCallback,
    discovery_info: dict[str, Any] | None = None,
) -> None:
    """Set up the weather platform from YAML."""
    await async_add_setuper(
        hass,
        config or discovery_info or {},
        Platform.WEATHER,
        _setuper(async_add_entities),
    )


def _setuper(add_entities: AddEntitiesCallback) -> Any:
    """Return the setuper of this platform."""

    def setup(client: TianqiClient) -> None:
        entity = client.entities.get(Platform.WEATHER) or WeatherEntity(client)
        if not entity.added:
            add_entities([entity])

    return setup


def _as_float(value: Any, unit: str = "") -> float | None:
    """Return a float from a raw value which may carry a unit suffix."""
    try:
        return float(f"{value}".strip().replace(unit, ""))
    except (TypeError, ValueError):
        return None


class TianqiForecast(Forecast, total=False):
    """Forecast with the extra attribute used by the caiyun card."""

    skycon: str


class WeatherEntity(BaseEntity):
    """Weather entity of a tianqi station."""

    _attr_should_poll = False

    added = False

    def __init__(self, client: TianqiClient) -> None:
        """Initialize the weather entity."""
        self.client = client
        self.hass = client.hass
        self.entity_id = f"{Platform.WEATHER}.{slugify(client.station_code)}"
        self._attr_name = client.station_name
        self._attr_unique_id = f"{client.entry_id}-{Platform.WEATHER}"
        self._attr_device_info = client.device_info
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._attr_supported_features = (
            WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
        )
        self._attr_native_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_native_pressure_unit = UnitOfPressure.HPA
        self._attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
        self._attr_native_visibility_unit = UnitOfLength.KILOMETERS
        self._attr_native_precipitation_unit = UnitOfLength.MILLIMETERS
        self.support_caiyun = client.config.get("caiyun")

    async def async_added_to_hass(self) -> None:
        """Run when the entity has been added to Home Assistant."""
        await super().async_added_to_hass()
        self.added = True
        self.client.entities[Platform.WEATHER] = self
        await self.async_update_from_client()

    async def async_update_from_client(self) -> None:
        """Refresh the entity from the data of the client."""
        data = self.client.data
        data_zs = data.get("dataZS") or {}
        data_sk = data.get("dataSK") or {}
        code = data_sk.get("weathercode", "")
        if code not in ConditionCodes.__members__:
            return

        condition = ConditionCodes[code].value
        self._attr_condition = condition[0]
        self._attr_humidity = _as_float(data_sk.get("sd"), "%")
        self._attr_native_pressure = _as_float(data_sk.get("qy"))
        self._attr_native_temperature = _as_float(data_sk.get("temp"))
        self._attr_native_wind_speed = _as_float(data_sk.get("wse"), "km/h")
        self._attr_native_visibility = _as_float(data_sk.get("njd"), "km")
        self._attr_wind_bearing = data_sk.get("WD") or data_sk.get("wde")
        self._attr_extra_state_attributes = {
            "condition_desc": data_sk.get("weather"),
            "skycon": condition[1],
            "aqi": data_sk.get("aqi"),
            "limit_number": data_sk.get("limitnumber"),
            "area_id": self.client.area_id,
            "forecast_minutely": (data.get("minutely") or {}).get("msg"),
            "forecast_hourly": data_zs.get("ct_des_s"),
            "forecast_keypoint": data_zs.get("ys_des_s"),
            "forecast_alert": {"status": "", "content": []},
            "updated_time": data_sk.get("time"),
        }

        if alarms := data.get("alarms") or []:
            self._attr_extra_state_attributes["forecast_alert"] = {
                "status": "ok",
                "content": [
                    {
                        "province": alarm.get("w1"),
                        "city": alarm.get("w2"),
                        "code": f"{alarm.get('w4')}{alarm.get('w6')}",
                        "title": alarm.get("w13", ""),
                        "description": alarm.get("w9", ""),
                        "alertld": alarm.get("w16"),
                        "link": (
                            f"{HTTP_REFERER}warning/publish_area.shtml"
                            f"?code={self.client.area_id}"
                        ),
                    }
                    for alarm in alarms
                ],
            }

        indexes: dict[str, Any] = {}
        indexes_short: dict[str, Any] = {}
        for key, name in data_zs.items():
            if "_name" not in key:
                continue
            short_key = f"{key}".replace("_name", "")
            if not (description := data_zs.get(f"{short_key}_des_s")):
                continue
            indexes[name] = description
            if hint := data_zs.get(f"{short_key}_hint"):
                indexes_short[f"{name}".removesuffix("指数")] = hint
        if indexes:
            self._attr_extra_state_attributes["indexes"] = indexes
        if indexes_short:
            self._attr_extra_state_attributes["indexes_short"] = indexes_short

        forecasts = await self.async_forecast_daily()
        if self.support_caiyun:
            self._attr_extra_state_attributes["forecast"] = forecasts

        await self.async_forecast_hourly()
        self.async_write_ha_state()

    async def async_forecast_daily(self) -> list[Forecast] | None:
        """Return the daily forecast in native units."""
        now = dt_util.now()
        forecasts: list[Forecast] = []
        if "dailies" not in self.client.data:
            await self.client.async_update_dailies()
        for item in self.client.data.get("dailies") or []:
            code = f"d{item.get('fa')}"
            if code not in ConditionCodes.__members__:
                continue
            condition = ConditionCodes[code].value
            row: TianqiForecast = {
                "condition": condition[0],
                "skycon": condition[1],
                "native_precipitation": condition[2],
            }
            day_of_month = item.get("fi", "")
            today = now.strftime("%m/%d").replace("/0", "/").lstrip("0")
            is_today = day_of_month == today
            try:
                day = datetime.strptime(day_of_month, "%m/%d")
                moment = now.replace(
                    month=day.month,
                    day=day.day,
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
                row["datetime"] = moment
            except (TypeError, ValueError):
                continue

            rain = _as_float((self.client.data.get("dataSK") or {}).get("rain"))
            if rain and moment.date() == now.date():
                row["native_precipitation"] = rain
            if (humidity := _as_float(item.get("fn"))) is not None:
                row["humidity"] = humidity
            if (high := _as_float(item.get("fc"))) is not None:
                row["native_temperature"] = high
                if is_today:
                    self._attr_extra_state_attributes["temphigh"] = high
            if (low := _as_float(item.get("fd"))) is not None:
                row["native_templow"] = low
                if is_today:
                    self._attr_extra_state_attributes["templow"] = low
            row["wind_bearing"] = item.get("fe")
            forecasts.append(row)
        return forecasts

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        """Return the hourly forecast in native units."""
        if self.support_caiyun:
            for key in (
                "hourly_temperature",
                "hourly_skycon",
                "hourly_cloudrate",
                "hourly_precipitation",
            ):
                self._attr_extra_state_attributes.setdefault(key, [])

        forecasts: list[Forecast] = []
        if "hourlies" not in self.client.data:
            await self.client.async_update_hourlies()
        for item in self.client.data.get("hourlies") or []:
            if len(forecasts) > 48:
                break
            code = f"d{item.get('ja')}"
            if code not in ConditionCodes.__members__:
                continue
            condition = ConditionCodes[code].value
            row: TianqiForecast = {
                "condition": condition[0],
                "skycon": condition[1],
                "native_precipitation": condition[2],
            }
            stamp = item.get("jf", "")
            observed = (self.client.data.get("observe") or {}).get(stamp) or {}
            if observed:
                row["native_precipitation"] = observed.get("rain")
            try:
                day = datetime.strptime(stamp, "%Y%m%d%H%M")
                moment = dt_util.now().replace(
                    month=day.month,
                    day=day.day,
                    hour=day.hour,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
                row["datetime"] = moment
            except (TypeError, ValueError):
                continue
            if dt_util.now() - moment > timedelta(hours=1.5):
                continue
            if (humidity := _as_float(item.get("je"))) is not None:
                row["humidity"] = humidity
            if (temperature := _as_float(item.get("jb"))) is not None:
                row["native_temperature"] = temperature
            if (pressure := _as_float(item.get("jj"))) is not None:
                row["native_pressure"] = pressure
            if (wind_speed := _as_float(item.get("jg"))) is not None:
                row["native_wind_speed"] = wind_speed
            row["wind_bearing"] = observed.get("wind")
            forecasts.append(row)

            if self.support_caiyun:
                self._attr_extra_state_attributes["hourly_temperature"].append(
                    {"datetime": moment, "value": row.get("native_temperature")}
                )
                self._attr_extra_state_attributes["hourly_precipitation"].append(
                    {"datetime": moment, "value": row.get("native_precipitation")}
                )
                self._attr_extra_state_attributes["hourly_skycon"].append(
                    {"datetime": moment, "value": condition[1]}
                )
                self._attr_extra_state_attributes["hourly_cloudrate"].append(
                    {"datetime": moment, "value": condition[3] / 100}
                )
        return forecasts


class ConditionCodes(Enum):
    """Weather condition codes of weather.com.cn.

    Value layout: (state, skycon, precipitation in mm/h, cloud coverage, name).
    """

    d00 = (ATTR_CONDITION_SUNNY, "CLEAR_DAY", 0, 10, "晴")
    d01 = (ATTR_CONDITION_PARTLYCLOUDY, "PARTLY_CLOUDY_DAY", 0, 50, "多云")
    d02 = (ATTR_CONDITION_CLOUDY, "CLOUDY", 0, 80, "阴")
    d03 = (ATTR_CONDITION_RAINY, "MODERATE_RAIN", 0.1, 70, "阵雨")
    d04 = (ATTR_CONDITION_LIGHTNING_RAINY, "LIGHT_RAIN", 0.1, 80, "雷阵雨")
    d05 = (ATTR_CONDITION_HAIL, "LIGHT_RAIN", 0.2, 80, "雷阵雨伴有冰雹")
    d06 = (ATTR_CONDITION_SNOWY_RAINY, "LIGHT_SNOW", 0.5, 90, "雨夹雪")
    d07 = (ATTR_CONDITION_RAINY, "LIGHT_RAIN", 0.5, 90, "小雨")
    d08 = (ATTR_CONDITION_RAINY, "MODERATE_RAIN", 1.0, 100, "中雨")
    d09 = (ATTR_CONDITION_RAINY, "HEAVY_RAIN", 2.0, 100, "大雨")
    d10 = (ATTR_CONDITION_POURING, "STORM_RAIN", 4.0, 100, "暴雨")
    d11 = (ATTR_CONDITION_POURING, "STORM_RAIN", 10.0, 100, "大暴雨")
    d12 = (ATTR_CONDITION_POURING, "STORM_RAIN", 20.0, 100, "特大暴雨")
    d13 = (ATTR_CONDITION_SNOWY, "LIGHT_SNOW", 0.1, 90, "阵雪")
    d14 = (ATTR_CONDITION_SNOWY, "LIGHT_SNOW", 0.25, 90, "小雪")
    d15 = (ATTR_CONDITION_SNOWY, "MODERATE_SNOW", 0.5, 100, "中雪")
    d16 = (ATTR_CONDITION_SNOWY, "HEAVY_SNOW", 1.0, 100, "大雪")
    d17 = (ATTR_CONDITION_SNOWY, "STORM_SNOW", 2.0, 100, "暴雪")
    d18 = (ATTR_CONDITION_FOG, "LIGHT_HAZE", 0, 80, "雾")
    d19 = (ATTR_CONDITION_HAIL, "LIGHT_RAIN", 0.5, 100, "冻雨")
    d20 = (ATTR_CONDITION_EXCEPTIONAL, "SAND", 0, 70, "沙尘暴")
    d21 = (ATTR_CONDITION_RAINY, "MODERATE_RAIN", 0.8, 90, "小到中雨")
    d22 = (ATTR_CONDITION_RAINY, "HEAVY_RAIN", 1.5, 100, "中到大雨")
    d23 = (ATTR_CONDITION_POURING, "STORM_RAIN", 3.0, 100, "大到暴雨")
    d24 = (ATTR_CONDITION_POURING, "STORM_RAIN", 7.0, 100, "暴雨到大暴雨")
    d25 = (ATTR_CONDITION_POURING, "STORM_RAIN", 15.0, 100, "大暴雨到特大暴雨")
    d26 = (ATTR_CONDITION_SNOWY, "MODERATE_SNOW", 0.35, 90, "小到中雪")
    d27 = (ATTR_CONDITION_SNOWY, "HEAVY_SNOW", 0.75, 100, "中到大雪")
    d28 = (ATTR_CONDITION_SNOWY, "STORM_SNOW", 1.5, 100, "大到暴雪")
    d29 = (ATTR_CONDITION_WINDY, "DUST", 0, 60, "浮尘")
    d30 = (ATTR_CONDITION_WINDY, "DUST", 0, 60, "扬沙")
    d31 = (ATTR_CONDITION_EXCEPTIONAL, "SAND", 0, 80, "强沙尘暴")
    d32 = (ATTR_CONDITION_FOG, "FOG", 0, 90, "浓雾")
    d49 = (ATTR_CONDITION_FOG, "FOG", 0, 100, "强浓雾")
    d53 = (ATTR_CONDITION_FOG, "LIGHT_HAZE", 0, 90, "霾")
    d54 = (ATTR_CONDITION_FOG, "MODERATE_HAZE", 90, 0, "中度霾")
    d55 = (ATTR_CONDITION_FOG, "HEAVY_HAZE", 0, 100, "重度霾")
    d56 = (ATTR_CONDITION_FOG, "HEAVY_HAZE", 0, 100, "严重霾")
    d57 = (ATTR_CONDITION_FOG, "FOG", 0, 100, "大雾")
    d58 = (ATTR_CONDITION_FOG, "FOG", 0, 100, "特强浓雾")
    d301 = (ATTR_CONDITION_RAINY, "MODERATE_RAIN", 1.0, 100, "雨")
    d302 = (ATTR_CONDITION_SNOWY, "MODERATE_SNOW", 0.5, 100, "雪")
