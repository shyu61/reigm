"""Shared utilities."""

import random
import time


def jitter_sleep(min_seconds: float, max_seconds: float) -> float:
    """Sleep for a uniformly random duration in `[min_seconds, max_seconds]` and return it."""
    delay = random.uniform(min_seconds, max_seconds)
    time.sleep(delay)
    return delay
