"""네이버 블로그 MCP 서버.

이 모듈은 Claude가 네이버 블로그와 상호작용할 수 있도록
MCP (Model Context Protocol) 서버를 제공합니다.
"""

import asyncio
import json
import logging
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .config import config, get_browser_config
from .mcp.tools import (
    TOOLS_METADATA,
    handle_create_post,
    # handle_delete_post,  # 비활성화
    handle_list_categories,
)
from .services.session_manager import SessionManager
from .utils.trace_manager import trace_manager

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NaverBlogMCPServer:
    """네이버 블로그 MCP 서버 클래스."""

    def __init__(self):
        """서버 초기화."""
        self.server = Server("naver-blog")
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

        # 설정 검증
        config.validate()

        # 세션 관리자 초기화
        self.session_manager = SessionManager(
            user_id=config.NAVER_BLOG_ID,
            password=config.NAVER_BLOG_PASSWORD
        )

        # Tool 등록
        self._register_tools()

    def _register_tools(self):
        """MCP Tool들을 등록합니다."""
        logger.info("Registering MCP tools...")

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[dict]:
            """Tool 호출 핸들러."""
            logger.info(f"Tool called: {name} with keys: {list(arguments.keys())}")
            return await self._handle_tool_call(name, arguments)

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """사용 가능한 Tool 목록을 반환합니다."""
            return [
                Tool(
                    name=tool_data["name"],
                    description=tool_data["description"],
                    inputSchema=tool_data["inputSchema"],
                )
                for tool_data in TOOLS_METADATA.values()
            ]

        logger.info(f"Registered {len(TOOLS_METADATA)} tools")

    async def _handle_tool_call(self, name: str, arguments: dict) -> list[dict]:
        """툴 호출을 처리하고 결과를 MCP 메시지로 변환합니다."""
        try:
            await self._ensure_session()

            if self.context:
                await trace_manager.start_trace(self.context, name=name)

            page = await self.get_page()
            result = await self._execute_tool(name, arguments, page)

            if self.context:
                await trace_manager.stop_trace(self.context, success=True)

            return [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2),
                }
            ]

        except Exception as e:
            logger.error(f"Tool execution error: {e}", exc_info=True)
            if self.context:
                await trace_manager.stop_trace(self.context, success=False)
            return [
                {
                    "type": "text",
                    "text": f"오류 발생: {str(e)}",
                }
            ]

    async def _execute_tool(self, name: str, arguments: dict, page: Page) -> dict:
        """Tool 이름에 따라 적절한 핸들러를 호출합니다."""
        if name == "naver_blog_create_post":
            return await handle_create_post(
                page=page,
                title=arguments["title"],
                content=arguments["content"],
                category=arguments.get("category"),
                tags=arguments.get("tags"),
                images=arguments.get("images"),
                publish=arguments.get("publish", True),
            )
        # elif name == "naver_blog_delete_post":
        #     return await handle_delete_post(page=page, post_url=arguments["post_url"])
        elif name == "naver_blog_list_categories":
            return await handle_list_categories(page=page)

        raise ValueError(f"알 수 없는 Tool: {name}")

    async def _ensure_session(self) -> None:
        """세션이 없거나 만료된 경우 재로그인 시도합니다."""
        if not self.context:
            logger.info("세션 없음 — 로그인 재시도 중...")
            if not await self._try_init_session():
                raise RuntimeError(
                    "네이버 로그인에 실패했습니다. "
                    ".env 파일의 NAVER_BLOG_ID, NAVER_BLOG_PASSWORD를 확인하거나 "
                    "HEADLESS=false로 설정 후 CAPTCHA를 수동으로 처리해주세요."
                )
        else:
            # 이미 context가 있어도 만료되었을 수 있으므로 검증
            self.context = await self.session_manager.refresh_session_if_needed(
                self.browser, self.context, headless=config.HEADLESS
            )

    async def initialize(self):
        """브라우저를 실행합니다. 로그인은 첫 Tool 호출 시점에 수행됩니다."""
        logger.info("Initializing Naver Blog MCP Server...")

        # Playwright 시작
        self.playwright = await async_playwright().start()

        # 브라우저 설정 가져오기
        browser_config = get_browser_config()

        # 브라우저 실행
        self.browser = await self.playwright.chromium.launch(**browser_config)
        logger.info(
            "Browser launched (headless=%s)", browser_config.get("headless", True)
        )

        # 세션 초기화 시도 (실패해도 서버는 계속 실행)
        await self._try_init_session()

    async def _try_init_session(self) -> bool:
        """세션 초기화를 시도합니다. 실패해도 서버를 종료하지 않습니다.

        Returns:
            초기화 성공 여부
        """
        try:
            self.context = await self.session_manager.get_or_create_session(
                self.browser, headless=config.HEADLESS
            )
            logger.info("Browser context initialized")
            return True
        except Exception as e:
            logger.warning(
                f"세션 초기화 실패 (Tool 호출 시 재시도됩니다): {e}"
            )
            self.context = None
            return False

    async def cleanup(self):
        """리소스 정리."""
        logger.info("Cleaning up resources...")

        if self.context:
            await self.context.close()
            logger.info("Browser context closed")

        if self.browser:
            await self.browser.close()
            logger.info("Browser closed")

        if self.playwright:
            await self.playwright.stop()
            logger.info("Playwright stopped")

    async def get_page(self) -> Page:
        """세션을 확인하고 페이지를 반환합니다. 세션이 없으면 로그인을 재시도합니다.

        Returns:
            Playwright Page 객체

        Raises:
            RuntimeError: 로그인 재시도 후에도 세션 생성에 실패한 경우
        """
        if not self.context:
            logger.info("세션 없음 — 로그인 재시도 중...")
            success = await self._try_init_session()
            if not success or not self.context:
                raise RuntimeError(
                    "네이버 로그인에 실패했습니다. "
                    ".env 파일의 NAVER_BLOG_ID, NAVER_BLOG_PASSWORD를 확인하거나 "
                    "HEADLESS=false로 설정 후 CAPTCHA를 수동으로 처리해주세요."
                )

        # 기존 페이지가 있으면 재사용, 없으면 새로 생성
        pages = self.context.pages
        if pages:
            return pages[0]
        else:
            return await self.context.new_page()

    async def run(self):
        """MCP 서버 실행."""
        try:
            # 브라우저 초기화
            await self.initialize()

            # stdio를 통해 MCP 서버 실행
            async with stdio_server() as (read_stream, write_stream):
                logger.info("MCP Server started successfully")
                await self.server.run(
                    read_stream,
                    write_stream,
                    self.server.create_initialization_options()
                )
        except Exception as e:
            logger.error(f"Server error: {e}", exc_info=True)
            raise
        finally:
            # 리소스 정리
            await self.cleanup()


async def async_main():
    """비동기 서버 엔트리포인트."""
    server = NaverBlogMCPServer()
    await server.run()


def main():
    """동기 서버 엔트리포인트 (CLI 진입점)."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
