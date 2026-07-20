"""공용 pytest 설정 및 픽스처.

- `src` 레이아웃 경로를 sys.path에 보장하여 개별 테스트 파일의
  `sys.path.insert(...)` 보일러플레이트 없이도 import가 가능하게 한다.
- `e2e` 마커가 붙은 테스트는 라이브 네이버 로그인을 시도하므로,
  `RUN_LIVE_TESTS=true` 환경 변수가 없으면 자동으로 skip 한다.
  (일반 `pytest` 실행이 실수로 실제 로그인/브라우저를 띄우는 것을 방지)
"""

import os
import sys
from pathlib import Path

import pytest

# src 레이아웃 경로 보장 (editable 설치 여부와 무관하게 import 가능)
_SRC = str(Path(__file__).parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

RUN_LIVE_TESTS = os.getenv("RUN_LIVE_TESTS", "").lower() == "true"


def pytest_collection_modifyitems(config, items):
    """RUN_LIVE_TESTS=true 가 아니면 e2e 마커 테스트를 자동으로 skip 한다."""
    if RUN_LIVE_TESTS:
        return
    skip_e2e = pytest.mark.skip(
        reason="라이브 테스트 비활성 — RUN_LIVE_TESTS=true 로 실행하세요."
    )
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)
