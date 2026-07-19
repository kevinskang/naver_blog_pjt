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
    handle_check_session,
    handle_create_post,
    handle_delete_comment,
    handle_delete_draft,
    handle_delete_post,
    handle_edit_post,
    handle_get_stats,
    handle_list_comments,
    handle_list_drafts,
    handle_list_posts,
    handle_publish_draft,
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

        # 멀티 계정 컨텍스트 및 세션 매니저 풀 추가
        self._extra_contexts = {}
        self._extra_session_managers = {}

        # 카테고리 캐시 (Key: account_id, Value: List[Dict[str, str]])
        self._categories = {}

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

    def _get_session_manager(self, account_id: Optional[str]) -> SessionManager:
        if not account_id:
            return self.session_manager
        if account_id not in self._extra_session_managers:
            import os
            user_id = os.getenv(f"NAVER_ACCOUNT_{account_id.upper()}_ID", "")
            password = os.getenv(f"NAVER_ACCOUNT_{account_id.upper()}_PASSWORD", "")
            storage_path = f"playwright-state/auth_{account_id}.json"
            self._extra_session_managers[account_id] = SessionManager(
                user_id=user_id,
                password=password,
                storage_path=storage_path,
                account_id=account_id
            )
        return self._extra_session_managers[account_id]

    def _get_context(self, account_id: Optional[str]) -> Optional[BrowserContext]:
        if not account_id:
            return self.context
        return self._extra_contexts.get(account_id)

    def _set_context(
        self, account_id: Optional[str], context: Optional[BrowserContext]
    ) -> None:
        if not account_id:
            self.context = context
        else:
            self._extra_contexts[account_id] = context

    async def _handle_tool_call(self, name: str, arguments: dict) -> list[dict]:
        """툴 호출을 처리하고 결과를 MCP 메시지로 변환합니다."""
        account_id = arguments.get("account_id")
        try:
            if not account_id:
                await self._ensure_session()
            else:
                await self._ensure_session_for(account_id)

            context = self._get_context(account_id)
            if context:
                await trace_manager.start_trace(context, name=name)

            if not account_id:
                page = await self.get_page()
            else:
                page = await self.get_page(account_id)
            result = await self._execute_tool(name, arguments, page)

            if context:
                await trace_manager.stop_trace(context, success=True)

            return [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2),
                }
            ]

        except Exception as e:
            logger.error(f"Tool execution error: {e}", exc_info=True)
            context = self._get_context(account_id)
            if context:
                await trace_manager.stop_trace(context, success=False)
            return [
                {
                    "type": "text",
                    "text": f"오류 발생: {str(e)}",
                }
            ]

    async def _execute_tool(self, name: str, arguments: dict, page: Page) -> dict:  # noqa: C901
        """Tool 이름에 따라 적절한 핸들러를 호출합니다."""
        account_id = arguments.get("account_id")
        if name == "naver_blog_create_post":
            # 1. 카테고리 캐시 검사 및 로딩
            key = account_id or ""
            if key not in self._categories or not self._categories[key]:
                await self.load_categories(account_id, force_reload=False)
                
            categories = self._categories.get(key, [])
            category_param = arguments.get("category")
            
            if not category_param:
                # 카테고리가 지정되지 않은 경우: 제일 상단 카테고리 자동 설정
                if categories:
                    category_param = categories[0]["name"]
                    logger.info(
                        "카테고리가 명시되지 않아 가장 상단 카테고리 "
                        f"'{category_param}'로 설정합니다."
                    )
                else:
                    logger.warning("블로그에 카테고리가 존재하지 않습니다.")
            else:
                # 1단계 검증: 로컬 캐시 확인
                category_names = [c["name"] for c in categories]
                if category_param not in category_names:
                    logger.info(
                        f"지정한 카테고리 '{category_param}'가 로컬 캐시에 없어 "
                        "네이버 실시간 조회를 통해 강제 동기화합니다."
                    )
                    
                    # 2단계 검증: 네이버 블로그 직접 강제 조회
                    categories = await self.load_categories(
                        account_id, force_reload=True
                    )
                    category_names = [c["name"] for c in categories]
                    
                    # 3단계: 양쪽 모두 부재 시 에러 처리
                    if category_param not in category_names:
                        err_msg = (
                            f"지정하신 카테고리 '{category_param}'가 "
                            "존재하지 않습니다. "
                            "현재 등록된 카테고리 목록: "
                            f"{', '.join(category_names) or '(없음)'}. "
                            "네이버 블로그 설정에서 먼저 카테고리를 생성해주세요."
                        )
                        raise ValueError(err_msg)
                    else:
                        logger.info(
                            "실시간 조회 결과 카테고리가 확인되었습니다. "
                            "로컬 캐시가 성공적으로 업데이트되었습니다."
                        )

            return await handle_create_post(
                page=page,
                title=arguments["title"],
                content=arguments["content"],
                category=category_param,
                tags=arguments.get("tags"),
                images=arguments.get("images"),
                publish=arguments.get("publish", True),
                schedule_time=arguments.get("schedule_time"),
                content_format=arguments.get("content_format", "text"),
            )
        elif name == "naver_blog_delete_post":
            return await handle_delete_post(page=page, post_url=arguments["post_url"])
        elif name == "naver_blog_check_session":
            return await handle_check_session(page=page)
        elif name == "naver_blog_edit_post":
            # 카테고리 변경 시에만 검증 수행
            category_param = arguments.get("category")
            if category_param:
                key = account_id or ""
                if key not in self._categories or not self._categories[key]:
                    await self.load_categories(account_id, force_reload=False)
                
                categories = self._categories.get(key, [])
                category_names = [c["name"] for c in categories]
                if category_param not in category_names:
                    logger.info(
                        f"변경할 카테고리 '{category_param}'가 로컬 캐시에 없어 "
                        "네이버 실시간 조회를 통해 강제 동기화합니다."
                    )
                    
                    # 2단계 검증
                    categories = await self.load_categories(
                        account_id, force_reload=True
                    )
                    category_names = [c["name"] for c in categories]
                    
                    if category_param not in category_names:
                        err_msg = (
                            f"변경할 카테고리 '{category_param}'가 "
                            "존재하지 않습니다. "
                            "현재 등록된 카테고리 목록: "
                            f"{', '.join(category_names) or '(없음)'}. "
                            "네이버 블로그 설정에서 먼저 카테고리를 생성해주세요."
                        )
                        raise ValueError(err_msg)
                    else:
                        logger.info(
                            "실시간 조회 결과 카테고리가 확인되었습니다. "
                            "로컬 캐시가 성공적으로 업데이트되었습니다."
                        )

            return await handle_edit_post(
                page=page,
                post_url=arguments["post_url"],
                title=arguments["title"],
                content=arguments["content"],
                category=category_param,
                tags=arguments.get("tags"),
            )
        elif name == "naver_blog_list_posts":
            return await handle_list_posts(
                page=page, limit=arguments.get("limit", 10)
            )
        elif name == "naver_blog_list_drafts":
            return await handle_list_drafts(page=page)
        elif name == "naver_blog_publish_draft":
            return await handle_publish_draft(page=page, draft_id=arguments["draft_id"])
        elif name == "naver_blog_delete_draft":
            return await handle_delete_draft(
                page=page,
                draft_id=arguments.get("draft_id"),
                title=arguments.get("title"),
            )
        elif name == "naver_blog_list_comments":
            return await handle_list_comments(
                page=page, limit=arguments.get("limit", 10)
            )
        elif name == "naver_blog_delete_comment":
            return await handle_delete_comment(
                page=page, comment_id=arguments["comment_id"]
            )
        elif name == "naver_blog_get_stats":
            return await handle_get_stats(page=page)
        elif name == "naver_blog_list_categories":
            # 항상 force_reload=True로 호출하여 최신 카테고리를 긁어오고 캐시를 동기화합니다.  # noqa: E501
            categories_data = await self.load_categories(account_id, force_reload=True)
            return {
                "success": True,
                "message": (
                    f"{len(categories_data)}개의 카테고리를 조회하고 "
                    "캐시를 갱신했습니다."
                ),
                "categories": categories_data
            }

        raise ValueError(f"알 수 없는 Tool: {name}")

    async def _ensure_session_for(self, account_id: Optional[str]) -> None:
        """지정된 계정의 세션이 없거나 만료된 경우 재로그인 시도합니다."""
        if not account_id:
            await self._ensure_session()
            return

        context = self._get_context(account_id)
        session_manager = self._get_session_manager(account_id)
        if not context:
            logger.info(f"세션 없음 ({account_id}) — 로그인 재시도 중...")
            if not await self._try_init_session_for(account_id):
                raise RuntimeError(
                    f"네이버 로그인에 실패했습니다 ({account_id}). "
                    f"환경 변수 설정을 확인하거나 HEADLESS=false로 설정 후 수동 CAPTCHA 해제를 진행해 주세요."  # noqa: E501
                )
        else:
            if not self.browser:
                raise RuntimeError("브라우저가 초기화되지 않았습니다.")
            refreshed = await session_manager.refresh_session_if_needed(
                self.browser, context, headless=config.HEADLESS
            )
            self._set_context(account_id, refreshed)

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
            if not self.browser:
                raise RuntimeError("브라우저가 초기화되지 않았습니다.")
            self.context = await self.session_manager.refresh_session_if_needed(
                self.browser, self.context, headless=config.HEADLESS
            )

    def _get_category_cache_path(self, account_id: Optional[str] = None) -> str:
        """계정별 카테고리 캐시 파일 경로를 반환합니다."""
        key = account_id or "default"
        return f"playwright-state/categories_{key}.json"

    async def load_categories(
        self, account_id: Optional[str] = None, force_reload: bool = False
    ) -> list[dict]:
        """지정된 계정의 블로그 카테고리를 가져와서 캐싱합니다.

        로컬 캐시 파일이 존재하면 이를 우선 읽어오고, 
        없을 때만 네이버에 직접 접속합니다.
        """
        key = account_id or ""
        cache_path = self._get_category_cache_path(account_id)

        # 1. force_reload가 아니고 로컬 캐시 파일이 존재하는 경우 파일에서 로드
        if not force_reload:
            import os
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self._categories[key] = data
                        logger.info(
                            "Loaded categories from local file cache: "
                            f"{cache_path}"
                        )
                        return data
                except Exception as e:
                    logger.warning(
                        f"Failed to read category cache file ({cache_path}): {e}"
                    )

        # 2. 캐시 파일이 없거나 강제 갱신이 필요할 경우 네이버 접속 로딩
        logger.info(
            f"Loading categories from Naver blog for account: {key or 'default'}"
        )
        try:
            page = await self.get_page(account_id)
            from .automation.category_actions import get_categories

            result = await get_categories(page)
            if result.get("success") and result.get("categories"):
                categories_data = result["categories"]
                self._categories[key] = categories_data

                # 로컬 파일 캐시에 동기화
                import os
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(categories_data, f, ensure_ascii=False, indent=2)

                logger.info(
                    "Successfully cached and saved "
                    f"{len(categories_data)} categories to {cache_path}."
                )
                return categories_data
            else:
                logger.warning(
                    f"Failed to load categories from Naver: {result.get('message')}"
                )
                self._categories[key] = []
                return []
        except Exception as e:
            logger.error(f"Error loading categories: {e}")
            self._categories[key] = []
            return []

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

        # 기본 세션 초기화 시도
        await self._try_init_session()

    async def _try_init_session_for(self, account_id: Optional[str]) -> bool:
        if not account_id:
            return await self._try_init_session()

        if not self.browser:
            logger.warning(
                f"세션 초기화 실패 ({account_id}): 브라우저가 초기화되지 않았습니다."
            )
            return False

        session_manager = self._get_session_manager(account_id)
        try:
            context = await session_manager.get_or_create_session(
                self.browser, headless=config.HEADLESS
            )
            self._set_context(account_id, context)
            logger.info(f"Browser context initialized ({account_id})")
            # 백그라운드에서 카테고리 로딩 시도 (기존 캐시 파일 우선 로드)
            asyncio.create_task(self.load_categories(account_id, force_reload=False))
            return True
        except Exception as e:
            logger.warning(
                f"세션 초기화 실패 ({account_id}) (Tool 호출 시 재시도됩니다): {e}"  # noqa: E501
            )
            self._set_context(account_id, None)
            return False

    async def _try_init_session(self) -> bool:
        """세션 초기화를 시도합니다. 실패해도 서버를 종료하지 않습니다.

        Returns:
            초기화 성공 여부
        """
        if not self.browser:
            logger.warning("세션 초기화 실패: 브라우저가 초기화되지 않았습니다.")
            return False

        try:
            self.context = await self.session_manager.get_or_create_session(
                self.browser, headless=config.HEADLESS
            )
            logger.info("Browser context initialized")
            # 백그라운드에서 카테고리 로딩 시도 (기존 캐시 파일 우선 로드)
            asyncio.create_task(self.load_categories(None, force_reload=False))
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

        for account_id, context in list(self._extra_contexts.items()):
            if context:
                try:
                    await context.close()
                    logger.info(f"Browser context closed ({account_id})")
                except Exception as e:
                    logger.warning(f"Error closing context ({account_id}): {e}")
        self._extra_contexts.clear()

        if self.context:
            await self.context.close()
            logger.info("Browser context closed")

        if self.browser:
            await self.browser.close()
            logger.info("Browser closed")

        if self.playwright:
            await self.playwright.stop()
            logger.info("Playwright stopped")

    async def get_page(self, account_id: Optional[str] = None) -> Page:
        """세션을 확인하고 페이지를 반환합니다."""
        context = self._get_context(account_id)
        if not context:
            logger.info(f"세션 없음 ({account_id or 'default'}) — 로그인 재시도 중...")
            if not account_id:
                success = await self._try_init_session()
            else:
                success = await self._try_init_session_for(account_id)
            context = self._get_context(account_id)
            if not success or not context:
                raise RuntimeError(
                    f"네이버 로그인에 실패했습니다 ({account_id or 'default'})."
                )

        pages = context.pages
        if pages:
            return pages[0]
        else:
            return await context.new_page()

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
