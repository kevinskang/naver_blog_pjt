---
name: mcp-qa-robustness
description: "pytest 테스트 생성 및 실행, Playwright Trace 디버깅, pyright 타입 검사 및 ruff 린트 수행을 규정합니다. 테스트 실패 분석, 코드 정적 품질 모니터링 작업을 할 때 이 스킬을 참조하십시오."
---

# MCP QA & Robustness — 테스트 및 코드 품질 검증 스킬

이 스킬은 네이버 블로그 MCP 서비스의 강인성 확보를 위한 테스트 전략과 품질 검증 도구 활용 방침을 제공합니다.

## 1. 테스트 자동화 실행 및 구조
- 테스트 스위트는 `tests/` 폴더 하위에 위치합니다.
- 단위 테스트와 네이버 로그인이 필요한 통합 테스트를 분리하여 실행할 수 있도록 지침을 준수하십시오.

```bash
# 전체 테스트 실행 (로컬 환경 세션 필요)
uv run pytest

# 로그인 유효성 및 로그인 제외 단위 테스트 위주 퀵 실행
uv run pytest -q tests/test_error_handling.py tests/test_iframe_helper.py tests/test_image_upload_helpers.py
```

## 2. Playwright Trace 및 디버깅 활용
- 자동화 오류가 감지될 때, `utils/error_handler.py` 및 `trace_manager.py`는 자동으로 현재 스냅샷 스크린샷과 HTML 소스를 기록하고 Trace Zip 아카이브를 `playwright-state/traces/`에 저장합니다.
- 오류 디버깅 시 아래 명령어를 실행하여 어떤 시점에서 요소 매칭이 실패했는지 시각적으로 분석해야 합니다.

```bash
# 특정 trace 파일 분석
playwright show-trace playwright-state/traces/error_naver_blog_create_post_xxxx.zip
```

## 3. 정적 코드 품질 및 타입 가이드
- 작업 수행 후 반드시 Ruff와 Pyright를 실행하여 코드 안정성과 타입 사양을 확인하십시오.
- 기존의 오류 잔여치 수준을 초과하는 신규 에러 발생을 금지합니다.
  - pyright 허용치: **최대 18개** (playwright import 환경 부재로 인한 missing import 허용)
  - ruff 허용치: **0개** (E, F, I, B, C, S 규칙 준수)

```bash
# 린트 검사 및 자동 수정
ruff check src/ --fix

# 타입 체크 검사
pyright src/
```
