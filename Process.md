# Process.md — 작업 진행 기록

> 이 파일은 버그 수정 및 개선 작업의 진행 과정을 기록합니다.
> 새 작업 시작 전 이 파일을 참고하여 맥락을 파악하세요.

---

## 작업 세션 #1 — 2026-06-02

### 배경

`uv run naver-blog-mcp` 실행 시 서버가 초기화 단계에서 크래시되는 문제 분석 및 수정.

---

### 발견된 버그 목록

| ID | 우선순위 | 파일 | 라인 | 내용 | 상태 |
|---|---|---|---|---|---|
| BUG-01 | P0 | `automation/login.py` | 114 | `.first()` — Playwright `.first`는 프로퍼티인데 메서드처럼 호출 → `TypeError: 'Locator' object is not callable` | ✅ 완료 |
| BUG-02 | P0 | `automation/login.py` | 180 | `logger` 미정의 — `_wait_for_captcha_manual` 함수에서 사용하지만 import 없음 → CAPTCHA 발생 시 `NameError` | ✅ 완료 |
| BUG-03 | P1 | `server.py` | 156 | `config.HEADLESS` 미전달 — `get_or_create_session()` 호출 시 기본값 `headless=True` 사용, `.env` 설정 무시 | ✅ 완료 |
| BUG-04 | P1 | `services/session_manager.py` | 100, 117 | `get_context_config()` 미적용 — `user_agent`, `viewport`, `locale` 등 컨텍스트 설정이 브라우저 컨텍스트에 전달되지 않음. 봇 탐지 위험 | ✅ 완료 |
| BUG-05 | P2 | `server.py` | 141–210 | 서버 초기화 시 로그인 실패 → 서버 전체 크래시. Graceful 처리 필요 | ✅ 완료 |

---

### 수정 내역

#### BUG-01, BUG-02 — `automation/login.py` (2026-06-02)

```diff
+ import logging
+ logger = logging.getLogger(__name__)

- error_msg_element = page.locator(".error_message").first()
+ error_msg_element = page.locator(".error_message").first
```

- `.first`는 Playwright Python API에서 프로퍼티(property)임. `()` 호출 불가.
- `logger`를 파일 최상단에 추가하여 `_wait_for_captcha_manual` 내 로그 호출 정상화.

#### BUG-03 — `server.py` (2026-06-02)

```diff
- self.context = await self.session_manager.get_or_create_session(self.browser)
+ self.context = await self.session_manager.get_or_create_session(
+     self.browser, headless=config.HEADLESS
+ )
```

- `.env`의 `HEADLESS=false` 설정이 실제 브라우저 실행에 반영되도록 수정.

#### BUG-04 — `services/session_manager.py` (2026-06-02)

```diff
+ from ..config import get_context_config

- context = await browser.new_context(storage_state=self.storage_path)
+ context = await browser.new_context(
+     storage_state=self.storage_path,
+     **get_context_config(),
+ )

- context = await browser.new_context()
+ context = await browser.new_context(**get_context_config())
```

- 세션 복원/신규 생성 모두 `user_agent`, `viewport`, `locale`, `timezone_id` 적용.
- 네이버 봇 탐지 회피 강화.

---

#### BUG-05 — `server.py` (2026-06-02)

**구조 변경**:
- `initialize()`: 브라우저 실행만 담당. 로그인은 `_try_init_session()`으로 분리.
- `_try_init_session()` (신규): 로그인 시도. 실패 시 `WARNING` 로그 후 `self.context = None` 유지. 서버는 계속 실행.
- `get_page()`: `self.context`가 없으면 `_try_init_session()` 재시도. 재시도도 실패하면 사용자에게 명확한 안내 메시지 반환.

```
# 변경 전 동작
로그인 실패 → ERROR 로그 → 프로세스 종료

# 변경 후 동작
로그인 실패 → WARNING 로그 → MCP Server started successfully
→ Tool 호출 시 재시도 → 실패 시 안내 메시지 반환
```

---

### 진행 중 / 예정 작업

현재 모든 P0~P2 버그 수정 완료.

---

### 현재 알려진 제약사항

- 네이버 headless 로그인: headless 모드에서는 CAPTCHA/봇 탐지로 인해 로그인이 차단될 수 있음. `.env`에 `HEADLESS=false`로 설정 후 최초 1회 수동 로그인 필요.
- 세션 유효 시간: `playwright-state/auth.json` 생성 후 24시간 유효 (설정 변경 가능: `SESSION_VALIDITY_HOURS`).
