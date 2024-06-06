"""
Module implements a simple gateway to send messages to telegram messenger
"""
import atexit
import logging
from typing import Optional

import requests

from lib.gateway.base import gw

log = logging.getLogger("main_logger")

MSG_CHAR_LIMIT = 4096
BASE_URL = "https://api.telegram.org"
SEND_MSG_ENDPOINT = "sendMessage"

class TelegramGateway(gw.HTTPClient):
    "Sends telegram messages"
    def __init__(self, bot_secret: str,
                 chat_id: int, log_chat_id: int,
                 timeout: int):
        "Constructor"
        self.send_msg_url = self._prepare_updates_chat_url(
            bot_secret=bot_secret,
            base_url=BASE_URL,
            send_msg_endpoint=SEND_MSG_ENDPOINT
        )
        super().__init__(timeout=timeout)
        self.base_message_data = {"chat_id": chat_id}
        self.log_message_data = {"chat_id": log_chat_id}
        self.sesh = requests.session()
        atexit.register(self.sesh.close)
    
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
    
    def _message_params_to_body(self, msg: str, is_log: bool) -> dict:
        if is_log:
            return {
                **self.log_message_data, 
                **{"text": self._truncate_to_char_limit(msg=msg)}
            }
        return {
            **self.base_message_data,
            **{"text": self._truncate_to_char_limit(msg=msg)}
        }
    
    def _message_params_to_request(
        self, msg: str, is_log: bool
    ) -> requests.Request:
        msg_data = self._message_params_to_body(msg=msg, is_log=is_log)
        log.debug("prepared telegram message boby: %s", msg_data)
        return requests.Request(
            method="POST",
            url=self.send_msg_url,
            data=msg_data
        )
    
    def send_message(self, msg: str, is_log: Optional[bool] = None) -> Exception:
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
                req=self._message_params_to_request(msg=msg, is_log=is_log)
            )
        except Exception as e:
            # TODO handle high RPS (429ish scenario)
            log.error("error sending message: %s", e)
            return e


