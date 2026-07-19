"""네이버 블로그 글쓰기 자동화."""

import asyncio
import logging
import re
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
    """발행 설정 대화상자에서 카테고리를 선택합니다.

    방법 0(라이브 검증): iframe#mainFrame 내부의 ``button.selectbox_button__jb1Dt``
    로 카테고리 목록을 열고, ``ul.list__RcvVA``의 항목 이름이 일치하는 라디오를
    선택한다(하위 카테고리는 blind '하위 카테고리' 접두를 제거해 이름 비교).
    실패 시 구형 native select/드롭다운 셀렉터로 폴백한다.
    """
    # 방법 0: 검증된 스마트에디터 ONE 카테고리 셀렉터
    main_frame = None
    try:
        iframe_element = await page.wait_for_selector("iframe#mainFrame", timeout=5000)
        if iframe_element is not None:
            main_frame = await iframe_element.content_frame()
    except Exception:  # noqa: S110
        main_frame = None

    if main_frame is not None:
        try:
            toggle = main_frame.locator("button.selectbox_button__jb1Dt").first
            if await toggle.count() > 0:
                await toggle.click(timeout=3000)
                await asyncio.sleep(0.8)
                selected = await main_frame.evaluate(
                    r"""(target) => {
                        const items = Array.from(
                            document.querySelectorAll(
                                'ul.list__RcvVA li.item__sAGX9'
                            )
                        );
                        for (const li of items) {
                            const span = li.querySelector('span.text__sraQE');
                            if (!span) continue;
                            const name = span.textContent.trim()
                                .replace(/^하위\s*카테고리/, '').trim();
                            if (name === target) {
                                const label =
                                    li.querySelector('label.radio_label__mB6ia');
                                const input =
                                    li.querySelector('input.radio_item__PIBr7');
                                if (label) label.click();
                                else if (input) input.click();
                                return true;
                            }
                        }
                        return false;
                    }""",
                    category_name,
                )
                if selected:
                    logger.info("카테고리 선택 완료 (검증 셀렉터): %s", category_name)
                    await asyncio.sleep(0.5)
                    return True
        except Exception as e:  # noqa: BLE001
            logger.debug("검증 카테고리 셀렉터 실패, 폴백 시도: %s", e)

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
                    logger.info("카테고리 선택 완료 (native select): %s", category_name)
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
                        f"li:has-text('{category_name}'), a:has-text('{category_name}')"
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
                "input.tag_input__rvUB5",  # 라이브 검증 (스마트에디터 ONE)
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
        iframe_element = await page.wait_for_selector("iframe#mainFrame", timeout=10000)
        if iframe_element is not None:
            main_frame = await iframe_element.content_frame()
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


async def publish_post(  # noqa: C901
    page: Page,
    wait_for_completion: bool = True,
    timeout: int = 30000,
    category: Optional[str] = None,
    tags: Optional[list] = None,
    schedule_time: Optional[str] = None,
) -> Dict[str, Any]:
    """
    블로그 글을 발행합니다.

    Args:
        page: Playwright Page 객체
        wait_for_completion: 발행 완료를 기다릴지 여부
        timeout: 발행 완료 대기 시간 (ms)
        category: 카테고리 이름 (선택)
        tags: 태그 목록 (선택)
        schedule_time: 예약 발행 시간 (선택, 형식: YYYY-MM-DD HH:MM)

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
        await page.bring_to_front()
        await page.evaluate(
            "() => { if (window.parent) { window.parent.focus(); } window.focus(); }"
        )
        await asyncio.sleep(1)

        # 페이지가 실제로 로드되었는지 확인
        logger.debug("현재 URL: %s", page.url)
        logger.debug("페이지 타이틀: %s", await page.title())

        # 페이지 내 모든 팝업/모달 닫기
        try:
            popup_close_selectors = [
                "button.se-popup-button-cancel",
                "button:has-text('닫기')",
                "button:has-text('확인')",
                "button.se-popup-close",
                ".se-popup-dim",
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
                for help_sel in [
                    ".se-help-panel-close-button",  # 라이브 검증
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
            if await _find_and_click_publish(page):
                publish_clicked = True

        if not publish_clicked:
            await page.screenshot(path="playwright-state/error_publish_btn.png")
            raise NaverBlogPostError("발행 버튼을 찾을 수 없습니다.")

        # 2. 발행 설정 대화상자에서 설정 후 최종 발행
        if publish_clicked:
            try:
                await asyncio.sleep(1)

                if category:
                    selected = await _select_category(page, category)
                    if not selected:
                        logger.warning(
                            "카테고리 '%s' 선택 실패 - 기본 카테고리로 발행", category
                        )
                    await asyncio.sleep(0.5)

                if tags:
                    await _fill_tags(page, tags)
                    await asyncio.sleep(0.5)

                # 예약 발행 설정
                if schedule_time:
                    for frame in page.frames:
                        if await _set_schedule_in_frame(frame, schedule_time):
                            break
                    await asyncio.sleep(0.5)

                final_publish_clicked = False
                for frame in page.frames:
                    try:
                        dialog_publish_selectors = [
                            "button.confirm_btn__WEaBq",  # 라이브 검증 (최종 발행)
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
                            if "Clicked" in result:
                                await asyncio.sleep(3)
                                break
                        except Exception:
                            continue

            except Exception:
                pass

        # 예약 발행 응답 분기
        if schedule_time:
            return {
                "success": True,
                "message": f"글이 예약 상태로 성공적으로 등록되었습니다 (예약 시간: {schedule_time}).",  # noqa: E501
                "post_url": None,
            }

        # 3. 발행 완료 대기
        if wait_for_completion:
            try:
                await page.wait_for_url("**/blog.naver.com/*/**", timeout=timeout)
                post_url = page.url

                if (
                    "postwrite" not in post_url.lower()
                    and "redirect=write" not in post_url.lower()
                ):
                    logger.info(f"발행 완료: {post_url}")
                    return {
                        "success": True,
                        "message": "글이 성공적으로 발행되었습니다.",
                        "post_url": post_url,
                    }
                else:
                    raise NaverBlogPostError("발행 후 페이지 이동에 실패했습니다.")

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


async def save_post_as_draft(page: Page) -> Dict[str, Any]:
    """작성 중인 글을 임시저장합니다 (공개 발행하지 않음).

    스마트에디터 ONE 상단 툴바의 '저장'(임시저장) 버튼을 클릭한다.
    버튼 class(save_btn__XXXXX)의 해시 접미사는 배포마다 바뀌므로
    class 접두 매칭과 정확 텍스트 매칭을 함께 사용한다.
    """
    save_selectors = [
        "button[class*='save_btn']",
        "button:text-is('저장')",
    ]

    main_frame = None
    try:
        iframe_element = await page.wait_for_selector("iframe#mainFrame", timeout=10000)
        if iframe_element is not None:
            main_frame = await iframe_element.content_frame()
    except Exception:
        main_frame = None

    scopes = ([main_frame] if main_frame is not None else []) + [page]
    for scope in scopes:
        for sel in save_selectors:
            try:
                btn = scope.locator(sel).first
                if await btn.count() > 0:
                    # 최초 진입 시 뜨는 '도움말' 캐러셀 오버레이가 저장 버튼 위를
                    # 덮어 일반 클릭이 가로채질 수 있다. 요소의 native click을 직접
                    # 호출하여 오버레이와 무관하게 저장 핸들러를 실행한다.
                    await btn.evaluate("el => el.click()")
                    await asyncio.sleep(1.5)
                    logger.info("임시저장 완료 (selector: %s)", sel)
                    return {
                        "success": True,
                        "message": "임시저장되었습니다.",
                        "post_url": None,
                    }
            except Exception:  # noqa: S112
                continue

    raise NaverBlogPostError("임시저장 버튼을 찾을 수 없습니다.")


async def create_blog_post(
    page: Page,
    title: str,
    content: str,
    blog_id: Optional[str] = None,
    use_html: bool = False,
    wait_for_completion: bool = True,
    category: Optional[str] = None,
    tags: Optional[list] = None,
    schedule_time: Optional[str] = None,
    publish: bool = True,
) -> Dict[str, Any]:
    """
    네이버 블로그에 새 글을 작성하고 발행(또는 임시저장)하는 전체 프로세스.

    Args:
        page: Playwright Page 객체 (로그인된 상태여야 함)
        title: 글 제목
        content: 글 본문
        blog_id: 블로그 ID (옵션)
        use_html: HTML 모드로 본문 입력할지 여부
        wait_for_completion: 발행 완료를 기다릴지 여부
        category: 카테고리 이름 (옵션)
        tags: 태그 목록 (옵션)
        schedule_time: 예약 발행 시간 (옵션, 형식: YYYY-MM-DD HH:MM)
        publish: True면 발행, False면 임시저장 (기본: True)

    Returns:
        발행/임시저장 결과 딕셔너리
    """
    try:
        await navigate_to_post_write_page(page, blog_id)
        await fill_post_title(page, title)
        await fill_post_content(page, content, use_html)
        if not publish:
            result = await save_post_as_draft(page)
        else:
            result = await publish_post(
                page,
                wait_for_completion,
                category=category,
                tags=tags,
                schedule_time=schedule_time,
            )
        result["title"] = title
        return result

    except NaverBlogPostError:
        raise
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "create_blog_post")
        raise NaverBlogPostError(f"글 작성 중 오류: {str(custom_error)}") from e


async def _set_schedule_in_frame(frame, schedule_time: str) -> bool:
    """발행 설정 레이어에서 예약 발행 시간을 입력합니다."""
    try:
        reserve_selectors = [
            "input[type='radio'][value='booking']",
            ".label_booking",
            "label:has-text('예약')",
            "input[id*='booking']",
        ]
        clicked = False
        for sel in reserve_selectors:
            if await frame.locator(sel).count() > 0:
                await frame.locator(sel).first.click()
                clicked = True
                logger.info("예약 발행 라디오 버튼 선택 완료")
                break
        if not clicked:
            return False

        await asyncio.sleep(0.5)

        dt_parts = schedule_time.strip().split()
        if len(dt_parts) < 2:
            return False
        date_str, time_str = dt_parts[0], dt_parts[1]
        time_parts = time_str.split(":")
        if len(time_parts) < 2:
            return False
        hour_str, minute_str = time_parts[0], time_parts[1]

        date_selectors = [
            "input[placeholder*='날짜']",
            ".input_date",
            "input[name='bookingDate']",
            "input[id*='date']",
        ]
        for sel in date_selectors:
            if await frame.locator(sel).count() > 0:
                date_input = frame.locator(sel).first
                await date_input.click()
                # page object가 frame scope에 없으므로 frame.page 사용 가능
                await frame.page.keyboard.press("Control+A")
                await frame.page.keyboard.press("Backspace")
                await date_input.fill(date_str)
                await frame.page.keyboard.press("Enter")
                logger.info(f"예약 날짜 설정 완료: {date_str}")
                break

        hour_selectors = [
            "select[name='bookingHour']",
            "select.booking_hour",
            "select[id*='hour']",
        ]
        for sel in hour_selectors:
            if await frame.locator(sel).count() > 0:
                await frame.locator(sel).first.select_option(value=str(int(hour_str)))
                logger.info(f"예약 시간(시) 설정 완료: {hour_str}")
                break

        minute_selectors = [
            "select[name='bookingMinute']",
            "select.booking_minute",
            "select[id*='minute']",
        ]
        for sel in minute_selectors:
            if await frame.locator(sel).count() > 0:
                await frame.locator(sel).first.select_option(value=str(int(minute_str)))
                logger.info(f"예약 시간(분) 설정 완료: {minute_str}")
                break

        return True
    except Exception as e:
        logger.warning(f"예약 발행 설정 중 예외 발생: {e}")
        return False


async def delete_blog_post(page: Page, post_url: str) -> Dict[str, Any]:
    """네이버 블로그의 글을 삭제합니다."""
    try:
        await page.goto(post_url, wait_until="networkidle")

        iframe_element = await page.wait_for_selector("iframe#mainFrame", timeout=10000)
        frame = await iframe_element.content_frame()
        if not frame:
            raise PostError("삭제를 위해 iframe#mainFrame에 접근할 수 없습니다.")

        page.once("dialog", lambda dialog: asyncio.create_task(dialog.accept()))

        delete_btn_selectors = [
            "button:has-text('삭제')",
            "a:has-text('삭제')",
            ".btn_delete",
            "a[href*='delete']",
            "a[onclick*='delete']",
        ]

        for more_sel in [
            ".btn_more",
            "a:has-text('더보기')",
            "button:has-text('더보기')",
        ]:
            try:
                if await frame.locator(more_sel).count() > 0:
                    await frame.locator(more_sel).first.click(timeout=2000)
                    await asyncio.sleep(0.5)
            except Exception:
                pass

        clicked = False
        for selector in delete_btn_selectors:
            try:
                btn = frame.locator(selector).first
                if await btn.count() > 0:
                    await btn.click(timeout=3000)
                    clicked = True
                    logger.info(f"글 삭제 버튼 클릭 성공: {selector}")
                    break
            except Exception:
                continue

        if not clicked:
            raise PostError("삭제 버튼을 찾을 수 없습니다.")

        await page.wait_for_url("**/PostList.naver*", timeout=15000)
        logger.info("글 삭제 성공 및 목록 이동 완료")
        return {
            "success": True,
            "message": "글이 성공적으로 삭제되었습니다.",
            "post_url": post_url,
        }
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "delete_blog_post")
        raise PostError(f"글 삭제 실패: {str(custom_error)}") from e


async def edit_blog_post(
    page: Page,
    post_url: str,
    title: str,
    content: str,
    category: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """발행된 블로그 글을 수정합니다."""
    try:
        await page.goto(post_url, wait_until="networkidle")

        iframe_element = await page.wait_for_selector("iframe#mainFrame", timeout=10000)
        frame = await iframe_element.content_frame()
        if not frame:
            raise PostError("수정을 위해 iframe#mainFrame에 접근할 수 없습니다.")

        edit_btn_selectors = [
            "button:has-text('수정')",
            "a:has-text('수정')",
            ".btn_edit",
            "a[href*='update']",
        ]

        for more_sel in [
            ".btn_more",
            "a:has-text('더보기')",
            "button:has-text('더보기')",
        ]:
            try:
                if await frame.locator(more_sel).count() > 0:
                    await frame.locator(more_sel).first.click(timeout=2000)
                    await asyncio.sleep(0.5)
            except Exception:
                pass

        clicked = False
        for selector in edit_btn_selectors:
            try:
                btn = frame.locator(selector).first
                if await btn.count() > 0:
                    await btn.click(timeout=3000)
                    clicked = True
                    logger.info(f"글 수정 버튼 클릭 성공: {selector}")
                    break
            except Exception:
                continue

        if not clicked:
            raise PostError("수정 버튼을 찾을 수 없습니다.")

        await page.wait_for_url("**/PostWriteForm.naver*", timeout=15000)
        await asyncio.sleep(2)

        # 제목 수정
        await page.mouse.click(450, 250)
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await page.keyboard.type(title, delay=30)
        logger.info("제목 수정 완료")

        # 본문 수정
        editor_frame = await get_editor_frame(page)
        body_selectors = (
            POST_WRITE_CONTENT_BODY
            if isinstance(POST_WRITE_CONTENT_BODY, list)
            else [POST_WRITE_CONTENT_BODY]
        )

        content_filled = False
        for body_selector in body_selectors:
            try:
                content_body = await editor_frame.wait_for_selector(
                    body_selector, timeout=5000
                )
                if content_body:
                    await content_body.click()
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                    await content_body.fill(content)
                    content_filled = True
                    logger.info("본문 수정 완료")
                    break
            except Exception:
                continue

        if not content_filled:
            raise PostError("본문 수정 영역을 작성할 수 없습니다.")

        result = await publish_post(
            page, wait_for_completion=True, category=category, tags=tags
        )
        result["title"] = title
        return result

    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "edit_blog_post")
        raise PostError(f"글 수정 실패: {str(custom_error)}") from e


async def list_blog_posts(page: Page, limit: int = 10) -> Dict[str, Any]:
    """글 목록을 조회합니다."""
    try:
        from ..config import config

        blog_id = config.NAVER_BLOG_ID

        # 내 블로그로 이동
        url = f"https://blog.naver.com/{blog_id}"
        await page.goto(url, wait_until="networkidle")

        iframe_element = await page.wait_for_selector("iframe#mainFrame", timeout=10000)
        frame = await iframe_element.content_frame()
        if not frame:
            raise PostError("글 목록을 위해 iframe#mainFrame에 접근할 수 없습니다.")

        for list_btn in [
            ".btn_show_list",
            "button:has-text('목록열기')",
            "a:has-text('목록열기')",
        ]:
            try:
                if await frame.locator(list_btn).count() > 0:
                    await frame.locator(list_btn).first.click(timeout=2000)
                    await asyncio.sleep(0.5)
            except Exception:
                pass

        post_links = []
        selectors = [
            ".title_post a",
            ".p_title a",
            "a[href*='PostView.naver?blogId=']",
            "a[href*='PostView.nhn?blogId=']",
            f"a[href*='/{blog_id}/']",
        ]

        for selector in selectors:
            locators = frame.locator(selector)
            count = await locators.count()
            if count > 0:
                for i in range(min(count, limit)):
                    loc = locators.nth(i)
                    title = (await loc.text_content() or "").strip()
                    href = await loc.get_attribute("href") or ""
                    if (
                        href
                        and title
                        and "categoryNo" not in href
                        and "currentPage" not in href
                    ):
                        if href.startswith("/"):
                            href = f"https://blog.naver.com{href}"
                        elif not href.startswith("http"):
                            href = f"https://blog.naver.com/{blog_id}/{href}"

                        if href not in [p["url"] for p in post_links]:
                            post_links.append(
                                {
                                    "title": title,
                                    "url": href,
                                }
                            )
                if len(post_links) >= limit:
                    break

        return {
            "success": True,
            "message": f"{len(post_links)}개의 글을 조회했습니다.",
            "posts": post_links[:limit],
        }
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "list_blog_posts")
        raise PostError(f"글 목록 조회 실패: {str(custom_error)}") from e


async def _open_draft_list_frame(page: Page):
    """글쓰기 페이지에서 임시저장 목록 팝업을 열고 (frame, opened)를 반환합니다.

    스마트에디터 ONE 기준 라이브 검증된 흐름:
    - ``iframe#mainFrame`` 진입 → 로드 복원 팝업 취소 → 도움말 오버레이 닫기
    - 임시저장 카운트 버튼(``button.save_count_btn__ZTLNa``)을 native click 으로
      눌러 목록을 연다(도움말 오버레이가 일반 클릭을 가로채므로 JS click 사용).
    """
    await navigate_to_post_write_page(page)
    await asyncio.sleep(2)

    iframe_element = await page.wait_for_selector("iframe#mainFrame", timeout=10000)
    frame = await iframe_element.content_frame()
    if frame is None:
        raise PostError("임시저장 목록을 위해 iframe#mainFrame에 접근할 수 없습니다.")

    # 로드 시 뜨는 '작성 중인 글 불러오기' 팝업은 취소해 빈 문서에서 시작
    try:
        cancel = frame.locator("button.se-popup-button-cancel").first
        if await cancel.count() > 0 and await cancel.is_visible():
            await cancel.click(timeout=2000)
            await asyncio.sleep(0.5)
    except Exception:  # noqa: S110
        pass

    # 도움말 오버레이가 버튼 클릭을 가로채므로 닫는다
    try:
        await frame.evaluate(
            """() => {
                document.querySelectorAll('.se-help-panel-close-button')
                    .forEach(b => { try { b.click(); } catch (e) {} });
            }"""
        )
        await asyncio.sleep(0.3)
    except Exception:  # noqa: S110
        pass

    # 임시저장 목록 열기 (native click 으로 오버레이 우회)
    opened = await frame.evaluate(
        """() => {
            const b = document.querySelector('button.save_count_btn__ZTLNa');
            if (b) { b.click(); return true; }
            return false;
        }"""
    )
    if opened:
        await asyncio.sleep(1.5)
    return frame, opened


async def list_draft_posts(page: Page) -> Dict[str, Any]:
    """임시저장 글 목록을 조회합니다."""
    try:
        frame, opened = await _open_draft_list_frame(page)
        if not opened:
            return {
                "success": True,
                "message": "임시저장 글이 없습니다.",
                "drafts": [],
            }

        drafts = await frame.evaluate(
            """() => {
                const items = Array.from(
                    document.querySelectorAll('li.item__mm7Zd')
                );
                return items.map((li, i) => {
                    const s = li.querySelector('strong.title__p1G9u');
                    const d = li.querySelector('span.date__toLrn');
                    return {
                        draft_id: String(i),
                        title: s ? s.textContent.trim()
                                 : ('임시저장 글 #' + (i + 1)),
                        date: d ? d.textContent.trim() : ''
                    };
                });
            }"""
        )
        return {
            "success": True,
            "message": f"{len(drafts)}개의 임시저장 글을 조회했습니다.",
            "drafts": drafts,
        }
    except PostError:
        raise
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "list_draft_posts")
        raise PostError(f"임시저장 글 목록 조회 실패: {str(custom_error)}") from e


async def publish_draft(page: Page, draft_id: str) -> Dict[str, Any]:
    """임시저장된 글을 발행합니다 (draft_id = 목록 인덱스 문자열)."""
    try:
        frame, opened = await _open_draft_list_frame(page)
        if not opened:
            raise PostError("임시저장 목록을 열 수 없습니다 (임시저장 글이 없음).")

        try:
            idx = int(draft_id)
        except (TypeError, ValueError) as ve:
            raise PostError(
                f"draft_id는 정수 인덱스 문자열이어야 합니다: {draft_id}"
            ) from ve

        # 해당 인덱스의 임시저장 글을 열어 편집기로 불러온다
        clicked = await frame.evaluate(
            """(i) => {
                const items = Array.from(
                    document.querySelectorAll('li.item__mm7Zd')
                );
                if (i < 0 || i >= items.length) return false;
                const btn = items[i].querySelector('button.article_button__JNVjf');
                if (!btn) return false;
                btn.click();
                return true;
            }""",
            idx,
        )
        if not clicked:
            raise PostError(
                f"식별자 {draft_id}에 해당하는 임시저장 항목을 찾을 수 없습니다."
            )
        await asyncio.sleep(2)

        return await publish_post(page, wait_for_completion=True)

    except PostError:
        raise
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "publish_draft")
        raise PostError(f"임시저장 글 발행 실패: {str(custom_error)}") from e


async def delete_draft(
    page: Page,
    draft_id: Optional[str] = None,
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """임시저장 글을 삭제합니다.

    ``draft_id``(목록 인덱스 문자열) 또는 ``title``(제목 완전 일치) 중 하나로
    대상을 지정합니다. 삭제는 되돌릴 수 없으므로, ``title`` 지정 시 완전 일치가
    정확히 1건일 때만 삭제합니다(0건/2건 이상이면 안전을 위해 중단).

    삭제 버튼 클릭 시 브라우저 ``confirm`` 대화상자가 뜨므로 자동 수락합니다.
    """
    if draft_id is None and not title:
        raise PostError("draft_id 또는 title 중 하나는 반드시 지정해야 합니다.")

    try:
        frame, opened = await _open_draft_list_frame(page)
        if not opened:
            raise PostError("임시저장 목록을 열 수 없습니다 (임시저장 글이 없음).")

        # 대상 인덱스 결정
        if title:
            matches = await frame.evaluate(
                """(t) => {
                    const items = Array.from(
                        document.querySelectorAll('li.item__mm7Zd')
                    );
                    const idxs = [];
                    items.forEach((li, i) => {
                        const s = li.querySelector('strong.title__p1G9u');
                        if (s && s.textContent.trim() === t) idxs.push(i);
                    });
                    return idxs;
                }""",
                title,
            )
            if len(matches) == 0:
                raise PostError(f"제목이 일치하는 임시저장 글이 없습니다: {title}")
            if len(matches) > 1:
                raise PostError(
                    f"제목이 일치하는 임시저장 글이 {len(matches)}건입니다. "
                    f"안전을 위해 삭제하지 않습니다: {title}"
                )
            target_index = matches[0]
        else:
            try:
                target_index = int(draft_id)  # type: ignore[arg-type]
            except (TypeError, ValueError) as ve:
                raise PostError(
                    f"draft_id는 정수 인덱스 문자열이어야 합니다: {draft_id}"
                ) from ve

        # 삭제 confirm 대화상자 자동 수락 (클릭 전에 등록)
        page.once("dialog", lambda dialog: asyncio.create_task(dialog.accept()))

        result = await frame.evaluate(
            """(i) => {
                const items = Array.from(
                    document.querySelectorAll('li.item__mm7Zd')
                );
                if (i < 0 || i >= items.length) {
                    return {ok: false, total: items.length};
                }
                const li = items[i];
                const s = li.querySelector('strong.title__p1G9u');
                const del = li.querySelector('button.delete_button__kdXNv');
                if (!del) return {ok: false, total: items.length};
                del.click();
                return {ok: true, title: s ? s.textContent.trim() : ''};
            }""",
            target_index,
        )
        if not result.get("ok"):
            raise PostError("삭제할 임시저장 항목/버튼을 찾을 수 없습니다.")

        await asyncio.sleep(2)  # 다이얼로그 수락 + 삭제 처리 대기
        deleted_title = title or result.get("title") or ""
        logger.info("임시저장 글 삭제 완료: %s", deleted_title)
        return {
            "success": True,
            "message": f"임시저장 글 1건을 삭제했습니다: {deleted_title}",
            "deleted_title": deleted_title,
        }

    except PostError:
        raise
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "delete_draft")
        raise PostError(f"임시저장 글 삭제 실패: {str(custom_error)}") from e
