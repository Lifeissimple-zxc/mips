"""
Module implements client for interacting with DC MIPS api.
"""
import logging
import re
from concurrent import futures
from typing import Callable, List, Optional, Union

import requests

from lib.gateway.base import gw
from lib.internal import utils

log = logging.getLogger("main_logger")

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
THREAD_PREFIX = "mips_"
DEFAULT_THREAD_COUNT = 20

# request params
RPC_BACKLIGHT_ON_STATUS = 1
RPC_BACKLIGHT_OFF_STATUS = 0
BACKLIGHT_PARAM_TO_NAME = {
    RPC_BACKLIGHT_ON_STATUS: "backlight_on",
    RPC_BACKLIGHT_OFF_STATUS: "backlight_off"
}

# modes
SHADOW_MODE = "shadow"
PROD_MODE = "production"

class InvalidAUTHError(Exception):
    "Raised when response indicates that auth is invalid"
    pass

# entities
class PatchBacklightAndValidateResult:
    "Represents result of patch_backlight_and_validate method calls"
    def __init__(
            self,
            device: Optional[int] = None,
            start_ts: Optional[str] = None,
            end_ts: Optional[str] = None,
            backlight_status: Optional[str] = None,
            error: Optional[Exception] = None,
            mode: Optional[str] = None 
        ):
        "Constructor"
        self.device = device
        self.start_ts = start_ts
        self.backlight_status = backlight_status
        self.end_ts = end_ts
        self.error = error
        self.mode = mode

    def to_dict(self) -> dict:
        "Converts instance to a dict"
        return {
            "device": self.device,
            "start_ts": self.start_ts,
            "backlight_status": self.backlight_status,
            "end_ts": self.end_ts,
            "error": self.error,
            "mode": self.mode
        }


class MIPSTask:
    "Abstraction for running MIPS requests with concurrent.futures"
    def __init__(self, fn: Callable, *args, **kwargs):
        "Constructs a task and saves the func to call within self"
        self.cancelled = False
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
    
    def __call__(self):
        "Makes instance of this class a function"
        if self.cancelled:
            return
        return self.fn(*self.args, **self.kwargs)
    
    def cancel(self):
        "Cancels a task"
        self.cancelled = True

#TODO this needs to be decoupled from session!
class MIPSClient(gw.HTTPClient):
    "Wrapper for interacting with MIPS API endpoints"

    def __init__(self, user: str, password: str,
                 timeout: int, base_url: str,
                 auto_auth: Optional[bool] = None,
                 rps_config: Optional[dict] = None,
                 rps_config_parsing_mode: Optional[Union[int,str]] = None):
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
        self.base_url = base_url
        self.__ok_auth = False
        super().__init__(timeout=timeout, rps_config=rps_config,
                         rps_config_parsing_mode=rps_config_parsing_mode)
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
            url=f"{self.base_url}/{AUTH_PATH}",
            data=self.auth_request_body
        )
    
    @staticmethod
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
        
    # mappers
    @staticmethod
    def _bool_flag_to_int_param(flag: bool) -> int:
        "Converts python bool to int that the API understands"
        if flag:
            return 1
        return 0

    def _get_devices_param_to_request(
        self,
        is_online: Optional[bool] = None,
        page: Optional[int] = None
    ) -> requests.Request:
            if page is None:
                page = 1
            if is_online is not None:
                is_online = self._bool_flag_to_int_param(is_online)
            return requests.Request(
                method="GET",
                url=f"{self.base_url}/{GET_DEVICES_PATH}",
                params={
                    "sort": "-device_name",
                    "is_online": is_online,
                    "page": page
                }
            )

    def _patch_backlight_params_to_request(
        self,
        device_id: int,
        switch_status: int
    ) -> requests.Request:
            if switch_status not in BACKLIGHT_PARAM_TO_NAME.keys():
                raise ValueError(f"unexpected switch status: {switch_status}")
            return requests.Request(
                method="PUT",
                url=f"{self.base_url}/{PATCH_BACKLIGHT_PATH}",
                data={
                    "type": 0,
                    "id": device_id,
                    "switchStatus": switch_status
                }
            )

    
    def _get_backlight_settings_params_to_request(self,device_id: int) -> requests.Request:  # noqa: E501
            return requests.Request(
                method="GET",
                url=f"{self.base_url}/{GET_BACKLIGHT_SETTINGS_PATH}",
                params={
                    "type": 0,
                    "id": device_id
                }
            )

    def _get_device_task_list_params_to_request(self, device_id: int) -> requests.Request:  # noqa: E501
        return requests.Request(
            method="GET",
            url=f"{self.base_url}/{GET_DEVICE_TASKS_PATH}",
            params={
                "deviceId": device_id,
                "page": 1,
                "per_page": 10,
                "perPage": 10,
                "sort": "startTime"
            }
        )
    
    def auth(self) -> Exception:
        "Performs client authentication"
        r = self.make_request(self._prepare_auth_req())
        if (e := self.response_to_exception(r=r)) is not None:
            return e
        self.__ok_auth = True
        # TODO this needs to be decoupled from session AND sesh needs to be periodically refreshed, like on every request we check time since last request and update session if needed!
        # TODO a lock is needed here
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
        try:
            r = self.make_request(
                req=self._get_devices_param_to_request(
                    is_online=is_online, page=page
                )
            )
        except Exception as e:
            return None, e
        if (e := self.response_to_exception(r)) is not None:
            return None, e
        resp_body = r.json()
        pagination = resp_body["pagination"]
        # reaching max page is the base case where we return
        if pagination["page"] == pagination["max"]:
            return results + resp_body["data"], None
        # recursive call with page: pagination.page+1 in params
        return self.get_devices(
            results=resp_body["data"],
            page=pagination["page"]+1,
            is_online=is_online
        )
    
    @needs_auth
    def patch_backlight(self, device_id: int,
                        switch_status: int,
                        shadow_mode: Optional[bool] = None) -> Exception:
        "Patches backlight settings of a single device"
        if shadow_mode is None:
            shadow_mode = True
        
        if shadow_mode:
            log.info("device id %s is not patched because of shadow mode",
                     device_id)
            return
        try:
            req = self._patch_backlight_params_to_request(
                device_id=device_id, switch_status=switch_status
            )
        except Exception as e:
            log.error("request prep failed: %s", e, exc_info=True)
            return  e
        try:
            return self.response_to_exception(r=self.make_request(req=req))
        except Exception as e:
            return e
        
    @needs_auth
    def get_backlight_settings(self, device_id: int,
                               only_status: Optional[bool] = None) -> tuple:
        "Fetches backlight settings from MIPS backend"
        if only_status is None:
            only_status = True
        try:
            r = self.make_request(
                req=self._get_backlight_settings_params_to_request(device_id=device_id)
            )
        except Exception as e:
            return None, e
        if (e := self.response_to_exception(r=r)) is not None:
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
        try:
            r = self.make_request(
                req=self._get_device_task_list_params_to_request(device_id=device_id)
            )
        except Exception as e:
            return None, e
        if (e := self.response_to_exception(r=r)) is not None:
            return None, e
        return r.json(), None
    
    @needs_auth
    def patch_backlight_and_validate(self, device_id: int,
                                     switch_status: int,
                                     shadow_mode: Optional[bool] = None) -> Exception:  # noqa: E501
        """Calls patch_backlight and get_backlight_settings to patch backlight and double check the change. 

        Args:
            device_id (int): id of the device (http://185.45.141.19:9000/MIPS/devices-mips/detail/112) 122 is device id
            switch_status (int): status to set, either 0 or 1

        Returns:
            Exception: error if any
        """  # noqa: E501
        if shadow_mode is None:
            shadow_mode = True
        
        result = PatchBacklightAndValidateResult(
            device=device_id, start_ts=utils.get_current_timestamp(),
            backlight_status=BACKLIGHT_PARAM_TO_NAME[switch_status],
            mode=PROD_MODE
        )
        if shadow_mode:
            result.mode = SHADOW_MODE
            log.info("no status check for device %s because of shadow mode",
                     device_id)
            return result
        patch_err = self.patch_backlight(device_id=device_id,
                                         switch_status=switch_status,
                                         shadow_mode=shadow_mode)
        if patch_err is not None:
            result.error = patch_err
            return result
        bl_status, e = self.get_backlight_settings(device_id=device_id)
        if e is not None:
            result.error = e
            return result
        
        if bl_status != switch_status:
            result.error = ValueError(
                f"patch validation failed. switch_status: {switch_status}. actual_status: {bl_status}"  # noqa: E501
            )
        return result
    
    @needs_auth
    def patch_backlight_and_validate_bulk(
        self, devices: List[int],
        switch_status: int,
        th_cap: Optional[int] = None,
        shadow_mode: Optional[bool] = None
    ) -> list:
        """Calls patch_backlight_and_validate for a sequence of device ids

        Args:
            devices (Sequence[int]): sequence of device ids to process.
            switch_staus (int): backlight status to apply.
            th_cap (int, optional): max count of worker threads. Defaults to 20.

        Returns:
            list: each entry follows {device_id: error}, ok executions will have None error. 
        """  # noqa: E501
        if th_cap is None:
            th_cap = DEFAULT_THREAD_COUNT
        if shadow_mode is None:
            shadow_mode = True

        results = []
        log.debug("starting bulk patching and validation for %s devices with %s threads", len(devices), th_cap)  # noqa: E501
        with futures.ThreadPoolExecutor(max_workers=th_cap, thread_name_prefix=THREAD_PREFIX) as ex:  # noqa: E501
            tasks = [
                MIPSTask(
                    self.patch_backlight_and_validate,
                    d, switch_status, shadow_mode
                ) for d in devices
            ]
            fs = {ex.submit(task): device for task, device in zip(tasks, devices)}  # noqa: E501
            group_timeout = self.timeout * len(fs)
            done, timed_out = futures.wait(fs, timeout=group_timeout,
                                           return_when=futures.ALL_COMPLETED)
            log.debug("%s out of %s devices bulk patched and validated",
                      len(done), len(done)+len(timed_out))
           
            ts = utils.get_current_timestamp()
            mode = SHADOW_MODE if shadow_mode else PROD_MODE
            backlight_status = BACKLIGHT_PARAM_TO_NAME[switch_status]
            for fut in done:
                device = fs[fut]
                try:
                    res = fut.result()
                except Exception as e:
                    log.debug("patch and validate failed for %s: %s", device, e)
                    results.append(
                        PatchBacklightAndValidateResult(
                            device=device, error=e,
                            start_ts=ts, end_ts=ts,
                            backlight_status=backlight_status,
                            mode=mode,
                        )
                    )
                else:
                    res.end_ts = ts
                    results.append(res)
            log.debug("processed %s done items", len(done))
            
            for fut in timed_out:
                device = fs[fut]
                results.append(
                    PatchBacklightAndValidateResult(
                        device=device,
                        error=TimeoutError(f"group timeout ({group_timeout}) breached"),  # noqa: E501
                        start_ts=ts, end_ts=ts,
                        backlight_status=backlight_status,
                        mode=mode
                    )
                )
                log.debug("patching %s timed out due to group timeout setting", device)  # noqa: E501
                fut.cancel()
            log.debug("processed %s timed out items", len(timed_out))
        return results
