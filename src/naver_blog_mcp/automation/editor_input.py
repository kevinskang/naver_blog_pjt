"""네이버 블로그 에디터 입력 자동화 (제목/본문 입력, 글쓰기 페이지 이동).

``post_actions.py`` 에서 분리된 모듈이다. 하위호환을 위해 여기의 심볼은
``post_actions.py`` 에서 re-export 된다.
"""

import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeout

from ..utils.exceptions import PostError
from ..utils.iframe_helper import get_editor_frame
from ..utils.selector_helper import find_element_with_alternatives
from .selectors import (
    POST_WRITE_CONTENT_BODY,
    POST_WRITE_TITLE,
)

logger = logging.getLogger(__name__)

NaverBlogPostError = PostError  # legacy alias for compatibility


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
                logger.info("본문 입력 완료 (iframe 방식, selector: %s)", body_selector)
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
                logger.info("본문 입력 완료 (직접 방식, selector: %s)", selector)
                return True
        except Exception:
            continue

    return False


async def fill_post_title(page: Page, title: str, move_to_body: bool = True) -> None:
    """
    블로그 글 제목을 입력합니다.

    Args:
        page: Playwright Page 객체
        title: 글 제목
        move_to_body: True면 제목 입력 후 Enter를 눌러 캐럿을 본문 첫 문단으로
            이동시킵니다(기본값). 스마트에디터 ONE의 제목은 단일 행이며 Enter 시
            포커스가 본문으로 넘어가므로, 본문 요소를 별도로 찾다 제목에 본문이
            잘못 입력되는 문제를 예방합니다.

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

        # 제목 입력 직후 Enter를 눌러 캐럿을 본문 첫 문단으로 이동시킨다.
        # 스마트에디터 ONE의 제목은 단일 행이므로 Enter 시 포커스가 본문으로 넘어간다.
        # 본문 요소를 별도로 찾아 클릭하다 제목에 본문이 잘못 입력되는 문제를 예방한다.
        if move_to_body:
            try:
                await page.keyboard.press("Enter")
                await asyncio.sleep(0.3)
                logger.info("제목 입력 후 Enter로 본문 영역으로 캐럿 이동")
            except Exception as e:  # noqa: BLE001
                logger.debug(f"제목 Enter 본문 이동 실패(무시하고 계속): {e}")

        await asyncio.sleep(0.5)

    except NaverBlogPostError:
        raise
    except Exception as e:
        raise NaverBlogPostError(f"제목 입력 중 오류: {str(e)}") from e


async def _paste_html_into_body(page: Page, html: str) -> bool:
    """HTML 본문을 서식 보존하여 붙여넣기(ClipboardEvent)로 주입합니다.

    스마트에디터 ONE 편집 프레임(``iframe#mainFrame``)에는 제목과 본문을 함께
    포함하는 contenteditable이 1개뿐이므로, 본문 문단
    (``.se-component.se-text .se-text-paragraph``)을 클릭해 캐럿을 본문에 둔 뒤
    단일 contenteditable에 ``paste`` 이벤트를 디스패치한다. 이렇게 하면 마크다운
    표·굵게·목록 등 서식이 네이버 에디터 서식으로 보존된다.
    """
    main_frame = None
    try:
        main_frame = await get_editor_frame(page, timeout=10000)
    except Exception:  # noqa: S110
        main_frame = None
    if main_frame is None:
        return False

    # 로드 복원 팝업 취소 + 도움말 오버레이 닫기
    try:
        popup = main_frame.locator("button.se-popup-button-cancel").first
        if await popup.count() > 0 and await popup.is_visible():
            await popup.click(timeout=2000)
            await asyncio.sleep(0.3)
    except Exception:  # noqa: S110
        pass
    try:
        await main_frame.evaluate(
            """() => { document.querySelectorAll('.se-help-panel-close-button')
                .forEach(b => { try { b.click(); } catch (e) {} }); }"""
        )
    except Exception:  # noqa: S110
        pass

    # 본문 문단 클릭 → 캐럿을 본문에 위치
    try:
        body_para = main_frame.locator(
            ".se-component.se-text .se-text-paragraph"
        ).first
        if await body_para.count() > 0:
            await body_para.click()
            await asyncio.sleep(0.3)
    except Exception:  # noqa: S110
        pass

    plain = re.sub(r"<[^>]*>", "", html)
    pasted = await main_frame.evaluate(
        """({html, plain}) => {
            let target = document.activeElement;
            if (target && target.closest) {
                const ce = target.closest('[contenteditable="true"]');
                if (ce) target = ce;
            }
            if (!target || target.getAttribute('contenteditable') !== 'true') {
                target = document.querySelector('[contenteditable="true"]');
            }
            if (!target) return false;
            const dt = new DataTransfer();
            dt.setData('text/html', html);
            dt.setData('text/plain', plain);
            const ev = new ClipboardEvent('paste', {
                clipboardData: dt, bubbles: true, cancelable: true
            });
            target.dispatchEvent(ev);
            return true;
        }""",
        {"html": html, "plain": plain},
    )
    await asyncio.sleep(2)
    return bool(pasted)


async def fill_post_content(  # noqa: C901
    page: Page, content: str, use_html: bool = False
) -> None:
    """
    블로그 글 본문을 입력합니다.

    스마트에디터 ONE의 본문은 ``iframe#mainFrame`` 내부의
    ``.se-component.se-text`` 텍스트 컴포넌트 문단(contenteditable)에 있습니다.
    (제목은 별도의 ``.se-documentTitle`` 컴포넌트이므로 본문 문단과 구분된다.)

    Args:
        page: Playwright Page 객체
        content: 글 본문 내용
        use_html: HTML 모드로 입력할지 여부 (기본: False, 텍스트 모드)

    Raises:
        NaverBlogPostError: 본문 입력 실패 시
    """
    # 순환 import 방지: _close_page_popups 는 post_actions 에 잔류(지연 import)
    from .post_actions import _close_page_popups

    try:
        # HTML(마크다운 변환본 포함) 본문은 서식 보존 paste 방식으로 주입
        if use_html:
            if await _paste_html_into_body(page, content):
                logger.info("본문 입력 완료 (HTML paste 방식)")
                await asyncio.sleep(1)
                return
            logger.warning("HTML paste 실패 — 텍스트 방식으로 폴백")
            content = re.sub(r"<[^>]*>", "", content)  # 폴백: 태그 제거 평문

        await _close_page_popups(page)

        content_filled = False

        # iframe#mainFrame(스마트에디터 ONE) 진입 후 본문 입력.
        # 방법 0=제목 Enter 후 캐럿 타이핑, 방법 1=본문 셀렉터 클릭 타이핑
        main_frame = None
        try:
            iframe_element = await page.wait_for_selector(
                "iframe#mainFrame", timeout=10000
            )
            if iframe_element is not None:
                main_frame = await iframe_element.content_frame()
        except Exception:
            main_frame = None

        if main_frame is not None:
            # 로드 시 뜨는 '작성 중인 글' 등 팝업을 닫아 에디터를 활성화한다.
            for popup_sel in (
                "button.se-popup-button-cancel",
                "button.se-popup-button-confirm",
            ):
                try:
                    popup = main_frame.locator(popup_sel).first
                    if await popup.count() > 0 and await popup.is_visible():
                        await popup.click(timeout=2000)
                        await asyncio.sleep(0.5)
                except Exception:  # noqa: S112
                    continue

            # 방법 0(우선): 제목 입력 후 Enter로 이미 본문 문단에 캐럿이 놓인 경우,
            # 현재 캐럿 위치(본문)에 바로 타이핑한다. 본문 요소를 별도로 찾아 클릭하다
            # 제목 문단에 본문이 잘못 입력되는 문제를 근본적으로 방지한다.
            try:
                caret_in_body = await main_frame.evaluate(
                    """() => {
                        const el = document.activeElement;
                        if (!el || typeof el.closest !== 'function') {
                            return false;
                        }
                        // 제목 컴포넌트에 포커스가 남아 있으면 본문이 아님
                        if (el.closest('.se-documentTitle, .se-title-text')) {
                            return false;
                        }
                        const ph = el.getAttribute
                            && el.getAttribute('data-placeholder');
                        if (ph === '제목') return false;
                        // 본문 텍스트 컴포넌트/편집 가능한 영역이면 본문으로 간주
                        if (el.closest('.se-component.se-text')) return true;
                        return el.getAttribute
                            && el.getAttribute('contenteditable') === 'true';
                    }"""
                )
            except Exception:  # noqa: BLE001
                caret_in_body = False

            if caret_in_body:
                try:
                    await page.keyboard.type(content, delay=10)
                    logger.info("본문 입력 완료 (제목 Enter 후 캐럿 위치 방식)")
                    content_filled = True
                except Exception as e:  # noqa: BLE001
                    logger.debug(
                        f"캐럿 위치 본문 입력 실패, 셀렉터 방식으로 전환: {e}"
                    )

            # 방법 1(폴백): 본문 텍스트 컴포넌트를 직접 클릭 후 타이핑
            # (제목 문단 오입력 방지를 위해 본문 컴포넌트만 대상으로 한다.)
            if not content_filled:
                body_selectors = (
                    ".se-component.se-text .se-text-paragraph",
                    ".se-component.se-text",
                )
                for sel in body_selectors:
                    try:
                        body = main_frame.locator(sel).first
                        if await body.count() > 0:
                            await body.click()
                            await asyncio.sleep(0.3)
                            await page.keyboard.type(content, delay=10)
                            logger.info(
                                "본문 입력 완료 (mainFrame, selector: %s)", sel
                            )
                            content_filled = True
                            break
                    except Exception:  # noqa: S112
                        continue

        # 방법 2: iframe 없이 직접 contenteditable (구형/폴백)
        if not content_filled:
            content_filled = await _type_content_direct(page, content)

        if not content_filled:
            raise NaverBlogPostError("본문 입력 영역을 찾을 수 없습니다.")

        await asyncio.sleep(1)

    except NaverBlogPostError:
        raise
    except PlaywrightTimeout as e:
        raise NaverBlogPostError(f"본문 입력 시간 초과: {str(e)}") from e
    except Exception as e:
        raise NaverBlogPostError(f"본문 입력 중 오류: {str(e)}") from e


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
                logger.info("글쓰기 버튼을 찾지 못했습니다. 기본 URL 사용: %s", url)

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
        raise NaverBlogPostError(f"글쓰기 페이지 이동 시간 초과: {str(e)}") from e
    except NaverBlogPostError:
        raise
    except Exception as e:
        logger.debug("글쓰기 페이지 이동 중 예외 발생", exc_info=True)
        raise NaverBlogPostError(f"글쓰기 페이지 이동 중 오류: {str(e)}") from e
