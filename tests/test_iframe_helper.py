import sys
from unittest.mock import AsyncMock, Mock

import pytest

sys.path.insert(0, "src")

from naver_blog_mcp.utils.iframe_helper import get_editor_frame
from naver_blog_mcp.utils.exceptions import ElementNotFoundError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


@pytest.mark.asyncio
async def test_get_editor_frame_returns_frame_when_selector_matches():
    fake_frame = Mock()
    fake_iframe_el = Mock()
    fake_iframe_el.content_frame = AsyncMock(return_value=fake_frame)

    page = Mock()
    page.wait_for_selector = AsyncMock(return_value=fake_iframe_el)

    frame = await get_editor_frame(page, selectors=["iframe#mainFrame"])

    assert frame is fake_frame


@pytest.mark.asyncio
async def test_get_editor_frame_raises_element_not_found_when_no_iframe():
    async def wait_for_selector(selector, timeout):
        raise PlaywrightTimeoutError("timeout")

    page = Mock()
    page.wait_for_selector = AsyncMock(side_effect=wait_for_selector)

    with pytest.raises(ElementNotFoundError) as exc:
        await get_editor_frame(page, selectors=["iframe#mainFrame"])

    assert "Editor iframe not found" in str(exc.value)
    assert exc.value.details["selectors"] == ["iframe#mainFrame"]
