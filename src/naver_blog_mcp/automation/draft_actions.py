"""네이버 블로그 임시저장 자동화 (임시저장/목록/발행/삭제).

``post_actions.py`` 에서 분리된 모듈이다. 하위호환을 위해 여기의 심볼은
``post_actions.py`` 에서 re-export 된다.
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from playwright.async_api import Page

from ..utils.error_handler import handle_playwright_error
from ..utils.exceptions import PostError
from ..utils.iframe_helper import get_editor_frame
from .constants import IFRAME_WAIT_MS
from .editor_input import navigate_to_post_write_page

logger = logging.getLogger(__name__)

NaverBlogPostError = PostError  # legacy alias for compatibility


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
        main_frame = await get_editor_frame(page, timeout=IFRAME_WAIT_MS)
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


async def _open_draft_list_frame(page: Page):
    """글쓰기 페이지에서 임시저장 목록 팝업을 열고 (frame, opened)를 반환합니다.

    스마트에디터 ONE 기준 라이브 검증된 흐름:
    - ``iframe#mainFrame`` 진입 → 로드 복원 팝업 취소 → 도움말 오버레이 닫기
    - 임시저장 카운트 버튼(``button.save_count_btn__ZTLNa``)을 native click 으로
      눌러 목록을 연다(도움말 오버레이가 일반 클릭을 가로채므로 JS click 사용).
    """
    await navigate_to_post_write_page(page)
    await asyncio.sleep(2)

    iframe_element = await page.wait_for_selector(
        "iframe#mainFrame", timeout=IFRAME_WAIT_MS
    )
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
    # 순환 import 방지: publish_post 는 post_actions 에 잔류(지연 import)
    from .post_actions import publish_post

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
