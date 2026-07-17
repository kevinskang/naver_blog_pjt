"""Iframe 관련 공통 유틸.

이 파일은 에디터 iframe을 찾고 반환하는 공통 함수를 제공합니다.
"""

import logging
from typing import List

from playwright.async_api import Frame, Page
from playwright.async_api import TimeoutError as PlaywrightTimeout

from .exceptions import ElementNotFoundError

logger = logging.getLogger(__name__)


async def get_editor_frame(
    page: Page, selectors: List[str] | None = None, timeout: int = 5000
) -> Frame:
    """페이지에서 에디터 iframe을 찾아 Frame 객체로 반환합니다.

    Args:
        page: Playwright Page
        selectors: iframe 셀렉터 리스트(기본값: 흔히 사용하는 선택자)
        timeout: 각 셀렉터별 대기 타임아웃(ms)

    Returns:
        Playwright Frame

    Raises:
        PlaywrightTimeout: iframe 탐색 중 타임아웃 발생
        ElementNotFoundError: iframe을 찾을 수 없는 경우
    """
    if selectors is None:
        selectors = ["iframe#mainFrame", "iframe[name='mainFrame']"]

    for sel in selectors:
        try:
            iframe_el = await page.wait_for_selector(sel, timeout=timeout)
            if iframe_el:
                frame = await iframe_el.content_frame()
                if frame:
                    logger.debug(f"Found editor iframe with selector: {sel}")
                    return frame
        except PlaywrightTimeout:
            continue
        except Exception:
            continue

    raise ElementNotFoundError(
        "Editor iframe not found",
        details={"selectors": selectors},
    )
