# 네이버 블로그 MCP 서버 아키텍처 설계서

## 1. 개요

### 1.1 프로젝트 목적
본 프로젝트는 Model Context Protocol(MCP)을 활용하여 네이버 블로그에 글을 작성할 수 있는 서버를 구축하는 것을 목표로 합니다. AI 어시스턴트가 MCP를 통해 네이버 블로그와 상호작용할 수 있도록 표준화된 인터페이스를 제공합니다.

### 1.2 시스템 개요
- **프로토콜**: Model Context Protocol (MCP)
- **통신 방식**: JSON-RPC 2.0 over stdio
- **자동화 방식**: Playwright (웹 브라우저 자동화)
- **언어**: Python 3.13
- **주요 라이브러리**: `mcp[cli]` v1.20.0+, `playwright` v1.40.0+

## 2. 네이버 블로그 API 현황 및 대안

### 2.1 공식 API 종료

#### 종료된 API
- **종료일**: 2020년 5월 6일
- **종료 대상**:
  - REST 기반 글쓰기 API
  - MetaWeblog XML-RPC API
- **종료 사유**: 광고성 글 대량 작성 악용 방지
- **현재 상태**: ❌ 복구 계획 없음, 영구 종료

#### 현재 사용 가능한 네이버 API (읽기 전용)
- **검색 API**: 블로그 글 검색/조회만 가능
- **로그인 API**: OAuth 인증만 제공

### 2.2 선택된 해결 방안: Playwright 웹 자동화

#### 왜 Playwright인가?

##### 비교: Selenium vs Playwright

| 항목 | Playwright | Selenium | 선택 |
|------|-----------|----------|------|
| **성능** | 30% 더 빠름 (WebSocket) | 느림 (HTTP) | ✅ Playwright |
| **자동 대기** | 내장 (Auto-wait) | 수동 설정 필요 | ✅ Playwright |
| **비동기 지원** | 네이티브 async/await | 제한적 | ✅ Playwright |
| **MCP 호환성** | 완벽 (비동기 구조) | 보통 | ✅ Playwright |
| **디버깅** | Inspector, Trace Viewer | 기본적 로깅 | ✅ Playwright |
| **브라우저 관리** | 자동 설치/업데이트 | 수동 ChromeDriver 관리 | ✅ Playwright |
| **안정성** | 높음 (자동 재시도) | 중간 (수동 처리) | ✅ Playwright |

**결론**: Playwright가 모든 주요 측면에서 우월

## 3. MCP 서버 아키텍처

### 3.1 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                        AI Assistant                          │
│                    (Claude, ChatGPT, etc.)                   │
└────────────────────────┬────────────────────────────────────┘
                         │ MCP Protocol (JSON-RPC 2.0)
                         │ stdio/transport
┌────────────────────────▼────────────────────────────────────┐
│                   MCP Server (Python)                        │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              MCP Protocol Handler                     │  │
│  └───────────────────────┬───────────────────────────────┘  │
│  ┌───────────────────────▼───────────────────────────────┐  │
│  │            Business Logic Layer                       │  │
│  │  - Post Manager / Category Manager / Session Manager  │  │
│  └───────────────────────┬───────────────────────────────┘  │
│  ┌───────────────────────▼───────────────────────────────┐  │
│  │       Playwright Automation Layer                     │  │
│  └───────────────────────┬───────────────────────────────┘  │
└────────────────────────┬─────────────────────────────────────┘
                         │ Browser Automation
┌────────────────────────▼────────────────────────────────────┐
│              Chromium Browser (Playwright)                   │
│           https://blog.naver.com (스마트에디터 ONE)          │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 레이어별 책임

#### 3.2.1 MCP Protocol Handler
- Tool 목록 제공 (`tools/list`)
- Tool 실행 요청 처리 (`tools/call`)
- Resource 목록 제공 및 조회

#### 3.2.2 Business Logic Layer
- **PostManager**: 포스트 작성, 조회, 삭제, 수정 로직
- **CategoryManager**: 카테고리 관리
- **MediaManager**: 이미지/미디어 업로드 처리
- **SessionManager**: 로그인 세션 관리, 인증 상태 유지

#### 3.2.3 Playwright Automation Layer
- **BrowserManager**: 브라우저 인스턴스 생명주기 관리
- **PageController**: 페이지 네비게이션 및 상태 관리
- **ElementLocator**: DOM 요소 찾기 (셀렉터 관리)
- **ActionExecutor**: 클릭, 입력, 스크롤 등 액션 실행
- **ErrorHandler**: 에러 감지, 재시도, 복구

## 4. MCP Tools 정의

### 4.1 Tool 목록

#### `naver_blog_create_post`
새로운 블로그 글을 작성합니다.
- 파라미터: title, content, category, tags, images, publish

#### `naver_blog_delete_post`
기존 블로그 글을 삭제합니다.
- 파라미터: post_url

#### `naver_blog_list_categories`
블로그의 카테고리 목록을 조회합니다.

## 5. 인증 및 세션 관리

### 5.1 세션 저장
- 세션은 `playwright-state/auth.json`에 저장
- 로그인 후 자동으로 세션 저장
- 다음 실행 시 세션 재사용 (재로그인 불필요)

### 5.2 환경 변수
```
NAVER_BLOG_ID=your_naver_id
NAVER_BLOG_PASSWORD=your_password
HEADLESS=false
SLOW_MO=100
LOG_LEVEL=INFO
```

## 6. 에러 처리 전략

### 6.1 에러 분류
- `LoginFailedError`: 로그인 실패
- `PostNotFoundError`: 글을 찾을 수 없음
- `ElementNotFoundError`: 페이지 요소를 찾을 수 없음
- `TimeoutError`: 작업 시간 초과
- `CaptchaDetectedError`: CAPTCHA 감지됨

### 6.2 재시도 로직
- tenacity 기반 지수 백오프 (2s → 4s → 8s)
- 최대 3회 재시도
- NetworkError, TimeoutError, NavigationError만 재시도

## 7. 주의사항 및 제약

### 7.1 기술적 제약
- **CAPTCHA**: 자동화 감지 시 수동 개입 필요
- **UI 변경**: 네이버 UI 변경 시 셀렉터 업데이트 필요
- **성능**: API보다 느림 (브라우저 실행 필요)

### 7.2 이용약관 준수
- 과도한 자동화 사용 자제
- 스팸성 콘텐츠 게시 금지
- 정상적인 사용 패턴 유지 (Rate Limiting)
