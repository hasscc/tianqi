from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING
import re

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
        try:
            val = float(f'{value}'.strip().replace(self.unit, ''))
            val = round(val, self.precision)
        except (TypeError, ValueError):
            val = None
        payload[self.attr] = val


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

@dataclass
class ForecastMinutelySensorConv(SensorConv):
    attr: str = 'forecast_minutely'
    prop: Optional[str] = 'msg'
    option = {
        'icon': 'mdi:tooltip',
        'payload_attrs': True,
    }

    def decode(self, client: "Client", payload: dict, value: Any):
        minutely = client.data.get('minutely') or {}
        times = minutely.get('times', [])
        values = minutely.get('values', [])
        minutes = dict(zip(times, values)) if len(times) == len(values) else {}
        payload.update({
            'forecast_minutely': minutely.get('msg'),
            **minutes,
        })


@dataclass
class AlarmsBinarySensorConv(Converter):
    attr: str = 'warning'
    prop: Optional[str] = 'alarms'
    domain: Optional[str] = 'binary_sensor'
    option = {
        'device_class': 'problem',
    }
    childs = {
        'title',
        'alarms',
    }

    def decode(self, client: "Client", payload: dict, value: Any):
        super().decode(client, payload, value)
        code = None
        titles = []
        alarms = []
        for v in client.data.get(self.prop) or []:
            code = f'{v.get("w4")}{v.get("w6")}'
            title = v.get('w13', '')
            titles.append(re.sub(r'.+发布的?(.+预警)', r'\1', title))
            alarms.append({
                'title': title,
                'description': v.get('w9', ''),
                'province': v.get('w1'),
                'city': v.get('w2'),
                'code': code,
                'alertld': v.get('w16'),
                'link': client.web_url('warning/publish_area.shtml?code=%s' % client.area_id),
            })
        payload['warning'] = len(alarms) > 0
        payload['title'] = ', '.join(set(titles))
        payload['alarms'] = alarms
        src = client.web_url('m2/i/about/alarmpic/%s.gif' % code, 'www') if code else None
        self.option['entity_picture'] = f'https://cfrp.hacs.vip/{src}' if src else None
