"""
Main entry point of the application.
"""
import logging.config
import time

import yaml

from lib import mips_app, setup
from lib.gateway import google_sheets, mips
from lib.internal import timer

# logging setup
with open("config/logging.yaml") as _f:
    LOG_CFG = yaml.safe_load(_f)
logging.config.dictConfig(LOG_CFG)
log = logging.getLogger("main_logger")


def main():
    "Encompasses main logic"
    log.info("starting execution in %s", setup.app_config.env)
    # dependencies configuration
    app = mips_app.App(
            sheets=google_sheets.GoogleSheetsGateway(
            service_acc_path=setup.app_config.sheets.token,
            read_rps=setup.app_config.sheets.read_rps,
            write_rps=setup.app_config.sheets.write_rps,
            request_timeout=setup.app_config.sheets.request_timeout
        ),
        mips_api_client=mips.MIPSClient(
            user=setup.app_config.mips.user,
            password=setup.app_config.mips.password,
            timeout=setup.app_config.mips.timeout,
            base_url=setup.app_config.mips.base_url,
            rps_config=setup.app_config.mips.rps_config,
            rps_config_parsing_mode=setup.app_config.mips.rps_config_parsing_mode
        ),
        telegram=setup.TG_GW,
        cfg=setup.app_config
    )
    
    e = app.execute_tasks()
    if e is not None:
        log.error("tasks execution resulted in an error: %s", e, exc_info=True)
        raise e
    # TODO documentation


if __name__ == "__main__":
    while True:
        try:
            try:
                with timer.TimerContext() as custom_timer:
                    main()
            except Exception as e:
                log.error("exception in main: %s", e)
            finally:
                log.info("completed an iteartion in %s sec",
                        custom_timer.elapsed)
                if setup.app_config.env == setup.DEV_ENV:
                    log.info("stopping loop because env is %s",
                            setup.app_config.env)
                    break
                to_sleep = round(setup.app_config.sleep_between_runs - custom_timer.elapsed, 2)  # noqa: E501
                log.info("sleeping for %s minutes before next iteration",
                        round(to_sleep/60, 2))
                time.sleep(to_sleep)
        except KeyboardInterrupt:
            log.error("received a termination signal from user")
            break

            

