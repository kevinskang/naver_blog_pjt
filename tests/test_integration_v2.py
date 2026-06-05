"""통합 테스트 v2 — 현재 코드 기반 시나리오 검증.

테스트 그룹:
  [단위] 네이버 로그인 없이 실행 가능한 모든 시나리오
  [라이브] playwright-state/auth.json 이 유효할 때만 실행
"""

import base64
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

sys.path.insert(0, "src")

from naver_blog_mcp.automation.image_upload import decode_base64_image
from naver_blog_mcp.automation.post_actions import (
    NaverBlogPostError,
    _fill_tags,
    _select_category,
)
from naver_blog_mcp.config import Config
from naver_blog_mcp.mcp.tools import (
    TOOLS_METADATA,
    handle_create_post,
    handle_list_categories,
)
from naver_blog_mcp.services.session_manager import SessionManager
from naver_blog_mcp.utils.exceptions import UploadError

# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

SESSION_PATH = "playwright-state/auth.json"


def _session_is_fresh() -> bool:
    """auth.json 이 24시간 이내이면 True."""
    p = Path(SESSION_PATH)
    if not p.exists():
        return False
    mtime = datetime.fromtimestamp(p.stat().st_mtime)
    return (datetime.now() - mtime) < timedelta(hours=24)


requires_live_session = pytest.mark.skipif(
    not _session_is_fresh(),
    reason="playwright-state/auth.json 이 없거나 만료됨 — 라이브 테스트 건너뜀",
)


# ===========================================================================
# 1. Config 검증
# ===========================================================================

class TestConfig:
    """Config 클래스 유효성 검사 및 설정 반환 로직."""

    def test_validate_raises_when_blog_id_missing(self):
        with patch.object(Config, "NAVER_BLOG_ID", ""), \
             patch.object(Config, "NAVER_BLOG_PASSWORD", "pw"):
            with pytest.raises(ValueError, match="NAVER_BLOG_ID"):
                Config.validate()

    def test_validate_raises_when_password_missing(self):
        with patch.object(Config, "NAVER_BLOG_ID", "user"), \
             patch.object(Config, "NAVER_BLOG_PASSWORD", ""):
            with pytest.raises(ValueError, match="NAVER_BLOG_PASSWORD"):
                Config.validate()

    def test_validate_passes_when_credentials_set(self):
        with patch.object(Config, "NAVER_BLOG_ID", "user"), \
             patch.object(Config, "NAVER_BLOG_PASSWORD", "pw"):
            Config.validate()  # 예외 없으면 통과

    def test_get_browser_config_structure(self):
        cfg = Config.get_browser_config()
        assert "headless" in cfg
        assert "args" in cfg
        assert isinstance(cfg["args"], list)
        assert any("AutomationControlled" in a for a in cfg["args"])

    def test_get_context_config_structure(self):
        cfg = Config.get_context_config()
        assert cfg["locale"] == "ko-KR"
        assert cfg["timezone_id"] == "Asia/Seoul"
        assert "user_agent" in cfg
        assert "viewport" in cfg
        assert cfg["viewport"]["width"] == 1920


# ===========================================================================
# 2. TOOLS_METADATA 스키마 검증
# ===========================================================================

class TestToolsMetadata:
    """MCP Tool 메타데이터 완결성 및 스키마 정확성."""

    REQUIRED_TOOLS = {"naver_blog_create_post", "naver_blog_list_categories"}

    def test_all_expected_tools_registered(self):
        missing = self.REQUIRED_TOOLS - set(TOOLS_METADATA.keys())
        assert not missing, f"미등록 Tool: {missing}"

    @pytest.mark.parametrize("tool_name", list(TOOLS_METADATA.keys()))
    def test_tool_has_required_metadata_fields(self, tool_name):
        meta = TOOLS_METADATA[tool_name]
        assert "name" in meta
        assert "description" in meta
        # MCP SDK가 사용하는 camelCase 키
        assert "inputSchema" in meta
        # 레거시 snake_case 키도 함께 존재해야 함
        assert "input_schema" in meta

    def test_create_post_requires_title_and_content(self):
        schema = TOOLS_METADATA["naver_blog_create_post"]["inputSchema"]
        assert schema["type"] == "object"
        assert "title" in schema["required"]
        assert "content" in schema["required"]

    def test_create_post_schema_has_optional_fields(self):
        props = TOOLS_METADATA["naver_blog_create_post"]["inputSchema"]["properties"]
        optional_fields = {"category", "tags", "images", "publish"}
        for field in optional_fields:
            assert field in props, f"선택 파라미터 '{field}' 누락"

    def test_list_categories_has_no_required_params(self):
        schema = TOOLS_METADATA["naver_blog_list_categories"]["inputSchema"]
        assert schema.get("required", []) == []

    def test_inputSchema_equals_input_schema(self):
        """두 키가 동일한 스키마 객체를 가리키는지 확인."""
        for tool_name, meta in TOOLS_METADATA.items():
            assert meta["inputSchema"] is meta["input_schema"], \
                f"{tool_name}: inputSchema != input_schema"


# ===========================================================================
# 3. Server 툴 라우팅 및 에러 핸들링
# ===========================================================================

class TestServerRouting:
    """NaverBlogMCPServer._execute_tool / _handle_tool_call 라우팅 로직."""

    @pytest.fixture
    def server(self):
        """서버 인스턴스 — config.validate()와 세션 초기화를 우회."""
        with patch("naver_blog_mcp.server.config") as mock_cfg, \
             patch("naver_blog_mcp.server.SessionManager"):
            mock_cfg.NAVER_BLOG_ID = "test_id"
            mock_cfg.NAVER_BLOG_PASSWORD = "test_pw"
            mock_cfg.validate = MagicMock()
            from naver_blog_mcp.server import NaverBlogMCPServer
            srv = NaverBlogMCPServer()
            srv.context = MagicMock()  # 컨텍스트 있는 척
            srv.browser = MagicMock()
            return srv

    @pytest.mark.asyncio
    async def test_execute_tool_routes_create_post(self, server):
        mock_page = AsyncMock()
        expected = {"success": True, "post_url": "http://x", "title": "t", "images_uploaded": 0}
        with patch("naver_blog_mcp.server.handle_create_post", new=AsyncMock(return_value=expected)):
            result = await server._execute_tool(
                "naver_blog_create_post",
                {"title": "t", "content": "c"},
                mock_page,
            )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_tool_routes_list_categories(self, server):
        mock_page = AsyncMock()
        expected = {"success": True, "categories": [], "message": "OK"}
        with patch("naver_blog_mcp.server.handle_list_categories", new=AsyncMock(return_value=expected)):
            result = await server._execute_tool(
                "naver_blog_list_categories", {}, mock_page
            )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_tool_raises_on_unknown_name(self, server):
        mock_page = AsyncMock()
        with pytest.raises(ValueError, match="알 수 없는 Tool"):
            await server._execute_tool("naver_blog_unknown_tool", {}, mock_page)

    @pytest.mark.asyncio
    async def test_handle_tool_call_returns_error_on_exception(self, server):
        """_execute_tool이 예외를 던지면 오류 텍스트를 포함한 응답 반환."""
        with patch.object(server, "_ensure_session", new=AsyncMock()), \
             patch.object(server, "get_page", new=AsyncMock()), \
             patch.object(server, "_execute_tool", side_effect=RuntimeError("test error")), \
             patch("naver_blog_mcp.server.trace_manager") as mock_trace:
            mock_trace.start_trace = AsyncMock()
            mock_trace.stop_trace = AsyncMock()
            result = await server._handle_tool_call("naver_blog_create_post", {"title": "t", "content": "c"})

        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert "오류 발생" in result[0]["text"]

    @pytest.mark.asyncio
    async def test_handle_tool_call_calls_ensure_session_first(self, server):
        """_ensure_session이 get_page보다 먼저 호출되는지 확인."""
        call_order = []

        async def fake_ensure():
            call_order.append("ensure")

        async def fake_get_page():
            call_order.append("get_page")
            return AsyncMock()

        expected = {"success": True, "title": "t", "post_url": None, "images_uploaded": 0}
        with patch.object(server, "_ensure_session", side_effect=fake_ensure), \
             patch.object(server, "get_page", side_effect=fake_get_page), \
             patch.object(server, "_execute_tool", new=AsyncMock(return_value=expected)), \
             patch("naver_blog_mcp.server.trace_manager") as mock_trace:
            mock_trace.start_trace = AsyncMock()
            mock_trace.stop_trace = AsyncMock()
            await server._handle_tool_call("naver_blog_create_post", {"title": "t", "content": "c"})

        assert call_order[0] == "ensure", "_ensure_session이 get_page보다 먼저 호출되어야 함"
        assert call_order[1] == "get_page"


# ===========================================================================
# 4. _ensure_session 로직 검증
# ===========================================================================

class TestEnsureSession:
    """NaverBlogMCPServer._ensure_session 분기 처리."""

    @pytest.fixture
    def server(self):
        with patch("naver_blog_mcp.server.config") as mock_cfg, \
             patch("naver_blog_mcp.server.SessionManager"):
            mock_cfg.NAVER_BLOG_ID = "test_id"
            mock_cfg.NAVER_BLOG_PASSWORD = "test_pw"
            mock_cfg.validate = MagicMock()
            mock_cfg.HEADLESS = True
            from naver_blog_mcp.server import NaverBlogMCPServer
            srv = NaverBlogMCPServer()
            srv.browser = MagicMock()
            return srv

    @pytest.mark.asyncio
    async def test_ensure_session_calls_try_init_when_context_none(self, server):
        server.context = None
        server.session_manager = MagicMock()

        async def fake_try_init():
            server.context = MagicMock()  # 성공 시 context 설정
            return True

        with patch.object(server, "_try_init_session", side_effect=fake_try_init) as mock_init:
            await server._ensure_session()
        mock_init.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ensure_session_raises_when_init_fails(self, server):
        server.context = None
        with patch.object(server, "_try_init_session", new=AsyncMock(return_value=False)):
            with pytest.raises(RuntimeError, match="네이버 로그인"):
                await server._ensure_session()

    @pytest.mark.asyncio
    async def test_ensure_session_refreshes_when_context_exists(self, server):
        """context가 있을 때 refresh_session_if_needed를 호출하는지 확인."""
        old_ctx = MagicMock()
        new_ctx = MagicMock()
        server.context = old_ctx

        server.session_manager = MagicMock()
        server.session_manager.refresh_session_if_needed = AsyncMock(return_value=new_ctx)

        await server._ensure_session()

        server.session_manager.refresh_session_if_needed.assert_awaited_once()
        assert server.context is new_ctx


# ===========================================================================
# 5. SessionManager 파일 기반 세션 검증
# ===========================================================================

class TestSessionManagerFileValidation:
    """SessionManager.is_session_file_valid() 파일 상태 판단 로직."""

    @pytest.fixture
    def manager(self, tmp_path):
        session_file = tmp_path / "auth.json"
        return SessionManager(
            user_id="user",
            password="pw",
            storage_path=str(session_file),
            session_validity_hours=24,
        )

    def test_returns_false_when_file_not_exist(self, manager):
        assert manager.is_session_file_valid() is False

    def test_returns_true_for_recent_file(self, manager):
        Path(manager.storage_path).write_text("{}")
        assert manager.is_session_file_valid() is True

    def test_returns_false_when_file_is_expired(self, manager):
        Path(manager.storage_path).write_text("{}")
        # 수정 시간을 25시간 전으로 조작
        expired_mtime = (datetime.now() - timedelta(hours=25)).timestamp()
        import os
        os.utime(manager.storage_path, (expired_mtime, expired_mtime))
        assert manager.is_session_file_valid() is False

    def test_session_validity_hours_respected(self, manager):
        """1시간짜리 세션인데 2시간 된 파일은 만료."""
        manager.session_validity_hours = 1
        Path(manager.storage_path).write_text("{}")
        expired_mtime = (datetime.now() - timedelta(hours=2)).timestamp()
        import os
        os.utime(manager.storage_path, (expired_mtime, expired_mtime))
        assert manager.is_session_file_valid() is False


# ===========================================================================
# 6. handle_create_post 핸들러 (모크)
# ===========================================================================

class TestHandleCreatePost:
    """handle_create_post 성공/실패 경로."""

    @pytest.mark.asyncio
    async def test_success_path_returns_success_dict(self):
        mock_page = AsyncMock()
        success_result = {
            "success": True,
            "message": "글이 성공적으로 발행되었습니다.",
            "post_url": "https://blog.naver.com/testudo/123",
            "title": "제목",
        }
        with patch("naver_blog_mcp.mcp.tools.create_blog_post", new=AsyncMock(return_value=success_result)):
            result = await handle_create_post(
                page=mock_page, title="제목", content="본문"
            )
        assert result["success"] is True
        assert "post_url" in result
        assert result["images_uploaded"] == 0

    @pytest.mark.asyncio
    async def test_post_error_returns_failure_dict(self):
        mock_page = AsyncMock()
        with patch("naver_blog_mcp.mcp.tools.create_blog_post",
                   side_effect=NaverBlogPostError("발행 실패")):
            result = await handle_create_post(
                page=mock_page, title="제목", content="본문"
            )
        assert result["success"] is False
        assert "오류" in result["message"]

    @pytest.mark.asyncio
    async def test_images_param_triggers_upload(self):
        """images 파라미터가 있으면 upload_images가 호출된다."""
        mock_page = AsyncMock()
        upload_result = {"uploaded": ["/img/a.png"], "failed": []}
        post_result = {
            "success": True,
            "message": "완료",
            "post_url": "https://blog.naver.com/x/1",
            "title": "t",
        }
        with patch("naver_blog_mcp.mcp.tools.upload_images",
                   new=AsyncMock(return_value=upload_result)) as mock_upload, \
             patch("naver_blog_mcp.mcp.tools.create_blog_post",
                   new=AsyncMock(return_value=post_result)):
            result = await handle_create_post(
                page=mock_page,
                title="t",
                content="c",
                images=["/img/a.png"],
            )
        mock_upload.assert_awaited_once()
        assert result["images_uploaded"] == 1

    @pytest.mark.asyncio
    async def test_upload_error_returns_failure_without_posting(self):
        """이미지 업로드 실패 시 글 작성 시도 없이 오류 반환."""
        mock_page = AsyncMock()
        with patch("naver_blog_mcp.mcp.tools.upload_images",
                   side_effect=UploadError("업로드 실패")) as mock_upload, \
             patch("naver_blog_mcp.mcp.tools.create_blog_post") as mock_post:
            result = await handle_create_post(
                page=mock_page,
                title="t",
                content="c",
                images=["/img/a.png"],
            )
        assert result["success"] is False
        mock_post.assert_not_called()


# ===========================================================================
# 7. handle_list_categories 핸들러 (모크)
# ===========================================================================

class TestHandleListCategories:
    """handle_list_categories 성공/실패 경로."""

    @pytest.mark.asyncio
    async def test_success_passthrough(self):
        mock_page = AsyncMock()
        cats = [{"name": "여행", "url": "http://x", "categoryNo": "1"}]
        with patch("naver_blog_mcp.mcp.tools.get_categories",
                   new=AsyncMock(return_value={"success": True, "message": "1개", "categories": cats})):
            result = await handle_list_categories(page=mock_page)
        assert result["success"] is True
        assert len(result["categories"]) == 1

    @pytest.mark.asyncio
    async def test_exception_returns_error_dict(self):
        mock_page = AsyncMock()
        with patch("naver_blog_mcp.mcp.tools.get_categories",
                   side_effect=RuntimeError("네트워크 오류")), \
             patch("naver_blog_mcp.mcp.tools.handle_playwright_error",
                   new=AsyncMock(return_value=RuntimeError("네트워크 오류"))):
            result = await handle_list_categories(page=mock_page)
        assert result["success"] is False
        assert result["categories"] == []


# ===========================================================================
# 8. 이미지 유틸리티 (decode_base64_image)
# ===========================================================================

class TestDecodeBase64Image:
    """decode_base64_image 형식별 처리."""

    def _make_b64_png(self) -> str:
        return base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()

    def test_decode_data_uri_format(self):
        raw = self._make_b64_png()
        data_uri = f"data:image/png;base64,{raw}"
        image_bytes, ext = decode_base64_image(data_uri)
        assert ext == ".png"
        assert image_bytes == base64.b64decode(raw)

    def test_decode_plain_base64(self):
        raw = self._make_b64_png()
        image_bytes, ext = decode_base64_image(raw)
        assert ext == ".png"  # 기본값
        assert image_bytes == base64.b64decode(raw)

    def test_decode_jpeg_data_uri(self):
        raw = base64.b64encode(b"JFIF").decode()
        _, ext = decode_base64_image(f"data:image/jpeg;base64,{raw}")
        assert ext == ".jpeg"

    def test_invalid_base64_raises_upload_error(self):
        with pytest.raises(UploadError, match="Failed to decode"):
            decode_base64_image("data:image/png;base64,!!!INVALID!!!")


# ===========================================================================
# 9. post_actions 헬퍼 함수 (모크 frame)
# ===========================================================================

class TestPostActionsHelpers:
    """_select_category, _fill_tags 의 frame 탐색 로직."""

    def _make_page_with_frames(self, *frame_configs):
        """frame_configs: [(selector → count)] 형태의 dict 목록."""
        frames = []
        for cfg in frame_configs:
            frame = MagicMock()

            async def make_count(c):
                return c

            async def locator_count(sel, _counts=cfg):
                return _counts.get(sel, 0)

            mock_locator = MagicMock()
            mock_locator.count = AsyncMock(side_effect=lambda sel=None: asyncio.coroutine(lambda: 0)())
            frame.locator = MagicMock(return_value=mock_locator)
            frames.append(frame)

        page = MagicMock()
        page.frames = frames
        return page

    @pytest.mark.asyncio
    async def test_select_category_returns_false_when_no_frame_matches(self):
        """일치하는 셀렉터가 없으면 False 반환."""
        import asyncio

        page = MagicMock()
        frame = MagicMock()

        async def zero_count():
            return 0

        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(return_value=0)
        frame.locator = MagicMock(return_value=mock_locator)
        page.frames = [frame]

        result = await _select_category(page, "존재하지않는카테고리")
        assert result is False

    @pytest.mark.asyncio
    async def test_fill_tags_returns_false_when_no_input_found(self):
        """태그 입력 필드가 없으면 False 반환."""
        page = MagicMock()
        frame = MagicMock()
        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(return_value=0)
        frame.locator = MagicMock(return_value=mock_locator)
        page.frames = [frame]

        result = await _fill_tags(page, ["tag1", "tag2"])
        assert result is False

    @pytest.mark.asyncio
    async def test_fill_tags_inputs_each_tag(self):
        """태그 입력 필드가 있으면 각 태그를 입력하고 Enter 누름."""
        page = MagicMock()
        frame = MagicMock()

        tag_input = AsyncMock()
        tag_input.click = AsyncMock()
        tag_input.type = AsyncMock()

        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(return_value=1)
        mock_locator.first = tag_input
        frame.locator = MagicMock(return_value=mock_locator)
        frame.keyboard = AsyncMock()
        frame.keyboard.press = AsyncMock()
        page.frames = [frame]

        result = await _fill_tags(page, ["태그1", "태그2"])
        assert result is True
        assert tag_input.type.call_count == 2
        assert frame.keyboard.press.call_count == 2


# ===========================================================================
# 10. SessionManager stealth 스크립트 적용 확인
# ===========================================================================

class TestSessionManagerStealth:
    """get_or_create_session 호출 시 stealth 스크립트가 추가되는지 확인."""

    @pytest.mark.asyncio
    async def test_stealth_script_applied_on_new_context(self, tmp_path):
        session_path = str(tmp_path / "auth.json")
        manager = SessionManager(
            user_id="user",
            password="pw",
            storage_path=session_path,
            session_validity_hours=24,
        )

        mock_context = AsyncMock()
        mock_context.add_init_script = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=AsyncMock())

        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)

        with patch("naver_blog_mcp.services.session_manager.login_to_naver",
                   new=AsyncMock(return_value={
                       "success": True,
                       "message": "로그인 성공",
                       "storage_state_path": session_path,
                   })):
            await manager.get_or_create_session(mock_browser, headless=True)

        mock_context.add_init_script.assert_awaited_once()
        script_arg = mock_context.add_init_script.call_args[0][0]
        assert "webdriver" in script_arg


# ===========================================================================
# 11. 라이브 통합 테스트 (유효한 세션 필요)
# ===========================================================================

@requires_live_session
class TestLiveIntegration:
    """실제 네이버 세션을 사용하는 통합 테스트."""

    @pytest.fixture(scope="class")
    async def live_page(self):
        """세션을 재사용한 Playwright 페이지 픽스처."""
        from playwright.async_api import async_playwright

        from naver_blog_mcp.config import get_context_config

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                storage_state=SESSION_PATH,
                **get_context_config(),
            )
            page = await ctx.new_page()
            yield page
            await ctx.close()
            await browser.close()

    @pytest.mark.asyncio
    async def test_session_is_valid_on_blog_main(self, live_page):
        """저장된 세션으로 blog.naver.com에 접근하면 로그인 상태여야 함."""
        from naver_blog_mcp.automation.login import verify_login_session

        result = await verify_login_session(live_page)
        assert result is True, "세션이 만료되었습니다 — auth.json 갱신 필요"

    @pytest.mark.asyncio
    async def test_list_categories_returns_data(self, live_page):
        """카테고리 목록 조회가 성공하고 리스트를 반환해야 함."""
        from naver_blog_mcp.automation.category_actions import get_categories

        result = await get_categories(live_page)
        assert result["success"] is True, f"카테고리 조회 실패: {result['message']}"
        assert isinstance(result["categories"], list)
        # 카테고리가 있거나 없어도 성공 응답이어야 함
        print(f"\n  카테고리 {len(result['categories'])}개: "
              f"{[c['name'] for c in result['categories']]}")

    @pytest.mark.asyncio
    async def test_navigate_to_post_write_page(self, live_page):
        """글쓰기 페이지로 이동할 수 있어야 함 (실제 발행 없이)."""
        from naver_blog_mcp.automation.post_actions import navigate_to_post_write_page

        await navigate_to_post_write_page(live_page)
        url = live_page.url.lower()
        assert any(kw in url for kw in ["postwrite", "postwriteform", "redirect=write"]), \
            f"글쓰기 페이지 이동 실패: {live_page.url}"

    @pytest.mark.asyncio
    async def test_full_post_creation(self, live_page):
        """제목·본문 입력 후 발행까지 전체 흐름 검증."""
        import time

        from naver_blog_mcp.automation.post_actions import create_blog_post

        ts = int(time.time())
        result = await create_blog_post(
            page=live_page,
            title=f"[통합테스트] 자동화 검증 {ts}",
            content="이 글은 통합 테스트에서 자동으로 작성된 글입니다.\n\n테스트 통과 여부 확인용.",
        )
        assert result["success"] is True, f"글 작성 실패: {result.get('message')}"
        assert result.get("post_url"), "발행 URL이 없습니다"
        print(f"\n  발행 URL: {result['post_url']}")
