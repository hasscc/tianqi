from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .. import TianqiClient as Client


@dataclass
class Converter:
    attr: str  # hass attribute
    domain: Optional[str] = None  # hass domain

    prop: Optional[str] = None
    parent: Optional[str] = None

    enabled: Optional[bool] = True  # support: True, False, None (lazy setup)
    poll: bool = False  # hass should_poll
    ignore_prop: bool = False

    # don't init with dataclass because no type:
    childs = None  # set or dict? of children attributes
    option = None

    # to hass
    def decode(self, client: "Client", payload: dict, value: Any):
        payload[self.attr] = value

    # from hass
    def encode(self, client: "Client", payload: dict, value: Any):
        payload[self.prop or self.attr] = value

    def with_option(self, option: dict):
        self.option = option
        return self


@dataclass
class SensorConv(Converter):
    domain: Optional[str] = 'sensor'


@dataclass
class NumberSensorConv(SensorConv):
    unit: Optional[str] = ' '
    precision: Optional[int] = 1

    def decode(self, client: "Client", payload: dict, value: Any):
        val = float(f'{value}'.strip().replace(self.unit, ''))
        payload[self.attr] = round(val, self.precision)


@dataclass
class WindSpeedSensorConv(NumberSensorConv):
    attr: str = 'wind_speed'
    prop: Optional[str] = 'wse'
    unit: Optional[str] = 'km/h'
    option = {
        'device_class': 'wind_speed',
        'state_class': 'measurement',
        'unit_of_measurement': unit,
    }
    childs = {
        'wind_direction',
        'wind_direction_code',
        'wind_level',
        'wind_speed_and_unit',
    }

    def decode(self, client: "Client", payload: dict, value: Any):
        super().decode(client, payload, value)
        dataSK = client.data.get('dataSK') or {}
        payload.update({
            'wind_direction': dataSK.get('WD'),
            'wind_direction_code': dataSK.get('wde'),
            'wind_level': dataSK.get('WS'),
            'wind_speed_and_unit': dataSK.get('wse'),
        })
