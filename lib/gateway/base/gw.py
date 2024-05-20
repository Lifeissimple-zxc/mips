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

    def __init__(self):
        "Constructor"
        self.sesh = requests.session()
        atexit.register(self.sesh.close)

    def make_request(self, req: requests.Request) -> requests.Response:
        # TODO add RPS limiting and retries
        return self.sesh.send(
            self.sesh.prepare_request(request=req)
        )
        


        

