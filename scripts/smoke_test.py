"""라이브 스모크 테스트 (Phase B-1).

인증이 정상화된 뒤 실제 네이버를 대상으로 최소 동작 경로를 검증한다:
    check_session → list_categories → create_post(임시저장)

저장된 세션(playwright-state/auth.json)이 필요하다. 없으면 먼저
``uv run python scripts/bootstrap_session.py`` 로 세션을 생성할 것.

사용법:
    uv run python scripts/smoke_test.py

주의:
    3단계에서 임시저장(publish=False)만 수행하므로 공개 발행은 일어나지 않는다.
"""

import asyncio
import json
import logging

from playwright.async_api import async_playwright

from naver_blog_mcp.config import config, get_browser_config
from naver_blog_mcp.mcp.tools import (
    handle_check_session,
    handle_create_post,
    handle_list_categories,
)
from naver_blog_mcp.services.session_manager import SessionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("smoke_test")


def _dump(label: str, result: dict) -> None:
    print(f"\n── {label} " + "─" * (56 - len(label)))
    print(json.dumps(result, ensure_ascii=False, indent=2))


async def main() -> None:
    """세션 → 카테고리 → 임시저장 순으로 최소 경로를 검증한다."""
    config.validate()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(**get_browser_config())
        manager = SessionManager(
            user_id=config.NAVER_BLOG_ID,
            password=config.NAVER_BLOG_PASSWORD,
        )
        try:
            context = await manager.get_or_create_session(
                browser, headless=config.HEADLESS
            )
            page = context.pages[0] if context.pages else await context.new_page()

            # 1) 세션 확인
            _dump("1) check_session", await handle_check_session(page=page))

            # 2) 카테고리 목록
            _dump("2) list_categories", await handle_list_categories(page=page))

            # 3) 임시저장 (공개 발행 아님)
            _dump(
                "3) create_post (임시저장)",
                await handle_create_post(
                    page=page,
                    title="[스모크테스트] 자동화 점검용 임시글",
                    content=(
                        "네이버 블로그 MCP 스모크 테스트로 생성된 "
                        "임시저장 글입니다."
                    ),
                    publish=False,
                ),
            )

            await context.close()
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
