# 설치 및 설정 가이드

네이버 블로그 MCP 서버의 설치 및 설정 방법을 안내합니다.

## 목차

1. [시스템 요구사항](#시스템-요구사항)
2. [사전 준비](#사전-준비)
3. [설치 방법](#설치-방법)
4. [환경 설정](#환경-설정)
5. [실행 및 테스트](#실행-및-테스트)
6. [MCP 클라이언트 연동](#mcp-클라이언트-연동)
7. [문제 해결](#문제-해결)

---

## 시스템 요구사항

### 필수 요구사항
- **Python**: 3.13 이상
- **운영체제**: Windows, macOS, Linux
- **메모리**: 최소 2GB RAM
- **디스크 공간**: 최소 500MB (Chromium 브라우저 포함)

---

## 사전 준비

### 1. Python 설치 확인

```bash
python --version
```

Python 3.13 이상이 설치되어 있어야 합니다.

### 2. uv 패키지 매니저 설치

```bash
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## 설치 방법

### 방법 1: Git Clone (권장)

```bash
git clone https://github.com/YOUR_USERNAME/naver-blog-mcp.git
cd naver-blog-mcp
uv sync
uv run playwright install chromium
```

---

## 환경 설정

### 1. .env 파일 생성

```bash
# Windows
copy .env.example .env

# macOS/Linux
cp .env.example .env
```

### 2. .env 파일 편집

```env
# 네이버 계정 정보 (필수)
NAVER_BLOG_ID=your_naver_id
NAVER_BLOG_PASSWORD=your_password

# Playwright 설정 (선택)
HEADLESS=false              # true로 설정 시 브라우저 숨김
SLOW_MO=100                 # 자동화 속도 조절 (ms)

# 로깅 설정 (선택)
LOG_LEVEL=INFO              # DEBUG, INFO, WARNING, ERROR
```

### 3. 환경 변수 설명

| 변수명 | 필수 | 기본값 | 설명 |
|--------|------|--------|------|
| `NAVER_BLOG_ID` | ✅ | - | 네이버 아이디 |
| `NAVER_BLOG_PASSWORD` | ✅ | - | 네이버 비밀번호 |
| `HEADLESS` | ❌ | `false` | 브라우저 표시 여부 |
| `SLOW_MO` | ❌ | `100` | 자동화 속도 (0~1000ms) |
| `LOG_LEVEL` | ❌ | `INFO` | 로그 레벨 |

⚠️ **중요**: `.env` 파일은 절대 Git에 커밋하지 마세요!

---

## 실행 및 테스트

### 1. 독립 실행 모드

```bash
uv run naver-blog-mcp
```

### 2. 기능 테스트

```bash
uv run python tests/test_image_upload.py
uv run python tests/test_error_handling.py
```

---

## MCP 클라이언트 연동

### Claude Desktop 연동

#### 설정 파일 위치

- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

#### MCP 서버 설정 추가

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

---

## 문제 해결

### 1. "uv: command not found"

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. "Playwright 브라우저를 찾을 수 없습니다"

```bash
uv run playwright install chromium
```

### 3. "로그인 실패"

1. `.env` 파일의 아이디/비밀번호 확인
2. 네이버 2단계 인증 비활성화
3. "자동 로그인 방지" 해제

### 4. 속도가 너무 느림

```env
SLOW_MO=0  # 0으로 설정하면 최고 속도
```

---

**문서 버전**: 1.0
**최종 업데이트**: 2025-11-04
