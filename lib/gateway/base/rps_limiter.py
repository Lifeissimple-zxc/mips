"""
Module implements a ratelimiter to be used by gateways
"""
import threading
import time
from typing import Optional


class ThreadingLimiter:
    """
    RPS limiter using threading.Lock.
    Usage:
        limiter = ThreadingLimiter(RPS, # of concurrent requests)
        with limiter:
            ...logic that needs to be throttled...
    """
    def __init__(self, rps: float, concurrent_requests: Optional[int] = None):
        """Constructor"""
        self.rps = rps
        self.rps_lock = threading.Lock()
        self.interval_ms = 1000/rps
        self.last_request_time = time.time() * 1000

        self.concurrency = False
        self.sem = None
        if concurrent_requests is not None:
            self.concurrency = True
            self.sem = threading.Semaphore(concurrent_requests)

    def __enter__(self):  # noqa: D105
        if self.concurrency:
            self.sem.acquire()
        with self.rps_lock:
            time.sleep(
                max(
                    0.,
                    self.interval_ms-((time.time() * 1000)-self.last_request_time))  # noqa: E501
                /1000
            )
            self.last_request_time = time.time() * 1000

    def __exit__(self, exc_type, exc, tb):  # noqa: D105
        if self.concurrency:
            self.sem.release()

    def __str__(self):
        "Helps with printing and logging class info"
        return f"ThreadingLimiter(rps={self.rps}, concurrency={self.concurrency})"  # noqa: E501