"""
Module implements TimerContext.
It simplifies logging code's execution time.
"""
import threading
import time


class TimerContext:
    """
    Class is meant to facilitate timing of other funcs and methods
    """

    def __init__(self):
        """Instantiates the class with threading lock as an attr"""
        self.lock = threading.Lock()

    def __enter__(self):
        """Context manager dunder method to facilitate catching start time"""
        self.start_time = int(time.time() * 1000)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager dunder method to facilitate catching end time"""
        # Doing with a lock here to avoid race conditions
        with self.lock:
            self.end_time = int(time.time() * 1000)
        elapsed = round((self.end_time - self.start_time) / 1000, 2)
        # Doing with a lock here to avoid race conditions
        with self.lock:
            self.elapsed = elapsed