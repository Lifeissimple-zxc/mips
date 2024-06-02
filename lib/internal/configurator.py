"""
Module implements custom config parser
"""
import os
import pathlib

import dotenv
import yaml

ENV_KEY = "ENV"
SECRETS_YAML_KEY = "secrets_yaml"
GSHEET_CONFIG_KEY = "google_sheets"
MIPS_CONFIG_KEY = "mips"

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
            rps_config: dict,
            rps_config_parsing_mode: int
        ):
        "Constructor"
        self.user = user
        self.password = password
        self.timeout = timeout
        self.rps_config = rps_config,
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
        # env & config
        dotenv.load_dotenv()
        if (env := os.getenv(key=ENV_KEY)) is None:
            raise ValueError(f"{ENV_KEY} is not located in the environment")
        with open(file=pathlib.Path(config_dir, f"{env}.yaml"), encoding="utf-8") as _f:  # noqa: E501
            config_data = yaml.safe_load(stream=_f)
        self.secrets = config_data[SECRETS_YAML_KEY]
        # parse yaml config - TODO
        self.sheets = SheetsConfig(**config_data[GSHEET_CONFIG_KEY])

        # secrets
        with open(file=pathlib.Path(self.secrets), encoding="utf-8") as _f:
            secret_data = yaml.safe_load(stream=_f)
        # parse secrets - TODO
        self.mips = MIPSConfig(
            user=secret_data[MIPS_CONFIG_KEY]["user"],
            password=secret_data[MIPS_CONFIG_KEY]["password"],
            **config_data[MIPS_CONFIG_KEY]
        )
