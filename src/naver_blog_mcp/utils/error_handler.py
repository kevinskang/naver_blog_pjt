"""Playwright 에러 핸들링 유틸리티."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Type

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .exceptions import (
    ElementNotFoundError,
    NaverBlogError,
    NaverBlogTimeoutError,
    NavigationError,
    NetworkError,
    UIChangedError,
)

logger = logging.getLogger(__name__)

# 에러 분류 키워드 매핑
_ERROR_KEYWORDS: list[tuple[list[str], Type[NaverBlogError]]] = [
    (["locator", "selector"], ElementNotFoundError),
    (["navigation", "goto"], NavigationError),
    (["net::", "network"], NetworkError),
]


def _make_error_details(
    context: str,
    screenshot_path: Optional[str],
    page_html_path: Optional[str],
    error_str: str,
    error_type: Optional[str] = None,
) -> dict:
    """에러 details dict를 생성합니다."""
    details: dict = {
        "context": context,
        "screenshot": screenshot_path,
        "page_html": page_html_path,
        "original_error": error_str,
    }
    if error_type:
        details["error_type"] = error_type
    return details


def _classify_playwright_error(
    error: Exception,
    error_str: str,
) -> Type[NaverBlogError]:
    """에러 문자열을 분석해 매핑되는 커스텀 예외 클래스를 반환합니다.
    """
    if isinstance(error, PlaywrightTimeoutError):
        return NaverBlogTimeoutError

    lower = error_str.lower()
    for keywords, exc_class in _ERROR_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return exc_class

    return NaverBlogError


async def handle_playwright_error(
    error: Exception,
    page: Optional[Page] = None,
    context: str = "unknown",
    save_screenshot: bool = True,
) -> Exception:
    """Playwright 에러를 커스텀 에러로 변환하고 스크린샷/HTML을 저장합니다.
    """
    error_str = str(error)
    error_type = type(error).__name__

    logger.error("Playwright error in %s: %s - %s", context, error_type, error_str)

    screenshot_path: Optional[str] = None
    page_html_path: Optional[str] = None

    if save_screenshot and page is not None:
        # 스크린샷과 HTML을 병렬로 저장 (Phase 4 성능 개선)
        screenshot_bytes, html_content = await asyncio.gather(
            _capture_screenshot(page),
            _capture_html(page),
            return_exceptions=True,
        )

        if isinstance(screenshot_bytes, bytes):
            screenshot_path = _write_file(
                Path("playwright-state/screenshots"),
                f"error_{context}_{error_type}",
                ".png",
                screenshot_bytes,
                binary=True,
            )
            logger.info("Screenshot saved: %s", screenshot_path)
        else:
            logger.warning("Failed to capture screenshot: %s", screenshot_bytes)

        if isinstance(html_content, str):
            page_html_path = _write_file(
                Path("playwright-state/html"),
                f"page_{context}",
                ".html",
                html_content.encode("utf-8"),
                binary=True,
            )
            logger.info("Page HTML saved: %s", page_html_path)
        else:
            logger.warning("Failed to capture HTML: %s", html_content)

    exc_class = _classify_playwright_error(error, error_str)
    details = _make_error_details(
        context, screenshot_path, page_html_path, error_str,
        error_type if exc_class is NaverBlogError else None,
    )
    msg_prefix = {
        NaverBlogTimeoutError: "Timeout",
        ElementNotFoundError: "Element not found",
        NavigationError: "Navigation failed",
        NetworkError: "Network error",
        NaverBlogError: "Unexpected error",
    }.get(exc_class, "Error")

    return exc_class(f"{msg_prefix} in {context}: {error_str}", details=details)


async def _capture_screenshot(page: Page) -> bytes:
    return await page.screenshot(full_page=True)


async def _capture_html(page: Page) -> str:
    return await page.content()


def _write_file(
    directory: Path,
    prefix: str,
    suffix: str,
    data: bytes,
    binary: bool = True,
) -> str:
    """타임스탬프 기반 파일을 directory에 저장하고 경로를 반환합니다.
    """
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = directory / f"{prefix}_{timestamp}{suffix}"
    if binary:
        filepath.write_bytes(data)
    else:
        filepath.write_text(data.decode("utf-8"), encoding="utf-8")
    return str(filepath)


async def save_error_screenshot(page: Page, context: str, error_type: str) -> str:
    """에러 발생 시 스크린샷을 저장합니다."""
    data = await _capture_screenshot(page)
    return _write_file(
        Path("playwright-state/screenshots"),
        f"error_{context}_{error_type}",
        ".png",
        data,
    )


async def save_page_html(page: Page, context: str) -> str:
    """디버깅을 위해 현재 페이지의 HTML을 저장합니다."""
    content = await _capture_html(page)
    return _write_file(
        Path("playwright-state/html"),
        f"page_{context}",
        ".html",
        content.encode("utf-8"),
    )


def is_retryable_error(error: Exception) -> bool:
    """
    에러가 재시도 가능한지 판단합니다.

    Args:
        error: 발생한 에러

    Returns:
        재시도 가능 여부
    """
    # 재시도 가능한 에러 타입
    retryable_types = (
        NetworkError,
        TimeoutError,
        NavigationError,
    )

    if isinstance(error, retryable_types):
        return True

    # Playwright 기본 에러 체크
    if isinstance(error, PlaywrightTimeoutError):
        return True

    error_str = str(error).lower()
    retryable_keywords = [
        "timeout",
        "network",
        "net::",
        "connection",
        "socket",
    ]

    return any(keyword in error_str for keyword in retryable_keywords)


def should_use_alternative_selector(error: Exception) -> bool:
    """
    대체 셀렉터를 사용해야 하는지 판단합니다.

    Args:
        error: 발생한 에러

    Returns:
        대체 셀렉터 사용 여부
    """
    if isinstance(error, (ElementNotFoundError, UIChangedError)):
        return True

    error_str = str(error).lower()
    selector_keywords = [
        "locator",
        "selector",
        "element",
        "not found",
        "no node found",
    ]

    return any(keyword in error_str for keyword in selector_keywords)
