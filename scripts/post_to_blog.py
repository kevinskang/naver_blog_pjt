"""네이버 블로그 글 직접 작성 스크립트."""

import asyncio
import sys
from pathlib import Path

# 프로젝트 src 경로 추가 (scripts/ 기준 상위 디렉토리)
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from naver_blog_mcp.config import config
from naver_blog_mcp.services.session_manager import SessionManager
from naver_blog_mcp.automation.post_actions import create_blog_post
from playwright.async_api import async_playwright

TITLE = "Naver Blog MCP 서버 개발 일지 — 버그 수정 및 개선 작업"

CONTENT = """안녕하세요! 오늘은 Playwright 기반 네이버 블로그 MCP 서버를 개발하면서 발견한 버그들과 개선 과정을 공유합니다.

■ 프로젝트 소개

네이버 블로그 공식 API가 2020년에 종료된 이후, Claude AI가 네이버 블로그를 직접 제어할 수 있도록 Playwright 웹 브라우저 자동화 기반의 MCP(Model Context Protocol) 서버를 구현했습니다.

주요 기능:
- 네이버 블로그 글 자동 작성
- 카테고리 목록 조회
- 이미지 업로드 지원
- 세션 저장 및 재사용 (로그인 유지)


■ 발견된 버그와 수정 과정

[BUG-01] Playwright .first() 잘못된 호출 (P0 — 서버 크래시 직접 원인)

Playwright Python API에서 .first는 메서드가 아니라 프로퍼티(property)입니다.
괄호()를 붙여 호출하면 TypeError: 'Locator' object is not callable 오류가 발생합니다.

수정 전: page.locator(".error_message").first()
수정 후: page.locator(".error_message").first

이 버그 하나 때문에 로그인 실패 시 서버 전체가 크래시 되고 있었습니다.


[BUG-02] logger 미정의 (P0)

login.py 파일 내 _wait_for_captcha_manual() 함수에서 logger.warning(), logger.info()를 호출하지만, 해당 파일에 logger가 선언되어 있지 않았습니다. CAPTCHA 발생 시 NameError로 이어질 수 있는 문제였습니다.

수정: import logging 및 logger = logging.getLogger(__name__) 추가


[BUG-03] config.HEADLESS 미전달 (P1)

서버 초기화 시 get_or_create_session() 호출에 headless 파라미터를 전달하지 않아 .env의 HEADLESS=false 설정이 무시되고 항상 headless 모드로 동작했습니다.

수정: config.HEADLESS 값을 명시적으로 전달


[BUG-04] 컨텍스트 설정 미적용 (P1)

브라우저 컨텍스트 생성 시 get_context_config()에서 정의한 User-Agent, 뷰포트, 로케일, 타임존 설정이 전혀 적용되지 않고 있었습니다. 봇 탐지 회피를 위한 핵심 설정이 빠진 상태였습니다.

수정: 세션 복원 및 신규 생성 시 **get_context_config() 전개 적용


[BUG-05] 로그인 실패 시 서버 전체 크래시 (P2)

로그인에 실패하면 예외가 run() 밖으로 전파되어 MCP 서버 프로세스 자체가 종료되는 설계 결함이 있었습니다.

수정: 서버 초기화와 로그인을 분리하는 Lazy Initialization 구조로 변경
- initialize(): 브라우저 실행만 담당
- _try_init_session(): 로그인 시도, 실패해도 서버 계속 실행
- get_page(): Tool 호출 시점에 로그인 재시도


■ 개선 결과

수정 전 실행 로그:
ERROR: Server error: 'Locator' object is not callable
(서버 프로세스 종료)

수정 후 실행 로그:
INFO: MCP Server started successfully
(로그인 실패 시 WARNING 출력 후 서버 계속 실행)

서버가 로그인 실패와 무관하게 항상 정상 시작되며, Tool 호출 시점에 로그인을 재시도하도록 구조가 개선되었습니다.


■ 주요 교훈

1. Playwright Python API 숙지 필요
   JavaScript와 달리 Python에서는 .first, .last 등이 프로퍼티입니다.

2. 초기화 실패를 전파하지 마라
   외부 서비스(로그인 등) 실패가 서버 전체를 종료시켜서는 안 됩니다.
   Lazy Initialization 패턴으로 분리하는 것이 좋습니다.

3. 설정값은 반드시 전달하라
   config 객체에 값이 있어도, 함수 호출 시 명시적으로 전달하지 않으면 기본값이 사용됩니다.


이번 작업을 통해 서버의 안정성이 크게 향상되었습니다. 앞으로도 네이버 블로그 자동화 기능을 계속 개선해 나갈 예정입니다. 감사합니다!
"""


async def main():
    config.validate()
    print(f"[설정] HEADLESS={config.HEADLESS}, ID={config.NAVER_BLOG_ID}")

    async with async_playwright() as p:
        from naver_blog_mcp.config import get_browser_config
        browser = await p.chromium.launch(**get_browser_config())

        session_manager = SessionManager(
            user_id=config.NAVER_BLOG_ID,
            password=config.NAVER_BLOG_PASSWORD,
        )

        print("[로그인] 세션 초기화 중...")
        context = await session_manager.get_or_create_session(
            browser, headless=config.HEADLESS
        )

        page = await context.new_page()
        print("[글쓰기] 블로그 포스트 작성 시작...")

        result = await create_blog_post(
            page=page,
            title=TITLE,
            content=CONTENT,
            wait_for_completion=True,
        )

        print(f"\n[결과] {result}")
        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
