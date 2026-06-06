"""재시도 로직 유틸리티."""

import logging

from tenacity import (
    after_log,
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .error_handler import is_retryable_error

logger = logging.getLogger(__name__)


def _is_retryable(error: BaseException) -> bool:
    """tenacity 호환 래퍼 — BaseException을 받아 재시도 가능 여부를 반환."""
    if isinstance(error, Exception):
        return is_retryable_error(error)
    return False


def create_retry_decorator(
    max_attempts: int = 3,
    min_wait: int = 2,
    max_wait: int = 10,
    multiplier: int = 2,
):
    """재시도 데코레이터를 생성합니다."""
    return retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=multiplier, min=min_wait, max=max_wait),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        after=after_log(logger, logging.INFO),
        reraise=True,
    )


# 기본 재시도 데코레이터 (3회, 2-10초)
retry_on_error = create_retry_decorator()

# 빠른 재시도 (3회, 1-5초)
retry_quick = create_retry_decorator(max_attempts=3, min_wait=1, max_wait=5)

# 느린 재시도 (5회, 5-30초)
retry_slow = create_retry_decorator(max_attempts=5, min_wait=5, max_wait=30)
