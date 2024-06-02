"""
Module implements utils that are used by other parts of the project
"""
from datetime import datetime, timezone
from typing import Optional, Union


def get_current_timestamp(
        utc: Optional[bool] = None,
        as_string: Optional[bool] = None,
        format: Optional[str] = None
    ) -> Union[datetime, str]:
    """Returns current timestamp

    Args:
        utc (Optional[bool], optional): True means timestamp will be returned in UTC. Defaults to True.
        as_string (Optional[bool], optional): True means a string is returned. Defaults to True.
        format (Optional[str], optional): Result timestamp string format. Defaults to "%Y-%m-%d %H:%M:%S".

    Returns:
        Timestamp as string or datetime
    """  # noqa: E501
    if utc is None:
        utc = True
    if as_string is None:
        as_string = True
    if format is None:
        format = "%Y-%m-%d %H:%M:%S"
    
    if utc:
        now = datetime.now(tz=timezone.utc)
    else:
        now = datetime.now()
    if not as_string:
        return now
    return now.strftime(format=format)