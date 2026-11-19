"""Constants for the tianqi integration."""

from __future__ import annotations

import base64

from homeassistant.const import Platform

DOMAIN = "tianqi"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.WEATHER,
]

HTTP_REFERER = base64.b64decode("aHR0cHM6Ly9tLndlYXRoZXIuY29tLmNuLw==").decode()
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_1) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)
HTTP_HEADERS = {
    "Referer": HTTP_REFERER,
    "User-Agent": USER_AGENT,
}

# Coordinator refresh intervals.
INTERVAL_ALARMS = 5  # minutes
INTERVAL_SUMMARY = 60  # seconds
INTERVAL_DAILIES = 60  # minutes
INTERVAL_OBSERVE = 30  # minutes
INTERVAL_HOURLIES = 30  # minutes
INTERVAL_MINUTELY = 5  # minutes
