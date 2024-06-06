"""
Main entry point of the application.
"""
import logging.config

import yaml

from lib import mips_app
from lib.gateway import google_sheets, mips
from lib.setup import app_config

# logging setup
with open("config/logging.yaml") as _f:
    LOG_CFG = yaml.safe_load(_f)
logging.config.dictConfig(LOG_CFG)
log = logging.getLogger("main_logger")


def main():
    "Encompasses main logic"
    # dependencies configuration
    app = mips_app.App(
            sheets=google_sheets.GoogleSheetsGateway(
            service_acc_path=app_config.sheets.token,
            read_rps=app_config.sheets.read_rps,
            write_rps=app_config.sheets.write_rps,
            request_timeout=app_config.sheets.request_timeout
        ),
        mips_api_client=mips.MIPSClient(
            user=app_config.mips.user,
            password=app_config.mips.password,
            timeout=app_config.mips.timeout
        ),
        cfg=app_config
    )
    
    e = app.execute_tasks()
    if e is not None:
        log.error("tasks execution resulted in an error: %s", e)
        raise e
    # TODO implement telegram messaging and logging
    # TODO add telegram properties to config and app object
    # TODO PROD config
    # TODO rps settings for gateways (blanket and by method)
    # TODO telegram messages on workflow finish


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error("exception in main: %s", e)
