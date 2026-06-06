"""셀렉터 헬퍼 유틸리티."""

import asyncio
import logging
from typing import Any, List, Optional, Union

from playwright.async_api import Frame, Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .exceptions import ElementNotFoundError

logger = logging.getLogger(__name__)

# page_or_frame 타입 alias
PageOrFrame = Union[Page, Frame]


async def try_selectors(
    page_or_frame: PageOrFrame,
    selectors: list[str],
    action: str = "click",
    **kwargs: Any,
) -> bool:
    """셀렉터 리스트를 순회하며 첫 매칭 요소에 action을 실행합니다.

    Args:
        page_or_frame: Playwright Page 또는 Frame 객체
        selectors: 시도할 셀렉터 목록
        action: 실행할 메서드명 ("click", "fill", "type" 등)
        **kwargs: action 메서드에 전달할 인자

    Returns:
        첫 번째 성공 시 True, 모두 실패 시 False
    """
    for selector in selectors:
        try:
            locator = page_or_frame.locator(selector)
            if await locator.count() > 0:
                await getattr(locator.first, action)(**kwargs)
                return True
        except Exception:
            continue
    return False


async def find_element_with_alternatives(
    page: PageOrFrame,
    selectors: Union[str, List[str]],
    timeout: int = 5000,
    context: str = "unknown",
) -> Locator:
    """여러 대체 셀렉터를 시도하여 요소를 찾습니다.

    Args:
        page: Playwright Page 또는 Frame 객체
        selectors: 셀렉터 문자열 또는 대체 셀렉터 리스트
        timeout: 각 셀렉터의 타임아웃 (ms)
        context: 컨텍스트 (로깅용)

    Returns:
        찾은 Locator

    Raises:
        ElementNotFoundError: 모든 셀렉터가 실패한 경우
    """
    if isinstance(selectors, str):
        selectors = [selectors]

    for idx, selector in enumerate(selectors):
        try:
            logger.debug(
                "Trying selector %d/%d in %s: %s",
                idx + 1,
                len(selectors),
                context,
                selector,
            )
            locator = page.locator(selector)
            count = await locator.count()
            if count > 0:
                logger.info(
                    "Found element with selector %d in %s: %s",
                    idx + 1,
                    context,
                    selector,
                )
                return locator.first
        except PlaywrightTimeoutError:
            logger.debug("Selector %d timed out in %s: %s", idx + 1, context, selector)
            continue
        except Exception as e:
            logger.warning(
                "Selector %d failed in %s: %s - %s", idx + 1, context, selector, e
            )
            continue

    raise ElementNotFoundError(
        f"Could not find element in {context} with any of {len(selectors)} selectors",
        details={"context": context, "selectors": selectors},
    )


async def click_with_alternatives(
    page: PageOrFrame,
    selectors: Union[str, List[str]],
    timeout: int = 5000,
    context: str = "unknown",
) -> bool:
    """대체 셀렉터를 시도하여 요소를 클릭합니다.

    Raises:
        ElementNotFoundError: 모든 셀렉터가 실패한 경우
    """
    locator = await find_element_with_alternatives(page, selectors, timeout, context)
    await locator.click(timeout=timeout)
    logger.info("Clicked element in %s", context)
    return True


async def fill_with_alternatives(
    page: PageOrFrame,
    selectors: Union[str, List[str]],
    value: str,
    timeout: int = 5000,
    context: str = "unknown",
) -> bool:
    """대체 셀렉터를 시도하여 요소에 값을 입력합니다.

    Raises:
        ElementNotFoundError: 모든 셀렉터가 실패한 경우
    """
    locator = await find_element_with_alternatives(page, selectors, timeout, context)
    await locator.fill(value, timeout=timeout)
    logger.info("Filled element in %s", context)
    return True


async def wait_for_any_selector(
    page: PageOrFrame,
    selectors: Union[str, List[str]],
    timeout: int = 30000,
    state: str = "visible",
    context: str = "unknown",
) -> Optional[Locator]:
    """여러 셀렉터 중 하나가 나타날 때까지 병렬로 대기합니다.

    Args:
        page: Playwright Page 또는 Frame 객체
        selectors: 셀렉터 문자열 또는 대체 셀렉터 리스트
        timeout: 전체 타임아웃 (ms)
        state: 요소 상태 ("visible", "attached", "hidden")
        context: 컨텍스트 (로깅용)

    Returns:
        찾은 Locator 또는 None

    Raises:
        ElementNotFoundError: 모든 셀렉터가 타임아웃된 경우
    """
    if isinstance(selectors, str):
        selectors = [selectors]

    async def _wait_one(selector: str) -> Optional[Locator]:
        try:
            locator = page.locator(selector).first
            await locator.wait_for(state=state, timeout=timeout)  # type: ignore[arg-type]
            return locator
        except Exception:
            return None

    results = await asyncio.gather(*[_wait_one(s) for s in selectors])
    for locator in results:
        if locator is not None:
            logger.info("Found element in %s", context)
            return locator

    raise ElementNotFoundError(
        f"Could not find any element in {context} with {len(selectors)} selectors",
        details={"context": context, "selectors": selectors},
    )
