"""
Module implements a base gateway class powered by requests module.
"""
import atexit
import logging
from typing import Optional, Union

import requests
import retry

from lib.gateway.base import rps_limiter
from lib.internal import timer

log = logging.getLogger("main_logger")

# RPS config parsing modes
RPS_PARSE_BY_METHOD_MODE = 0
RPS_PARSE_BLANKET_MODE = 1
_MODE_TO_NAME = {
    RPS_PARSE_BY_METHOD_MODE: "method",
    RPS_PARSE_BLANKET_MODE: "blanket"
}
_NAME_TO_MODE = {
    "method": RPS_PARSE_BY_METHOD_MODE,
    "blanket": RPS_PARSE_BLANKET_MODE
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
                 use_session: Optional[bool] = None,
                 rps_config: Optional[dict] = None,
                 rps_config_parsing_mode: Optional[Union[int,str]] = None):
        "Constructor"
        if use_session is None:
            use_session = True
        log.debug(
            "instantiating HTTP client with timeout %s, rps config %s and parsing mode %s",
            timeout, rps_config, rps_config_parsing_mode
        )
        self.rps_by_method = None
        self.base_rps_limiter = None
        self.timeout = timeout
        self.sesh = None
        if rps_config is not None and rps_config_parsing_mode is not None:
            self._parse_rps_config(cfg=rps_config, mode=rps_config_parsing_mode)
        if use_session:
            log.debug("instantiating gw with session")
            self.sesh = requests.session()
            atexit.register(self.sesh.close)

    @staticmethod
    def _parse_mode(mode: Union[int,str]) -> int:
        if isinstance(mode, str):
            return _NAME_TO_MODE.get(mode.lower(), None)
        elif isinstance(mode, int):
            if mode not in _MODE_TO_NAME.keys():
                raise NotImplementedError("provided mode is not supported")
            return mode
        else:
            raise NotImplementedError("mode argument is of unsupported type: %s", type(mode))  # noqa: E501
    
    def _parse_rps_config(self, cfg: dict,
                          mode: Optional[Union[int,str]] = None):
        "Parses and configures client RPS limits"
        log.debug("parsing rps config with mode %s", mode)
        if mode is None:
            mode = RPS_PARSE_BLANKET_MODE
        self.mode = self._parse_mode(mode=mode)
        rps_setup = {}
        mode_name = _MODE_TO_NAME[self.mode]
        log.debug("rps config mode name %s", mode_name)
        # base
        if self.mode == RPS_PARSE_BLANKET_MODE:
            log.debug("rps parsing mode: %s. Setting self.base_rps_limiter",
                      mode_name)
            self.base_rps_limiter = rps_limiter.ThreadingLimiter(**cfg)
            return
        for key, setup in cfg[mode_name].items():
            rps_setup[key] = rps_limiter.ThreadingLimiter(**setup)
        # by method
        if self.mode == RPS_PARSE_BY_METHOD_MODE:
            log.debug("rps parsing mode: %s. Setting limiters by method: %s",
                      mode_name, rps_setup)
            self.rps_by_method = rps_setup
            return

    @staticmethod
    def response_to_exception(r: requests.Response) -> Exception:
        "Converts status code of a response to an exception"
        if r.status_code == 200:
            return
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
        sesh = self.sesh if self.sesh is not None else requests.session()
        if limiter is None:
            with timer.TimerContext() as t:
                r = sesh.send(
                    request=sesh.prepare_request(request=req),
                    timeout=self.timeout
                )
        else:
            with limiter:
                with timer.TimerContext() as t:
                    r = sesh.send(
                        request=sesh.prepare_request(request=req),
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
            log.debug("rps limiting by method is enabled")
            limiter = self.rps_by_method.get(req.method.lower(), None)
            log.debug("limiter %s was selected by request method name %s",
                      limiter, req.method.lower())
        elif self.base_rps_limiter is not None:
            log.debug("base rps limiting is enabled")
            limiter = self.base_rps_limiter
            log.debug("limiter %s was selected based on self.base_rps_limiter attr",
                      limiter)
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

    

        


        

