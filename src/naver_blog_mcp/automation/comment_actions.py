"""네이버 블로그 댓글 자동화."""

import asyncio
import logging
from typing import Any, Dict, Optional

from playwright.async_api import Page

from ..utils.error_handler import handle_playwright_error
from ..utils.exceptions import CommentError
from .constants import IFRAME_WAIT_MS, PAGE_NAV_TIMEOUT_MS

logger = logging.getLogger(__name__)


async def list_comments(
    page: Page, limit: int = 10, blog_id: Optional[str] = None
) -> Dict[str, Any]:
    """네이버 블로그의 댓글 목록을 가져옵니다.

    Args:
        page: Playwright Page 객체 (로그인 상태)
        limit: 조회할 댓글 수
        blog_id: 블로그 ID

    Returns:
        댓글 목록 결과 딕셔너리
    """
    try:
        from ..config import config

        target_blog_id = blog_id or config.NAVER_BLOG_ID

        # 댓글 관리 페이지로 이동
        url = f"https://blog.naver.com/ManageComments.naver?blogId={target_blog_id}"
        logger.info(f"댓글 관리 페이지 이동: {url}")
        await page.goto(url, wait_until="networkidle", timeout=PAGE_NAV_TIMEOUT_MS)

        # iframe#mainFrame 접근
        iframe_element = await page.wait_for_selector(
            "iframe#mainFrame", timeout=IFRAME_WAIT_MS
        )
        frame = await iframe_element.content_frame()
        if not frame:
            raise CommentError(
                "댓글 조회를 위해 iframe#mainFrame에 접근할 수 없습니다."
            )

        # 댓글 행들 탐색
        comments = []
        row_selectors = [
            "tr.comment_row",
            "tr[id*='comment']",
            "tr[id*='tr_']",
            "tbody tr",
        ]

        for r_sel in row_selectors:
            rows = frame.locator(r_sel)
            count = await rows.count()
            if count > 0:
                for i in range(count):
                    row = rows.nth(i)
                    text = (await row.text_content() or "").strip()
                    if not text or "작성자" in text or "내용" in text:
                        continue

                    comment_id = ""
                    chk = row.locator("input[type='checkbox']").first
                    if await chk.count() > 0:
                        comment_id = await chk.get_attribute("value") or ""

                    lines = [line.strip() for line in text.split("\n") if line.strip()]
                    author = lines[0] if len(lines) > 0 else "N/A"
                    content = lines[1] if len(lines) > 1 else "N/A"
                    date = lines[2] if len(lines) > 2 else "N/A"

                    if not comment_id:
                        comment_id = f"dummy_{i}"

                    comments.append(
                        {
                            "comment_id": comment_id,
                            "author": author,
                            "content": content,
                            "date": date,
                        }
                    )

                if comments:
                    break

        return {
            "success": True,
            "message": f"{len(comments)}개의 댓글을 조회했습니다.",
            "comments": comments[:limit],
        }

    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "list_comments")
        raise CommentError(f"댓글 목록 조회 실패: {str(custom_error)}") from e


async def delete_comment(
    page: Page, comment_id: str, blog_id: Optional[str] = None
) -> Dict[str, Any]:
    """네이버 블로그의 특정 댓글을 삭제합니다.

    Args:
        page: Playwright Page 객체 (로그인 상태)
        comment_id: 삭제할 댓글 식별자
        blog_id: 블로그 ID

    Returns:
        작업 결과 딕셔너리
    """
    try:
        from ..config import config

        target_blog_id = blog_id or config.NAVER_BLOG_ID

        url = f"https://blog.naver.com/ManageComments.naver?blogId={target_blog_id}"
        logger.info(f"댓글 관리 페이지 이동: {url}")
        await page.goto(url, wait_until="networkidle", timeout=PAGE_NAV_TIMEOUT_MS)

        # iframe#mainFrame 접근
        iframe_element = await page.wait_for_selector(
            "iframe#mainFrame", timeout=IFRAME_WAIT_MS
        )
        frame = await iframe_element.content_frame()
        if not frame:
            raise CommentError(
                "댓글 삭제를 위해 iframe#mainFrame에 접근할 수 없습니다."
            )

        page.once("dialog", lambda d: asyncio.create_task(d.accept()))

        chk_sel = f"input[type='checkbox'][value='{comment_id}']"
        chk = frame.locator(chk_sel).first
        if await chk.count() > 0:
            await chk.check()
        else:
            chk_any = frame.locator("input[type='checkbox']").first
            if await chk_any.count() > 0:
                await chk_any.check()
            else:
                raise CommentError("삭제할 댓글의 체크박스를 찾을 수 없습니다.")

        await asyncio.sleep(0.5)

        delete_btn_selectors = [
            "button:has-text('삭제')",
            "a:has-text('삭제')",
            ".btn_delete",
            "input[type='button'][value='삭제']",
        ]

        clicked = False
        for btn_sel in delete_btn_selectors:
            btn = frame.locator(btn_sel).first
            if await btn.count() > 0:
                await btn.click()
                clicked = True
                logger.info(f"댓글 삭제 버튼 클릭 성공: {btn_sel}")
                break

        if not clicked:
            raise CommentError("댓글 삭제 버튼을 찾을 수 없습니다.")

        await asyncio.sleep(2)

        return {
            "success": True,
            "message": "댓글이 성공적으로 삭제되었습니다.",
            "comment_id": comment_id,
        }

    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "delete_comment")
        raise CommentError(f"댓글 삭제 실패: {str(custom_error)}") from e
