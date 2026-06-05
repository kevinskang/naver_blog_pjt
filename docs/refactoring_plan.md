# Refactoring Plan: Performance, Readability, Security

## 1. 목표

이 문서는 네이버 블로그 MCP 서버 리팩토링 목표를 정리합니다. 현재 `src/naver_blog_mcp/` 코드에서 성능, 가독성, 보안 세 가지 축을 중심으로 개선 계획을 수립합니다.

- 성능: Playwright 브라우저/컨텍스트 재사용, 불필요한 대기 제거, 재시도 정책 조정
- 가독성: 모듈 책임 분리, 함수 분해, 일관된 네이밍, 코드 간결화
- 보안: 민감 정보 관리 강화, 환경 설정 검증, 로그 민감 정보 누출 방지

## 2. 검토 대상 파일

- `src/naver_blog_mcp/server.py`
- `src/naver_blog_mcp/automation/post_actions.py`
- `src/naver_blog_mcp/automation/image_upload.py`
- `src/naver_blog_mcp/config.py`
- `src/naver_blog_mcp/services/session_manager.py`
- `src/naver_blog_mcp/utils/error_handler.py`
- `src/naver_blog_mcp/utils/retry.py`

## 3. 성능 개선 계획

1. 브라우저/컨텍스트 재사용
   - `NaverBlogMCPServer.initialize()`와 `get_page()`에서 브라우저 컨텍스트 수명 주기를 명확히 관리
   - 기존 페이지가 있으면 재사용하고, 불필요한 새 페이지 생성 최소화

2. 세션 검증 전략 개선
   - `SessionManager.is_session_valid()`에서 페이지를 새로 열고 닫는 비용을 줄이는 방법 검토
   - 세션 재사용 실패 시 재로그인 흐름을 명확화

3. 불필요한 `asyncio.sleep()` 제거
   - `automation/post_actions.py`와 `automation/image_upload.py`에서 `sleep` 기반 대기를 가능한 `wait_for_selector()`로 대체
   - 고정 지연 대신 동적 대기 방식 적용

4. 재시도 로직 최적화
   - `retry_on_error` 조건을 검토하고 재시도 가능한 오류 정의 재조정
   - 타임아웃과 재시도 간 균형 재검증

## 4. 가독성 개선 계획

1. `server.py` 책임 분리
   - Tool 등록 핸들러를 `_handle_tool_call()` 같은 별도 메서드로 분리
   - `get_page()` 내부 로직을 `ensure_session()`, `create_or_reuse_page()` 등으로 분리

2. `post_actions.py` 리팩토링
   - `navigate_to_post_write_page()`를 `determine_post_write_url()`과 `ensure_post_write_page()`로 분리
   - `_type_content_in_iframe()`과 `_type_content_direct()`를 명확히 구분하고, 각각의 선택 로직을 작은 유틸 함수로 추출
   - `_close_page_popups()`를 공통 유틸로 이동시키고 중복 호출 제거

3. `image_upload.py` 구조화
   - 이미지 클릭, 파일 입력 찾기, 업로드 완료 대기 로직을 더 작은 함수로 분리
   - 파일 유효성 검증을 별도 유틸로 모듈화
   - `click_image_button()`과 `_find_file_input()` 책임을 명확히 나누기

4. 설정/상수 정리
   - `config.py`의 `Config` 클래스는 환경 변수 검증과 설정 반환으로 명확히 분리
   - 셀렉터 목록, 업로드 허용 형식, 파일 크기 제한 등 상수를 중앙화

## 5. 보안 개선 계획

1. 환경 변수 및 민감 정보
   - `Config.validate()` 강화: 필수 값 누락 시 명확한 예외 메시지
   - `SessionManager`에서 `storage_path`를 환경 변수 기반으로 일관되게 사용
   - `.env` 파일 경로와 민감 정보가 로그에 노출되지 않도록 주의

2. 브라우저 보안 설정 검토
   - `get_context_config()`에서 `ignore_https_errors` 등의 보안 약화 옵션이 포함되어 있지 않은지 확인
   - `BROWSER_ARGS` 또는 콘텍스트 옵션으로 불필요한 보안 완화 옵션이 추가되지 않았는지 점검

3. 로깅 민감도 관리
   - 로그인 정보, 비밀번호, 세션 토큰 등 민감 정보가 로그에 남지 않도록 로거 출력 내용 검토
   - `error_handler.py`에서 저장되는 스크린샷/HTML 경로는 디버깅용으로만 활용하고, 민감 정보가 포함되지 않게 처리

## 6. 구현 세부 작업

1. `src/naver_blog_mcp/server.py`
   - Tool 호출 로직을 별도 메서드로 분리
   - `get_page()`와 `initialize()`의 책임 간소화
   - 세션 초기화 실패 시 명확한 재시도 및 사용자 메시지 제공

2. `src/naver_blog_mcp/automation/post_actions.py`
   - 글쓰기 페이지 이동, 제목 입력, 본문 입력, 발행 흐름을 모듈화
   - IFrame 접근, 팝업 닫기, 카테고리/태그 입력을 더 작은 함수로 재구성

3. `src/naver_blog_mcp/automation/image_upload.py`
   - 셀렉터 탐색 로직을 간결하게 정리
   - 파일 유효성 검사 로직을 별도 함수로 추출
   - 업로드 완료 대기 로직을 명확히 분리

4. `src/naver_blog_mcp/config.py` 및 `src/naver_blog_mcp/services/session_manager.py`
   - `Config`와 `SessionManager`의 설정/세션 검증 책임 분리
   - `storage_path`와 `session_validity_hours`를 환경 변수에서 일관되게 읽도록 정리
   - 세션 재검증 및 갱신 흐름을 명확히 정의

5. `src/naver_blog_mcp/utils/error_handler.py`
   - Playwright 에러 변환과 스크린샷/HTML 저장 로직을 간소화
   - 재시도 가능한 오류 판정 기준을 명확히 정리

## 7. 검증 계획

1. 정적 분석
   - `ruff` 실행
   - `mypy` 실행
   - `black` 포맷 확인

2. 단위/통합 테스트
   - `uv run python tests/test_server.py`
   - `uv run python tests/test_post_write.py`
   - `uv run python tests/test_image_upload.py`
   - `uv run python tests/test_login.py`

3. 수동 시나리오 확인
   - 세션 재사용
   - 글쓰기 및 발행
   - 이미지 업로드
   - 로그인 실패/세션 만료 처리

## 8. 우선순위

1. `server.py`와 세션 관리 리팩토링
2. `post_actions.py` 및 `image_upload.py` 흐름 정리
3. `config.py` 및 보안 검토
4. 테스트 강화 및 문서화

## 9. 추가 고려 사항

- `asyncio.sleep()` 기반 대기 로직은 변동성이 높으므로 가능한 한 명시적 `wait_for_*`로 대체
- `SessionManager.is_session_valid()`가 페이지 새로 열기/닫기 방식으로 비용이 크다면 재사용 전략을 개선
- `error_handler.py`에서 스크린샷/HTML 저장 실패가 전체 오류 처리에 영향을 주지 않도록 예외 격리
