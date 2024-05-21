"""
Module implements a base gateway class powered by requests module.
"""
import atexit
import logging

import requests

log = logging.getLogger("main_logger")

class ClientError(Exception):
    "Raised for all 4XX errors."
    pass

class ServerError(Exception):
    "Raised for all 5XX errors."
    pass

class UnexpectedStatusCodeError(Exception):
    "Raised when status code is weird."
    pass


class HTTPClient:
    "Wrapper on top requests module to interact with http APIs"

    def __init__(self, timeout: int):
        "Constructor"
        self.timeout = timeout
        self.sesh = requests.session()
        atexit.register(self.sesh.close)

    def make_request(self, req: requests.Request) -> requests.Response:
        # TODO add RPS limiting and retries
        log.debug("making %s req to %s", req.method, req.url)
        r = self.sesh.send(
            request=self.sesh.prepare_request(request=req),
            timeout=self.timeout
        )
        log.debug("%s to %s resulted in %s status response",
                  req.method, req.url, r.status_code)
        return r
        


        

