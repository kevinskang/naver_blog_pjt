# 리팩토링 실행 입력 (2026-07-20)

코드 리뷰(automation / MCP 레이어 / 테스트·루트) 종합 결과에 기반한 5단계 리팩토링.

## 사용자 결정
- 실행 범위: **Phase 0~4 전체**
- `@retry_on_error`: **데코레이터 제거** (재시도 포기, 현재 실제 동작과 일치시킴)

## 검증 게이트 (매 Phase 종료 시)
- `ruff check src/` → 오류 0 유지 (기준선: 0)
- `uv run pytest tests/test_integration_v2.py -q` (유닛 부분) 통과
- 동작 불변이 목표인 Phase(2,3)는 diff 리뷰로 회귀 점검

## Phase 목록
- **P0 파일 정리**: main.py/test_integration.py/*_research.py 4종 `git rm`; test_mcp_tools.py·post_to_blog.py·post_technical_exam.py·test_paste_posting.py → `git mv scripts/`
- **P1 자원·정확성**: cleanup try/except 보호; trace_manager context별 상태화; session_manager context 누수; @retry_on_error 제거; 에러 응답 JSON 단일화
- **P2 중복 제거**: iframe 접근 9곳 → get_editor_frame; 셀렉터 순회 → selector_helper; 카테고리 검증 헬퍼 추출; _execute_tool 디스패치 테이블화; 죽은 코드 제거; 멀티계정 env 단일화
- **P3 구조 분리**: post_actions.py → draft_actions/publish_actions/editor_input; 하드코딩 셀렉터 selectors.py 이관
- **P4 품질 인프라**: conftest.py; pytest markers; 유령 테스트 정리; 매직 넘버 상수화; pyright 설치·기준선

## 근거 리뷰 요약 (파일:라인)
- iframe 인라인 중복 9곳: post_actions 34/387/825/990/1055/1155/1231, comment 39/124, category 128
- 광범위 except pass: publish_post:768 등 30+곳 (noqa 억제)
- cleanup 미보호: server.py:507-517
- trace 싱글톤: trace_manager.py:13-147
- retry 무력화: tools.py 전반 (핸들러가 예외 삼킴)
- 디스패처 거대 if/elif: server.py:163-312
- 죽은 코드: handle_list_categories, get_tools_list, get_account_blog_id, get_session_path
