"""네이버 로그인 자동화."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeout

from ..utils.error_handler import handle_playwright_error
from ..utils.exceptions import CaptchaDetectedError, InvalidCredentialsError, LoginError
from .selectors import LOGIN_BTN, LOGIN_ID_INPUT, LOGIN_PW_INPUT

logger = logging.getLogger(__name__)

_LOGIN_ERROR_SELECTORS = [".error_message", ".error_txt", ".err_txt", "#error"]


async def _check_login_error(page: Page) -> Optional[str]:
    """로그인 에러 메시지를 확인합니다. 에러가 있으면 메시지 반환, 없으면 None."""
    for selector in _LOGIN_ERROR_SELECTORS:
        try:
            element = page.locator(selector).first
            if await element.count() > 0 and await element.is_visible():
                text = await element.text_content()
                if text and text.strip():
                    return text.strip()
        except Exception:  # noqa: S110
            continue
    return None


async def _verify_login_success(page: Page) -> bool:
    """blog.naver.com 도메인과 네이버 쿠키 존재로 로그인 성공을 확인합니다."""
    current_url = page.url
    if "nid.naver.com" in current_url:
        return False
    if "blog.naver.com" not in current_url:
        raise LoginError(f"예상치 못한 URL로 리다이렉트: {current_url}")

    logger.debug("blog.naver.com 도메인 접속 성공: %s", current_url)
    cookies = await page.context.cookies()
    naver_cookies = [c for c in cookies if "naver.com" in c["domain"]]
    if not naver_cookies:
        raise LoginError("로그인 후 세션 확인에 실패했습니다. (쿠키 없음)")
    logger.debug("네이버 쿠키 %d개 확인", len(naver_cookies))
    return True


async def login_to_naver(
    page: Page,
    user_id: str,
    password: str,
    storage_state_path: Optional[str] = None,
    headless: bool = True,
) -> dict:
    """네이버에 로그인하고 세션을 저장합니다.

    Raises:
        CaptchaDetectedError: CAPTCHA가 감지된 경우
        InvalidCredentialsError: 로그인 정보가 잘못된 경우
        LoginError: 기타 로그인 에러
    """
    if storage_state_path is None:
        storage_state_path = "playwright-state/auth.json"

    try:
        # 1. 로그인 페이지로 이동 후 입력 필드 대기
        await page.goto(
            "https://nid.naver.com/nidlogin.login", wait_until="networkidle"
        )
        await page.wait_for_selector(LOGIN_ID_INPUT, state="visible", timeout=10000)

        # 2. 아이디 입력
        await page.click(LOGIN_ID_INPUT)
        await page.fill(LOGIN_ID_INPUT, user_id)
        await page.dispatch_event(LOGIN_ID_INPUT, "input")
        await page.dispatch_event(LOGIN_ID_INPUT, "change")

        # 3. 비밀번호 입력
        await page.wait_for_selector(LOGIN_PW_INPUT, state="visible", timeout=5000)
        await page.click(LOGIN_PW_INPUT)
        await page.fill(LOGIN_PW_INPUT, password)
        await page.dispatch_event(LOGIN_PW_INPUT, "input")
        await page.dispatch_event(LOGIN_PW_INPUT, "change")

        # 4. 로그인 버튼 클릭 (대체 셀렉터 지원)
        login_clicked = False
        btn_list = LOGIN_BTN if isinstance(LOGIN_BTN, list) else [LOGIN_BTN]
        for selector in btn_list:
            try:
                await page.click(selector, timeout=3000)
                login_clicked = True
                break
            except PlaywrightTimeout:
                continue

        if not login_clicked:
            raise LoginError("로그인 버튼을 찾을 수 없습니다.")

        # 5. 로그인 완료 대기
        for state in ("networkidle", "load"):
            try:
                await page.wait_for_load_state(state, timeout=10000)
                break
            except PlaywrightTimeout:
                continue

        current_url = page.url
        if "nid.naver.com" in current_url:
            # CAPTCHA 확인
            captcha_count = await page.locator("iframe[src*='captcha']").count()
            captcha_visible = (
                await page.locator("#rcapt").is_visible()
                or await page.locator("#captchaimg").is_visible()
            )
            if captcha_count > 0 or captcha_visible:
                if not headless:
                    await _wait_for_captcha_manual(page)
                else:
                    raise CaptchaDetectedError(
                        "CAPTCHA가 감지되었습니다. "
                        "HEADLESS=false로 설정하고 수동으로 풀어주세요."
                    )

            error_msg = await _check_login_error(page)
            if error_msg:
                raise InvalidCredentialsError(f"로그인 실패: {error_msg}")
            raise LoginError("로그인에 실패했습니다.")

        # 6. 세션 저장
        Path(storage_state_path).parent.mkdir(parents=True, exist_ok=True)
        await page.context.storage_state(path=storage_state_path)

        # 7. 블로그 페이지로 이동하여 로그인 확인
        await page.goto("https://blog.naver.com", wait_until="load")
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
        await _verify_login_success(page)

        return {
            "success": True,
            "message": "로그인에 성공했습니다.",
            "storage_state_path": storage_state_path,
        }

    except CaptchaDetectedError:
        raise
    except InvalidCredentialsError:
        raise
    except PlaywrightTimeout as e:
        raise LoginError(f"로그인 시간 초과: {str(e)}") from e
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "login")
        raise LoginError(f"로그인 중 오류 발생: {str(custom_error)}") from e


async def _wait_for_captcha_manual(page: Page, timeout: int = 60000) -> None:
    """
    사용자가 수동으로 CAPTCHA를 풀 때까지 대기합니다.

    Args:
        page: Playwright Page 객체
        timeout: 대기 시간 (ms, 기본 60초)

    Raises:
        LoginError: CAPTCHA를 풀지 못한 경우
    """
    logger.warning("CAPTCHA가 감지되었습니다.")
    logger.info("브라우저에서 CAPTCHA를 풀어주세요. (60초 대기)")

    try:
        # CAPTCHA iframe이 사라질 때까지 대기
        await page.wait_for_function(
            "document.querySelector('iframe[src*=\"captcha\"]') === null",
            timeout=timeout,
        )
        logger.info("CAPTCHA 해결 완료!")
        await asyncio.sleep(2)  # 추가 대기
    except PlaywrightTimeout as e:
        raise LoginError("CAPTCHA 해결 시간 초과") from e


async def verify_login_session(page: Page) -> bool:
    """
    현재 세션이 로그인 상태인지 확인합니다.

    Args:
        page: Playwright Page 객체

    Returns:
        로그인 여부
    """
    try:
        await page.goto("https://blog.naver.com", wait_until="load", timeout=10000)
        await asyncio.sleep(1)  # 추가 로딩 대기

        # URL 및 쿠키 확인
        current_url = page.url

        # 로그인 페이지로 리다이렉트되지 않았는지 확인
        if "nid.naver.com" in current_url:
            return False

        # blog.naver.com 도메인에 있고 쿠키가 있으면 로그인된 것으로 간주
        if "blog.naver.com" in current_url:
            cookies = await page.context.cookies()
            naver_cookies = [c for c in cookies if 'naver.com' in c['domain']]
            return len(naver_cookies) > 0

        return False
    except Exception as e:
        await handle_playwright_error(
            e, page, "verify_login_session", save_screenshot=False
        )
        return False


async def logout_from_naver(page: Page) -> None:
    """
    네이버에서 로그아웃합니다.

    Args:
        page: Playwright Page 객체
    """
    try:
        await page.goto("https://nid.naver.com/nidlogin.logout")
        await asyncio.sleep(1)
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "logout")
        raise LoginError(f"로그아웃 중 오류 발생: {str(custom_error)}") from e
