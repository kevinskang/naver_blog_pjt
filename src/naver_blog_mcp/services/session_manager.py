"""네이버 블로그 세션 관리자."""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from playwright.async_api import Browser, BrowserContext

from ..automation.login import login_to_naver, verify_login_session
from ..config import config, get_context_config

logger = logging.getLogger(__name__)

# userAgentData의 브랜드/플랫폼/버전은 config.USER_AGENT 및 실제 번들 Chromium과
# 일치해야 봇 탐지를 피할 수 있다. 버전·플랫폼은 config에서 주입하며, JS 객체
# 리터럴의 중괄호와 충돌하지 않도록 placeholder 치환 방식을 쓴다.
_STEALTH_TEMPLATE = r"""
Object.defineProperty(navigator, 'webdriver', {
    get: () => false,
});
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});
Object.defineProperty(navigator, 'languages', {
    get: () => ['ko-KR', 'ko'],
});
Object.defineProperty(navigator, 'userAgentData', {
    get: () => ({
        brands: [
            { brand: 'Chromium', version: '__MAJOR__' },
            { brand: 'Google Chrome', version: '__MAJOR__' },
            { brand: 'Not?A_Brand', version: '24' },
        ],
        mobile: false,
        platform: '__PLATFORM__',
        getHighEntropyValues: async () => ({
            architecture: 'x86',
            bitness: '64',
            model: '',
            platform: '__PLATFORM__',
            platformVersion: '10.0.0',
            uaFullVersion: '__FULL__',
            fullVersionList: [
                { brand: 'Chromium', version: '__FULL__' },
                { brand: 'Google Chrome', version: '__FULL__' },
                { brand: 'Not?A_Brand', version: '24.0.0.0' },
            ],
        }),
    }),
});
window.chrome = {
    runtime: {},
};
"""

STEALTH_SCRIPT = (
    _STEALTH_TEMPLATE.replace("__MAJOR__", config.CHROME_MAJOR_VERSION)
    .replace("__FULL__", config.CHROME_FULL_VERSION)
    .replace("__PLATFORM__", "Windows")
)


class SessionManager:
    """네이버 블로그 세션을 관리하는 클래스."""

    def __init__(
        self,
        user_id: str,
        password: str,
        storage_path: str = config.SESSION_STORAGE_PATH,
        session_validity_hours: int = config.SESSION_VALIDITY_HOURS,
        account_id: Optional[str] = None,
    ):
        """세션 매니저 초기화."""
        self.user_id = user_id
        # 패스워드는 메모리에 저장하지 않고, 로그인 시점에 config에서 직접 참조
        self._password_hint = bool(password)  # 설정 여부만 기록
        self.storage_path = storage_path
        self.session_validity_hours = session_validity_hours
        self.last_login_time: Optional[datetime] = None
        self.account_id = account_id

    def _get_password(self) -> str:
        """계정별 비밀번호를 환경 변수에서 읽어옵니다 (메모리 저장 방지)."""
        return config.get_account_password(self.account_id)

    def is_session_file_valid(self) -> bool:
        """
        세션 파일이 유효한지 확인합니다.

        Returns:
            세션 파일 유효 여부
        """
        # 1. 파일 존재 여부
        if not Path(self.storage_path).exists():
            return False

        # 2. 파일 수정 시간 확인
        file_mtime = datetime.fromtimestamp(Path(self.storage_path).stat().st_mtime)
        elapsed = datetime.now() - file_mtime

        # 설정된 유효 시간 이내인지 확인
        if elapsed > timedelta(hours=self.session_validity_hours):
            return False

        return True

    async def is_session_valid(self, context: BrowserContext) -> bool:
        """
        실제 네이버 페이지에 접속하여 세션 유효성을 검사합니다.

        Args:
            context: Playwright BrowserContext 객체

        Returns:
            세션 유효 여부
        """
        # 1. 파일 유효성 확인
        if not self.is_session_file_valid():
            return False

        # 2. 실제 페이지 접속 테스트
        page = await context.new_page()
        try:
            is_valid = await verify_login_session(page)
            return is_valid
        finally:
            await page.close()

    async def get_or_create_session(
        self, browser: Browser, headless: bool = True
    ) -> BrowserContext:
        """
        유효한 세션이 있으면 재사용하고, 없으면 새로 로그인합니다.

        Args:
            browser: Playwright Browser 객체
            headless: 헤드리스 모드 여부

        Returns:
            BrowserContext 객체

        Raises:
            LoginError: 로그인 실패 시
        """
        # 1. 기존 세션 파일이 있고 유효하면 재사용
        if self.is_session_file_valid():
            try:
                context = await browser.new_context(
                    storage_state=self.storage_path,
                    **get_context_config(),
                )
                await self._apply_stealth_scripts(context)

                # 실제 로그인 상태 확인
                if await self.is_session_valid(context):
                    logger.info("저장된 세션 재사용: %s", self.storage_path)
                    return context
                else:
                    logger.info("저장된 세션이 만료되었습니다. 재로그인합니다.")
                    await context.close()
            except Exception as e:
                logger.warning("세션 복원 실패: %s. 재로그인합니다.", e)

        # 2. 새로 로그인
        context = await browser.new_context(**get_context_config())
        await self._apply_stealth_scripts(context)
        page = await context.new_page()

        try:
            current_password = self._get_password()
            result = await login_to_naver(
                page=page,
                user_id=self.user_id,
                password=current_password,  # 메모리 저장 없이 직접 참조
                storage_state_path=self.storage_path,
                headless=headless,
            )

            self.last_login_time = datetime.now()
            logger.info(
                "%s (세션 저장: %s)", result["message"], result["storage_state_path"]
            )

            return context

        except Exception:
            # 로그인 실패(LoginError 포함) 시 context 누수를 막기 위해 정리합니다.
            await context.close()
            raise
        finally:
            await page.close()

    async def _apply_stealth_scripts(self, context: BrowserContext) -> None:
        """
        브라우저 컨텍스트에 자동화 탐지를 회피하기 위한 초기 스크립트를 추가합니다.
        """
        await context.add_init_script(STEALTH_SCRIPT)

    async def refresh_session_if_needed(
        self, browser: Browser, context: BrowserContext, headless: bool = True
    ) -> BrowserContext:
        """
        필요 시 세션을 갱신합니다.

        Args:
            browser: Playwright Browser 객체
            context: 현재 BrowserContext 객체
            headless: 헤드리스 모드 여부

        Returns:
            갱신된 또는 기존 BrowserContext 객체
        """
        # 세션이 유효하면 그대로 반환
        if await self.is_session_valid(context):
            return context

        # 세션이 만료되었으면 재로그인
        logger.info("세션이 만료되었습니다. 재로그인합니다.")
        await context.close()
        return await self.get_or_create_session(browser, headless)

    def clear_session(self) -> None:
        """저장된 세션 파일을 삭제합니다."""
        if Path(self.storage_path).exists():
            Path(self.storage_path).unlink()
            logger.info("세션 파일 삭제: %s", self.storage_path)
