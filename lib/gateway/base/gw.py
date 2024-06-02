"""
Module implements a base gateway class powered by requests module.
"""
import atexit
import logging
from typing import Optional

import requests
import retry

from lib.gateway.base import rps_limiter
from lib.internal import timer

log = logging.getLogger("main_logger")

# RPS config parsing modes
RPS_PARSE_BY_METHOD_MODE = 0
_MODE_TO_NAME = {
    RPS_PARSE_BY_METHOD_MODE: "method"
}


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

    def __init__(self, timeout: int,
                 rps_config: Optional[dict] = None,
                 rps_config_parsing_mode: Optional[int] = None):
        "Constructor"
        self.timeout = timeout
        self.sesh = requests.session()
        if rps_config is not None and rps_config_parsing_mode is not None:
            self._parse_rps_config(cfg=rps_config, mode=rps_config_parsing_mode)
        self.rps_by_method = None
        atexit.register(self.sesh.close)

    def _parse_rps_config(self, cfg: dict, mode: Optional[int] = None):
        "Parses and configures client RPS limits"
        if mode is None:
            mode = RPS_PARSE_BY_METHOD_MODE
        # TODO add other modes
        if mode not in {RPS_PARSE_BY_METHOD_MODE}:
            raise NotImplementedError("provided mode is not supported")
        self.mode = mode
        rps_setup = {}
        mode_name = _MODE_TO_NAME[self.mode]
        log.debug("parsing rps config with mode %s", mode_name)
        for key, setup in cfg[mode_name].items():
            rps_setup[key] = rps_limiter.ThreadingLimiter(**setup)
        if self.mode == RPS_PARSE_BY_METHOD_MODE:
            self.rps_by_method = rps_setup

    @staticmethod
    def response_to_exception(r: requests.Response) -> Exception:
        "Converts status code of a response to an exception"
        msg = f"status code: {r.status_code}. details: {r.text}"
        if 400 <= r.status_code < 500:
            return ClientError(msg)
        elif 500 <= r.status_code < 600:
            return ServerError(msg)
        else:
            return UnexpectedStatusCodeError(msg)
    
    @retry.retry(exceptions=(ServerError, UnexpectedStatusCodeError),
                 backoff=2, tries=10, delay=1, logger=log)
    def _make_request(
        self,
        req: requests.Request,
        limiter: Optional[rps_limiter.ThreadingLimiter] = None
    ) -> requests.Response:
        log.debug("making %s req to %s", req.method, req.url)
        if limiter is None:
            with timer.TimerContext() as t:
                r = self.sesh.send(
                    request=self.sesh.prepare_request(request=req),
                    timeout=self.timeout
                )
        else:
            with limiter:
                with timer.TimerContext() as t:
                    r = self.sesh.send(
                        request=self.sesh.prepare_request(request=req),
                        timeout=self.timeout
                    )
        log.debug(
            "%s to %s resulted in %s status response in %s seconds",
            req.method, req.url, r.status_code, t.elapsed
        )
        if (e := self.response_to_exception(r=r)) is None:
            return r
        raise e # trigger decorator
    
    def _request_wrapper(self, req: requests.Request) -> requests.Response:
        # choose limiter
        limiter = None
        if self.rps_by_method is not None:
            limiter = self.rps_by_method.get(req.method.lower(), None)
        # TODO implement endpoint-specific limiting if needed
        return self._make_request(req=req, limiter=limiter)
    
    def make_request(self, req: requests.Request) -> requests.Response:
        """Combines private methods to execute an HTTP request.

        Args:
            req (requests.Request): request to execute

        Raises:
            e: ClientError | ServerError | UnexpectedStatusCodeError

        Returns:
            requests.Response: server response
        """
        try:
            return self._request_wrapper(req=req)
        except Exception as e:
            log.error("request failed despite retries: %s", e)
            raise e

    

        


        

