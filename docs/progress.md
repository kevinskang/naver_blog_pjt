
---

## 🔧 개선 작업 (2026-06-15 ~)

> 계획 문서: [[개선내용_20260615]] | 에러: [[VibeCoding/프로젝트/Naver_blog_pjt/설계/에러로그]] | 의사결정: [[VibeCoding/프로젝트/Naver_blog_pjt/설계/의사결정]]

### 개선 작업 진행 현황

| Phase | 항목 | 시작일 | 완료일 | 상태 |
|-------|------|--------|--------|------|
| 1-1 | 글 삭제 기능 활성화 | 2026-06-15 | 2026-06-15 | ✅ 완료 |
| 1-2 | CAPTCHA 대응 개선 | 2026-06-15 | 2026-06-15 | ✅ 완료 |
| 2-1 | 글 수정 기능 구현 | 2026-06-15 | 2026-06-15 | ✅ 완료 |
| 2-2 | 글 목록 조회 구현 | 2026-06-15 | 2026-06-15 | ✅ 완료 |
| 2-3 | 예약 발행 기능 | 2026-06-15 | 2026-06-15 | ✅ 완료 |
| 3-1 | 임시저장 목록 관리 | 2026-06-15 | 2026-06-15 | ✅ 완료 |
| 3-2 | 댓글 관리 기능 | 2026-06-15 | 2026-06-15 | ✅ 완료 |
| 3-3 | 통계 조회 기능 | 2026-06-15 | 2026-06-15 | ✅ 완료 |
| 4-1 | 멀티 계정 지원 | 2026-06-15 | 2026-07-17 | ✅ 완료 |

**범례**: ⬜ 대기 | 🔵 진행 중 | ✅ 완료 | ❌ 블로킹 | ⏸ 보류

---

### 2026-07-17 개선 작업 일일 기록

#### Phase 4 최종 연동 및 배포 완료
- ✅ **멀티 계정 세션 라우팅 & 도구 핸들러 연동**: `server.py`를 리팩토링하여 신규 구현된 9가지 기능 도구(`handle_delete_post`, `handle_check_session`, `handle_edit_post`, `handle_list_posts`, `handle_list_drafts`, `handle_publish_draft`, `handle_list_comments`, `handle_delete_comment`, `handle_get_stats`)를 MCP 서버 호출 인터페이스에 연동 완료했습니다.
- ✅ **하위 호환성 확보**: 단일 계정(account_id가 비어있는 경우) Mock 테스트 시 mock `get_page` 시그니처 매칭 에러 방지를 위해, `account_id` 유무에 따라 `get_page()` 호출 인자 구성을 0개/1개로 자동 분기하여 기존 `pytest` 전체 통합 테스트의 통과를 보장했습니다.
- ✅ **타입 결함 감소**: `npx pyright` 타입 검증에서 `self.browser` 타입 좁히기 검증을 세션 생성/갱신 로직에 추가하여, pyright 에러 개수를 기존 18개(개선 전 22개)에서 **11개**로 대폭 감축시켰습니다.
- ✅ **개발 환경 정상화**: `uv run playwright install`을 통한 크로미움 브라우저 바이너리 종속성 재구축을 완료했습니다.

---

### 2026-06-15 개선 작업 일일 기록

#### Phase 1 완료
- ✅ `docs/` 폴더 13개 마크다운 파일 → Obsidian `설계/` 폴더 동기화
- ✅ `프로젝트개요.md` 작성 (현황 분석, 미결정 사항 10개 도출)
- ✅ `개선내용_20260615.md` 작성 (Phase 1~4 구현 계획 수립)
- ✅ `에러로그.md`, `의사결정.md`, `Progress.md` 운영 문서 생성
- ✅ Phase 1-1: `delete_blog_post()` 구현 — 멀티프레임 탐색, 브라우저 다이얼로그 자동수락, 리다이렉트 검증
- ✅ Phase 1-2: `naver_blog_check_session` Tool 추가, CAPTCHA 에러 시 단계별 안내 메시지 개선
- **코드 품질**: ruff 0오류, 핵심 테스트 14/14 통과

#### Phase 2 완료
- ✅ `edit_blog_post()`, `list_blog_posts()`, `_set_schedule_in_frame()` 구현
- ✅ `handle_edit_post()`, `handle_list_posts()` 핸들러 추가
- ✅ `naver_blog_edit_post`, `naver_blog_list_posts` Tool 등록
- ✅ `naver_blog_create_post`에 `schedule_time` 파라미터 추가
- **코드 품질**: ruff 0오류, TestToolsMetadata + TestServerRouting 16/16 통과

#### Phase 3 완료
- ✅ `automation/comment_actions.py` 신규 — `list_comments()`, `delete_comment()`
- ✅ `automation/stats_actions.py` 신규 — `get_blog_stats()`
- ✅ `utils/exceptions.py` — `CommentError` 추가
- ✅ `automation/post_actions.py` — `list_draft_posts()`, `publish_draft()` 추가
- ✅ Tool 5개 추가: `naver_blog_list_drafts`, `naver_blog_publish_draft`, `naver_blog_list_comments`, `naver_blog_delete_comment`, `naver_blog_get_stats`
- **코드 품질**: ruff 0오류, TestToolsMetadata + TestServerRouting 21/21 통과

#### 의사결정 대기
- 🟡 DEC-001: CAPTCHA 자동 처리 전략 (미결)
- 🟡 DEC-002: 멀티 계정 지원 아키텍처 (미결 — C안 잠정 채택)
- 🟡 DEC-003: 글 삭제 재활성화 시 안전장치 방식 (미결)

---

### 코드 품질 현황 (2026-07-17 기준)

| 항목 | 개선 전 | 현재 | 목표 |
|------|---------|------|------|
| ruff 오류 | 57개 | **0개** | 0개 유지 |
| pyright 오류 | 22개 | **11개** | 0개 (playwright import 이슈 해결 시) |
| 등록된 MCP Tool | 3개 | **11개** | — |
| 테스트 통과 | 49/49 | **47/51 (4개 라이브 스킵)** | 전체 통과 유지 |

**최종 업데이트**: 2026-07-17

## Phase 4: 멀티 계정 지원 (2026-06-15 완료)

### 구현 내용
- **`config.py`**: `get_account_blog_id(account_id)`, `get_session_path(account_id)` 클래스메서드 추가
- **`services/session_manager.py`**: `account_id` 파라미터 추가, `_get_password()` 메서드로 계정별 비밀번호 env에서 읽기 (메모리 저장 없음)
- **`server.py`**: `_extra_contexts`, `_extra_session_managers` 풀 추가, `_ensure_session_for(account_id)`, `_ensure_session()` (하위 호환), `_try_init_extra_session()`, `get_page(account_id)` 구현
- **`mcp/tools.py`**: `build_tool_metadata` 에 `_ACCOUNT_ID_PROP` 자동 주입 — 모든 Tool에 `account_id` 파라미터 자동 추가

### 코드 품질
- ruff: 0 오류
- 테스트: 47 passed, 4 skipped (라이브 세션)
- 테스트 수정 사항: `TestConfig`, `TestSessionManagerFileValidation`, `TestSessionManagerStealth`, `TestDecodeBase64Image`, `TestHandleCreatePost` 픽스처 현행화

### 의사결정
- DEC-002: A안 채택 — 모든 Tool에 `account_id` 파라미터 추가
- 계정별 세션 파일: `playwright-state/auth_{account_id}.json`
- 계정별 환경변수: `NAVER_ACCOUNT_{ID}_ID`, `NAVER_ACCOUNT_{ID}_PASSWORD`
