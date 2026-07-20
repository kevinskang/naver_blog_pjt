"""MCP Tool 정의.

이 모듈은 Claude가 호출할 수 있는 네이버 블로그 관련 Tool들을 정의합니다.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import markdown
from playwright.async_api import Page

from ..automation.category_actions import get_categories
from ..automation.comment_actions import delete_comment, list_comments
from ..automation.image_upload import upload_images
from ..automation.post_actions import (
    NaverBlogPostError,
    create_blog_post,
    delete_blog_post,
    delete_draft,
    edit_blog_post,
    list_blog_posts,
    list_draft_posts,
    publish_draft,
)
from ..automation.stats_actions import get_blog_stats
from ..utils.error_handler import handle_playwright_error
from ..utils.exceptions import NaverBlogError, UploadError

logger = logging.getLogger(__name__)


def build_tool_metadata(name: str, description: str, input_schema: dict) -> dict:
    # 모든 도구에 account_id 매개변수 자동 주입 (멀티 계정 지원)
    if "properties" in input_schema:
        input_schema["properties"]["account_id"] = {
            "type": "string",
            "description": (
                "네이버 계정 식별자 (선택, 지정 시 "
                "NAVER_ACCOUNT_{ID}_ID/PASSWORD 환경변수 사용)"
            ),
        }
    return {
        "name": name,
        "description": description,
        "inputSchema": input_schema,
        "input_schema": input_schema,
    }


TOOLS_METADATA = {
    "naver_blog_create_post": build_tool_metadata(
        "naver_blog_create_post",
        "네이버 블로그에 새 글을 작성합니다. 이미지 첨부 및 예약 발행도 지원합니다.",
        {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "글 제목",
                },
                "content": {
                    "type": "string",
                    "description": "글 본문 내용",
                },
                "content_format": {
                    "type": "string",
                    "enum": ["text", "markdown", "html"],
                    "description": (
                        "본문 형식 (기본: text). 'markdown'은 표·굵게·목록 등 "
                        "서식을 보존해 발행하고, 'html'은 HTML을 그대로 붙여넣습니다."
                    ),
                    "default": "text",
                },
                "category": {
                    "type": "string",
                    "description": "카테고리 이름 (선택). 하위 카테고리는 이름만 지정.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "태그 목록 (선택)",
                },
                "images": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "첨부할 이미지 파일 경로 목록 (선택). "
                        "본문 작성 전에 이미지를 먼저 업로드합니다."
                    ),
                },
                "publish": {
                    "type": "boolean",
                    "description": "즉시 발행 여부 (기본: true, false면 임시저장)",
                    "default": True,
                },
                "schedule_time": {
                    "type": "string",
                    "description": "예약 발행 시간 (선택, 형식: YYYY-MM-DD HH:MM)",
                },
            },
            "required": ["title", "content"],
        },
    ),
    "naver_blog_delete_post": build_tool_metadata(
        "naver_blog_delete_post",
        "네이버 블로그의 글을 삭제합니다.",
        {
            "type": "object",
            "properties": {
                "post_url": {
                    "type": "string",
                    "description": "삭제할 글의 URL",
                },
            },
            "required": ["post_url"],
        },
    ),
    "naver_blog_check_session": build_tool_metadata(
        "naver_blog_check_session",
        "현재 네이버 로그인 세션이 유효한지 확인하고 상태를 반환합니다.",
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    "naver_blog_edit_post": build_tool_metadata(
        "naver_blog_edit_post",
        "이미 발행된 블로그 글을 수정합니다.",
        {
            "type": "object",
            "properties": {
                "post_url": {
                    "type": "string",
                    "description": "수정할 글의 URL",
                },
                "title": {
                    "type": "string",
                    "description": "새로운 글 제목",
                },
                "content": {
                    "type": "string",
                    "description": "새로운 글 본문 내용",
                },
                "category": {
                    "type": "string",
                    "description": "수정할 카테고리 이름 (선택)",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "수정할 태그 목록 (선택)",
                },
            },
            "required": ["post_url", "title", "content"],
        },
    ),
    "naver_blog_list_posts": build_tool_metadata(
        "naver_blog_list_posts",
        "발행된 블로그 글 목록을 조회합니다.",
        {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "조회할 글 수 (기본: 10, 최대: 30)",
                    "default": 10,
                },
            },
            "required": [],
        },
    ),
    "naver_blog_list_drafts": build_tool_metadata(
        "naver_blog_list_drafts",
        "네이버 블로그의 임시저장 글 목록을 조회합니다.",
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    "naver_blog_publish_draft": build_tool_metadata(
        "naver_blog_publish_draft",
        "임시저장된 글을 발행합니다.",
        {
            "type": "object",
            "properties": {
                "draft_id": {
                    "type": "string",
                    "description": "발행할 임시저장 글의 식별자(목록 인덱스)",
                },
            },
            "required": ["draft_id"],
        },
    ),
    "naver_blog_delete_draft": build_tool_metadata(
        "naver_blog_delete_draft",
        (
            "임시저장된 글을 삭제합니다. draft_id(목록 인덱스) 또는 "
            "title(제목 완전 일치)로 대상을 지정합니다. title 지정 시 완전 "
            "일치가 정확히 1건일 때만 삭제되며, 삭제는 되돌릴 수 없습니다."
        ),
        {
            "type": "object",
            "properties": {
                "draft_id": {
                    "type": "string",
                    "description": "삭제할 임시저장 글의 식별자(목록 인덱스)",
                },
                "title": {
                    "type": "string",
                    "description": (
                        "삭제할 임시저장 글의 제목(완전 일치). "
                        "일치 항목이 정확히 1건일 때만 삭제됩니다."
                    ),
                },
            },
            "required": [],
        },
    ),
    "naver_blog_list_comments": build_tool_metadata(
        "naver_blog_list_comments",
        "최신 댓글 목록을 가져옵니다.",
        {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "가져올 댓글 수 (기본: 10)",
                    "default": 10,
                },
            },
            "required": [],
        },
    ),
    "naver_blog_delete_comment": build_tool_metadata(
        "naver_blog_delete_comment",
        "특정 댓글을 삭제합니다.",
        {
            "type": "object",
            "properties": {
                "comment_id": {
                    "type": "string",
                    "description": "삭제할 댓글 식별자(ID)",
                },
            },
            "required": ["comment_id"],
        },
    ),
    "naver_blog_get_stats": build_tool_metadata(
        "naver_blog_get_stats",
        "블로그 방문자 수 및 조회수 통계를 가져옵니다.",
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    "naver_blog_list_categories": build_tool_metadata(
        "naver_blog_list_categories",
        "네이버 블로그의 카테고리 목록을 가져옵니다.",
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
}


# ============================================================================
# Tool Handler Functions
# ============================================================================


async def handle_create_post(
    page: Page,
    title: str,
    content: str,
    category: Optional[str] = None,
    tags: Optional[list[str]] = None,
    images: Optional[list[str]] = None,
    publish: bool = True,
    schedule_time: Optional[str] = None,
    content_format: str = "text",
) -> Dict[str, Any]:
    """네이버 블로그에 새 글을 작성합니다.

    Args:
        page: Playwright Page 객체 (로그인된 상태)
        title: 글 제목
        content: 글 본문 내용
        category: 카테고리 이름 (선택). 하위 카테고리는 이름만으로 지정.
        tags: 태그 목록 (선택)
        images: 첨부할 이미지 파일 경로 목록 (선택)
        publish: 즉시 발행 여부 (기본: True, False면 임시저장)
        schedule_time: 예약 발행 시간 (선택)
        content_format: 본문 형식 — "text"(기본, 평문 타이핑),
            "markdown"(마크다운→HTML 변환 후 서식 보존 붙여넣기),
            "html"(HTML 그대로 서식 보존 붙여넣기)

    Returns:
        작업 결과 딕셔너리
    """
    images_uploaded = 0
    try:
        logger.info(f"글 작성 시작: {title} (format={content_format})")

        # 0. 본문 형식 처리: markdown/html 은 서식 보존 붙여넣기(use_html) 경로 사용
        body_content = content
        use_html = False
        if content_format == "markdown":
            body_content = markdown.markdown(
                content, extensions=["tables", "nl2br"]
            )
            use_html = True
        elif content_format == "html":
            use_html = True

        # 1. 이미지 업로드 (본문 작성 전)
        if images:
            logger.info(f"이미지 업로드 시작: {len(images)}개")
            try:
                image_paths: List[Union[str, Path]] = [Path(p) for p in images]
                upload_result = await upload_images(page, image_paths)
                images_uploaded = len(upload_result.get("uploaded", []))

                if upload_result.get("failed"):
                    logger.warning(
                        "일부 이미지 업로드 실패: %s", upload_result["failed"]
                    )

                logger.info("이미지 업로드 완료: %d/%d개", images_uploaded, len(images))

            except UploadError as e:
                logger.error(f"이미지 업로드 실패: {e}")
                return {
                    "success": False,
                    "message": "이미지 업로드 중 오류가 발생했습니다.",
                    "post_url": None,
                    "title": title,
                    "images_uploaded": 0,
                }

        # 2. 본문 작성
        result = await create_blog_post(
            page=page,
            title=title,
            content=body_content,
            blog_id=None,
            use_html=use_html,
            wait_for_completion=publish and (not schedule_time),
            category=category,
            tags=tags,
            schedule_time=schedule_time,
            publish=publish,
        )

        result["images_uploaded"] = images_uploaded

        logger.info(
            "글 작성 완료: %s (이미지 %d개)",
            result.get("post_url", "N/A"),
            images_uploaded,
        )
        return result

    except NaverBlogPostError as e:
        logger.error(f"글 작성 실패: {e}")
        return {
            "success": False,
            "message": "글 작성 중 오류가 발생했습니다.",
            "post_url": None,
            "title": title,
            "images_uploaded": images_uploaded,
        }
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "create_post")
        logger.error("예상치 못한 오류: %s", custom_error)

        if isinstance(custom_error, NaverBlogError):
            raise custom_error from e

        return {
            "success": False,
            "message": "예상치 못한 오류가 발생했습니다.",
            "post_url": None,
            "title": title,
        }


async def handle_delete_post(page: Page, post_url: str) -> Dict[str, Any]:
    """네이버 블로그의 글을 삭제합니다."""
    logger.info(f"글 삭제 시작: {post_url}")
    try:
        return await delete_blog_post(page, post_url)
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "delete_post")
        logger.error("글 삭제 중 예외 발생: %s", custom_error)
        return {
            "success": False,
            "message": f"글 삭제 중 오류가 발생했습니다: {str(custom_error)}",
            "post_url": post_url,
        }


async def handle_check_session(page: Page) -> Dict[str, Any]:
    """현재 로그인 세션의 유효성을 검사합니다."""
    logger.info("세션 상태 검사 시작")
    try:
        from ..automation.login import verify_login_session

        is_valid = await verify_login_session(page)
        return {
            "success": True,
            "is_logged_in": is_valid,
            "message": "세션이 유효합니다."
            if is_valid
            else "세션이 만료되었거나 로그인이 해제되었습니다.",
        }
    except Exception as e:
        logger.error(f"세션 검사 중 예외 발생: {e}")
        return {"success": False, "is_logged_in": False, "message": str(e)}


async def handle_edit_post(
    page: Page,
    post_url: str,
    title: str,
    content: str,
    category: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """블로그 글을 수정합니다."""
    logger.info(f"글 수정 시작: {post_url}")
    try:
        return await edit_blog_post(
            page=page,
            post_url=post_url,
            title=title,
            content=content,
            category=category,
            tags=tags,
        )
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "edit_post")
        logger.error("글 수정 중 예외 발생: %s", custom_error)
        return {
            "success": False,
            "message": f"글 수정 중 오류가 발생했습니다: {str(custom_error)}",
        }


async def handle_list_posts(page: Page, limit: int = 10) -> Dict[str, Any]:
    """글 목록을 조회합니다."""
    logger.info(f"글 목록 조회 시작 (limit: {limit})")
    try:
        return await list_blog_posts(page, limit=limit)
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "list_posts")
        logger.error("글 목록 조회 중 예외 발생: %s", custom_error)
        return {
            "success": False,
            "message": f"글 목록 조회 중 오류가 발생했습니다: {str(custom_error)}",
            "posts": [],
        }


async def handle_list_drafts(page: Page) -> Dict[str, Any]:
    """임시저장 글 목록을 조회합니다."""
    logger.info("임시저장 글 목록 조회 시작")
    try:
        return await list_draft_posts(page)
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "list_drafts")
        logger.error("임시저장 목록 조회 중 예외 발생: %s", custom_error)
        return {
            "success": False,
            "message": f"임시저장 목록 조회 중 오류가 발생했습니다: {str(custom_error)}",  # noqa: E501
            "drafts": [],
        }


async def handle_publish_draft(page: Page, draft_id: str) -> Dict[str, Any]:
    """임시저장된 글을 발행합니다."""
    logger.info(f"임시저장 글 발행 시작 (draft_id: {draft_id})")
    try:
        return await publish_draft(page, draft_id)
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "publish_draft")
        logger.error("임시저장 발행 중 예외 발생: %s", custom_error)
        return {
            "success": False,
            "message": f"임시저장 발행 중 오류가 발생했습니다: {str(custom_error)}",
        }


async def handle_delete_draft(
    page: Page,
    draft_id: Optional[str] = None,
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """임시저장된 글을 삭제합니다 (draft_id 인덱스 또는 title 완전 일치).

    삭제는 되돌릴 수 없으므로 재시도 데코레이터를 적용하지 않습니다
    (부분 실행 후 재시도로 다른 글이 삭제되는 것을 방지).
    """
    logger.info(f"임시저장 글 삭제 시작 (draft_id: {draft_id}, title: {title})")
    try:
        return await delete_draft(page, draft_id=draft_id, title=title)
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "delete_draft")
        logger.error("임시저장 삭제 중 예외 발생: %s", custom_error)
        return {
            "success": False,
            "message": f"임시저장 삭제 중 오류가 발생했습니다: {str(custom_error)}",
        }


async def handle_list_comments(page: Page, limit: int = 10) -> Dict[str, Any]:
    """댓글 목록을 조회합니다."""
    logger.info(f"댓글 목록 조회 시작 (limit: {limit})")
    try:
        return await list_comments(page, limit=limit)
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "list_comments")
        logger.error("댓글 목록 조회 중 예외 발생: %s", custom_error)
        return {
            "success": False,
            "message": f"댓글 목록 조회 중 오류가 발생했습니다: {str(custom_error)}",
            "comments": [],
        }


async def handle_delete_comment(page: Page, comment_id: str) -> Dict[str, Any]:
    """댓글을 삭제합니다."""
    logger.info(f"댓글 삭제 시작 (comment_id: {comment_id})")
    try:
        return await delete_comment(page, comment_id)
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "delete_comment")
        logger.error("댓글 삭제 중 예외 발생: %s", custom_error)
        return {
            "success": False,
            "message": f"댓글 삭제 중 오류가 발생했습니다: {str(custom_error)}",
        }


async def handle_get_stats(page: Page) -> Dict[str, Any]:
    """블로그 통계를 조회합니다."""
    logger.info("블로그 통계 조회 시작")
    try:
        return await get_blog_stats(page)
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "get_stats")
        logger.error("블로그 통계 조회 중 예외 발생: %s", custom_error)
        return {
            "success": False,
            "message": f"블로그 통계 조회 중 오류가 발생했습니다: {str(custom_error)}",
        }


async def handle_list_categories(page: Page) -> Dict[str, Any]:
    """네이버 블로그의 카테고리 목록을 가져옵니다.

    Args:
        page: Playwright Page 객체 (로그인된 상태)

    Returns:
        작업 결과 딕셔너리
    """
    logger.info("카테고리 목록 조회 시작")

    try:
        result = await get_categories(page)

        if result["success"]:
            logger.info(f"카테고리 조회 완료: {len(result['categories'])}개")
        else:
            logger.error(f"카테고리 조회 실패: {result['message']}")

        return result

    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "list_categories")
        logger.error("카테고리 조회 중 예외 발생: %s", custom_error)
        return {
            "success": False,
            "message": "카테고리 조회 중 오류가 발생했습니다.",
            "categories": [],
        }
