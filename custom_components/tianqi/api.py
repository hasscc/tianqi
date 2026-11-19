"""HTTP API for the tianqi integration (weather.com.cn)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import IntegrationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import HTTP_HEADERS

_LOGGER = logging.getLogger(__name__)

_P = ParamSpec("_P")
_R = TypeVar("_R")

HTTP_TIMEOUT = aiohttp.ClientTimeout(total=60, connect=30)
RETRY_ON_STATUS = {500, 502, 503, 504}
DNS_ERRORS: tuple[type[BaseException], ...] = tuple(
    filter(None, (getattr(aiohttp, "ClientConnectorDNSError", None),))
)


def aiohttp_retry(
    max_retries: int = 10,
    backoff_factor: float = 2.0,
    retry_on_status: set[int] | None = None,
    exceptions: tuple[type[BaseException], ...] = (aiohttp.ClientError, TimeoutError),
) -> Callable[
    [Callable[_P, Coroutine[Any, Any, _R]]], Callable[_P, Coroutine[Any, Any, _R]]
]:
    """Retry an aiohttp request with exponential backoff on transient errors.

    :param max_retries: Retries in addition to the first attempt.
    :param backoff_factor: Base delay in seconds, doubled after each attempt.
    :param retry_on_status: HTTP statuses worth retrying, defaults to 5xx.
    :param exceptions: Exceptions that may be retried.
    """
    statuses = RETRY_ON_STATUS if retry_on_status is None else retry_on_status

    def decorator(
        func: Callable[_P, Coroutine[Any, Any, _R]],
    ) -> Callable[_P, Coroutine[Any, Any, _R]]:
        @wraps(func)
        async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            last_exception: BaseException | None = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    _LOGGER.warning(
                        "Error while fetching data from %s: %s",
                        func.__name__,
                        exc,
                        exc_info=True,
                    )
                    last_exception = exc
                    if attempt == max_retries:
                        break
                    retryable = bool(DNS_ERRORS) and isinstance(exc, DNS_ERRORS)
                    if isinstance(exc, aiohttp.ClientResponseError):
                        retryable = exc.status in statuses
                    if not retryable:
                        break
                    await asyncio.sleep(backoff_factor * (2**attempt))
            if last_exception is not None:
                raise last_exception
            raise IntegrationError(f"Unable to call {func.__name__}")

        return wrapper

    return decorator


@dataclass(slots=True)
class StationInfo:
    """Station (city/district) information."""

    data: dict[str, Any]

    @property
    def area_id(self) -> str | None:
        """Return the area id, e.g. 101110101."""
        return self.data.get("areaid")

    @property
    def area_name(self) -> str | None:
        """Return the localized area name."""
        return self.data.get("namecn")

    @property
    def area_code(self) -> str | None:
        """Return the transliterated area name, e.g. xian."""
        return self.data.get("nameen")

    @property
    def latitude(self) -> float | None:
        """Return the latitude."""
        return self.data.get("lat")

    @property
    def longitude(self) -> float | None:
        """Return the longitude."""
        return self.data.get("lng")


class TianqiApi:
    """Thin HTTP client for the endpoints used by this integration."""

    def __init__(self, hass: HomeAssistant, domain: str | None) -> None:
        """Initialize the API client."""
        self.hass = hass
        self.domain = domain
        self._session = async_get_clientsession(hass, verify_ssl=False)

    def async_url(self, path: str, node: str = "d1", with_time: bool = True) -> str:
        """Build a request URL for the given node and path."""
        if not self.domain:
            raise IntegrationError("Domain cannot be empty")
        url = f"https://{node}.{self.domain}/{path.lstrip('/')}"
        if with_time:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}_={int(time.time() * 1000)}"
        return url

    def web_url(self, path: str, node: str = "m") -> str:
        """Build a human readable (web page) URL."""
        return self.async_url(path, node, with_time=False)

    @aiohttp_retry()
    async def async_fetch(
        self,
        path: str,
        node: str = "d1",
        params: Mapping[str, Any] | None = None,
        with_time: bool = True,
    ) -> tuple[int, str]:
        """Fetch a page and return its status and text."""
        url = self.async_url(path, node, with_time)
        response = await self._session.get(
            url,
            params=params,
            headers=HTTP_HEADERS,
            allow_redirects=False,
            timeout=HTTP_TIMEOUT,
        )
        text = await response.text()
        if not text:
            detail = f" {dict(params)}" if params else ""
            raise IntegrationError(f"Empty response from: {url}{detail}")
        return response.status, text

    @aiohttp_retry()
    async def async_get_station(
        self,
        area_id: str | None = None,
        lat: float | None = None,
        lng: float | None = None,
    ) -> StationInfo:
        """Return station information for an area id or coordinates."""
        params: dict[str, Any] = {"method": "stationinfo"}
        if area_id and area_id != "auto":
            params["areaid"] = area_id
        elif not lat or not lng:
            params["lat"] = self.hass.config.latitude
            params["lng"] = self.hass.config.longitude
        else:
            raise IntegrationError(
                f"Arguments invalid for {self.async_url('geong/v1/api', 'd7')}"
            )

        _, text = await self.async_fetch(
            "geong/v1/api",
            "d7",
            params={"params": json.dumps(params, separators=(",", ":"))},
        )
        try:
            payload = json.loads(text) or {}
        except ValueError as exc:
            raise IntegrationError(f"{exc}:\n{text}") from exc

        station = (payload.get("data") or {}).get("station") or {}
        if not station:
            raise IntegrationError(f"Unable to get station info: {params} {text}")
        return StationInfo({**(payload.get("location") or {}), **station})

    async def async_search_areas(self, name: str) -> dict[str, str]:
        """Search areas by name, returning {area_id: display name}."""
        params = {"cityname": name}
        _, text = await self.async_fetch("search", "toy1", params=params)
        areas: dict[str, str] = {}
        for item in json.loads(text.strip("()")) or []:
            if not (ref := item.get("ref")):
                continue
            fields = f"{ref}".split("~")
            area_id = fields[0]
            if len(area_id) > 9 or len(fields) < 10:
                continue
            areas[area_id] = f"{fields[9]}-{fields[2]}"
        return areas
