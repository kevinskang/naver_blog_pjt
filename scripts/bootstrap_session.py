"""최초 세션 부트스트랩 스크립트 (DEC-006).

네이버 안티봇은 headless 자동 로그인 시 CAPTCHA/기기 인증을 유발하므로,
최초 1회는 이 스크립트를 **브라우저가 보이는 상태(HEADLESS=false 강제)**로 실행하여
필요 시 사람이 직접 CAPTCHA를 풀고 ``playwright-state/auth.json`` 세션을 생성한다.
이후에는 저장된 세션이 재사용되어 headless 운영이 가능하다.

사용법:
    uv run python scripts/bootstrap_session.py

전제:
    .env 에 NAVER_BLOG_ID, NAVER_BLOG_PASSWORD 가 설정되어 있어야 한다.
"""

import asyncio
import logging

from playwright.async_api import async_playwright

from naver_blog_mcp.automation.login import verify_login_session
from naver_blog_mcp.config import config
from naver_blog_mcp.services.session_manager import SessionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bootstrap_session")


async def main() -> None:
    """브라우저를 띄워 로그인하고 세션 파일을 생성한다."""
    config.validate()

    # 부트스트랩은 수동 CAPTCHA 대응을 위해 반드시 브라우저를 표시한다.
    browser_config = config.get_browser_config()
    browser_config["headless"] = False

    print("=" * 60)
    print(" 네이버 세션 부트스트랩")
    print(f"  - 계정: {config.NAVER_BLOG_ID}")
    print(f"  - 세션 저장 경로: {config.SESSION_STORAGE_PATH}")
    print("  - CAPTCHA/기기 인증이 뜨면 브라우저에서 직접 처리하세요.")
    print("=" * 60)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(**browser_config)
        manager = SessionManager(
            user_id=config.NAVER_BLOG_ID,
            password=config.NAVER_BLOG_PASSWORD,
        )
        try:
            context = await manager.get_or_create_session(browser, headless=False)
            page = context.pages[0] if context.pages else await context.new_page()

            if await verify_login_session(page):
                print("\n✅ 로그인 성공 — 세션이 저장되었습니다.")
                print(f"   {config.SESSION_STORAGE_PATH}")
            else:
                print("\n❌ 로그인 확인 실패 — 세션이 유효하지 않습니다.")

            await context.close()
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
