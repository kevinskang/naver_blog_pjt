---
name: naver-blog-mcp-orchestrator
description: "네이버 블로그 MCP 서버 개발 및 유지보수 작업을 총괄 조율하는 오케스트레이터 스킬입니다. 네이버 블로그 도구 추가, 버그 수정, 테스트 실행, 코드 개선 및 다시 실행, 리팩토링, 업데이트, 이전 결과 개선 등 모든 프로젝트 확장/유지보수 작업 요청 시 반드시 이 스킬을 호출하십시오."
---

# Naver Blog MCP Orchestrator

이 스킬은 `blog_automation_expert`, `mcp_integrator`, `blog_qa_engineer`로 구성된 에이전트 팀을 생성하고 작업을 동적으로 할당/통합하는 조율 스킬입니다.

## 실행 모드: 에이전트 팀

## 에이전트 구성

| 팀원 | 에이전트 타입 | 역할 | 연관 스킬 | 출력 |
|:---|:---|:---|:---|:---|
| **`blog_automation_expert`** | `blog_automation_expert` | Playwright 기반 네이버 블로그 제어 모듈 및 셀렉터 개발 | `blog-automation-dev` | `src/naver_blog_mcp/automation/` |
| **`mcp_integrator`** | `mcp_integrator` | MCP 프로토콜 연결, tools.py 스키마, server.py 연동 | `mcp-server-dev` | `src/naver_blog_mcp/server.py` |
| **`blog_qa_engineer`** | `blog_qa_engineer` | pytest 작성 및 실행, ruff/pyright 품질 검증 | `mcp-qa-robustness` | `tests/` 및 품질 리포트 |

---

## 워크플로우

### Phase 0: 컨텍스트 확인 (후속 작업 지원)
1. 작업 공간에 `_workspace/` 디렉토리와 이전 구현 산출물이 있는지 확인합니다.
2. 실행 모드를 결정합니다:
   - **`_workspace/` 미존재**: 초기 빌드 및 구현. Phase 1로 진입합니다.
   - **`_workspace/` 존재 + 부분 수정/개선 요청**: 부분 재실행 모드로 진입합니다. 기존 산출물을 유지한 채 해당 작업 담당 에이전트에게 컨텍스트(피드백 및 기존 경로)를 전달하여 집중 수정을 요청합니다.
   - **`_workspace/` 존재 + 완전히 새로운 작업 요청**: 신규 실행 모드로 진입합니다. 기존 `_workspace/`를 백업(`_workspace_backup_timestamp/`)으로 이동하고 새로 시작합니다.

### Phase 1: 준비 및 작업 정의
1. 사용자의 요청사항을 파악하고 필요한 태스크 목록을 도출합니다.
2. `_workspace/` 디렉토리를 생성하고, 변경할 파일이나 대상 모듈 정보를 `_workspace/00_input.md`에 정리합니다.

### Phase 2: 팀 구성 및 태스크 등록
1. `TeamCreate` 도구를 이용하여 에이전트들을 스폰합니다. 모든 에이전트 호출에는 반드시 `model: "opus"`를 설정하십시오.
   ```
   TeamCreate(
     team_name: "naver-blog-mcp-dev-team",
     members: [
       { name: "blog_automation_expert", agent_type: "blog_automation_expert", model: "opus", prompt: "Playwright 자동화 코드 구현 담당" },
       { name: "mcp_integrator", agent_type: "mcp_integrator", model: "opus", prompt: "MCP API 연동 및 설정 담당" },
       { name: "blog_qa_engineer", agent_type: "blog_qa_engineer", model: "opus", prompt: "QA 테스트 검증 및 코드 품질 담당" }
     ]
   )
   ```
2. 작업 목록(`TaskCreate`)을 정의하여 등록합니다:
   - [태스크 1] `blog_automation_expert`에게 신규 자동화 함수(예: 글 삭제) 구현 요청.
   - [태스크 2] `mcp_integrator`에게 신규 MCP Tool 선언 및 핸들러 연동 요청.
   - [태스크 3] `blog_qa_engineer`에게 해당 구현에 대한 테스트 시나리오 작성 및 pyright/ruff 린트 검수 요청 (의존성: 태스크 1, 2 완료 후).

### Phase 3: 에이전트 협업 실행
1. 에이전트들이 생성된 작업 목록을 기준으로 작업을 청구(claim)하고 협업을 개시합니다.
2. **소통 채널**:
   - `blog_automation_expert`와 `mcp_integrator`는 `SendMessage`로 연동 규격(인자명, 데이터 모델 타입 등)을 실시간 논의합니다.
   - `blog_qa_engineer`는 테스트 실패 시 발생한 스크린샷과 로그 정보를 `SendMessage`로 담당자에게 전송하여 오류 수정을 유도합니다.
3. 중간 개발 산출물은 `_workspace/` 하위에 작성되어 공유합니다 (예: `_workspace/03_automation_code_draft.py`).

### Phase 4: 통합 및 품질 검증
1. `blog_qa_engineer`가 최종 테스트를 구동하여 pytest가 통과하고 ruff/pyright 에러 증가치가 없음을 확인합니다.
2. 검증 완료 후, 에이전트들의 작업 산출물을 `src/` 및 `tests/` 실제 경로에 최종 병합합니다.

### Phase 5: 팀 정리 및 최종 보고
1. 에이전트 팀을 해제합니다 (`TeamDelete`).
2. `_workspace/` 폴더는 차후 개선 및 디버깅을 위해 보존합니다.
3. 사용자에게 구현 사항, 테스트 통과 상태, 린트 수준 등을 최종 요약 보고합니다.

---

## 데이터 흐름

```
[리더: 오케스트레이터] 
       │ 
       ├─ TeamCreate ─→ [automation_expert] ──SendMessage──→ [mcp_integrator]
       │                        │                                   │
       │                        ├─────────── Write/Read ────────────┤
       │                        ▼                                   ▼
       │                  [_workspace/ 개발 소스 코드 및 중간 산출물 저장]
       │                        ▲
       │                        │ (Read & Test execution)
       │                  [blog_qa_engineer]
       │                        │
       │                        └─ SendMessage (오류 리포트 전달) ─→ [개발 에이전트]
       │
       └─ 통합 & TeamDelete ─→ 최종 소스 병합 및 사용자 완료 보고
```

---

## 에러 핸들링

| 시나리오 | 대응 전략 |
|:---|:---|
| 특정 에이전트 비정상 종료/대기 | 오케스트레이터가 유휴 알림 수신 후 `SendMessage`로 생사 여부 및 진행 차단 요소 체크, 필요시 해당 에이전트를 재부팅 또는 다른 에이전트에게 할당. |
| 자동화 테스트 연속 실패 | `blog_qa_engineer`가 로그 분석 후 `blog_automation_expert`에게 에디터 UI 변경 여부 재조사를 요청하고, 2회 이상 동일 지점 실패 시 사용자에게 환경 변수(네이버 로그인 계정 정보 유효성 등) 검토 요청. |
| ruff/pyright 위반 감지 | `blog_qa_engineer`가 해당 코드 라인을 특정하여 에이전트에게 수정 요청 메시지를 보내고, 수정이 완료되기 전까지 Phase 4 머지를 보류함. |

---

## 테스트 시나리오

### 정상 흐름
1. 사용자가 "글 삭제 도구를 추가해주세요" 라고 요청.
2. 오케스트레이터가 `_workspace/` 준비 및 에이전트 팀 생성.
3. `blog_automation_expert`가 글 삭제 Playwright 로직을 `post_actions.py`에 추가.
4. `mcp_integrator`가 `tools.py`에 `naver_blog_delete_post` 스키마 및 핸들러 완성.
5. `blog_qa_engineer`가 `tests/test_delete_post.py`를 실행하여 통과 확인, ruff/pyright 검사 통과.
6. 최종 머지 및 오케스트레이터가 작업을 보고하며 종료.

### 에러 흐름
1. `blog_automation_expert`가 구현 도중 스마트에디터 DOM 셀렉터 클릭 타임아웃에 부딪힘.
2. `blog_qa_engineer`가 테스트 실행 후 스크린샷과 함께 실패 메시지 리포트.
3. `blog_automation_expert`가 수신한 실패 프레임을 분석하여 좌표 클릭 방식 또는 대체 셀렉터 리스트를 보강하여 코드 패치.
4. 재차 진행하여 테스트 통과 후 오케스트레이터 마무리.
