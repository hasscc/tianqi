"""Runtime client for the tianqi integration."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_DOMAIN,
    PERCENTAGE,
    UnitOfLength,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import StationInfo, TianqiApi
from .const import (
    DOMAIN,
    INTERVAL_ALARMS,
    INTERVAL_DAILIES,
    INTERVAL_HOURLIES,
    INTERVAL_MINUTELY,
    INTERVAL_OBSERVE,
    INTERVAL_SUMMARY,
)
from .converters.base import (
    MICROGRAMS_PER_CUBIC_METER,
    AlarmsBinarySensorConv,
    Converter,
    ForecastMinutelySensorConv,
    NumberSensorConv,
    SensorConv,
    WindSpeedSensorConv,
)

if TYPE_CHECKING:
    from .entity import XEntity

_LOGGER = logging.getLogger(__name__)

RE_DATA_SK = re.compile(r"dataSK\s*=\s*({.*?})\s*;", re.DOTALL)
RE_DATA_ZS = re.compile(r"dataZS\s*=\s*({.*?})\s*;", re.DOTALL)
RE_ALARMS = re.compile(r"var alarmDZ\w*\s*=\s*({.*})", re.DOTALL)
RE_DAILIES = re.compile(r"fc\s*=\s*({.*})", re.DOTALL)
RE_HOURLIES = re.compile(r"fc180\s*=\s*({.*})", re.DOTALL)
RE_OBSERVE = re.compile(r"observe24h_data\s*=\s*({.*?})\s*;", re.DOTALL)
OBSERVE_TIME_FORMAT = "%Y%m%d%H%M"


class TianqiClient:
    """Keep the shared state for a single config entry (or YAML config)."""

    def __init__(self, hass: HomeAssistant, config: Mapping[str, Any]) -> None:
        """Initialize the client."""
        self.hass = hass
        self.config = dict(config)
        self.entry_id = self.config.get("entry_id") or "yaml"
        self.entry = hass.config_entries.async_get_entry(self.entry_id)
        self.api = TianqiApi(hass, self.config.get(CONF_DOMAIN))
        self.data: dict[str, Any] = {}
        self.station: StationInfo | None = None
        self.setups: dict[str, Callable[..., Any]] = {}
        self.entities: dict[str, XEntity] = {}
        self.converters: dict[str, Converter] = {}
        self.coordinators = [
            DataUpdateCoordinator(
                hass,
                _LOGGER,
                config_entry=self.entry,
                name="alarms",
                update_method=self.async_update_alarms,
                update_interval=timedelta(minutes=INTERVAL_ALARMS),
            ),
            DataUpdateCoordinator(
                hass,
                _LOGGER,
                config_entry=self.entry,
                name="summary",
                update_method=self.async_update_summary_and_entities,
                update_interval=timedelta(seconds=INTERVAL_SUMMARY),
            ),
            DataUpdateCoordinator(
                hass,
                _LOGGER,
                config_entry=self.entry,
                name="dailies",
                update_method=self.async_update_dailies,
                update_interval=timedelta(minutes=INTERVAL_DAILIES),
            ),
            DataUpdateCoordinator(
                hass,
                _LOGGER,
                config_entry=self.entry,
                name="observe",
                update_method=self.async_update_observe,
                update_interval=timedelta(minutes=INTERVAL_OBSERVE),
            ),
            DataUpdateCoordinator(
                hass,
                _LOGGER,
                config_entry=self.entry,
                name="hourlies",
                update_method=self.async_update_hourlies,
                update_interval=timedelta(minutes=INTERVAL_HOURLIES),
            ),
            DataUpdateCoordinator(
                hass,
                _LOGGER,
                config_entry=self.entry,
                name="minutely",
                update_method=self.async_update_minutely,
                update_interval=timedelta(minutes=INTERVAL_MINUTELY),
            ),
        ]
        self._remove_listeners: list[Callable[[], None]] = []

        self.add_converters(
            NumberSensorConv("precipitation", prop="rain").with_option(
                {
                    "device_class": SensorDeviceClass.PRECIPITATION,
                    "state_class": SensorStateClass.MEASUREMENT,
                    "unit_of_measurement": UnitOfLength.MILLIMETERS,
                }
            ),
            NumberSensorConv("precipitation_24h", prop="rain24h").with_option(
                {
                    "device_class": SensorDeviceClass.PRECIPITATION,
                    "state_class": SensorStateClass.MEASUREMENT,
                    "unit_of_measurement": UnitOfLength.MILLIMETERS,
                }
            ),
            NumberSensorConv("temperature", prop="temp").with_option(
                {
                    "device_class": SensorDeviceClass.TEMPERATURE,
                    "state_class": SensorStateClass.MEASUREMENT,
                    "unit_of_measurement": UnitOfTemperature.CELSIUS,
                }
            ),
            NumberSensorConv("humidity", prop="sd", unit="%").with_option(
                {
                    "device_class": SensorDeviceClass.HUMIDITY,
                    "state_class": SensorStateClass.MEASUREMENT,
                    "unit_of_measurement": PERCENTAGE,
                }
            ),
            NumberSensorConv("pm25", prop="aqi_pm25").with_option(
                {
                    "device_class": SensorDeviceClass.PM25,
                    "state_class": SensorStateClass.MEASUREMENT,
                    "unit_of_measurement": MICROGRAMS_PER_CUBIC_METER,
                }
            ),
            NumberSensorConv("atmospheric_pressure", prop="qy").with_option(
                {
                    "device_class": SensorDeviceClass.ATMOSPHERIC_PRESSURE,
                    "state_class": SensorStateClass.MEASUREMENT,
                    "unit_of_measurement": UnitOfPressure.HPA,
                }
            ),
            NumberSensorConv("visibility", prop="njd", unit="km").with_option(
                {
                    "device_class": SensorDeviceClass.DISTANCE,
                    "state_class": SensorStateClass.MEASUREMENT,
                    "unit_of_measurement": UnitOfLength.KILOMETERS,
                }
            ),
            WindSpeedSensorConv(),
            AlarmsBinarySensorConv(),
            ForecastMinutelySensorConv(),
            SensorConv("limit_number", prop="limitnumber", enabled=False).with_option(
                {
                    "icon": "mdi:counter",
                }
            ),
        )

    @classmethod
    async def async_get(
        cls, hass: HomeAssistant, entry: ConfigEntry | Mapping[str, Any]
    ) -> TianqiClient:
        """Return the client of a config entry (or of the YAML config)."""
        hass.data.setdefault(DOMAIN, {})
        clients: dict[str, TianqiClient] = hass.data[DOMAIN].setdefault("clients", {})
        if isinstance(entry, ConfigEntry):
            config: dict[str, Any] = {
                "entry_id": entry.entry_id,
                **entry.data,
                **entry.options,
            }
        else:
            config = dict(entry)

        entry_id = config.get("entry_id") or "yaml"
        client = clients.get(entry_id)
        if client is None:
            client = cls(hass, config)
            clients[entry_id] = client
            _LOGGER.info("New client: %s", config)

        if not client.station:
            client.station = await client.api.async_get_station(
                area_id=config.get("area_id")
            )
            _LOGGER.info("New station: %s", [entry_id, client.station.data])
        return client

    async def async_init(self) -> None:
        """Fetch the initial data and start the coordinators."""
        if not self.station:
            self.station = await self.api.async_get_station()

        for coordinator in self.coordinators:

            @callback
            def _handle_coordinator_update(name: str = coordinator.name) -> None:
                _LOGGER.debug("Coordinator %s done", name)

            self._remove_listeners.append(
                coordinator.async_add_listener(_handle_coordinator_update)
            )
            try:
                if self.entry is not None:
                    await coordinator.async_config_entry_first_refresh()
                else:
                    await coordinator.async_refresh()
            except Exception:  # noqa: BLE001 - a missing minutely forecast is fine
                if coordinator.name != "minutely":
                    raise
                _LOGGER.warning(
                    "Unable to fetch minutely forecast; continuing setup without it",
                    exc_info=True,
                )

    async def async_unload(self, *args: Any) -> None:
        """Stop listening to the coordinators."""
        while self._remove_listeners:
            self._remove_listeners.pop()()
        self._remove_listeners = []

    def add_converter(self, converter: Converter) -> None:
        """Register a converter."""
        self.converters[converter.attr] = converter

    def add_converters(self, *converters: Converter) -> None:
        """Register multiple converters."""
        for converter in converters:
            self.add_converter(converter)

    def subscribe_attrs(self, converter: Converter) -> set[str]:
        """Return the payload attributes the given converter subscribes to."""
        attrs = {converter.attr}
        if converter.childs:
            attrs |= set(converter.childs)
        attrs.update(
            item.attr
            for item in self.converters.values()
            if item.parent == converter.attr
        )
        return attrs

    def decode(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Decode a raw payload for Home Assistant."""
        payload: dict[str, Any] = {}
        for converter in self.converters.values():
            prop = converter.prop or converter.attr
            if converter.ignore_prop:
                value = data
            elif prop in data:
                value = data[prop]
            else:
                continue
            converter.decode(self, payload, value)
        return payload

    def push_state(self, value: dict[str, Any]) -> None:
        """Push new states to the entities."""
        if not value:
            return
        attrs = value.keys()
        for entity in self.entities.values():
            if not hasattr(entity, "subscribed_attrs"):
                continue
            if not entity.subscribed_attrs & attrs:
                continue
            entity.async_set_state(value)
            if entity.added:
                entity.async_write_ha_state()

    async def setup_entities(self, only_domain: str | None = None) -> None:
        """Create the entities of the given (or of every) platform."""
        if not self.converters:
            _LOGGER.warning("Has none converters: %s", [type(self), self.config])
        for converter in self.converters.values():
            if only_domain and only_domain != converter.domain:
                continue
            if converter.domain is None or converter.attr in self.entities:
                continue
            await self.setup_entity(converter)

    async def setup_entity(self, converter: Converter) -> None:
        """Hand a converter over to its platform."""
        handler = self.setups.get(converter.domain)
        if handler:
            handler(self, converter)
        else:
            _LOGGER.warning(
                "Setup %s not ready for %s", converter.domain, [self, converter]
            )

    async def async_update_entities(self) -> None:
        """Ask every entity to refresh from the current data."""
        for entity in self.entities.values():
            if not hasattr(entity, "async_update_from_client"):
                continue
            await entity.async_update_from_client()

    async def async_update_summary_and_entities(self) -> dict[str, Any]:
        """Refresh the current weather and the entities using it."""
        await self.async_update_summary()
        await self.async_update_entities()
        return self.data

    async def async_fetch(self, path: str, node: str = "d1") -> tuple[int, str]:
        """Fetch a page from the configured domain."""
        return await self.api.async_fetch(path, node)

    async def async_get_station(
        self,
        area_id: str | None = None,
        lat: float | None = None,
        lng: float | None = None,
    ) -> StationInfo:
        """Return the station information as a service response."""
        station = await self.api.async_get_station(area_id=area_id, lat=lat, lng=lng)
        return station.data

    def web_url(self, path: str, node: str = "m") -> str:
        """Return a human readable web page URL."""
        return self.api.web_url(path, node)

    async def async_update_summary(self, **kwargs: Any) -> dict[str, Any]:
        """Refresh the current weather."""
        area_id = kwargs.get("area_id") or self.area_id
        status, text = await self.async_fetch(f"weather_index/{area_id}.html")
        if status != 200:
            self.data["summary_text"] = text
        else:
            self.data.pop("summary_text", None)

        if match := RE_DATA_SK.search(text):
            self.data["dataSK"] = json.loads(match.group(1)) or {}
            self.push_state(self.decode(self.data["dataSK"]))

        if match := RE_DATA_ZS.search(text):
            self.data["dataZS"] = (json.loads(match.group(1)) or {}).get("zs") or {}

        return self.data

    async def async_update_alarms(self, **kwargs: Any) -> dict[str, Any]:
        """Refresh the weather alarms."""
        area_id = kwargs.get("area_id") or self.area_id
        status, text = await self.async_fetch(f"dingzhi/{area_id}.html")
        if status != 200:
            self.data["alarms_text"] = text
        else:
            self.data.pop("alarms_text", None)

        if match := RE_ALARMS.search(text):
            self.data["alarms"] = (json.loads(match.group(1)) or {}).get("w") or []
            self.push_state(self.decode(self.data))

        return self.data

    async def async_update_dailies(self, **kwargs: Any) -> dict[str, Any]:
        """Refresh the daily forecast."""
        area_id = kwargs.get("area_id") or self.area_id
        status, text = await self.async_fetch(f"weixinfc/{area_id}.html")
        if status != 200:
            self.data["dailies_text"] = text
        else:
            self.data.pop("dailies_text", None)

        if match := RE_DAILIES.search(text):
            self.data["dailies"] = (json.loads(match.group(1)) or {}).get("f") or []

        return self.data

    async def async_update_hourlies(self, **kwargs: Any) -> dict[str, Any]:
        """Refresh the hourly forecast."""
        area_id = kwargs.get("area_id") or self.area_id
        status, text = await self.async_fetch(f"wap_180h/{area_id}.html")
        if status != 200:
            self.data["hourlies_text"] = text
        else:
            self.data.pop("hourlies_text", None)

        if match := RE_HOURLIES.search(text):
            self.data["hourlies"] = (json.loads(match.group(1)) or {}).get("jh") or []

        return self.data

    async def async_update_minutely(self, **kwargs: Any) -> dict[str, Any]:
        """Refresh the minutely forecast."""
        _, text = await self.api.async_fetch(
            "mpf_v3/webgis/minute",
            "mpf",
            params={
                "lat": self.station.latitude,
                "lon": self.station.longitude,
            },
        )
        self.data["minutely"] = json.loads(text) or {}
        self.push_state(self.decode(self.data["minutely"]))
        await self.async_update_entities()
        return self.data

    async def async_update_observe(self, **kwargs: Any) -> dict[str, Any]:
        """Refresh the observed data of the last 24 hours."""
        area_id = kwargs.get("area_id") or self.area_id
        _, text = await self.async_fetch(f"weather/{area_id}.shtml", "www")

        data: dict[str, Any] = {}
        if not (match := RE_OBSERVE.search(text)):
            return data

        observed = (json.loads(match.group(1)) or {}).get("od") or {}
        rows = observed.get("od2") or []
        rows.reverse()
        try:
            start = datetime.strptime(observed.get("od0", ""), OBSERVE_TIME_FORMAT)
        except ValueError as exc:
            data = {
                "error": str(exc),
                "api": self.api.async_url(f"weather/{area_id}.shtml", "www"),
                "data": observed,
            }
            _LOGGER.warning("Update observe failed: %s", data)
            return data

        for row in rows:
            moment = start.replace(hour=int(row.get("od21", 0)))
            if moment < start:
                moment += timedelta(days=1)
            start = moment
            try:
                data[moment.strftime(OBSERVE_TIME_FORMAT)] = {
                    **row,
                    "aqi": row.get("od28"),
                    "temp": float(row.get("od22")),
                    "humi": float(row.get("od27")),
                    "rain": float(row.get("od26") or 0),
                    "wind": row.get("od24"),
                    "wind_level": float(row.get("od25") or 0),
                    "wind_angel": float(row.get("od23") or 0),
                }
            except (TypeError, ValueError):
                continue

        if data:
            self.data["observe"] = data
        return data

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device information of this station."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.area_id)},
            name=f"{self.station_name}天气",
            model=f"{self.station_code}({self.area_id})",
            configuration_url=self.web_url(f"mweather/{self.area_id}.shtml"),
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def domain(self) -> str | None:
        """Return the configured domain."""
        return self.config.get(CONF_DOMAIN)

    @property
    def area_id(self) -> str | None:
        """Return the area id of the station."""
        return self.station.area_id if self.station else None

    @property
    def station_code(self) -> str:
        """Return the station code used in entity ids."""
        if not self.station:
            return self.hass.config.location_name
        return (
            self.station.area_code
            or self.station.area_name
            or self.hass.config.location_name
        )

    @property
    def station_name(self) -> str:
        """Return the station name used in the device name."""
        return (self.station.area_name if self.station else None) or self.station_code
