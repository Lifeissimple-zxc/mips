"""
Main entry point of the application.
"""
import os
import pathlib
import platform
import time

import yaml

# logging setup
# with open("config/logging.yaml") as _f:
#     LOG_CFG = yaml.safe_load(_f)
# logging.config.dictConfig(LOG_CFG)
# log = logging.getLogger("log_cleaner_logger")

RETENTION_DAYS = 7
LOG_PATTERN = ".log."

def _get_creation_time(filepath: str) -> float:
    if platform.system() == "Windows":
        return os.path.getctime(filename=filepath)
    stat = os.stat(path=filepath).st_mtime
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
    print(f"cleaning files in {search_root.absolute()}")
    for f in search_root.iterdir():
        if LOG_PATTERN not in f.name or not f.is_file():
            continue
        created_or_modified = _get_creation_time(f.absolute())
        days_elapsed = int((time.time() - created_or_modified) / (3600 * 24))
        print(f"{f.name} is a log file days elapsed: {days_elapsed}")
        if days_elapsed > RETENTION_DAYS and delete:
            print(f"calling .unlink on {f.name}", )
            f.unlink()

        

