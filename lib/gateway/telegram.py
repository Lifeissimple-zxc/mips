"""
Module implements a simple gateway to send messages to telegram messenger
"""
import atexit
import logging
from typing import Optional, Union
import time

import jinja2
import requests
import retry

from lib.gateway.base import gw

log = logging.getLogger("main_logger")

MSG_CHAR_LIMIT = 4096
BASE_URL = "https://api.telegram.org"
SEND_MSG_ENDPOINT = "sendMessage"
MARKDOWN_PARSE_MODE = "MarkdownV2"
HTML_PARSE_MODE = "HTML"
TAG_TMPL = """<a href="tg://user?id={{ user_to_tag }}">{{ msg }}</a>"""

class TooManyRequestsError(Exception):
    "Raised when telegram returns a 429"
    def __init__(self, msg: str, sleep_for: int):
        "Constructor"
        self.msg = msg
        self.sleep_for = sleep_for


class TelegramGateway(gw.HTTPClient):
    "Sends telegram messages"
    def __init__(self, bot_secret: str,
                 chat_id: int, log_chat_id: int, timeout: int,
                 rps_config: Optional[dict] = None,
                 rps_config_parsing_mode: Optional[Union[int,str]] = None):
        "Constructor"
        self.send_msg_url = self._prepare_updates_chat_url(
            bot_secret=bot_secret,
            base_url=BASE_URL,
            send_msg_endpoint=SEND_MSG_ENDPOINT
        )
        super().__init__(timeout=timeout, rps_config=rps_config,
                         rps_config_parsing_mode=rps_config_parsing_mode)
        self.base_message_data = {"chat_id": chat_id}
        self.log_message_data = {"chat_id": log_chat_id}
        self.sesh = requests.session()
        atexit.register(self.sesh.close)
    
    @staticmethod
    def response_to_exception(r: requests.Response) -> Exception:
        "Converts status code of a response to an exception"
        if r.status_code == 200:
            return
        msg = f"status code: {r.status_code}. details: {r.text}"
        if r.status_code == 429:
            data = r.json()
            return TooManyRequestsError(
                msg=msg,
                sleep_for=int(data["parameters"]["retry_after"])
            )
        elif 400 <= r.status_code < 500:
            return gw.ClientError(msg)
        elif 500 <= r.status_code < 600:
            return gw.ServerError(msg)
        else:
            return gw.UnexpectedStatusCodeError(msg)
    
    @staticmethod
    def _prepare_updates_chat_url(bot_secret: str, base_url: str,
                                  send_msg_endpoint: str) -> str:
        """
        Prepares a url for the chat where updates are sent
        """
        return f"{base_url}/bot{bot_secret}/{send_msg_endpoint}"
    
    @staticmethod
    def _truncate_to_char_limit(msg: str):
        return msg[:MSG_CHAR_LIMIT]
    
    @staticmethod
    def _tag_wrapper(msg: str, user_to_tag: int):
        return jinja2.Template(source=TAG_TMPL).render(
            user_to_tag=user_to_tag,
            msg=msg
        )
    
    def _message_params_to_body(self, msg: str, is_log: bool) -> dict:
        if is_log:
            return {
                **self.log_message_data, 
                **{
                    "text": self._truncate_to_char_limit(msg=msg),
                    "parse_mode": HTML_PARSE_MODE
                }
            }
        return {
            **self.base_message_data,
            **{
                "text": self._truncate_to_char_limit(msg=msg),
                "parse_mode": HTML_PARSE_MODE
            }
        }
    
    def _message_params_to_request(
        self,
        msg: str,
        is_log: bool,
        user_to_tag: Optional[int] = None
    ) -> requests.Request:
        if user_to_tag is not None:
            msg = self._tag_wrapper(msg=msg, user_to_tag=user_to_tag)
        msg_data = self._message_params_to_body(
            msg=msg,
            is_log=is_log
        )
        log.debug("prepared telegram message boby: %s", msg_data)
        return requests.Request(
            method="POST",
            url=self.send_msg_url,
            data=msg_data
        )
    
    @retry.retry(exceptions=(TooManyRequestsError,),
                 backoff=2, tries=3 ,delay=1, logger=log)
    def send_message(self, msg: str,
                     is_log: Optional[bool] = None,
                     user_to_tag: Optional[int] = None) -> Exception:
        """Sends a telegram message via an HTTP post request

        Args:
            msg (str): message to send
            is_log (Optional[bool]): True means message is a log record which are sent to a different destination

        Returns:
            Exception: _description_
        """  # noqa: E501
        if is_log is None:
            is_log = False

        try:
            self.make_request(
                req=self._message_params_to_request(
                    msg=msg, is_log=is_log, user_to_tag=user_to_tag
                )
            )
        except TooManyRequestsError as e:
            log.debug("TooManyRequestsError hit, sleeping for %s",
                      e.sleep_for)
            time.sleep(e.sleep_for)
            raise e
        except Exception as e:
            log.error("error sending message: %s", e)
            return e


