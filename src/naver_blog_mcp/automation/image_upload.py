"""이미지 업로드 자동화 함수.

이 모듈은 네이버 블로그 글쓰기 에디터에서 이미지를 업로드하는
Playwright 자동화 함수를 제공합니다.
"""

import asyncio
import base64
import logging
import tempfile
from pathlib import Path
from typing import List, Optional, Union

from playwright.async_api import Frame, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ..utils.error_handler import handle_playwright_error
from ..utils.exceptions import (
    ElementNotFoundError,
    TimeoutError,
    UploadError,
)
from ..utils.iframe_helper import get_editor_frame
from ..utils.retry import retry_on_error
from ..utils.selector_helper import wait_for_any_selector

logger = logging.getLogger(__name__)


# 이미지 업로드 관련 셀렉터
IMAGE_BUTTON_SELECTORS = [
    "button[data-name='image']",
    "button[data-name='photo']",
    "button[aria-label*='사진']",
    "button[aria-label*='이미지']",
    "button[title*='사진']",
    "button[title*='이미지']",
    "button:has-text('사진')",
    "button:has-text('이미지')",
    ".se-toolbar-group button[data-name='image']",
    ".se-toolbar-group button[data-name='photo']",
    "button.se-toolbar-button-image",
    "[class*='image'][class*='button']",
]

FILE_INPUT_SELECTORS = [
    "input[type='file']",
    "input[accept*='image']",
    "input[name*='file']",
    "input[name*='image']",
    "input[name*='upload']",
]

# 업로드된 이미지를 나타내는 셀렉터
UPLOADED_IMAGE_SELECTORS = [
    ".se-image-resource",
    ".se-component-content img",
    "img[data-type='img']",
]


# Delegate iframe lookup to shared util
# `get_editor_frame` is provided by `naver_blog_mcp.utils.iframe_helper.get_editor_frame`


async def click_image_button(frame: Frame, page: Optional[Page] = None) -> None:
    """이미지 업로드 버튼을 클릭합니다.

    Args:
        frame: 에디터 iframe
        page: 전체 페이지 객체 (fallback용)

    Raises:
        ElementNotFoundError: 이미지 버튼을 찾을 수 없는 경우
    """
    for selector in IMAGE_BUTTON_SELECTORS:
        try:
            button = frame.locator(selector).first
            if await button.count() > 0:
                await button.click()
                logger.info(f"Image button clicked inside frame: {selector}")
                return
        except Exception as e:
            logger.debug(f"Frame button click failed for {selector}: {e}")

        if page is not None:
            try:
                button = page.locator(selector).first
                if await button.count() > 0:
                    await button.click()
                    logger.info(f"Image button clicked on page: {selector}")
                    return
            except Exception as e:
                logger.debug(f"Page button click failed for {selector}: {e}")

    raise ElementNotFoundError(
        "Image button not found",
        details={"selectors": IMAGE_BUTTON_SELECTORS}
    )


async def wait_for_upload_complete(
    frame: Frame,
    timeout: int = 10000,
    initial_count: int = 0,
) -> bool:
    """이미지 업로드가 완료될 때까지 대기합니다.

    Args:
        frame: 에디터 iframe
        timeout: 타임아웃 (밀리초)
        initial_count: 업로드 전 이미지 개수

    Returns:
        업로드 성공 여부

    Raises:
        TimeoutError: 업로드 타임아웃
    """
    try:
        # 이미지가 에디터에 삽입될 때까지 대기
        for selector in UPLOADED_IMAGE_SELECTORS:
            try:
                # 새로운 이미지가 추가되었는지 확인
                current_count = await frame.locator(selector).count()
                if current_count > initial_count:
                    logger.info(f"Image uploaded successfully: {selector}")
                    return True

                # 이미지가 나타날 때까지 대기
                await frame.wait_for_selector(
                    selector,
                    state="visible",
                    timeout=timeout,
                )
                logger.info(f"Image element appeared: {selector}")
                return True

            except PlaywrightTimeoutError:
                continue

        raise TimeoutError(
            "Upload completion timeout",
            details={
                "timeout": timeout,
                "selectors": UPLOADED_IMAGE_SELECTORS,
            }
        )

    except Exception as e:
        logger.error(f"Error while waiting for upload: {e}")
        raise


def _validate_image_path(image_path: Path) -> None:
    """Validate image path, size and format. Raises UploadError on failure."""
    if not image_path.exists():
        raise UploadError(
            f"Image file not found: {image_path}",
            details={"path": str(image_path)}
        )

    file_size = image_path.stat().st_size
    if file_size > 10 * 1024 * 1024:
        raise UploadError(
            f"Image file too large: {file_size / 1024 / 1024:.2f}MB (max 10MB)",
            details={"path": str(image_path), "size": file_size}
        )

    supported_formats = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.heic', '.heif', '.webp']
    if image_path.suffix.lower() not in supported_formats:
        raise UploadError(
            f"Unsupported image format: {image_path.suffix}",
            details={"path": str(image_path), "format": image_path.suffix}
        )


async def _find_file_input(frame: Frame, page: Page, timeout: int = 3000):
    """Find a file input inside the frame or on the page."""
    try:
        return await wait_for_any_selector(frame, FILE_INPUT_SELECTORS, timeout=timeout, state="attached", context="file_input")
    except Exception:
        pass

    try:
        return await wait_for_any_selector(page, FILE_INPUT_SELECTORS, timeout=timeout, state="attached", context="file_input")
    except Exception:
        return None


async def _set_file_input_and_submit(
    frame: Frame,
    image_path: Path,
    page: Optional[Page] = None,
    wait_timeout: int = 3000,
) -> None:
    """Wait for file input and set input files."""
    file_input = await _find_file_input(frame, page, timeout=wait_timeout)
    if file_input is None:
        raise ElementNotFoundError(
            "File input not found after clicking image button",
            details={"selectors": FILE_INPUT_SELECTORS}
        )

    await file_input.set_input_files(str(image_path.absolute()))
    logger.info(f"File selected: {image_path}")


@retry_on_error
async def upload_image(
    page: Page,
    image_path: Union[str, Path],
    wait_for_complete: bool = True,
) -> dict:
    """단일 이미지를 업로드합니다.

    Args:
        page: Playwright Page 객체
        image_path: 이미지 파일 경로
        wait_for_complete: 업로드 완료까지 대기 여부

    Returns:
        업로드 결과 딕셔너리
        - success: 성공 여부
        - file: 업로드한 파일 경로
        - message: 결과 메시지

    Raises:
        UploadError: 이미지 업로드 실패
        ElementNotFoundError: 필요한 요소를 찾을 수 없는 경우
    """
    try:
        image_path = Path(image_path)
        _validate_image_path(image_path)

        logger.info(f"Uploading image: {image_path}")

        # 에디터 iframe 가져오기
        frame = await get_editor_frame(page)

        # 업로드 전 이미지 개수 확인
        initial_image_count = 0
        for selector in UPLOADED_IMAGE_SELECTORS:
            try:
                count = await frame.locator(selector).count()
                if count > initial_image_count:
                    initial_image_count = count
            except Exception:
                pass

        # 이미지 버튼 클릭 -> 파일 input set -> 업로드 대기
        await click_image_button(frame, page)
        await _set_file_input_and_submit(frame, image_path, page=page)

        if wait_for_complete:
            await wait_for_upload_complete(
                frame,
                timeout=10000,
                initial_count=initial_image_count,
            )

        return {
            "success": True,
            "file": str(image_path),
            "message": f"Image uploaded successfully: {image_path.name}",
        }

    except (UploadError, ElementNotFoundError, TimeoutError):
        # 커스텀 에러는 그대로 전달
        raise

    except Exception as e:
        logger.error(f"Unexpected error during image upload: {e}", exc_info=True)
        custom_error = await handle_playwright_error(e, page, "upload_image")
        raise UploadError(
            f"Failed to upload image: {str(custom_error)}",
            details={"path": str(image_path), "error": str(custom_error)}
        ) from e


def decode_base64_image(base64_string: str) -> tuple[bytes, str]:
    """Base64 인코딩된 이미지를 디코딩합니다.

    Args:
        base64_string: Base64 문자열 (data:image/png;base64,... 또는 순수 base64)

    Returns:
        (이미지 바이트, 파일 확장자) 튜플

    Raises:
        UploadError: 디코딩 실패
    """
    try:
        # data:image/... 형식 처리
        if base64_string.startswith("data:image/"):
            # data:image/png;base64,iVBORw0KG... 형식
            header, encoded = base64_string.split(",", 1)
            # image/png 추출
            mime_type = header.split(";")[0].split(":")[1]
            extension = "." + mime_type.split("/")[1]
        else:
            # 순수 base64 문자열
            encoded = base64_string
            extension = ".png"  # 기본값

        # 디코딩
        image_bytes = base64.b64decode(encoded)
        return image_bytes, extension

    except Exception as e:
        raise UploadError(
            f"Failed to decode base64 image: {str(e)}",
            details={"error": str(e)}
        ) from e


@retry_on_error
async def upload_base64_image(
    page: Page,
    base64_string: str,
    filename: Optional[str] = None,
    wait_for_complete: bool = True,
) -> dict:
    """Base64 인코딩된 이미지를 업로드합니다.

    Args:
        page: Playwright Page 객체
        base64_string: Base64 인코딩된 이미지 문자열
        filename: 파일명 (선택, 미지정시 임시 파일명 사용)
        wait_for_complete: 업로드 완료까지 대기 여부

    Returns:
        업로드 결과 딕셔너리

    Raises:
        UploadError: 이미지 업로드 실패
    """
    temp_file = None
    try:
        # Base64 디코딩
        image_bytes, extension = decode_base64_image(base64_string)

        # 임시 파일 생성
        if filename is None:
            filename = f"image{extension}"

        with tempfile.NamedTemporaryFile(
            suffix=extension,
            delete=False,
        ) as temp_file:
            temp_file.write(image_bytes)
            temp_path = Path(temp_file.name)

        logger.info(f"Base64 image saved to temporary file: {temp_path}")

        # 일반 이미지 업로드 사용
        result = await upload_image(page, temp_path, wait_for_complete)

        # 결과 수정 (임시 파일 경로 대신 원래 파일명 사용)
        result["file"] = filename
        result["message"] = f"Base64 image uploaded successfully: {filename}"

        return result

    except (UploadError, ElementNotFoundError, TimeoutError):
        raise

    except Exception as e:
        logger.error(f"Unexpected error during base64 upload: {e}", exc_info=True)
        custom_error = await handle_playwright_error(e, page, "upload_base64_image")
        raise UploadError(
            f"Failed to upload base64 image: {str(custom_error)}",
            details={"error": str(custom_error)}
        ) from e

    finally:
        # 임시 파일 삭제
        if temp_file and Path(temp_file.name).exists():
            try:
                Path(temp_file.name).unlink()
                logger.debug(f"Temporary file deleted: {temp_file.name}")
            except Exception as e:
                logger.warning(f"Failed to delete temporary file: {e}")


@retry_on_error
async def upload_images(
    page: Page,
    image_paths: List[Union[str, Path]],
) -> dict:
    """여러 이미지를 순차적으로 업로드합니다.

    Args:
        page: Playwright Page 객체
        image_paths: 이미지 파일 경로 리스트

    Returns:
        업로드 결과 딕셔너리
        - success: 전체 성공 여부
        - uploaded: 성공한 파일 리스트
        - failed: 실패한 파일 리스트
        - message: 결과 메시지

    Raises:
        UploadError: 모든 이미지 업로드 실패
    """
    if not image_paths:
        return {
            "success": True,
            "uploaded": [],
            "failed": [],
            "message": "No images to upload",
        }

    uploaded = []
    failed = []

    for image_path in image_paths:
        try:
            result = await upload_image(page, image_path, wait_for_complete=True)
            if result["success"]:
                uploaded.append(str(image_path))
                logger.info(f"✓ {Path(image_path).name}")
            else:
                failed.append(str(image_path))
                logger.warning(f"✗ {Path(image_path).name}")

            # 이미지 간 간격
            await asyncio.sleep(0.5)

        except Exception as e:
            logger.error(f"Failed to upload {image_path}: {e}")
            failed.append(str(image_path))

    # 결과 정리
    success = len(uploaded) > 0 and len(failed) == 0

    if len(failed) == len(image_paths):
        raise UploadError(
            "All images failed to upload",
            details={"failed": failed}
        )

    return {
        "success": success,
        "uploaded": uploaded,
        "failed": failed,
        "message": f"Uploaded {len(uploaded)}/{len(image_paths)} images",
    }
