"""
Main entry point of the application.
"""
import logging.config
import os
import pathlib
import platform
import time

import yaml

# logging setup
with open("config/logging.yaml") as _f:
    LOG_CFG = yaml.safe_load(_f)
logging.config.dictConfig(LOG_CFG)
log = logging.getLogger("main_logger")

RETENTION_DAYS = 7
LOG_PATTERN = ".log."

def _get_creation_time(filepath: str) -> float:
    if platform.system() == "Windows":
        return os.path.getctime(filename=filepath)
    stat = os.stat(path=filepath)
    try:
        return stat.st_birthtime
    except AttributeError:
        # We're probably on Linux. No easy way to get creation dates here,
        # so we'll settle for when it was last modified
        return stat.st_mtime

def clean_log_files(path: str, delete=False):
    """Helper func to periodically delete old log files

    Args:
        path (str): path where to search for log files
        delete (bool, optional): True means files are deleted. Defaults to False.
    """
    search_root = pathlib.Path(path)
    log.info("cleaning files in %s", search_root.absolute())
    for f in search_root.iterdir():
        if LOG_PATTERN not in f.name or not f.is_file():
            continue
        created_or_modified = _get_creation_time(f.absolute())
        log.info("%s is a log file created or modified at %s",
                 f.name, created_or_modified)
        days_elapsed = int((time.time() - created_or_modified) / (3600 * 24))
        if days_elapsed <= RETENTION_DAYS:
            continue
        log.info("deletion mode is %s", delete)
        if delete:
            log.info("calling .unlink on %s", f.name)
            f.unlink()

        

