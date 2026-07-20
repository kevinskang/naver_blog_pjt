"""네이버 블로그 카테고리 관련 자동화 기능."""

import logging
import re
from typing import Any, Dict, Optional

from playwright.async_api import ElementHandle, Page

from ..config import config
from ..utils.error_handler import handle_playwright_error
from ..utils.iframe_helper import get_editor_frame
from .constants import IFRAME_WAIT_MS

logger = logging.getLogger(__name__)

# 카테고리로 인정하지 않을 이름
_EXCLUDE_CATEGORY_NAMES = {"블로그 홈", "전체보기"}
# 페이징/탐색 파라미터 (카테고리가 아닌 링크 제외)
_EXCLUDE_HREF_PARAMS = ("currentPage=", "parentCategoryNo=", "categoryNo=0")


async def _extract_blog_id(page: Page) -> Optional[str]:
    """현재 URL에서 blog_id를 추출합니다. 실패 시 config에서 가져옵니다."""
    current_url = page.url
    if "blog.naver.com" in current_url:
        match = re.search(r"blogId=([^&]+)", current_url)
        if match:
            candidate = match.group(1)
            if candidate and not any(p in candidate for p in _EXCLUDE_HREF_PARAMS):
                return candidate
        path_match = re.search(r"blog\.naver\.com/([^/?]+)", current_url)
        if path_match:
            candidate = path_match.group(1)
            exclude_prefixes = {"PostList.naver", "postwrite", "PostView.naver"}
            # 블로그 ID에는 '.'이 없다. BlogHome.naver, GoBlogWrite.naver 등
            # 엔드포인트 경로를 blog_id로 오추출하지 않도록 제외한다.
            if (
                candidate
                and candidate not in exclude_prefixes
                and not candidate.startswith("Post")
                and "." not in candidate
            ):
                return candidate

    fallback = config.NAVER_BLOG_ID
    if fallback:
        logger.debug("URL에서 blog_id 추출 실패, config 값 사용: %s", fallback)
        return fallback
    return None


async def _parse_category_link(
    link: ElementHandle,
    seen_category_nos: set,
    seen_names: set,
) -> Optional[Dict[str, str]]:
    """카테고리 링크 ElementHandle을 파싱하고 유효하면 dict를 반환합니다."""
    text = await link.text_content()
    href = await link.get_attribute("href")

    if not text or not href:
        return None

    name = text.strip()
    if not name or len(name) > 50 or name.isdigit():
        return None
    if name in _EXCLUDE_CATEGORY_NAMES:
        return None
    if any(param in href for param in _EXCLUDE_HREF_PARAMS):
        return None

    no_match = re.search(r"categoryNo=(\d+)", href)
    if not no_match:
        return None
    category_no = no_match.group(1)
    if category_no == "0" or category_no in seen_category_nos or name in seen_names:
        return None

    if href.startswith("/"):
        url = f"https://blog.naver.com{href}"
    elif href.startswith("http"):
        url = href
    else:
        url = f"https://blog.naver.com/{href}"

    seen_category_nos.add(category_no)
    seen_names.add(name)
    return {"name": name, "url": url, "categoryNo": category_no}


async def get_categories(
    page: Page,
    blog_id: Optional[str] = None,
) -> Dict[str, Any]:
    """네이버 블로그의 카테고리 목록을 가져옵니다.

    Args:
        page: Playwright Page 객체
        blog_id: 블로그 아이디 (None이면 현재 로그인한 블로그)

    Returns:
        {
            "success": bool,
            "message": str,
            "categories": [
                {
                    "name": str,           # 카테고리명
                    "url": str,            # 카테고리 URL
                    "categoryNo": str,     # 카테고리 번호
                },
                ...
            ]
        }

    Raises:
        NaverBlogError: 카테고리 조회 실패 시
    """
    try:
        logger.info("카테고리 목록 조회 시작")

        # 1. blog_id 결정
        if not blog_id:
            blog_id = await _extract_blog_id(page)

        blog_url = f"https://blog.naver.com/{blog_id}"
        await page.goto(blog_url, wait_until="networkidle")
        logger.info("블로그 페이지 접근: %s", blog_url)

        # 2. iframe 접근
        try:
            main_frame = await get_editor_frame(page, timeout=IFRAME_WAIT_MS)
            logger.info("iframe#mainFrame 접근 성공")
        except Exception as e:
            logger.error("iframe 접근 실패: %s", e)
            return {
                "success": False,
                "message": "블로그 페이지 구조를 찾을 수 없습니다",
                "categories": [],
            }

        # 3. PostList 링크에서 카테고리 추출
        try:
            category_links = await main_frame.query_selector_all("a[href*='PostList']")
            logger.info("PostList 링크 %d개 발견", len(category_links))
        except Exception as e:
            logger.error("카테고리 링크 조회 실패: %s", e)
            return {
                "success": False,
                "message": f"카테고리 조회 중 오류 발생: {e}",
                "categories": [],
            }

        # 4. 각 링크를 파싱하여 카테고리 정보 추출
        categories = []
        seen_category_nos: set = set()
        seen_names: set = set()

        for link in category_links:
            try:
                # blog_id와 동일한 이름은 블로그 제목이므로 제외
                result = await _parse_category_link(link, seen_category_nos, seen_names)
                if result and (not blog_id or result["name"] != blog_id):
                    categories.append(result)
                    logger.debug(
                        "카테고리 추가: %s (categoryNo=%s)",
                        result["name"],
                        result["categoryNo"],
                    )
            except Exception as e:
                logger.warning("카테고리 정보 추출 중 오류: %s", e)
                continue

        # 5. 결과 반환
        count = len(categories)
        logger.info("카테고리 %d개 조회 완료", count)
        return {
            "success": True,
            "message": (
                f"{count}개의 카테고리를 찾았습니다" if count else "카테고리가 없습니다"
            ),
            "categories": categories,
        }

    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "get_categories")
        logger.error("카테고리 조회 실패: %s", custom_error)
        return {
            "success": False,
            "message": "카테고리 조회 중 오류가 발생했습니다.",
            "categories": [],
        }
