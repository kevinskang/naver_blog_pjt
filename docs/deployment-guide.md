# 네이버 블로그 MCP 서버 배포 가이드

이 문서는 네이버 블로그 MCP 서버를 다른 사용자에게 배포하고 설치하는 방법을 안내합니다.

## 📋 목차

### Part A: 개발자용 (배포 방법)
1. [배포 방식 개요](#배포-방식-개요)
2. [방식 1: GitHub 공개 저장소 (권장)](#방식-1-github-공개-저장소-권장)
3. [방식 2: PyPI 패키지 배포](#방식-2-pypi-패키지-배포)
4. [방식 3: Docker 컨테이너](#방식-3-docker-컨테이너)
5. [방식 4: MCP Registry 등록](#방식-4-mcp-registry-등록)

### Part B: 사용자용 (설치 및 사용)
6. [사전 요구사항](#사전-요구사항)
7. [설치 방법](#설치-방법)
8. [Claude Desktop 연동](#claude-desktop-연동)

---

# Part A: 개발자용 (배포 방법)

## 배포 방식 개요

| 방식 | 난이도 | 사용자 편의성 | 권장도 |
|------|--------|--------------|--------|
| GitHub 공개 저장소 | ⭐ 쉬움 | ⭐⭐⭐ 보통 | ✅ **권장** |
| PyPI 패키지 | ⭐⭐⭐ 어려움 | ⭐⭐⭐⭐⭐ 매우 쉬움 | 🔥 **최고** |
| Docker 컨테이너 | ⭐⭐ 보통 | ⭐⭐⭐⭐ 쉬움 | 🚀 추천 |
| MCP Registry | ⭐⭐ 보통 | ⭐⭐⭐⭐⭐ 매우 쉬움 | 🎯 미래 |

---

## 방식 1: GitHub 공개 저장소 (권장)

### 배포 체크리스트

- ✅ `README.md` - 프로젝트 소개
- ✅ `LICENSE` - 라이선스 (MIT 권장)
- ✅ `.gitignore` - 민감 정보 제외
- ✅ `pyproject.toml` - 의존성 정의
- ✅ `.env.example` - 환경 변수 템플릿

### 릴리스 생성

```bash
git tag -a v1.0.0 -m "첫 번째 공식 릴리스"
git push origin v1.0.0
```

---

## 방식 2: PyPI 패키지 배포

### 빌드 및 업로드

```bash
pip install build twine
python -m build

# TestPyPI에 먼저 업로드 (테스트용)
twine upload --repository testpypi dist/*

# 실제 PyPI에 업로드
twine upload dist/*
```

### 사용자 설치 방법

```bash
pip install naver-blog-mcp
playwright install chromium
naver-blog-mcp
```

---

## 방식 3: Docker 컨테이너

### Dockerfile

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen
RUN uv run playwright install chromium --with-deps
COPY src/ ./src/
CMD ["uv", "run", "naver-blog-mcp"]
```

---

## 방식 4: MCP Registry 등록

### 현재 상태
- 🚧 MCP Registry는 아직 개발 중
- 📅 2025년 중 출시 예정

---

# Part B: 사용자용 (설치 및 사용)

## 사전 요구사항

1. **Python 3.13 이상**
2. **uv (Python 패키지 매니저)**
   ```bash
   # Windows (PowerShell)
   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
   # macOS/Linux
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
3. **Claude Desktop**
4. **네이버 블로그 계정**

---

## 설치 방법

### 1단계: 프로젝트 다운로드

```bash
git clone https://github.com/space-cap/naver-blog-mcp.git
cd naver-blog-mcp
```

### 2단계: 의존성 설치

```bash
uv sync
uv run playwright install chromium
```

### 3단계: 환경 변수 설정

```env
NAVER_BLOG_ID=your_naver_id
NAVER_BLOG_PASSWORD=your_password
HEADLESS=false
SLOW_MO=100
LOG_LEVEL=INFO
```

---

## Claude Desktop 연동

### Windows 설정 파일

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

---

## 문제 해결

### 문제 1: "Server failed to start" 오류

```bash
python --version  # Python 3.13 이상이어야 함
uv --version
```

### 문제 2: "로그인 실패" 오류

1. `.env` 파일에서 계정 정보 재확인
2. `HEADLESS=false`로 설정하여 브라우저 표시
3. CAPTCHA가 나타나면 수동으로 해결

---

## 보안 고려사항

- ✅ `.env` 파일을 Git에 커밋하지 마세요
- ✅ 세션 파일(`playwright-state/auth.json`)을 공유하지 마세요
- ✅ 과도한 자동화 요청 자제

---

**마지막 업데이트**: 2025-11-05
