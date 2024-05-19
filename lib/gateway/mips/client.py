"""
Module implements client for interacting with DC MIPS api.
"""
import logging
import atexit
from typing import Optional

import requests

log = logging.getLogger("main_logger")

# TODO implement needs_auth decorator
# TODO server error retries
# TODO implement a class for device info, JSONs are tricky to navigate

# urls and endpoint paths
BASE_URL = "http://185.45.141.19:9000/MIPS"
AUTH_PATH = "signin"
GET_DEVICES_PATH = "devices-mips"

# other module level constants
CLIENT_LANG = "en"

# move these to GW module?
class ClientError(Exception):
    "Raised for all 4XX errors."
    pass

class ServerError(Exception):
    "Raised for all 5XX errors."
    pass

class UnexpectedStatusCodeError(Exception):
    "Raised when status code is weird."
    pass


def failed_response_to_exception(r: requests.Response) -> Exception:
    "Converts status code of a response to an exception"
    if 400 <= r.status_code < 500:
        return ClientError(r.text)
    elif 500 <= r.status_code < 600:
        return ServerError(r.text)
    else:
        return UnexpectedStatusCodeError(r.text)
    
def bool_flag_to_int_param(flag: bool) -> int:
    "Converts python bool to int that the API understands"
    if flag:
        return 1
    return 0


class MIPSClient:
    "Wrapper for interacting with MIPS API endpoints"

    def __init__(self, user: str, password: str, timeout: int):
        # saving auth data within self to re-auth when needed
        self.auth_request_body = {
            "login_id": user,
            "password": password,
            "lang": CLIENT_LANG
        }
        self.timeout = timeout
        self.__ok_auth = False
        self.sesh = requests.session()
        atexit.register(self.sesh.close)
        try:
            self.auth()
        except ClientError:
            log.error("auth failed due to invalid creds")
            raise
        except ServerError:
            log.error("auth failed due to a server error")
            raise
        except UnexpectedStatusCodeError:
            log.error("auth failed due to an unknown reason")
            raise

    def auth(self):
        "Performs client authentication"
        # TODO implement retries for server errors
        r = self.sesh.post(
            url=f"{BASE_URL}/{AUTH_PATH}",
            data=self.auth_request_body
        )
        if r.status_code == 200:
            self.__ok_auth = True
            self.sesh.cookies = r.cookies
            log.debug("auth ok, cookies updated. len: %s", len(self.sesh.cookies.items()))  # noqa: E501
            return
        raise failed_response_to_exception(r=r)
        
    def get_devices(self, results: Optional[list] = None,
                    page: Optional[int] = None,
                    is_online: Optional[bool] = None) -> tuple:
        "Fetches devices"
        if page is None:
            page = 1
        if results is None:
            results = []
        if is_online is not None:
            is_online = bool_flag_to_int_param(is_online)
        # GET to devices-mips
        r = self.sesh.get(
            url=f"{BASE_URL}/{GET_DEVICES_PATH}",
            params={
                "sort": "-device_name",
                "is_online": is_online,
                "page": page
            }
        )
        if r.status_code != 200:
            return None, failed_response_to_exception(r)
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
        
    


        

