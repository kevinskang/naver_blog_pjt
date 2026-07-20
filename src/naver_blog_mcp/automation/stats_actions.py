"""네이버 블로그 통계 자동화."""

import logging
from typing import Any, Dict, Optional

from playwright.async_api import Page

from ..utils.error_handler import handle_playwright_error
from ..utils.exceptions import StatsError
from .constants import PAGE_NAV_TIMEOUT_MS

logger = logging.getLogger(__name__)


async def get_blog_stats(page: Page, blog_id: Optional[str] = None) -> Dict[str, Any]:
    """네이버 블로그 통계 데이터를 조회합니다.

    Args:
        page: Playwright Page 객체 (로그인 상태)
        blog_id: 블로그 ID

    Returns:
        통계 데이터 딕셔너리
    """
    try:
        from ..config import config

        target_blog_id = blog_id or config.NAVER_BLOG_ID

        stats_url = (
            f"https://stat.blog.naver.com/stat/overview.naver?blogId={target_blog_id}"
        )
        logger.info(f"통계 페이지 이동: {stats_url}")

        await page.goto(
            stats_url, wait_until="networkidle", timeout=PAGE_NAV_TIMEOUT_MS
        )
        await page.wait_for_timeout(2000)  # 차트/데이터 로딩 대기

        today_visitors = "0"
        yesterday_visitors = "0"
        views = "0"

        # 오늘/어제 방문자수 탐색 셀렉터 후보
        try:
            visitor_container = page.locator(
                ".visitor_summary, .stat_summary, .cnt_visitor, .today_area"
            )
            if await visitor_container.count() > 0:
                text = await visitor_container.first.inner_text()
                lines = [line.strip() for line in text.split("\n") if line.strip()]
                for i, line in enumerate(lines):
                    if "오늘" in line and i + 1 < len(lines):
                        today_visitors = lines[i + 1]
                    elif "어제" in line and i + 1 < len(lines):
                        yesterday_visitors = lines[i + 1]
        except Exception as ex:
            logger.debug(f"방문자수 파싱 실패: {ex}")

        # 개별 셀렉터 후보군 시도
        try:
            today_loc = page.locator(
                ".today_count, .num_today, .visitor_today, .visitor_count .num"
            ).first
            if await today_loc.count() > 0:
                today_visitors = (await today_loc.text_content() or "0").strip()

            yesterday_loc = page.locator(
                ".yesterday_count, .num_yesterday, "
                ".visitor_yesterday, .visitor_count .yesterday"
            ).first
            if await yesterday_loc.count() > 0:
                yesterday_visitors = (await yesterday_loc.text_content() or "0").strip()

            views_loc = page.locator(".view_count, .num_view, .cnt_view").first
            if await views_loc.count() > 0:
                views = (await views_loc.text_content() or "0").strip()
        except Exception as ex:
            logger.debug(f"개별 통계 셀렉터 추출 실패: {ex}")

        return {
            "success": True,
            "message": "블로그 통계 조회가 완료되었습니다.",
            "stats": {
                "today_visitors": today_visitors,
                "yesterday_visitors": yesterday_visitors,
                "views": views,
            },
        }

    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "get_blog_stats")
        raise StatsError(f"블로그 통계 조회 실패: {str(custom_error)}") from e
