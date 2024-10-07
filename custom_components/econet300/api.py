"""Econet300 API class class describint methods of getting and setting data."""

import asyncio
from http import HTTPStatus
import logging
from typing import Any

from aiohttp import BasicAuth, ClientSession
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_EDITABLE_PARAMS_LIMITS_DATA,
    API_EDITABLE_PARAMS_LIMITS_URI,
    API_REG_PARAMS_DATA_PARAM_DATA,
    API_REG_PARAMS_DATA_URI,
    API_SYS_PARAMS_PARAM_HW_VER,
    API_SYS_PARAMS_PARAM_SW_REV,
    API_SYS_PARAMS_PARAM_UID,
    API_SYS_PARAMS_URI,
    EDITABLE_PARAMS_MAPPING_TABLE,
)
from .mem_cache import MemCache

_LOGGER = logging.getLogger(__name__)


def map_param(param_name):
    """Check params mapping in const.py."""
    if param_name not in EDITABLE_PARAMS_MAPPING_TABLE:
        return None

    return EDITABLE_PARAMS_MAPPING_TABLE[param_name]


class Limits:
    """Class difining entity value set limits."""

    def __init__(self, min_v: int | None, max_v: int | None):
        """Construct the necessary attributes for the Limits object."""
        self.min = min_v
        self.max = max_v

    class AuthError(Exception):
        """Raised when authentication fails."""


class AuthError(Exception):
    """Raised when authentication fails."""


class ApiError(Exception):
    """Raised when an API error occurs."""


class DataError(Exception):
    """Raised when there is an error with the data."""


class EconetClient:
    """Econet client class."""

    def __init__(
        self, host: str, username: str, password: str, session: ClientSession
    ) -> None:
        """Initializethe EconetClient."""

        proto = ["http://", "https://"]

        not_contains = all(p not in host for p in proto)

        if not_contains:
            _LOGGER.info("Manually adding 'http' to host")
            host = "http://" + host

        self._host = host
        self._session = session
        self._auth = BasicAuth(username, password)

    @property
    def host(self) -> str:
        """Get host address."""
        return self._host

    async def set_param(self, key: str, value: str):
        """Set a parameter via API call."""
        return await self._get(
            f"{self._host}/econet/rmCurrNewParam?newParamKey={key}&newParamValue={value}"
        )

    async def get_params(self, reg: str):
        """Call for getting api param."""
        return await self._get(f"{self._host}/econet/{reg}")

    async def _get(self, url):
        attempt = 1
        max_attempts = 5

        while attempt <= max_attempts:
            try:
                async with await self._session.get(
                    url, auth=self._auth, timeout=10
                ) as resp:
                    if resp.status == HTTPStatus.UNAUTHORIZED:
                        raise AuthError

                    if resp.status != HTTPStatus.OK:
                        return None

                    return await resp.json()

            except TimeoutError:
                _LOGGER.warning("Timeout error, retry(%i/%i)", attempt, max_attempts)
                await asyncio.sleep(1)
            attempt += 1


class Econet300Api:
    """Client for interacting with the ecoNET-300 API."""

    def __init__(self, client: EconetClient, cache: MemCache) -> None:
        """Initialize the Econet300Api object with a client, cache, and default values for uid, sw_revision, and hw_version."""
        self._client = client
        self._cache = cache
        self._uid = "default-uid"
        self._sw_revision = "default-sw-revision"
        self._hw_version = "default-hw-version"

    @classmethod
    async def create(cls, client: EconetClient, cache: MemCache):
        """Create and return initial object."""
        c = cls(client, cache)
        await c.init()

        return c

    @property
    def host(self) -> str:
        """Get clients host address."""
        return self._client.host

    @property
    def uid(self) -> str:
        """Get uid."""
        return self._uid

    @property
    def sw_rev(self) -> str:
        """Get software version."""
        return self._sw_revision

    @property
    def hw_ver(self) -> str:
        """Get hardware version."""
        return self._hw_version

    async def init(self):
        """Econet300 Api initilization."""
        sys_params = await self._client.get_params(API_SYS_PARAMS_URI)

        if API_SYS_PARAMS_PARAM_UID not in sys_params:
            _LOGGER.warning(
                "%s not in sys_params - cannot set proper UUID",
                API_SYS_PARAMS_PARAM_UID,
            )
        else:
            self._uid = sys_params[API_SYS_PARAMS_PARAM_UID]

        if API_SYS_PARAMS_PARAM_SW_REV not in sys_params:
            _LOGGER.warning(
                "%s not in sys_params - cannot set proper sw_revision",
                API_SYS_PARAMS_PARAM_SW_REV,
            )
        else:
            self._sw_revision = sys_params[API_SYS_PARAMS_PARAM_SW_REV]

        if API_SYS_PARAMS_PARAM_HW_VER not in sys_params:
            _LOGGER.warning(
                "%s not in sys_params - cannot set proper hw_version",
                API_SYS_PARAMS_PARAM_HW_VER,
            )
        else:
            self._hw_version = sys_params[API_SYS_PARAMS_PARAM_HW_VER]

    async def set_param(self, param, value) -> bool:
        """Set param value in Econet300 API."""
        if param is None:
            _LOGGER.warning(
                "Requested param set for: '{param}' but mapping for this param does not exist"
            )
            return False

        data = await self._client.set_param(param, value)

        if data is None or "result" not in data:
            return False

        if data["result"] != "OK":
            return False

        self._cache.set(param, value)

        return True

    async def get_param_limits(self, param: str):
        """Fetch and return the limits for a particular parameter from the Econet 300 API, using a cache for efficient retrieval if available."""
        if not self._cache.exists(API_EDITABLE_PARAMS_LIMITS_DATA):
            limits = await self._fetch_reg_key(
                API_EDITABLE_PARAMS_LIMITS_URI, API_EDITABLE_PARAMS_LIMITS_DATA
            )
            self._cache.set(API_EDITABLE_PARAMS_LIMITS_DATA, limits)

        limits = self._cache.get(API_EDITABLE_PARAMS_LIMITS_DATA)

        if param is None:
            _LOGGER.warning(
                "Requested param limits for: '%s' but mapping for this param does not exist",
                param,
            )
            return None

        if param not in limits:
            _LOGGER.warning(
                "Requested param limits for: '%s' but limits for this param do not exist. Limits: '%s' ",
                param,
                limits,
            )
            return None

        curr_limits = limits[param]
        return Limits(curr_limits["min"], curr_limits["max"])

    async def fetch_data(self) -> dict[str, Any]:
        """Fetch data from regParamsData."""
        return await self._fetch_reg_key(
            API_REG_PARAMS_DATA_URI, API_REG_PARAMS_DATA_PARAM_DATA
        )

    async def _fetch_reg_key(self, reg, data_key: str | None = None):
        """Fetch a key from the json-encoded data returned by the API for a given registry If key is None, then return whole data."""
        data = await self._client.get_params(reg)

        if data is None:
            raise DataError(f"Data fetched by API for reg: {reg} is None")

        if data_key is None:
            return data

        if data_key not in data:
            _LOGGER.debug(data)
            raise DataError(f"Data for key: {data_key} does not exist")

        return data[data_key]


async def make_api(hass: HomeAssistant, cache: MemCache, data: dict):
    """Create api object."""
    return await Econet300Api.create(
        EconetClient(
            data["host"],
            data["username"],
            data["password"],
            async_get_clientsession(hass),
        ),
        cache,
    )
