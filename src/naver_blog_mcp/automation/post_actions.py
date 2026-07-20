"""네이버 블로그 글쓰기 자동화.

이 모듈은 발행/카테고리/태그/예약/글 관리 오케스트레이션을 담당한다.
에디터 입력 로직은 ``editor_input.py``, 임시저장 로직은 ``draft_actions.py``
로 분리되어 있으며, 하위호환을 위해 해당 심볼들을 이 모듈에서 re-export 한다.
따라서 ``from ...post_actions import X`` 는 분리 이전과 동일하게 동작한다.
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeout

from ..utils.error_handler import handle_playwright_error
from ..utils.exceptions import PostError
from ..utils.iframe_helper import get_editor_frame
from ..utils.selector_helper import dismiss_overlays

# --- 하위호환 re-export (분리된 모듈의 심볼을 이 모듈 이름공간에 노출) ---
# create_blog_post 는 아래 심볼들을 호출하므로 실사용이기도 하다.
from .draft_actions import (
    _open_draft_list_frame,
    delete_draft,
    list_draft_posts,
    publish_draft,
    save_post_as_draft,
)
from .editor_input import (
    _paste_html_into_body,
    _type_content_direct,
    _type_content_in_iframe,
    fill_post_content,
    fill_post_title,
    navigate_to_post_write_page,
)
from .selectors import (
    POST_WRITE_CONTENT_BODY,
    POST_WRITE_PUBLISH_BTN,
    PUBLISH_CATEGORY_SELECT_BTN,
    PUBLISH_CONFIRM_BTN,
    PUBLISH_TAG_INPUT,
)

logger = logging.getLogger(__name__)

# ``__all__`` 에 등재하여 re-export 심볼이 ruff F401(미사용 import)로 오탐되지
# 않도록 한다. 외부 모듈(tools.py/tests/scripts)의 import 경로 호환을 보장한다.
__all__ = [
    "NaverBlogPostError",
    "_click_final_publish_button",
    "_close_page_popups",
    "_fill_tags",
    "_open_draft_list_frame",
    "_paste_html_into_body",
    "_select_category",
    "_set_schedule_in_frame",
    "_type_content_direct",
    "_type_content_in_iframe",
    "create_blog_post",
    "delete_blog_post",
    "delete_draft",
    "edit_blog_post",
    "fill_post_content",
    "fill_post_title",
    "list_blog_posts",
    "list_draft_posts",
    "navigate_to_post_write_page",
    "publish_draft",
    "publish_post",
    "save_post_as_draft",
]


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
        main_frame = await get_editor_frame(page, timeout=5000)
    except Exception:  # noqa: S110
        main_frame = None

    if main_frame is not None:
        try:
            toggle = main_frame.locator(PUBLISH_CATEGORY_SELECT_BTN).first
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
                "input#tag-input",
                PUBLISH_TAG_INPUT,  # 라이브 검증 (스마트에디터 ONE)
                "input[placeholder*='태그']",
                ".tag_input input",
                "#tagInput",
                "input[id*='tag']",
            ]
            for sel in tag_selectors:
                locator = frame.locator(sel).first
                try:
                    # 태그 입력 필드가 나타날 때까지 프레임당 최대 1초 대기
                    await locator.wait_for(state="visible", timeout=1000)
                    for tag in tags:
                        await locator.click()
                        await locator.type(tag, delay=50)
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(0.3)
                    logger.info(f"태그 입력 완료: {tags}")
                    return True
                except Exception:  # noqa: S110
                    continue
        except Exception:  # noqa: S110
            continue

    logger.warning("태그 입력 필드를 찾을 수 없습니다")
    return False


async def _close_page_popups(page: Page) -> None:
    """Close common popups on the page to ensure editor is accessible."""
    await dismiss_overlays(page)


NaverBlogPostError = PostError  # legacy alias for compatibility


async def _click_final_publish_button(page: Page) -> bool:
    """최종 발행 팝업 대화상자에서 최종 발행(확인) 단추를 클릭합니다."""
    final_publish_clicked = False
    for frame in page.frames:
        try:
            dialog_publish_selectors = [
                PUBLISH_CONFIRM_BTN,  # 라이브 검증 (최종 발행)
                ".layer_popup__i0QOY button[class*='confirm']:has-text('발행')",
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
                except Exception:  # noqa: S110
                    continue

            if final_publish_clicked:
                break
        except Exception:  # noqa: S110
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
                    final_publish_clicked = True
                    break
            except Exception:  # noqa: S110
                continue

    return final_publish_clicked


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
        await dismiss_overlays(page)

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
                    except Exception:  # noqa: S110
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
                    except Exception:  # noqa: S110
                        continue
            except Exception:  # noqa: S110
                return False
            return False

        publish_clicked = False
        for frame in page.frames:
            try:
                # 각 프레임 진입 시 불필요한 도움말/오버레이 닫기 수행
                await dismiss_overlays(frame)

                if await _find_and_click_publish(frame):
                    publish_clicked = True
                    logger.info("발행 버튼 클릭 성공 (frame)")
                    break
            except Exception:  # noqa: S110
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

                # 최종 발행 확인 버튼 클릭 수행
                await _click_final_publish_button(page)

            except Exception:  # noqa: S110
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
