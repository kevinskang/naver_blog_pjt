import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

sys.path.insert(0, "src")

from naver_blog_mcp.automation.image_upload import (
    _validate_image_path,
    _set_file_input_and_submit,
)


@pytest.mark.asyncio
async def test_validate_image_path_missing_file(tmp_path: Path):
    missing_path = tmp_path / "missing.png"
    with pytest.raises(Exception) as exc:
        _validate_image_path(missing_path)
    assert "Image file not found" in str(exc.value)


@pytest.mark.asyncio
async def test_validate_image_path_unsupported_format(tmp_path: Path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello")

    with pytest.raises(Exception) as exc:
        _validate_image_path(test_file)
    assert "Unsupported image format" in str(exc.value)


@pytest.mark.asyncio
async def test_validate_image_path_size_limit(tmp_path: Path):
    test_file = tmp_path / "large.png"
    # 10MB + 1 byte
    test_file.write_bytes(b"0" * (10 * 1024 * 1024 + 1))

    with pytest.raises(Exception) as exc:
        _validate_image_path(test_file)
    assert "too large" in str(exc.value)


@pytest.mark.asyncio
async def test_set_file_input_and_submit_uses_input_files(tmp_path: Path):
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"PNGDATA")

    mock_input = AsyncMock()
    mock_locator = Mock()
    mock_locator.count = AsyncMock(return_value=1)
    mock_locator.first = Mock()
    mock_locator.first.wait_for = AsyncMock()
    mock_locator.first.set_input_files = AsyncMock()

    frame = Mock()
    frame.locator.return_value = mock_locator

    await _set_file_input_and_submit(frame, image_path)

    mock_locator.first.wait_for.assert_any_await(state="attached", timeout=3000)
    mock_locator.first.set_input_files.assert_awaited_once_with(str(image_path.absolute()))

