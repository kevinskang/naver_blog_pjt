"""네이버 블로그 글쓰기 자동화."""

import asyncio
import logging
from typing import Any, Dict, Optional

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeout

from ..utils.error_handler import handle_playwright_error
from ..utils.exceptions import PostError
from ..utils.iframe_helper import get_editor_frame
from ..utils.selector_helper import find_element_with_alternatives
from .selectors import (
    POST_WRITE_CONTENT_BODY,
    POST_WRITE_PUBLISH_BTN,
    POST_WRITE_TITLE,
)

logger = logging.getLogger(__name__)


async def _select_category(page: Page, category_name: str) -> bool:
    """발행 설정 대화상자에서 카테고리를 선택합니다."""
    for frame in page.frames:
        try:
            # 방법 1: native <select> 요소
            native_selectors = [
                "select[name='categoryNo']",
                "select[name='category']",
                "select.category_select",
            ]
            for sel in native_selectors:
                if await frame.locator(sel).count() > 0:
                    await frame.locator(sel).first.select_option(label=category_name)
                    logger.info(
                        "카테고리 선택 완료 (native select): %s", category_name
                    )
                    return True

            # 방법 2: 커스텀 드롭다운 버튼 클릭 후 목록에서 선택
            dropdown_selectors = [
                ".blog2_series",
                "[class*='category_select']",
                "button[class*='category']",
                "[class*='CategorySelect']",
            ]
            for sel in dropdown_selectors:
                if await frame.locator(sel).count() > 0:
                    await frame.locator(sel).first.click()
                    await asyncio.sleep(0.5)
                    option_sel = (
                        f"li:has-text('{category_name}'),"
                        f" a:has-text('{category_name}')"
                    )
                    if await frame.locator(option_sel).count() > 0:
                        await frame.locator(option_sel).first.click()
                        logger.info(
                            "카테고리 선택 완료 (커스텀 드롭다운): %s", category_name
                        )
                        return True
        except Exception:
            continue

    logger.warning(f"카테고리 '{category_name}'을 찾을 수 없습니다")
    return False


async def _fill_tags(page: Page, tags: list) -> bool:
    """발행 설정 대화상자에서 태그를 입력합니다."""
    for frame in page.frames:
        try:
            tag_selectors = [
                "input[placeholder*='태그']",
                ".tag_input input",
                "#tagInput",
                "input[id*='tag']",
            ]
            for sel in tag_selectors:
                if await frame.locator(sel).count() > 0:
                    tag_input = frame.locator(sel).first
                    for tag in tags:
                        await tag_input.click()
                        await tag_input.type(tag, delay=30)
                        await frame.keyboard.press("Enter")
                        await asyncio.sleep(0.3)
                    logger.info(f"태그 입력 완료: {tags}")
                    return True
        except Exception:
            continue

    logger.warning("태그 입력 필드를 찾을 수 없습니다")
    return False


async def _close_page_popups(page: Page) -> None:
    """Close common popups on the page to ensure editor is accessible."""
    popup_close_selectors = [
        "button.se-popup-button-cancel",
        "button:has-text('닫기')",
        "button:has-text('확인')",
        "button.se-popup-close",
        ".se-popup-dim",
    ]

    for sel in popup_close_selectors:
        try:
            locator = page.locator(sel)
            if await locator.count() > 0:
                await locator.first.click(timeout=2000)
        except Exception:
            continue


async def _type_content_in_iframe(iframe, content: str) -> bool:
    """Type content into iframe's contenteditable body selectors."""
    body_selectors = (
        POST_WRITE_CONTENT_BODY
        if isinstance(POST_WRITE_CONTENT_BODY, list)
        else [POST_WRITE_CONTENT_BODY]
    )

    for body_selector in body_selectors:
        try:
            content_body = await iframe.wait_for_selector(body_selector, timeout=5000)
            if content_body:
                await content_body.click()
                await content_body.fill(content)
                logger.info(
                    "본문 입력 완료 (iframe 방식, selector: %s)", body_selector
                )
                return True
        except Exception:
            continue

    return False


async def _type_content_direct(page: Page, content: str) -> bool:
    """Type content directly into contenteditable on the main page."""
    content_selectors = [
        "div[contenteditable='true']:not([data-placeholder='제목'])",
        "div[contenteditable='true'][role='textbox']",
        "div.se-component",
        "div:has-text('글감과 함께')",
    ]

    for selector in content_selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() > 0:
                await locator.click()
                await locator.fill(content)
                logger.info(
                    "본문 입력 완료 (직접 방식, selector: %s)", selector
                )
                return True
        except Exception:
            continue

    return False


NaverBlogPostError = PostError  # legacy alias for compatibility


async def navigate_to_post_write_page(
    page: Page, blog_id: Optional[str] = None, timeout: int = 30000
) -> None:
    """
    네이버 블로그 글쓰기 페이지로 이동합니다.

    Args:
        page: Playwright Page 객체
        blog_id: 블로그 ID (옵션, 없으면 자동으로 현재 로그인된 블로그 사용)
        timeout: 페이지 로딩 대기 시간 (ms)

    Raises:
        NaverBlogPostError: 페이지 이동 실패 시
    """
    try:
        # 방법 1: blog_id가 주어진 경우
        url: str
        if blog_id:
            url = f"https://blog.naver.com/{blog_id}/postwrite"
        else:
            # 방법 2: 블로그 메인에서 글쓰기 버튼 찾아서 클릭
            await page.goto(
                "https://blog.naver.com", wait_until="networkidle", timeout=timeout
            )

            write_btn_selectors = [
                "a[href*='postwrite']",
                "a:has-text('글쓰기')",
                "button:has-text('글쓰기')",
            ]

            url = "https://blog.naver.com/postwrite"  # 기본값 선언
            for selector in write_btn_selectors:
                count = await page.locator(selector).count()
                if count > 0:
                    element = page.locator(selector).first
                    href = await element.get_attribute("href")
                    if href:
                        if href.startswith("/"):
                            url = f"https://blog.naver.com{href}"
                        elif href.startswith("http"):
                            url = href
                        else:
                            url = f"https://blog.naver.com/{href}"
                        logger.info("글쓰기 버튼 발견: %s", url)
                        break
            else:
                logger.info(
                    "글쓰기 버튼을 찾지 못했습니다. 기본 URL 사용: %s", url
                )

        await page.goto(url, wait_until="networkidle", timeout=timeout)

        current_url = page.url
        logger.info("현재 URL: %s", current_url)

        if (
            "postwrite" in current_url.lower()
            or "PostWriteForm" in current_url
            or "Redirect=Write" in current_url
        ):
            logger.info("글쓰기 페이지로 이동: %s", current_url)
            return

        # 제목 입력란 확인 (추가 검증)
        title_input_exists = False
        selectors = (
            POST_WRITE_TITLE
            if isinstance(POST_WRITE_TITLE, list)
            else [POST_WRITE_TITLE]
        )
        for selector in selectors:
            count = await page.locator(selector).count()
            if count > 0:
                title_input_exists = True
                logger.debug("제목 입력란 발견: %s", selector)
                break

        if title_input_exists:
            logger.info("글쓰기 페이지로 이동: %s", url)
            return

        raise NaverBlogPostError(
            f"글쓰기 페이지 로딩에 실패했습니다. 현재 URL: {current_url}"
        )

    except PlaywrightTimeout as e:
        raise NaverBlogPostError(
            f"글쓰기 페이지 이동 시간 초과: {str(e)}"
        ) from e
    except NaverBlogPostError:
        raise
    except Exception as e:
        logger.debug("글쓰기 페이지 이동 중 예외 발생", exc_info=True)
        raise NaverBlogPostError(
            f"글쓰기 페이지 이동 중 오류: {str(e)}"
        ) from e


async def fill_post_title(page: Page, title: str) -> None:
    """
    블로그 글 제목을 입력합니다.

    Args:
        page: Playwright Page 객체
        title: 글 제목

    Raises:
        NaverBlogPostError: 제목 입력 실패 시
    """
    try:
        # 제목 입력란 찾기 (대체 셀렉터 시도)
        title_filled = False

        try:
            locator = await find_element_with_alternatives(
                page,
                POST_WRITE_TITLE,
                timeout=5000,
                context="title_input",
            )
            is_contenteditable = await locator.get_attribute("contenteditable")
            await locator.click()
            if is_contenteditable:
                await locator.type(title, delay=50)
            else:
                await locator.fill(title)
            title_filled = True
            logger.info(f"제목 입력 완료: {title}")
        except Exception as e:
            logger.debug(f"제목 입력 대체 셀렉터 실패: {e}")

        if not title_filled:
            try:
                await page.mouse.click(450, 250)
                await page.keyboard.type(title, delay=50)
                title_filled = True
                logger.info(f"제목 입력 완료 (클릭 방식): {title}")
            except Exception as e:
                logger.debug(f"제목 클릭 방식 실패: {e}")

        if not title_filled:
            try:
                await page.keyboard.press("Tab")
                await page.keyboard.type(title, delay=50)
                title_filled = True
                logger.info(f"제목 입력 완료 (Tab 방식): {title}")
            except Exception as e:
                logger.debug(f"제목 Tab 방식 실패: {e}")

        if not title_filled:
            raise NaverBlogPostError("제목 입력란을 찾을 수 없습니다.")

        await asyncio.sleep(0.5)

    except NaverBlogPostError:
        raise
    except Exception as e:
        raise NaverBlogPostError(f"제목 입력 중 오류: {str(e)}") from e


async def fill_post_content(page: Page, content: str, use_html: bool = False) -> None:
    """
    블로그 글 본문을 입력합니다.
    스마트에디터 ONE은 iframe 없이 직접 contenteditable을 사용합니다.

    Args:
        page: Playwright Page 객체
        content: 글 본문 내용
        use_html: HTML 모드로 입력할지 여부 (기본: False, 텍스트 모드)

    Raises:
        NaverBlogPostError: 본문 입력 실패 시
    """
    try:
        # 팝업이 있으면 먼저 닫기
        await _close_page_popups(page)

        content_filled = False

        # 방법 1: iframe이 있는 경우 (구형 스마트에디터)
        try:
            iframe = None
            try:
                iframe = await get_editor_frame(page)
            except Exception:
                iframe = None

            if iframe:
                content_filled = await _type_content_in_iframe(iframe, content)
                if content_filled:
                    await page.evaluate("() => { window.focus(); }")
                    await asyncio.sleep(0.5)
        except Exception:
            pass

        # 방법 2: iframe 없이 직접 contenteditable (스마트에디터 ONE)
        if not content_filled:
            content_filled = await _type_content_direct(page, content)

        if not content_filled:
            raise NaverBlogPostError("본문 입력 영역을 찾을 수 없습니다.")

        await asyncio.sleep(1)

    except PlaywrightTimeout as e:
        raise NaverBlogPostError(f"본문 입력 시간 초과: {str(e)}") from e
    except Exception as e:
        raise NaverBlogPostError(f"본문 입력 중 오류: {str(e)}") from e


async def publish_post(  # noqa: C901
    page: Page,
    wait_for_completion: bool = True,
    timeout: int = 30000,
    category: Optional[str] = None,
    tags: Optional[list] = None,
) -> Dict[str, Any]:
    """
    블로그 글을 발행합니다.

    Args:
        page: Playwright Page 객체
        wait_for_completion: 발행 완료를 기다릴지 여부
        timeout: 발행 완료 대기 시간 (ms)

    Returns:
        발행 결과 딕셔너리
        {
            "success": bool,
            "message": str,
            "post_url": str (발행된 글 URL, 성공 시)
        }

    Raises:
        NaverBlogPostError: 발행 실패 시
    """
    try:
        # 0. 메인 페이지로 포커스 전환 (iframe에서 나오기)
        # 명시적으로 메인 페이지로 전환
        await page.bring_to_front()
        await page.evaluate(
            "() => { if (window.parent) { window.parent.focus(); } window.focus(); }"
        )
        await asyncio.sleep(1)

        # 페이지가 실제로 로드되었는지 확인
        logger.debug("현재 URL: %s", page.url)
        logger.debug("페이지 타이틀: %s", await page.title())

        # 페이지 내 모든 팝업/모달 닫기 (도움말 팝업 등)
        try:
            # 도움말 팝업 닫기
            popup_close_selectors = [
                "button.se-popup-button-cancel",  # 취소 버튼
                "button:has-text('닫기')",
                "button:has-text('확인')",
                "button.se-popup-close",
                ".se-popup-dim",  # 팝업 배경 클릭
            ]
            for close_sel in popup_close_selectors:
                popup_count = await page.locator(close_sel).count()
                if popup_count > 0:
                    try:
                        await page.locator(close_sel).first.click(timeout=2000)
                        logger.debug("페이지 팝업 닫기: %s", close_sel)
                        await asyncio.sleep(0.5)
                    except Exception:
                        pass
        except Exception:
            pass

        # 1. 발행 버튼 찾기 및 클릭
        async def _find_and_click_publish(page_or_frame) -> bool:
            """Try to find and click a publish-like button in the given page/frame."""
            try:
                search_texts = ["발행", "글쓰기", "등록"]
                for txt in search_texts:
                    try:
                        sel = f"button:has-text('{txt}'):visible"
                        if await page_or_frame.locator(sel).count() > 0:
                            await page_or_frame.locator(sel).first.click(timeout=5000)
                            await asyncio.sleep(1)
                            return True
                    except Exception:
                        continue

                # fallback: configured selector
                if isinstance(POST_WRITE_PUBLISH_BTN, list):
                    candidates = POST_WRITE_PUBLISH_BTN
                else:
                    candidates = [POST_WRITE_PUBLISH_BTN]

                for cs in candidates:
                    try:
                        if await page_or_frame.locator(cs).count() > 0:
                            await page_or_frame.locator(cs).first.click(timeout=5000)
                            await asyncio.sleep(1)
                            return True
                    except Exception:
                        continue
            except Exception:
                return False
            return False

        publish_clicked = False
        for frame in page.frames:
            try:
                # close frame help popups
                for help_sel in [
                    "button.se-help-close-btn",
                    "button:has-text('닫기')",
                    ".se-help-close",
                ]:
                    try:
                        if await frame.locator(help_sel).count() > 0:
                            await frame.locator(help_sel).first.click(timeout=2000)
                            await asyncio.sleep(0.3)
                    except Exception:
                        continue

                if await _find_and_click_publish(frame):
                    publish_clicked = True
                    logger.info("발행 버튼 클릭 성공 (frame)")
                    break
            except Exception:
                continue

        if not publish_clicked:
            # try main page
            if await _find_and_click_publish(page):
                publish_clicked = True

        if not publish_clicked:
            await page.screenshot(path="playwright-state/error_publish_btn.png")
            raise NaverBlogPostError("발행 버튼을 찾을 수 없습니다.")

        # 2. 발행 설정 대화상자에서 카테고리/태그 설정 후 최종 "발행" 버튼 클릭
        if publish_clicked:
            try:
                await asyncio.sleep(1)  # 대화상자 로딩 대기

                # 카테고리 선택
                if category:
                    selected = await _select_category(page, category)
                    if not selected:
                        logger.warning(
                            "카테고리 '%s' 선택 실패 - 기본 카테고리로 발행", category
                        )
                    await asyncio.sleep(0.5)

                # 태그 입력
                if tags:
                    await _fill_tags(page, tags)
                    await asyncio.sleep(0.5)

                # 대화상자 내 발행 버튼을 force=True로 클릭 시도
                final_publish_clicked = False
                for frame in page.frames:
                    try:
                        dialog_publish_selectors = [
                            (
                                ".layer_popup__i0QOY"
                                " button[class*='confirm']:has-text('발행')"
                            ),
                            ".layer_popup__i0QOY button:has-text('발행')",
                        ]

                        for selector in dialog_publish_selectors:
                            try:
                                btn_count = await frame.locator(selector).count()
                                if btn_count > 0:
                                    await frame.locator(selector).first.click(
                                        force=True, timeout=5000
                                    )
                                    final_publish_clicked = True
                                    await asyncio.sleep(2)
                                    break
                            except Exception:
                                continue

                        if final_publish_clicked:
                            break
                    except Exception:
                        continue

                # JavaScript로 대화상자 내 발행 버튼 클릭 (fallback)
                if not final_publish_clicked:
                    for frame in page.frames:
                        try:
                            result = await frame.evaluate("""
                                () => {
                                    const popup = document.querySelector(
                                        '.layer_popup__i0QOY.is_show__TMSLq'
                                    );
                                    if (!popup) return 'No popup';

                                    const buttons = popup.querySelectorAll('button');
                                    for (let btn of buttons) {
                                        if (
                                            (btn.textContent || '').trim() === '발행'
                                        ) {
                                            btn.click();
                                            return 'Clicked';
                                        }
                                    }
                                    return 'No button';
                                }
                            """)
                            if 'Clicked' in result:
                                await asyncio.sleep(3)
                                break
                        except Exception:
                            continue

            except Exception:
                pass

        # 3. 발행 완료 대기 (옵션)
        if wait_for_completion:
            try:
                # 발행 후 글 보기 페이지로 리다이렉트되는지 확인
                # URL 패턴: https://blog.naver.com/{blog_id}/{post_id}
                await page.wait_for_url("**/blog.naver.com/*/**", timeout=timeout)
                post_url = page.url

                # PostView 페이지인지 확인 (본문 영역이 있는지)
                # 글쓰기 페이지가 아닌 글 보기 페이지인지 체크
                if (
                    "postwrite" not in post_url.lower()
                    and "redirect=write" not in post_url.lower()
                ):
                    # URL이 {blog_id}/{post_id} 형태인지 확인
                    logger.info(f"발행 완료: {post_url}")
                    return {
                        "success": True,
                        "message": "글이 성공적으로 발행되었습니다.",
                        "post_url": post_url,
                    }
                else:
                    raise NaverBlogPostError(
                        "발행 후 페이지 이동에 실패했습니다."
                    )

            except PlaywrightTimeout as e:
                raise NaverBlogPostError("발행 완료 대기 시간 초과") from e
        else:
            return {
                "success": True,
                "message": "발행 요청을 전송했습니다.",
                "post_url": None,
            }

    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "publish_post")
        raise NaverBlogPostError(f"발행 중 오류: {str(custom_error)}") from e


async def create_blog_post(
    page: Page,
    title: str,
    content: str,
    blog_id: Optional[str] = None,
    use_html: bool = False,
    wait_for_completion: bool = True,
    category: Optional[str] = None,
    tags: Optional[list] = None,
) -> Dict[str, Any]:
    """
    네이버 블로그에 새 글을 작성하고 발행하는 전체 프로세스.

    Args:
        page: Playwright Page 객체 (로그인된 상태여야 함)
        title: 글 제목
        content: 글 본문
        blog_id: 블로그 ID (옵션)
        use_html: HTML 모드로 본문 입력할지 여부
        wait_for_completion: 발행 완료를 기다릴지 여부
        category: 카테고리 이름 (옵션)
        tags: 태그 목록 (옵션)

    Returns:
        발행 결과 딕셔너리
        {
            "success": bool,
            "message": str,
            "post_url": str,
            "title": str,
        }

    Raises:
        NaverBlogPostError: 글 작성 실패 시
    """
    try:
        # 1. 글쓰기 페이지로 이동
        await navigate_to_post_write_page(page, blog_id)

        # 2. 제목 입력
        await fill_post_title(page, title)

        # 3. 본문 입력
        await fill_post_content(page, content, use_html)

        # 4. 발행
        result = await publish_post(
            page, wait_for_completion, category=category, tags=tags
        )

        result["title"] = title
        return result

    except NaverBlogPostError:
        raise
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "create_blog_post")
        raise NaverBlogPostError(f"글 작성 중 오류: {str(custom_error)}") from e
