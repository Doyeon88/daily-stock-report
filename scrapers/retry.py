"""
Retry helper shared by the scrapers
"""

import logging
import time
from typing import Callable, Tuple, Type, TypeVar

from config import MAX_RETRIES, RETRY_DELAY

logger = logging.getLogger(__name__)

T = TypeVar('T')


def call_with_retry(
    func: Callable[[], T], description: str, give_up_on: Tuple[Type[Exception], ...] = ()
) -> T:
    """
    Call func, retrying on any exception

    Args:
        func: Zero-argument callable to run
        description: What is being fetched, for the log
        give_up_on: Exception types that are raised at once instead of retried
                    (for refusals where asking again cannot help)

    Returns:
        The result of func

    Raises:
        The last exception if every attempt fails
    """
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func()
        except give_up_on:
            raise
        except Exception as e:
            last_error = e
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES} failed for {description}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    raise last_error
