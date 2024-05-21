"""
Module implements client for interacting with DC MIPS api.
"""
import logging
import re
from typing import Callable, Optional

import requests

from lib.gateway.base import gw

log = logging.getLogger("main_logger")

# TODO server error retries
# TODO implement retries and RPS throttling
# TODO implement bulk patch method (needs to be concurrent)
# TODO implement retry logic for InvalidAUTHError
# TODO gsheet
# TODO telegram logging
# TODO configuration
# TODO tests


# urls and endpoint paths
BASE_URL = "http://185.45.141.19:9000/MIPS"
AUTH_PATH = "signin"
GET_DEVICES_PATH = "devices-mips"
PATCH_BACKLIGHT_PATH = "devices/rpc-backlight"
GET_BACKLIGHT_SETTINGS_PATH = "devices/rpc-initial-backlight"
GET_DEVICE_TASKS_PATH = "device/task/list"

# other module level constants
CLIENT_LANG = "en"
JS_NEEDED_SUBSTRING = "trunk_1.0.0 doesn't work properly without JavaScript enabled"  # noqa: E501
BACKLIGHT_STATUS_KEY = "is_blacklight"

# request params
RPC_BACKLIGHT_ON_STATUS = 1
RPC_BACKLIGHT_OFF_STATUS = 0

class InvalidAUTHError(Exception):
    "Raised when response indicates that auth is invalid"
    pass

# mappers
def response_to_exception(r: requests.Response) -> Exception:
    "Converts status code of a response to an exception"
    if r.status_code == 200:
        if re.search(pattern=JS_NEEDED_SUBSTRING, string=r.text): 
            return InvalidAUTHError(f"auth is invalid. response text: {r.text}")
        return
    msg = f"status code: {r.status_code}. details: {r.text}"
    if 400 <= r.status_code < 500:
        return gw.ClientError(msg)
    elif 500 <= r.status_code < 600:
        return gw.ServerError(msg)
    else:
        return gw.UnexpectedStatusCodeError(msg)
    
def _bool_flag_to_int_param(flag: bool) -> int:
    "Converts python bool to int that the API understands"
    if flag:
        return 1
    return 0

def _get_devices_param_to_request(
    is_online: Optional[bool] = None,
    page: Optional[int] = None) -> requests.Request:
    if page is None:
        page = 1
    if is_online is not None:
        is_online = _bool_flag_to_int_param(is_online)
    return requests.Request(
        method="GET",
        url=f"{BASE_URL}/{GET_DEVICES_PATH}",
        params={
            "sort": "-device_name",
            "is_online": is_online,
            "page": page
        }
    )

def _patch_backlight_params_to_request(
    device_id: int,
    switch_status: int) -> requests.Request:
    if switch_status not in {RPC_BACKLIGHT_OFF_STATUS, RPC_BACKLIGHT_ON_STATUS}:  # noqa: E501
        raise ValueError(f"unexpected switch status: {switch_status}")
    return requests.Request(
        method="PUT",
        url=f"{BASE_URL}/{PATCH_BACKLIGHT_PATH}",
        data={
            "type": 0,
            "id": device_id,
            "switchStatus": switch_status
        }
    )

def _get_backlight_settings_params_to_request(device_id: int) -> requests.Request:  # noqa: E501
    return requests.Request(
        method="GET",
        url=f"{BASE_URL}/{GET_BACKLIGHT_SETTINGS_PATH}",
        params={
            "type": 0,
            "id": device_id
        }
    )

def _get_device_task_list_params_to_request(device_id: int) -> requests.Request:
    return requests.Request(
        method="GET",
        url=f"{BASE_URL}/{GET_DEVICE_TASKS_PATH}",
        params={
            "deviceId": device_id,
            "page": 1,
            "per_page": 10,
            "perPage": 10,
            "sort": "startTime"
        }
    )


class MIPSClient(gw.HTTPClient):
    "Wrapper for interacting with MIPS API endpoints"

    def __init__(self, user: str, password: str, timeout: int,
                 auto_auth: Optional[bool] = None):
        """Instantiates MIPS client

        Args:
            user (str): username to use for auth
            password (str): password for auth
            timeout (int): timeout of a single request in seconds.
            auto_auth (bool): True means auth is performed on __init__. Defaults to True.

        Raises:
            e: _description_
        """  # noqa: E501
                
        if auto_auth is None:
            auto_auth = True
        # saving auth data within self to re-auth when needed
        self.auth_request_body = {
            "login_id": user,
            "password": password,
            "lang": CLIENT_LANG
        }
        self.__ok_auth = False
        super().__init__(timeout=timeout)
        if not auto_auth:
            return
        if (e := self.auth()) is None:
            return
        
        if isinstance(e, gw.ClientError):
            log.error("auth failed due to invalid creds")
        elif isinstance(e, gw.ServerError):
            log.error("auth failed due to a server error")
        elif isinstance(e, gw.UnexpectedStatusCodeError):
            log.error("auth failed due to an unknown reason")
        raise e

    def _prepare_auth_req(self) -> requests.PreparedRequest:
        return requests.Request(
            method="POST",
            url=f"{BASE_URL}/{AUTH_PATH}",
            data=self.auth_request_body
        )
    
    def auth(self) -> Exception:
        "Performs client authentication"
        # TODO implement retries for server errors
        r = self.make_request(self._prepare_auth_req())
        if (e := response_to_exception(r=r)) is not None:
            return e
        # getting here means we are ok
        self.__ok_auth = True
        self.sesh.cookies = r.cookies
        log.debug("auth ok, cookies updated. len: %s", len(self.sesh.cookies.items()))  # noqa: E501
        
    def needs_auth(method: Callable):
        "Decorator to enforce auth for calling endpoints requiring it"
        def wrapper(self, *args, **kwargs):
            if not self.__ok_auth:
                self.auth()
            return method(self, *args, **kwargs)
        return wrapper
    
    @needs_auth
    def get_devices(self, results: Optional[list] = None,
                    page: Optional[int] = None,
                    is_online: Optional[bool] = None) -> tuple:
        "Sends a GET request to /devices-mips recursively until all the pages are processed."  # noqa: E501
        if results is None:
            results = []
        r = self.make_request(
            req=_get_devices_param_to_request(
                is_online=is_online, page=page
            )
        )
        if (e := response_to_exception(r)) is not None:
            return None, e
        resp_body = r.json()
        pagination = resp_body["pagination"]
        # reaching max page is base case where we return
        if pagination["page"] == pagination["max"]:
            return results + resp_body["data"], None
        # recursive call with page: pagination.page+1 in params
        return self.get_devices(
            results=resp_body["data"],
            page=pagination["page"]+1,
            is_online=is_online
        )
    
    @needs_auth
    def patch_backlight(self, device_id: int, switch_status: int) -> Exception:
        "Patches backlight settings of a single device"
        try:
            req = _patch_backlight_params_to_request(
                device_id=device_id, switch_status=switch_status
            )
        except Exception as e:
            log.error("request prep failed: %s", e, exc_info=True)
            return  e
        r = self.make_request(req=req)
        return response_to_exception(r=r)
        
    @needs_auth
    def get_backlight_settings(self, device_id: int,
                               only_status: Optional[bool] = None) -> tuple:
        "Fetches backlight settings from MIPS backend"
        if only_status is None:
            only_status = True
        r = self.make_request(
            req=_get_backlight_settings_params_to_request(device_id=device_id)
        )
        if (e := response_to_exception(r=r)) is not None:
            return None, e
        
        body = r.json()
        if not only_status:
            return body, None
        try:
            return int(body[BACKLIGHT_STATUS_KEY]), None
        except KeyError:
            return None, ValueError(f"response body has not data for {BACKLIGHT_STATUS_KEY}")  # noqa: E501
                
    @needs_auth
    def get_device_task_list(self, device_id: int) -> tuple:
        "Fetches most recent tasks associated with a device id"
        r = self.make_request(
            req=_get_device_task_list_params_to_request(device_id=device_id)
        )
        if (e := response_to_exception(r=r)) is not None:
            return None, e
        return r.json(), None
    
    @needs_auth
    def patch_backlight_and_validate(self, device_id: int, switch_status: int) -> Exception:  # noqa: E501
        """Calls patch_backlight and get_backlight_settings to patch backlight and double check the change. 

        Args:
            device_id (int): id of the device (http://185.45.141.19:9000/MIPS/devices-mips/detail/112) 122 is device id
            switch_status (int): status to set, either 0 or 1

        Returns:
            Exception: error if any
        """  # noqa: E501
        patch_err = self.patch_backlight(device_id=device_id,
                                         switch_status=switch_status)
        if patch_err is not None:
            return patch_err
        bl_status, e = self.get_backlight_settings(device_id=device_id)
        if e is not None:
            return e
        if bl_status != switch_status:
            return ValueError(
                f"patch validation failed. switch_status: {switch_status}. actual_status: {bl_status}"  # noqa: E501
            )
    # patch_backlight_and_validate_bulk() needs to be concurrent TODO
    # get device task list (paginated) TODO decide if implementation is needed.
        
        
    


        

