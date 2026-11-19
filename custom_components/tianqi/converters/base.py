"""Converters translating tianqi payloads into Home Assistant states."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    Platform,
    UnitOfSpeed,
)

if TYPE_CHECKING:
    from ..client import TianqiClient

# `UnitOfDensity` (the replacement for the deprecated
# `CONCENTRATION_MICROGRAMS_PER_CUBIC_METER`) is only available in
# Home Assistant 2026.10 and newer.
MICROGRAMS_PER_CUBIC_METER = "µg/m³"


@dataclass
class Converter:
    """Base converter between a raw payload field and an entity."""

    attr: str
    domain: Platform | None = None
    prop: str | None = None
    parent: str | None = None
    enabled: bool | None = True  # True, False or None (created on demand)
    poll: bool = False
    ignore_prop: bool = False

    # Declared by subclasses, never mutated in place.
    childs: ClassVar[set[str] | None] = None
    option: ClassVar[dict[str, Any] | None] = None

    def decode(self, client: TianqiClient, payload: dict[str, Any], value: Any) -> None:
        """Convert a payload value into entity states."""
        payload[self.attr] = value

    def encode(self, client: TianqiClient, payload: dict[str, Any], value: Any) -> None:
        """Convert an entity state back into a payload value."""
        payload[self.prop or self.attr] = value

    def with_option(self, option: dict[str, Any]) -> Converter:
        """Return the converter with extra entity options."""
        self.option = dict(option)
        return self


@dataclass
class SensorConv(Converter):
    """Converter for a plain sensor."""

    domain: Platform | None = Platform.SENSOR


@dataclass
class NumberSensorConv(SensorConv):
    """Converter for a numeric sensor."""

    unit: str | None = " "
    precision: int | None = 1

    def decode(self, client: TianqiClient, payload: dict[str, Any], value: Any) -> None:
        """Convert a value with a trailing unit into a number."""
        try:
            number = float(f"{value}".strip().replace(self.unit or "", ""))
            number = round(number, self.precision or 0)
        except (TypeError, ValueError):
            number = None
        payload[self.attr] = number


@dataclass
class WindSpeedSensorConv(NumberSensorConv):
    """Converter for wind speed, with the related wind attributes."""

    attr: str = "wind_speed"
    prop: str | None = "wse"
    unit: str | None = "km/h"
    option = {
        "device_class": SensorDeviceClass.WIND_SPEED,
        "state_class": SensorStateClass.MEASUREMENT,
        "unit_of_measurement": UnitOfSpeed.KILOMETERS_PER_HOUR,
    }
    childs = {
        "wind_direction",
        "wind_direction_code",
        "wind_level",
        "wind_speed_and_unit",
    }

    def decode(self, client: TianqiClient, payload: dict[str, Any], value: Any) -> None:
        """Convert wind speed and add the matching wind attributes."""
        super().decode(client, payload, value)
        data = client.data.get("dataSK") or {}
        payload.update(
            {
                "wind_direction": data.get("WD"),
                "wind_direction_code": data.get("wde"),
                "wind_level": data.get("WS"),
                "wind_speed_and_unit": data.get("wse"),
            }
        )


@dataclass
class ForecastMinutelySensorConv(SensorConv):
    """Converter for the minutely forecast message and its attributes."""

    attr: str = "forecast_minutely"
    prop: str | None = "msg"
    option = {
        "icon": "mdi:tooltip",
        "payload_attrs": True,
    }

    def decode(self, client: TianqiClient, payload: dict[str, Any], value: Any) -> None:
        """Convert the minutely forecast into a message plus attributes."""
        minutely = client.data.get("minutely") or {}
        times = minutely.get("times") or []
        values = minutely.get("values") or []
        minutes = (
            dict(zip(times, values, strict=False)) if len(times) == len(values) else {}
        )
        payload.update(
            {
                "forecast_minutely": minutely.get("msg"),
                **minutes,
            }
        )


@dataclass
class AlarmsBinarySensorConv(Converter):
    """Converter for weather alarms."""

    attr: str = "warning"
    prop: str | None = "alarms"
    domain: Platform | None = Platform.BINARY_SENSOR
    option = {
        "device_class": BinarySensorDeviceClass.PROBLEM,
    }
    childs = {
        "title",
        "alarms",
    }

    def decode(self, client: TianqiClient, payload: dict[str, Any], value: Any) -> None:
        """Convert the alarm list into a binary state plus attributes."""
        super().decode(client, payload, value)
        code = None
        titles: list[str] = []
        alarms: list[dict[str, Any]] = []
        raw_alarms = sorted(
            client.data.get(self.prop or "") or [],
            key=lambda alarm: alarm.get("w6", ""),
            reverse=True,
        )
        for alarm in raw_alarms:
            alarm_code = f"{alarm.get('w4')}{alarm.get('w6')}"
            if code is None:
                code = alarm_code
            title = alarm.get("w13", "")
            titles.append(re.sub(r".+发布的?(.+预警)", r"\1", title))
            alarms.append(
                {
                    "title": title,
                    "description": alarm.get("w9", ""),
                    "province": alarm.get("w1"),
                    "city": alarm.get("w2"),
                    "code": alarm_code,
                    "alertld": alarm.get("w16"),
                    "link": client.web_url(
                        f"warning/publish_area.shtml?code={client.area_id}"
                    ),
                }
            )
        payload["warning"] = len(alarms) > 0
        payload["title"] = ", ".join(dict.fromkeys(titles))
        payload["alarms"] = alarms
        picture = (
            client.web_url(f"m2/i/about/alarmpic/{code}.gif", "www") if code else None
        )
        self.option = {
            **(self.option or {}),
            "entity_picture": f"https://cfrp.hacs.vip/{picture}" if picture else None,
        }
