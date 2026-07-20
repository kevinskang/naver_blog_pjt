"""프로젝트 설정 관리."""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# .env 파일 로드
project_root = Path(__file__).parent.parent.parent
load_dotenv(project_root / ".env")


class Config:
    """프로젝트 설정 클래스."""

    # 네이버 블로그 계정
    NAVER_BLOG_ID: str = os.getenv("NAVER_BLOG_ID", "")
    NAVER_BLOG_PASSWORD: str = os.getenv("NAVER_BLOG_PASSWORD", "")

    # Playwright 설정
    HEADLESS: bool = os.getenv("HEADLESS", "true").lower() == "true"
    SLOW_MO: int = int(os.getenv("SLOW_MO", "0"))

    # 로깅 설정
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

    # 세션 설정
    SESSION_STORAGE_PATH: str = os.getenv(
        "SESSION_STORAGE_PATH", "playwright-state/auth.json"
    )
    SESSION_VALIDITY_HOURS: int = int(os.getenv("SESSION_VALIDITY_HOURS", "24"))

    # Playwright 브라우저 설정
    BROWSER_ARGS: list[str] = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--disable-infobars",
        "--window-size=1920,1080",
        "--no-sandbox",
        "--disable-setuid-sandbox",
    ]

    # Chrome/Chromium 버전 — Playwright 번들 Chromium과 반드시 일치시킨다.
    # UA, stealth userAgentData, 실제 브라우저 버전이 불일치하면 안티봇이 즉시
    # 탐지하므로 단일 상수로 관리한다. Playwright 업그레이드 시 이 값만 갱신하면
    # USER_AGENT와 STEALTH_SCRIPT가 함께 반영된다. (현재 Playwright 1.55 = Chromium 140)
    CHROME_MAJOR_VERSION: str = os.getenv("CHROME_MAJOR_VERSION", "140")
    CHROME_FULL_VERSION: str = os.getenv("CHROME_FULL_VERSION", "140.0.0.0")

    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{CHROME_FULL_VERSION} Safari/537.36"
    )

    VIEWPORT: dict[str, int] = {"width": 1920, "height": 1080}

    @classmethod
    def is_debug(cls) -> bool:
        """DEBUG 로그 레벨 여부를 반환합니다."""
        return cls.LOG_LEVEL == "DEBUG"

    # ------------------------------------------------------------------
    # 멀티 계정 자격증명/경로 해석 (단일 소스)
    # account_id 가 없으면 기본 계정, 있으면
    # NAVER_ACCOUNT_{ID}_ID / _PASSWORD 환경 변수를 사용한다.
    # ------------------------------------------------------------------
    @classmethod
    def get_account_id(cls, account_id: Optional[str]) -> str:
        """계정 식별자에 해당하는 네이버 로그인 ID를 반환합니다."""
        if not account_id:
            return cls.NAVER_BLOG_ID
        return os.getenv(f"NAVER_ACCOUNT_{account_id.upper()}_ID", "")

    @classmethod
    def get_account_password(cls, account_id: Optional[str]) -> str:
        """계정 식별자에 해당하는 네이버 비밀번호를 반환합니다."""
        if not account_id:
            return cls.NAVER_BLOG_PASSWORD
        return os.getenv(f"NAVER_ACCOUNT_{account_id.upper()}_PASSWORD", "")

    @classmethod
    def get_session_path(cls, account_id: Optional[str]) -> str:
        """계정 식별자에 해당하는 세션 파일 경로를 반환합니다."""
        if not account_id:
            return cls.SESSION_STORAGE_PATH
        return f"playwright-state/auth_{account_id}.json"

    @classmethod
    def validate(cls) -> None:
        """설정 유효성 검사."""
        if not cls.NAVER_BLOG_ID:
            raise ValueError("NAVER_BLOG_ID가 설정되지 않았습니다.")
        if not cls.NAVER_BLOG_PASSWORD:
            raise ValueError("NAVER_BLOG_PASSWORD가 설정되지 않았습니다.")

    @classmethod
    def get_browser_config(cls) -> dict:
        """Playwright 브라우저 설정을 반환합니다."""
        return {
            "headless": cls.HEADLESS,
            "args": cls.BROWSER_ARGS,
            "slow_mo": cls.SLOW_MO,
        }

    @classmethod
    def get_context_config(cls) -> dict:
        """Playwright 컨텍스트 설정을 반환합니다."""
        return {
            "user_agent": cls.USER_AGENT,
            "viewport": cls.VIEWPORT,
            "locale": "ko-KR",
            "timezone_id": "Asia/Seoul",
        }


# 전역 설정 인스턴스
config = Config()


# 편의 함수
def get_browser_config() -> dict:
    """Playwright 브라우저 설정을 반환합니다."""
    return config.get_browser_config()


def get_context_config() -> dict:
    """Playwright 컨텍스트 설정을 반환합니다."""
    return config.get_context_config()
