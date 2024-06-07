"""
Module implements custom logging handlers and filters
"""
import atexit
import logging
import pathlib
import queue
from logging import config, handlers
from typing import Optional

from lib.gateway import telegram

# from lib.gateways import tg

_LOG_QUEUE = queue.Queue() # used in logging yaml

log = logging.getLogger("main_logger")
backup_log = logging.getLogger("backup_logger")


class QListenerHandler(handlers.QueueHandler):
    """
    This class listens to the handlers attached to the queue
    Inspired by @marco.vita and https://rob-blackbourn.medium.com/how-to-use-python-logging-queuehandler-with-dictconfig-1e8b1284e27a
    """
    def __init__(self, handler_list: list, queue: queue.Queue,
                 respect_handler_level: Optional[bool] = None,
                 auto_run: Optional[bool] = None):
        """
        Constructor of the class.
        Attaches a list of handlers attaches them to a _listener within self.
        :param handlers: handlers to be attached to a QueueListener of self.
        :param queue: Queue that will handle our logs.
        :param auto_run: True means the listener starts & stops automatically.
        :param respectHandlerLevel: sets respect_handler_level of the listener.
        """
        if respect_handler_level is None:
            respect_handler_level = False
        if auto_run is None:
            auto_run = True
        # Inherit from QueueHandler with queue passed to constructor
        super().__init__(queue)
        # Data type transformation step for handlers
        if isinstance(handler_list, config.ConvertingList):
            # Cannot do for hander in handlers, this would return strings
            handler_list = [handler_list[i] for i in range(len(handler_list))]
        # Store listener within self
        self._listener = handlers.QueueListener(
            self.queue,
            *handler_list,
            respect_handler_level = respect_handler_level
        )
        # IMPORTANT: we enable the class to start and stop automatically
        # w/o the need to call start() and stop() explicitly
        if auto_run:
            self._listener.start()
            # Using atexit lib to register the stop method
            # to be called when the program stops
            # https://docs.python.org/3/library/atexit.html
            atexit.register(self._listener.stop)

    def start(self):
        """
        Starts QueueListener attached to the class
        """
        self._listener.start()

    def stop(self):
        """
        Stops QueueListener attached to the class
        """
        self._listener.stop()

    def emit(self, record: logging.LogRecord):
        """
        Performs logging
        :param record: LogRecord we want to handle
        """
        return super().emit(record)


class LevelFilter(logging.Filter):
    """
    QueueListener doesn't level filter by default, this class takes care of it
    """
    def __init__(self, level: str, strict: Optional[bool] = None):
        """
        Constructor of the class
        :param level: level of a LogRecord message, None by default
        :param strict: True means records of the specified level are handled
        """
        level = level or "DEBUG"
        if strict is None:
            strict = False
        super().__init__()
        # Validate that level we receive is valid
        if level not in (allowed_keys := logging._nameToLevel.keys()):
            raise ValueError(f"must be in {allowed_keys}")
        self.level = logging._nameToLevel[level]
        self.strict = strict

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filters LogRecord for handling
        """
        if self.level is None:
            allow = True
        else:
            # Account for strict parameter of the class
            if self.strict:
                allow = (self.level == record.levelno)
            # Allow all records above or equal to a certain level go through
            else:
                allow = (record.levelno >= self.level)
        return allow


class AttributeFilter(logging.Filter):
    """
    Class for filtering based on attributes of a LogRecord
    passed in extra = {} dict
    """
    def __init__(self, attr_name: str, allow_value: bool, default_value: bool):
        """
        :param attr_name: key of the extra dict passed in logging call.
        :param allow_value: value of the attribute for filter to return True.
        :param default_value: default value of the attribute.
        """
        super().__init__()
        # Store values for filtering logic within self
        self.attr_name = attr_name
        self.allow_value = allow_value
        self.default_value = default_value

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filters LogRecord for handling
        """
        val = getattr(record, self.attr_name, self.default_value)
        return val == self.allow_value

class BackupFileHandler(handlers.TimedRotatingFileHandler):
    """
    Backup handler that is meant to be used only when other handlers fail
    """
    def __init__(self, folder: str, file: str):
        """
        Creates folder for log files (if it does not exist)
        Destination files are rotated at UTC midnight
        :param folder: name of the folder to store our log files
        :param file: name of the log file
        """
        # First we need to handle creation of a directory for log files
        folder_path = pathlib.Path(folder)
        if folder_path.exists():
            if not folder_path.is_dir():
                folder_path.mkdir(parents = True)
        else:
            folder_path.mkdir(parents = True)
        log_file = pathlib.Path(folder, file)
        # Actually construct our class
        super().__init__(filename=log_file, when="MIDNIGHT", utc=True)


class TGHandler(logging.Handler):
    "Handles logging to telegram"
    def __init__(self, gw: telegram.TelegramGateway,
                 user_to_tag_on_error: Optional[int] = None):
        "Constructor of the class"
        super().__init__()
        self.gw = gw
        self.user_to_tag_on_error = user_to_tag_on_error

    def _prepare_message(self, record: logging.LogRecord) -> str:
        """
        Creates a formatted message using info from the record
        """
        msg_str = f"{self.format(record)}"
        # Add urgency if record message is above warning + tag POCs
        if record.levelno >= 30:
            msg_str = f"\u26A0\uFE0F {msg_str}"
        return msg_str

    def _log_to_tg(self, record: logging.LogRecord) -> None:
        if self.user_to_tag_on_error is not None and record.levelno >= 30:
            self.gw.send_message(
                msg=self._prepare_message(record=record),
                is_log=True, user_to_tag=self.user_to_tag_on_error
            )
            return
        self.gw.send_message(
            msg=self._prepare_message(record=record), is_log=True
        )

    def emit(self, record: logging.LogRecord) -> None:
        """
        Actually performs logging
        """
        self._log_to_tg(record=record)