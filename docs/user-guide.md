# 네이버 블로그 MCP 서버 사용 가이드

## 📖 목차
1. [개요](#개요)
2. [설치](#설치)
3. [설정](#설정)
4. [Claude Desktop 연동](#claude-desktop-연동)
5. [사용 가능한 Tool](#사용-가능한-tool)
6. [사용 예시](#사용-예시)
7. [문제 해결](#문제-해결)

---

## 개요

네이버 블로그 MCP 서버는 Claude가 네이버 블로그와 상호작용할 수 있도록 하는 [Model Context Protocol](https://modelcontextprotocol.io/) 서버입니다.

### 주요 기능
- ✅ 네이버 블로그 글 작성 및 발행
- ✅ 이미지 업로드 (단일/다중, 파일/Base64)
- ✅ 카테고리 목록 조회
- ✅ 세션 자동 관리 (로그인 상태 유지)
- ✅ Playwright 기반 안정적인 브라우저 자동화

---

## 설치

### 필수 요구사항
- Python 3.13+
- [uv](https://github.com/astral-sh/uv) 패키지 매니저
- 네이버 블로그 계정

### 설치 명령

```bash
git clone https://github.com/space-cap/naver-blog-mcp.git
cd naver-blog-mcp
uv sync
uv run playwright install chromium
```

---

## 설정

### 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 편집:

```env
NAVER_BLOG_ID=your_naver_id
NAVER_BLOG_PASSWORD=your_naver_password
HEADLESS=false
SLOW_MO=100
LOG_LEVEL=INFO
```

---

## Claude Desktop 연동

### 설정 파일 위치

| OS | 경로 |
|----|------|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

### Windows 설정

```json
{
  "mcpServers": {
    "naver-blog": {
      "command": "uv",
      "args": ["run", "naver-blog-mcp"],
      "cwd": "C:\\workdir\\space-cap\\naver-blog-mcp",
      "env": {
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

> **주의:** `cwd` 경로를 본인의 프로젝트 경로로 변경하세요!

---

## 사용 가능한 Tool

### 1. naver_blog_create_post

네이버 블로그에 새 글을 작성합니다.

**파라미터:**
- `title` (필수): 글 제목
- `content` (필수): 글 본문 내용
- `category` (선택): 카테고리 이름
- `tags` (선택): 태그 목록 (배열)
- `images` (선택): 이미지 파일 경로 목록 (배열)
- `publish` (선택): 즉시 발행 여부 (기본: true)

**응답:**
```json
{
  "success": true,
  "message": "글이 성공적으로 발행되었습니다.",
  "post_url": "https://blog.naver.com/your_id/123456789",
  "title": "글 제목"
}
```

### 2. naver_blog_delete_post

네이버 블로그의 글을 삭제합니다.

**파라미터:**
- `post_url` (필수): 삭제할 글의 URL

### 3. naver_blog_list_categories

네이버 블로그의 카테고리 목록을 가져옵니다.

**파라미터:** 없음

**응답:**
```json
{
  "success": true,
  "message": "3개의 카테고리를 찾았습니다",
  "categories": [
    {"name": "개발", "url": "...", "categoryNo": "13"},
    {"name": "일상", "url": "...", "categoryNo": "14"}
  ]
}
```

---

## 사용 예시

### 예시 1: 간단한 글 작성

```
네이버 블로그에 글을 써줘.
제목: 오늘의 일기
내용: 오늘은 MCP 서버를 처음 사용해봤다.
```

### 예시 2: 이미지 포함 글 작성

```
네이버 블로그에 여행 후기를 작성해줘.
제목: 제주도 여행 후기
내용: 제주도 여행이 정말 즐거웠습니다.
이미지: C:/Pictures/jeju1.jpg, C:/Pictures/jeju2.jpg
카테고리: 여행
태그: 제주도, 여행, 힐링
```

### 예시 3: 카테고리 확인 후 글 작성

```
먼저 카테고리 목록을 보여주고,
"개발" 카테고리에 "Python 팁 모음"이라는 글을 작성해줘.
태그는 "Python, 개발, 팁"으로 설정해줘.
```

---

## 문제 해결

### 1. 로그인 실패

**원인:** 잘못된 아이디/비밀번호 또는 CAPTCHA 감지

**해결방법:**
1. `.env` 파일의 아이디/비밀번호 확인
2. `HEADLESS=false`로 설정하여 브라우저를 보면서 디버깅
3. CAPTCHA가 나타나면 수동으로 풀기

### 2. 세션 만료

```bash
rm playwright-state/auth.json  # macOS/Linux
del playwright-state\auth.json  # Windows
```

서버를 재실행하면 자동으로 재로그인합니다.

### 3. MCP 서버 시작 실패

1. `claude_desktop_config.json`의 `cwd` 경로 확인
2. 터미널에서 직접 실행:
   ```bash
   cd /path/to/naver-blog-mcp
   uv run naver-blog-mcp
   ```
3. 로그 확인:
   - Windows: `%APPDATA%\Claude\logs\`
   - macOS: `~/Library/Logs/Claude/`

### 4. 한글 깨짐

```env
PYTHONIOENCODING=utf-8
```

### 5. 이미지 업로드 실패

지원 포맷: JPG, PNG, GIF, BMP, HEIC, HEIF, WebP
크기 제한: 10MB

---

## 추가 정보

### 로그 레벨 변경

```env
LOG_LEVEL=DEBUG
```

### 테스트 실행

```bash
uv run python tests/test_server.py
uv run python tests/test_tools.py
uv run python tests/test_integration.py
```

---

MIT License
