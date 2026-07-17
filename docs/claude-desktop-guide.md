# Claude Desktop 설정 가이드

네이버 블로그 MCP 서버를 Claude Desktop과 연동하는 방법을 상세히 안내합니다.

## 목차

1. [개요](#개요)
2. [사전 준비](#사전-준비)
3. [설정 파일 위치](#설정-파일-위치)
4. [설정 방법](#설정-방법)
5. [실전 사용 예제](#실전-사용-예제)
6. [고급 설정](#고급-설정)
7. [문제 해결](#문제-해결)
8. [보안 고려사항](#보안-고려사항)

---

## 개요

### Claude Desktop이란?

Claude Desktop은 Anthropic의 공식 데스크톱 애플리케이션으로, MCP (Model Context Protocol)를 통해 외부 도구와 연동할 수 있습니다.

### 연동 후 가능한 기능

- ✅ 네이버 블로그 글 작성 (제목, 본문, 카테고리, 태그)
- ✅ 이미지 업로드 (단일/다중)
- ✅ 글 삭제
- ✅ 카테고리 목록 조회
- ✅ 자연어로 명령 ("블로그에 글 써줘")

---

## 사전 준비

### 1. Claude Desktop 설치

아직 설치하지 않았다면:
1. Claude Desktop 다운로드 (claude.ai/download)
2. 운영체제에 맞는 설치 파일 다운로드
3. 설치 및 로그인

### 2. 네이버 블로그 MCP 서버 설치

```bash
git clone https://github.com/YOUR_USERNAME/naver-blog-mcp.git
cd naver-blog-mcp
uv sync
uv run playwright install chromium
```

---

## 설정 파일 위치

### Windows
```
%APPDATA%\Claude\claude_desktop_config.json
```

### macOS
```
~/Library/Application Support/Claude/claude_desktop_config.json
```

### Linux
```
~/.config/Claude/claude_desktop_config.json
```

---

## 설정 방법

### 기본 설정 (환경 변수 사용)

```json
{
  "mcpServers": {
    "naver-blog": {
      "command": "uv",
      "args": [
        "--directory",
        "C:/workdir/space-cap/naver-blog-mcp",
        "run",
        "naver-blog-mcp"
      ],
      "env": {
        "NAVER_BLOG_ID": "your_naver_id",
        "NAVER_BLOG_PASSWORD": "your_password",
        "HEADLESS": "true",
        "LOG_LEVEL": "INFO"
      }
    }
  }
}
```

### 환경 변수 설명

| 변수명 | 필수 | 설명 | 예시 |
|--------|------|------|------|
| `NAVER_BLOG_ID` | ✅ | 네이버 아이디 | `"myid"` |
| `NAVER_BLOG_PASSWORD` | ✅ | 네이버 비밀번호 | `"mypassword"` |
| `HEADLESS` | ❌ | 브라우저 숨김 (`true`/`false`) | `"true"` |
| `SLOW_MO` | ❌ | 자동화 속도 (ms) | `"100"` |
| `LOG_LEVEL` | ❌ | 로그 레벨 | `"INFO"` |

---

## 실전 사용 예제

### 1. 카테고리 목록 조회

```
네이버 블로그 카테고리 목록을 보여줘
```

### 2. 간단한 글 작성

```
네이버 블로그에 "오늘의 일기"라는 제목으로 글을 써줘.
본문은 "오늘 날씨가 정말 좋았다."로 해줘.
```

### 3. 이미지 포함 글 작성

```
네이버 블로그에 여행 후기를 작성해줘.
제목: 제주도 여행 후기
이미지: C:/Pictures/jeju1.jpg, C:/Pictures/jeju2.jpg
카테고리: 여행
태그: 제주도, 여행, 힐링
```

---

## 문제 해결

### "MCP 서버를 찾을 수 없습니다"

1. 설정 파일 경로 확인
2. JSON 형식 검증 (JSONLint 활용)
3. Claude Desktop 완전히 재시작

### "로그인 실패" 또는 "인증 오류"

1. 아이디/비밀번호 확인
2. 네이버 2단계 인증 비활성화
3. "자동 로그인 방지" 해제

### 로그 확인 방법

- **Windows**: `%APPDATA%\Claude\logs\`
- **macOS**: `~/Library/Logs/Claude/`
- **Linux**: `~/.config/Claude/logs/`

---

## 보안 고려사항

### 1. 비밀번호 보호

⚠️ **중요**: 설정 파일에 비밀번호가 평문으로 저장됩니다.

**권장 사항**:
1. `.env` 파일 사용 (프로젝트 디렉토리)
2. 파일 권한 설정 (chmod 600)
3. 별도 계정 사용

### 2. Git 저장소에 업로드 금지

```gitignore
.env
claude_desktop_config.json
playwright-state/
*.log
```

---

**문서 버전**: 1.0
**최종 업데이트**: 2025-11-04
**Claude Desktop 지원 버전**: 0.7.0+
