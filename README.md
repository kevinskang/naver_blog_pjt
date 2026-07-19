# 네이버 블로그 MCP 서버

[![Python](https://img.shields.io/badge/Python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Playwright](https://img.shields.io/badge/Playwright-1.55.0-green.svg)](https://playwright.dev/)
[![MCP](https://img.shields.io/badge/MCP-1.20.0+-orange.svg)](https://modelcontextprotocol.io/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Playwright 기반 네이버 블로그 자동화를 위한 Model Context Protocol (MCP) 서버입니다. Claude 등 LLM 어시스턴트가 네이버 블로그의 글 작성, 수정, 삭제, 댓글 관리, 통계 조회 및 임시저장 목록 제어 등 블로그 운영 전반을 수행할 수 있도록 12가지의 강력한 자동화 도구를 제공합니다.

---

## 📋 프로젝트 개요

네이버 블로그의 공식 API 서비스가 종료됨에 따라, Playwright 웹 브라우저 자동화를 활용하여 MCP (Model Context Protocol) 서버를 구현했습니다. 스마트에디터 ONE의 복잡한 React 렌더링에 직접 입력을 모방한 초고속 Copy-Paste(붙여넣기) 주입 기법을 적용하여 풍부한 마크다운/HTML 서식과 표(Table) 레이아웃을 네이버 에디터 내에 깨짐 없이 완벽히 이식합니다.

---

## ✨ 주요 기능

- 🔑 **네이버 로그인 자동화 및 2단계 계정 보호**: 최초 수동 기기인증 후 세션(`auth.json`)을 최대 24시간 동안 완벽 보존 및 재사용합니다.
- 🚀 **가상 Clipboard HTML Paste 주입**: 브라우저 상에서 가상의 `ClipboardEvent('paste')`와 `DataTransfer` 객체를 생성 및 주입하여 본문을 타이핑 없이 0.01초대로 삽입하고 복잡한 표(Table), 굵게, 링크 등 마크다운 스타일 서식을 그대로 원형 보존합니다.
- 📁 **2단계 Fail-safe 카테고리 동기화**: 세션 연결 시 백그라운드로 카테고리를 자동 로드하여 로컬 캐시 파일(`categories_{key}.json`)에 보관하며, 카테고리 부재 시 실시간 재조회를 수행하는 동적 2단계 검증 설계를 반영했습니다.
- 📊 **상시 셀렉터 헬스체크 모니터링**: 네이버의 주기적인 UI 및 DOM 개편에 유연하게 대응하기 위해, 핵심 셀렉터 작동 여부를 E2E 방식으로 주기적 검사하고 결과를 기록하는 헬스체크 감시 도구(`scripts/monitor_selectors.py`)를 탑재했습니다.
- 🖼️ **다중 이미지 업로드**: 7개 포맷(JPG, PNG, GIF, BMP, HEIC, HEIF, WebP)의 이미지 파일을 한 포스트당 다중으로 자동 첨부 및 업로드 처리합니다.
- 🛠️ **12가지 블로그 관리 도구 완비**: 단순 글 작성을 넘어 삭제, 수정, 발행글 및 임시저장 목록 확인/삭제, 댓글 관리, 통계 수집 기능까지 일괄 제공합니다.

---

## 🛠️ 기술 스택

- **Python 3.13+**
- **Playwright 1.55.0** - Chromium 브라우저 자동화
- **MCP Python SDK** - Model Context Protocol 통신 규격
- **Pytest 8.4.2** - 회귀 검사 및 통합 테스트 스위트
- **Ruff & Pyright** - 정적 린트 및 엄격한 타입 체킹 환경 확보

---

## 📦 설치 및 설정

### 1. 저장소 클론 및 패키지 설치
```bash
git clone https://github.com/space-cap/naver-blog-mcp.git
cd naver-blog-mcp

# uv 패키지 매니저를 활용하여 고속 설치
uv sync

# Playwright 핵심 브라우저 바이너리 설치 (필수!)
uv run playwright install chromium
```

### 2. 환경 변수 설정
`.env.example` 파일을 복사하여 `.env` 파일을 생성하고 네이버 계정 및 구동 환경을 입력합니다.
```bash
cp .env.example .env
```

`.env` 파일 설정 내용:
```env
# 네이버 계정 정보 (기기 최초 로그인 인증 후 세션 저장됨)
NAVER_BLOG_ID=your_naver_id
NAVER_BLOG_PASSWORD=your_password

# Playwright 작동 옵션
HEADLESS=true    # 백그라운드 구동 시 true, 수동 로그인/인증이 필요할 시 false
SLOW_MO=100      # 액션 사이의 대기 딜레이 (ms)

# 로깅
LOG_LEVEL=INFO
```

---

## 🚀 Claude Desktop 연동 (MCP 서버 등록)

Claude Desktop 어플리케이션 환경 설정 파일(`claude_desktop_config.json`)에 네이버 블로그 MCP 설정을 추가하여 연동할 수 있습니다.

- **설정 파일 경로**: 
  - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
  - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

**json 설정 예시:**
```json
{
  "mcpServers": {
    "naver-blog": {
      "command": "uv",
      "args": ["run", "naver-blog-mcp"],
      "cwd": "/home/testudo/one/02.workspace/mcp_pjt/naver-blog-mcp",
      "env": {
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```
*주의: `cwd` 경로는 프로젝트 패키지가 실제로 위치한 절대 경로로 작성해야 합니다.*

---

## 🎯 지원하는 12가지 MCP Tools

네이버 블로그 MCP 서버는 Claude가 연동 즉시 사용할 수 있도록 아래의 도구를 완비하고 있습니다.

### 1. 포스팅 작성 및 관리
- **`naver_blog_create_post`**: 새 글을 블로그에 작성합니다.
  - 파라미터: `title`(필수), `content`(필수), `category`(선택), `tags`(선택 list), `images`(선택 list), `publish`(선택 bool - 기본값 true로 설정되어 즉시 발행, false 시 임시저장 저장), `schedule_time`(선택 - 예약 발행 시간)
- **`naver_blog_edit_post`**: 이미 발행된 블로그 글을 수정합니다.
  - 파라미터: `post_url`(필수), `title`(필수), `content`(필수), `category`(선택), `tags`(선택 list)
- **`naver_blog_delete_post`**: 지정한 URL의 발행된 글을 삭제합니다.
  - 파라미터: `post_url`(필수)
- **`naver_blog_list_posts`**: 이미 발행된 내 블로그 포스트의 최신 글 목록을 가져옵니다.
  - 파라미터: `limit`(선택 - 기본 10건)

### 2. 임시저장 글 제어
- **`naver_blog_list_drafts`**: 저장된 임시저장 글 목록을 조회합니다.
  - 파라미터: 없음
- **`naver_blog_publish_draft`**: 임시저장된 글 중 하나를 발행 처리합니다.
  - 파라미터: `draft_id`(필수)
- **`naver_blog_delete_draft`**: 임시저장 목록에서 특정 글을 영구 삭제합니다.
  - 파라미터: `draft_id`(선택), `title`(선택) - 두 값 중 하나를 활용해 선택 일치 1건에 대해 안전하게 삭제합니다.

### 3. 카테고리 및 세션/통계 정보
- **`naver_blog_list_categories`**: 네이버 블로그에 등록된 카테고리 구조를 조회합니다. (자동 2단계 캐싱 적용)
  - 파라미터: 없음
- **`naver_blog_check_session`**: 현재 플레이라이트 세션의 로그인 생존 및 접속 상태를 조회합니다.
  - 파라미터: 없음
- **`naver_blog_get_stats`**: 블로그 방문자수, 조회수 등 기본 통계 대시보드 데이터를 조회합니다.
  - 파라미터: 없음

### 4. 댓글 소통 도구
- **`naver_blog_list_comments`**: 내 블로그 글에 달린 최신 댓글 목록을 가져옵니다.
  - 파라미터: `limit`(선택 - 기본 10건)
- **`naver_blog_delete_comment`**: 스팸 댓글이나 악성 댓글을 원격 삭제 처리합니다.
  - 파라미터: `comment_id`(필수)

---

## 🔧 운영 및 개발 가이드

### 1. 상시 셀렉터 헬스체크 모니터링 실행
네이버 UI 개편으로 인해 에디터 DOM 구조가 변경되었는지 주기적으로 스캔하여 예방 조치할 수 있습니다.
```bash
# E2E 헬스체크 스크립트 실행
uv run python scripts/monitor_selectors.py
```
*검증이 완료되면 결과 리포트가 `playwright-state/selector_health.json`에 영구 업데이트됩니다.*

### 2. 단위/통합 회귀 테스트 실행
```bash
# 오프라인 및 로컬 Mock 테스트 스위트 구동
uv run pytest

# 라이브 세션 테스트를 포함하여 구동할 시 (auth.json 세션 갱신 필요)
RUN_LIVE_TESTS=true uv run pytest
```

### 3. 코드 품질 검사
```bash
# Ruff 린트 검사
uv run ruff check src/

# Pyright 정적 타입 무결성 검사
uv run npx pyright src/
```

---

## ⚠️ 주의사항 및 제한 사항

- ⚠️ **최초 로그인 수동 기기인증**: 네이버 2단계 인증이 설정되어 있을 경우, 최초 1회는 `.env`의 `HEADLESS=false` 상태에서 직접 브라우저로 2단계 스마트폰 승인을 눌러 완료해주어야 세션 캐시가 생성됩니다.
- ⚠️ **세션 만료 기한**: 세션 파일(`playwright-state/auth.json`)의 보안상 유효 기간은 최대 24시간입니다. 만료 시 백그라운드 로그인 모듈에 의해 자동 재로그인이 트리거됩니다.
- ⚠️ **마크다운 서식 지원**: 네이버 스마트에디터 ONE은 자체 마크다운 모드를 지원하지 않으므로, MCP 서버가 마크다운을 백그라운드에서 HTML로 렌더링한 후 Clipboard Paste 방식으로 주입하여 스타일(표, 강조 등)을 깨짐 없이 그대로 전송합니다.

---

## 🤝 라이선스

This project is licensed under the MIT License - see the LICENSE file for details.
