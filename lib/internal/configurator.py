"""
Module implements custom config parser
"""
import logging
import os
import pathlib
from typing import Union

import dotenv
import yaml

ENV_KEY = "ENV"
LOG_LEVEL_KEY = "LOGGING_LEVEL"
SECRETS_YAML_KEY = "secrets_yaml"
GSHEET_CONFIG_KEY = "google_sheets"
MIPS_CONFIG_KEY = "mips"
TELEGRAM_CONFIG_KEY = "telegram"

class SheetsConfig:
    "Represents configs needed to interact with gsheet API"
    def __init__(
            self,
            spreadsheet: str,
            tabs: dict,
            token: str,
            read_rps: float,
            write_rps: float,
            request_timeout: float
        ):
        "Constructor"
        self.spreadsheet = spreadsheet
        self.tabs = tabs
        self.token = token
        self.read_rps = read_rps
        self.write_rps = write_rps
        self.request_timeout = request_timeout

class MIPSConfig:
    "Represents configs needed to interact with MIPS API"
    def __init__(
            self,
            user: str,
            password: str,
            timeout: int,
            base_url: str,
            rps_config: dict,
            rps_config_parsing_mode: Union[str,int]
        ):
        "Constructor"
        self.user = user
        self.password = password
        self.timeout = timeout
        self.base_url = base_url
        self.rps_config = rps_config
        self.rps_config_parsing_mode = rps_config_parsing_mode
        

class TelegramConfig:
    "Represents data needed to configure telegram gateway"
    def __init__(
        self,
        bot_secret: str,
        chat_id: int,
        log_chat_id: int,
        timeout: int,
        user_to_tag: int,
        rps_config: dict,
        rps_config_parsing_mode: Union[str,int]
    ):
        "Constructor"
        self.bot_secret = bot_secret
        self.chat_id = chat_id
        self.log_chat_id = log_chat_id
        self.timeout = timeout
        self.user_to_tag = user_to_tag
        self.rps_config = rps_config
        self.rps_config_parsing_mode = rps_config_parsing_mode


class Configurator:
    "Helper class to read and parse configs"
    def __init__(self, config_dir: str):
        """Instantiates configurator and parses app's configs & secrets 

        Args:
            config_dir (str): directory with config yamls. Expected to be in the project's root.

        Raises:
            error if any
        """  # noqa: E501
        # env
        dotenv.load_dotenv(override=True)
        if (env := os.getenv(key=ENV_KEY)) is None:
            raise ValueError(f"{ENV_KEY} is not located in the environment")
        self.env = env
        if (log_lvl := os.getenv(key=LOG_LEVEL_KEY)) is not None:
            log_lvl = logging._nameToLevel.get(log_lvl.upper(), None)
        else:
            log_lvl = logging.DEBUG
        self.log_lvl = log_lvl
        
        # configs
        with open(file=pathlib.Path(config_dir, f"{self.env}.yaml"), encoding="utf-8") as _f:  # noqa: E501
            config_data = yaml.safe_load(stream=_f)
        self.sheets = SheetsConfig(**config_data[GSHEET_CONFIG_KEY])

        # secrets
        with open(file=pathlib.Path(config_data[SECRETS_YAML_KEY]), encoding="utf-8") as _f:  # noqa: E501
            secret_data = yaml.safe_load(stream=_f)
        self.mips = MIPSConfig(
            user=secret_data[MIPS_CONFIG_KEY]["user"],
            password=secret_data[MIPS_CONFIG_KEY]["password"],
            base_url=config_data[MIPS_CONFIG_KEY]["base_url"],
            timeout=config_data[MIPS_CONFIG_KEY]["timeout"],
            rps_config=config_data[MIPS_CONFIG_KEY]["rps_config"],
            rps_config_parsing_mode=config_data[MIPS_CONFIG_KEY]["rps_config_parsing_mode"]
        )
        self.telegram = TelegramConfig(
            bot_secret=secret_data[TELEGRAM_CONFIG_KEY]["bot_secret"],
            chat_id=config_data[TELEGRAM_CONFIG_KEY]["chat_id"],
            log_chat_id=config_data[TELEGRAM_CONFIG_KEY]["log_chat_id"],
            timeout=config_data[TELEGRAM_CONFIG_KEY]["timeout"],
            user_to_tag=config_data[TELEGRAM_CONFIG_KEY]["user_to_tag"],
            rps_config=config_data[TELEGRAM_CONFIG_KEY]["rps_config"],
            rps_config_parsing_mode=config_data[TELEGRAM_CONFIG_KEY]["rps_config_parsing_mode"]
        )
        self.sleep_between_runs = config_data["sleep_between_runs"]
