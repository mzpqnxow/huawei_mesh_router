"""Huawei api extended functions."""

from functools import wraps
import logging
from typing import Any, Final, Iterable, Tuple

from aiohttp import ClientResponse

from .classes import (
    MAC_ADDR,
    FilterAction,
    FilterMode,
    HuaweiClientDevice,
    HuaweiConnectionInfo,
    HuaweiDeviceNode,
    HuaweiFilterInfo,
    HuaweiRouterInfo,
)
from .coreapi import APICALL_ERRCAT_UNAUTHORIZED, ApiCallError, HuaweiCoreApi

SWITCH_NFC: Final = "nfc_switch"
SWITCH_WIFI_80211R: Final = "wifi_80211r_switch"
SWITCH_WIFI_TWT: Final = "wifi_twt_switch"
SWITCH_WLAN_FILTER: Final = "wlan_filter_switch"

ACTION_REBOOT: Final = "reboot_action"

CONNECTED_VIA_ID_PRIMARY: Final = "primary"

FEATURE_NFC: Final = "feature_nfc"
FEATURE_WIFI_80211R: Final = "feature_wifi_80211r"
FEATURE_WIFI_TWT: Final = "feature_wifi_twt"
FEATURE_WLAN_FILTER: Final = "feature_wlan_filter"

_URL_DEVICE_INFO: Final = "api/system/deviceinfo"
_URL_HOST_INFO: Final = "api/system/HostInfo"
_URL_DEVICE_TOPOLOGY: Final = "api/device/topology"
_URL_SWITCH_NFC: Final = "api/bsp/nfc_switch"
_URL_SWITCH_WIFI_80211R: Final = "api/ntwk/WlanGuideBasic?type=notshowpassall"
_URL_SWITCH_WIFI_TWT: Final = "api/ntwk/WlanGuideBasic?type=notshowpassall"
_URL_REBOOT: Final = "api/service/reboot.cgi"
_URL_WANDETECT: Final = "api/ntwk/wandetect"
_URL_WLAN_FILTER: Final = "api/ntwk/wlanfilterenhance"

_STATUS_CONNECTED: Final = "Connected"

_LOGGER = logging.getLogger(__name__)


# ---------------------------
#   UnsupportedActionError
# ---------------------------
class UnsupportedActionError(Exception):
    def __init__(self, message: str) -> None:
        """Initialize."""
        super().__init__(message)
        self._message = message

    def __str__(self, *args, **kwargs) -> str:
        """Return str(self)."""
        return self._message


# ---------------------------
#   InvalidActionError
# ---------------------------
class InvalidActionError(Exception):
    def __init__(self, message: str) -> None:
        """Initialize."""
        super().__init__(message)
        self._message = message

    def __str__(self, *args, **kwargs) -> str:
        """Return str(self)."""
        return self._message


# ---------------------------
#   HuaweiFeaturesDetector
# ---------------------------
class HuaweiFeaturesDetector:
    def __init__(self, core_api: HuaweiCoreApi):
        """Initialize."""
        self._core_api = core_api
        self._available_features = set()
        self._is_initialized = False

    @staticmethod
    def unauthorized_as_false(func):
        @wraps(func)
        async def wrapper(*args, **kwargs) -> bool:
            try:
                return await func(*args, **kwargs)
            except ApiCallError as ace:
                if ace.category == APICALL_ERRCAT_UNAUTHORIZED:
                    return False
                raise

        return wrapper

    @staticmethod
    def log_feature(feature_name: str):
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                try:
                    _LOGGER.debug("Check feature '%s' availability", feature_name)
                    result = await func(*args, **kwargs)
                    if result:
                        _LOGGER.debug("Feature '%s' is available", feature_name)
                    else:
                        _LOGGER.debug("Feature '%s' is not available", feature_name)
                    return result
                except Exception:
                    _LOGGER.debug(
                        "Feature availability check failed on %s", feature_name
                    )
                    raise

            return wrapper

        return decorator

    @log_feature(FEATURE_NFC)
    @unauthorized_as_false
    async def _is_nfc_available(self) -> bool:
        data = await self._core_api.get(_URL_SWITCH_NFC)
        return data.get("nfcSwitch") is not None

    @log_feature(FEATURE_WIFI_80211R)
    @unauthorized_as_false
    async def _is_wifi_80211r_available(self) -> bool:
        data = await self._core_api.get(_URL_SWITCH_WIFI_80211R)
        return data.get("WifiConfig", [{}])[0].get("Dot11REnable") is not None

    @log_feature(FEATURE_WIFI_TWT)
    @unauthorized_as_false
    async def _is_wifi_twt_available(self) -> bool:
        data = await self._core_api.get(_URL_SWITCH_WIFI_TWT)
        return data.get("WifiConfig", [{}])[0].get("TWTEnable") is not None

    @log_feature(FEATURE_WLAN_FILTER)
    @unauthorized_as_false
    async def _is_wlan_filter_available(self) -> bool:
        data = self._core_api.get(_URL_WLAN_FILTER)
        return data is not None

    async def update(self) -> None:
        """Update the available features list."""
        if await self._is_nfc_available():
            self._available_features.add(FEATURE_NFC)

        if await self._is_wifi_80211r_available():
            self._available_features.add(FEATURE_WIFI_80211R)

        if await self._is_wifi_twt_available():
            self._available_features.add(FEATURE_WIFI_TWT)

        if await self._is_wlan_filter_available():
            self._available_features.add(FEATURE_WLAN_FILTER)

    def is_available(self, feature: str) -> bool:
        """Return true if feature is available."""
        return feature in self._available_features


# ---------------------------
#   HuaweiApi
# ---------------------------
class HuaweiApi:
    def __init__(
        self,
        host: str,
        port: int,
        use_ssl: bool,
        user: str,
        password: str,
        verify_ssl: bool,
    ) -> None:
        """Initialize."""
        self._core_api = HuaweiCoreApi(host, port, use_ssl, user, password, verify_ssl)
        self._is_features_updated = False
        self._features = HuaweiFeaturesDetector(self._core_api)
        self._logger = logging.getLogger(f"{__name__} ({host})")
        self._logger.debug("New instance of HuaweiApi created")

    async def authenticate(self) -> None:
        """Perform authentication."""
        await self._core_api.authenticate()

    async def disconnect(self) -> None:
        """Disconnect from api."""
        await self._core_api.disconnect()

    async def _ensure_features_updated(self):
        if not self._is_features_updated:
            self._logger.debug("Updating available features")
            await self._features.update()
            self._is_features_updated = True
            self._logger.debug("Available features updated")

    @property
    def router_url(self) -> str:
        """URL address of the router."""
        return self._core_api.router_url

    async def is_feature_available(self, feature: str) -> bool:
        """Return true if specified feature is known and available."""
        await self._ensure_features_updated()
        return self._features.is_available(feature)

    @staticmethod
    def _router_data_check_authorized(
        response: ClientResponse, result: dict[str, Any]
    ) -> bool:
        if response.status == 404:
            return False
        if result is None or result.get("EmuiVersion", "-") == "-":
            return False
        return True

    @staticmethod
    def _wan_info_check_authorized(
        response: ClientResponse, result: dict[str, Any]
    ) -> bool:
        if response.status == 404:
            return False
        if result is None or result.get("ExternalIPAddress", "-") == "-":
            return False
        return True

    async def get_router_info(self) -> HuaweiRouterInfo:
        """Return the router information."""
        data = await self._core_api.get(
            _URL_DEVICE_INFO, check_authorized=HuaweiApi._router_data_check_authorized
        )

        return HuaweiRouterInfo(
            name=data.get("FriendlyName"),
            model=data.get("custinfo", {}).get("CustDeviceName"),
            serial_number=data.get("SerialNumber"),
            software_version=data.get("SoftwareVersion"),
            hardware_version=data.get("HardwareVersion"),
            harmony_os_version=data.get("HarmonyOSVersion"),
            uptime=data.get("UpTime"),
        )

    async def get_wan_connection_info(self) -> HuaweiConnectionInfo:
        data = await self._core_api.get(
            _URL_WANDETECT, check_authorized=HuaweiApi._wan_info_check_authorized
        )

        return HuaweiConnectionInfo(
            uptime=data.get("Uptime", 0),
            connected=data.get("Status") == _STATUS_CONNECTED,
            address=data.get("ExternalIPAddress"),
        )

    async def get_switch_state(self, name: str) -> bool:
        """Return the specified switch state."""
        await self._ensure_features_updated()

        if name == SWITCH_NFC and self._features.is_available(FEATURE_NFC):
            data = await self._core_api.get(_URL_SWITCH_NFC)
            return data.get("nfcSwitch") == 1

        elif name == SWITCH_WIFI_80211R and self._features.is_available(
            FEATURE_WIFI_80211R
        ):
            data = await self._core_api.get(_URL_SWITCH_WIFI_80211R)
            setting_value = data.get("WifiConfig", [{}])[0].get("Dot11REnable")
            return isinstance(setting_value, bool) and setting_value

        elif name == SWITCH_WIFI_TWT and self._features.is_available(FEATURE_WIFI_TWT):
            data = await self._core_api.get(_URL_SWITCH_WIFI_TWT)
            setting_value = data.get("WifiConfig", [{}])[0].get("TWTEnable")
            return isinstance(setting_value, bool) and setting_value

        elif name == SWITCH_WLAN_FILTER and self._features.is_available(
            FEATURE_WLAN_FILTER
        ):
            _, data = await self.get_wlan_filter_info()
            return data.enabled

        else:
            raise UnsupportedActionError(f"Unsupported switch name: {name}")

    async def set_switch_state(self, name: str, state: bool) -> None:
        """Set the specified switch state."""
        await self._ensure_features_updated()

        if name == SWITCH_NFC and self._features.is_available(FEATURE_NFC):
            await self._core_api.post(_URL_SWITCH_NFC, {"nfcSwitch": 1 if state else 0})

        elif name == SWITCH_WIFI_80211R and self._features.is_available(
            FEATURE_WIFI_80211R
        ):
            await self._core_api.post(
                _URL_SWITCH_WIFI_80211R,
                {"Dot11REnable": state},
                extra_data={"action": "11rSetting"},
            )

        elif name == SWITCH_WIFI_TWT and self._features.is_available(FEATURE_WIFI_TWT):
            await self._core_api.post(
                _URL_SWITCH_WIFI_TWT,
                {"TWTEnable": state},
                extra_data={"action": "TWTSetting"},
            )

        elif name == SWITCH_WLAN_FILTER and self._features.is_available(
            FEATURE_WLAN_FILTER
        ):
            await self._set_wlan_filter_enabled(state)

        else:
            raise UnsupportedActionError(f"Unsupported switch name: {name}")

    async def get_known_devices(self) -> Iterable[HuaweiClientDevice]:
        """Return the known devices."""
        return [
            HuaweiClientDevice(item)
            for item in await self._core_api.get(_URL_HOST_INFO)
        ]

    @staticmethod
    def _get_device(node: dict[str, Any]) -> HuaweiDeviceNode:
        device = HuaweiDeviceNode(node.get("MACAddress"), node.get("HiLinkType"))
        connected_devices = node.get("ConnectedDevices", [])
        for connected_device in connected_devices:
            inner_node = HuaweiApi._get_device(connected_device)
            device.add_device(inner_node)
        return device

    async def get_devices_topology(self) -> Iterable[HuaweiDeviceNode]:
        """Return the topology of the devices."""
        return [
            self._get_device(item)
            for item in await self._core_api.get(_URL_DEVICE_TOPOLOGY)
        ]

    async def execute_action(self, action_name: str) -> None:
        """Execute specified action."""
        if action_name == ACTION_REBOOT:
            await self._core_api.post(_URL_REBOOT, {})
        else:
            raise UnsupportedActionError(f"Unsupported action name: {action_name}")

    async def apply_wlan_filter(
        self,
        filter_mode: FilterMode,
        filter_action: FilterAction,
        device_mac: MAC_ADDR,
        device_name: str | None = None,
    ) -> bool:
        """Apply filter to the device."""

        def verify_state(target_state: dict[str, Any]) -> bool:
            enabled = target_state.get("MACAddressControlEnabled")
            verification_result = isinstance(enabled, bool) and enabled
            if not verification_result:
                _LOGGER.warning("WLAN Filtering is not enabled")
            return verification_result

        state_2g, state_5g = await self._get_filter_states()

        if state_2g is None:
            _LOGGER.debug("Can not find actual 2.4GHz filter state")
            return False

        if state_5g is None:
            _LOGGER.debug("Can not find actual 5GHz filter state")
            return False

        if not verify_state(state_2g) or not verify_state(state_5g):
            _LOGGER.debug("Verification failed")
            return False

        need_action_2g, whitelist_2g, blacklist_2g = await self._process_access_lists(
            state_2g, filter_mode, filter_action, device_mac, device_name
        )
        if whitelist_2g is None or blacklist_2g is None or need_action_2g is None:
            _LOGGER.debug("Processing 2.4GHz filter failed")
            return False

        need_action_5g, whitelist_5g, blacklist_5g = await self._process_access_lists(
            state_5g, filter_mode, filter_action, device_mac, device_name
        )
        if whitelist_5g is None or blacklist_5g is None or need_action_5g is None:
            _LOGGER.debug("Processing 5GHz filter failed")
            return False

        if not need_action_2g and not need_action_5g:
            return True

        command = {
            "config2g": {
                "MACAddressControlEnabled": True,
                "WMacFilters": whitelist_2g,
                "ID": state_2g.get("ID"),
                "MacFilterPolicy": state_2g.get("MacFilterPolicy"),
                "BMacFilters": blacklist_2g,
                "FrequencyBand": state_2g.get("FrequencyBand"),
            },
            "config5g": {
                "MACAddressControlEnabled": True,
                "WMacFilters": whitelist_5g,
                "ID": state_5g.get("ID"),
                "MacFilterPolicy": state_5g.get("MacFilterPolicy"),
                "BMacFilters": blacklist_5g,
                "FrequencyBand": state_5g.get("FrequencyBand"),
            },
        }

        await self._core_api.post(_URL_WLAN_FILTER, command)
        return True

    async def _set_wlan_filter_enabled(self, value: bool) -> bool:
        """Enable or disable wlan filtering."""

        state_2g, state_5g = await self._get_filter_states()

        if state_2g is None:
            _LOGGER.debug("Can not find actual 2.4GHz filter state")
            return False

        if state_5g is None:
            _LOGGER.debug("Can not find actual 5GHz filter state")
            return False

        current_value_2g = state_2g.get("MACAddressControlEnabled")
        current_value_2g = isinstance(current_value_2g, bool) and current_value_2g

        current_value_5g = state_5g.get("MACAddressControlEnabled")
        current_value_5g = isinstance(current_value_5g, bool) and current_value_5g

        current_state = current_value_2g and current_value_5g

        if current_state == value:
            return True

        command = {
            "config2g": {
                "MACAddressControlEnabled": value,
                "WMacFilters": state_2g.get("WMACAddresses"),
                "ID": state_2g.get("ID"),
                "MacFilterPolicy": state_2g.get("MacFilterPolicy"),
                "BMacFilters": state_2g.get("BMACAddresses"),
                "FrequencyBand": state_2g.get("FrequencyBand"),
            },
            "config5g": {
                "MACAddressControlEnabled": value,
                "WMacFilters": state_5g.get("WMACAddresses"),
                "ID": state_5g.get("ID"),
                "MacFilterPolicy": state_5g.get("MacFilterPolicy"),
                "BMacFilters": state_5g.get("BMACAddresses"),
                "FrequencyBand": state_5g.get("FrequencyBand"),
            },
        }

        await self._core_api.post(_URL_WLAN_FILTER, command)
        return True

    async def set_wlan_filter_mode(self, value: FilterMode) -> bool:
        """Enable or disable wlan filtering."""

        state_2g, state_5g = await self._get_filter_states()

        if state_2g is None:
            _LOGGER.debug("Can not find actual 2.4GHz filter state")
            return False

        if state_5g is None:
            _LOGGER.debug("Can not find actual 5GHz filter state")
            return False

        current_state = state_5g.get("MacFilterPolicy")

        if current_state == value.value:
            return True

        command = {
            "config2g": {
                "MACAddressControlEnabled": state_2g.get("MACAddressControlEnabled"),
                "WMacFilters": state_2g.get("WMACAddresses"),
                "ID": state_2g.get("ID"),
                "MacFilterPolicy": value.value,
                "BMacFilters": state_2g.get("BMACAddresses"),
                "FrequencyBand": state_2g.get("FrequencyBand"),
            },
            "config5g": {
                "MACAddressControlEnabled": state_5g.get("MACAddressControlEnabled"),
                "WMacFilters": state_5g.get("WMACAddresses"),
                "ID": state_5g.get("ID"),
                "MacFilterPolicy": value.value,
                "BMacFilters": state_5g.get("BMACAddresses"),
                "FrequencyBand": state_5g.get("FrequencyBand"),
            },
        }

        await self._core_api.post(_URL_WLAN_FILTER, command)
        return True

    async def get_wlan_filter_info(self) -> Tuple[HuaweiFilterInfo, HuaweiFilterInfo]:
        state_2g, state_5g = await self._get_filter_states()
        info_2g = HuaweiFilterInfo.parse(state_2g)
        info_5g = HuaweiFilterInfo.parse(state_5g)
        return info_2g, info_5g

    async def _get_filter_states(self):
        actual_states = await self._core_api.get(_URL_WLAN_FILTER)
        state_2g = None
        state_5g = None
        for state in actual_states:
            frequency = state.get("FrequencyBand")
            if frequency == "2.4GHz":
                state_2g = state
            elif frequency == "5GHz":
                state_5g = state
        return state_2g, state_5g

    async def _process_access_lists(
        self,
        state: dict[str, Any],
        filter_mode: FilterMode,
        filter_action: FilterAction,
        device_mac: MAC_ADDR,
        device_name: str | None,
    ) -> (bool | None, dict[str, Any] | None, dict[str, Any] | None):
        """Return (need_action, whitelist, blacklist)"""
        whitelist = state.get("WMACAddresses")
        blacklist = state.get("BMACAddresses")

        if whitelist is None:
            _LOGGER.debug("Can not find whitelist")
            return None, None, None

        if blacklist is None:
            _LOGGER.debug("Can not find blacklist")
            return None, None, None

        async def get_access_list_item() -> dict[str, Any]:
            if device_name:
                return {"MACAddress": device_mac, "HostName": device_name}
            # search for HostName if no item popped and no name provided
            known_devices = await self.get_known_devices()
            for device in known_devices:
                if device.mac_address == device_mac:
                    return {"MACAddress": device_mac, "HostName": device.actual_name}
            _LOGGER.debug("Can not find known device '%s'", device_mac)
            return {
                "MACAddress": device_mac,
                "HostName": f"Unknown device {device_mac}",
            }

        # | FilterAction | FilterMode |    WL    |   BL   |
        # |--------------|------------|----------|--------|
        # | ADD          | WHITELIST  |   Add    | Remove |
        # | ADD          | BLACKLIST  |  Remove  |  Add   |
        # | REMOVE       | WHITELIST  |  Remove  |  None  |
        # | REMOVE       | BLACKLIST  |   None   | Remove |

        whitelist_index: int | None = None
        blacklist_index: int | None = None

        for index in range(len(whitelist)):
            if device_mac == whitelist[index].get("MACAddress"):
                whitelist_index = index
                _LOGGER.debug(
                    "Device '%s' found at %s whitelist",
                    device_mac,
                    state.get("FrequencyBand"),
                )
                break

        for index in range(len(blacklist)):
            if device_mac == blacklist[index].get("MACAddress"):
                blacklist_index = index
                _LOGGER.debug(
                    "Device '%s' found at %s blacklist",
                    device_mac,
                    state.get("FrequencyBand"),
                )
                break

        if filter_action == FilterAction.REMOVE:

            if filter_mode == FilterMode.BLACKLIST:
                if blacklist_index is None:
                    _LOGGER.debug(
                        "Can not find device '%s' to remove from blacklist", device_mac
                    )
                    return False, whitelist, blacklist
                del blacklist[blacklist_index]
                return True, whitelist, blacklist
            elif filter_mode == FilterMode.WHITELIST:
                if whitelist_index is None:
                    _LOGGER.debug(
                        "Can not find device '%s' to remove from whitelist", device_mac
                    )
                    return False, whitelist, blacklist
                del whitelist[whitelist_index]
                return True, whitelist, blacklist
            else:
                raise InvalidActionError(f"Unknown FilterMode: {filter_mode}")

        elif filter_action == FilterAction.ADD:
            item_to_add = None

            if filter_mode == FilterMode.BLACKLIST:
                if whitelist_index is not None:
                    item_to_add = whitelist.pop(whitelist_index)
                if blacklist_index is not None:
                    _LOGGER.debug(
                        "Device '%s' already in the %s blacklist",
                        device_mac,
                        state.get("FrequencyBand"),
                    )
                    return False, whitelist, blacklist
                else:
                    blacklist.append(item_to_add or await get_access_list_item())
                    return True, whitelist, blacklist

            if filter_mode == FilterMode.WHITELIST:
                if blacklist_index is not None:
                    item_to_add = blacklist.pop(blacklist_index)
                if whitelist_index is not None:
                    _LOGGER.debug(
                        "Device '%s' already in the %s whitelist",
                        device_mac,
                        state.get("FrequencyBand"),
                    )
                    return False, whitelist, blacklist
                else:
                    whitelist.append(item_to_add or await get_access_list_item())
                    return True, whitelist, blacklist
            else:
                raise InvalidActionError(f"Unknown FilterMode: {filter_mode}")

        else:
            raise InvalidActionError(f"Unknown FilterAction: {filter_action}")
