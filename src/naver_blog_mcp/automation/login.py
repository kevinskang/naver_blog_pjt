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

# 로그인 성공 시에만 발급되고 로그아웃 시 제거되는 네이버 인증 쿠키.
# NNB 등 비로그인 상태에도 존재하는 쿠키로 판정하면 오탐(false positive)이
# 발생하므로, 반드시 이 로그인 전용 쿠키의 존재로 세션 유효성을 판정한다.
_LOGIN_COOKIE_NAMES = ("NID_AUT", "NID_SES")


async def _has_login_cookies(page: Page) -> bool:
    """로그인 전용 쿠키(NID_AUT/NID_SES) 존재 여부로 로그인 상태를 판정합니다."""
    cookies = await page.context.cookies()
    cookie_names = {c.get("name") for c in cookies}
    return any(name in cookie_names for name in _LOGIN_COOKIE_NAMES)


async def _dismiss_device_registration(page: Page) -> None:
    """로그인 직후 나타날 수 있는 '새로운 기기 등록' 페이지를 '등록안함'으로 넘깁니다.

    로그인 자체는 이미 성공(쿠키 발급 완료)한 상태이므로, 이 페이지가 없으면
    아무 것도 하지 않고, 있으면 등록하지 않고 진행합니다.
    """
    dontsave_selectors = [
        "#new\\.dontsave",
        "a#new\\.dontsave",
        "button:has-text('등록안함')",
        "a:has-text('등록안함')",
    ]
    for selector in dontsave_selectors:
        try:
            locator = page.locator(selector).first
            if await locator.count() > 0 and await locator.is_visible():
                await locator.click(timeout=2000)
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
                logger.debug("기기 등록 페이지를 '등록안함'으로 넘김")
                return
        except Exception:  # noqa: S110
            continue


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
    if not await _has_login_cookies(page):
        raise LoginError(
            "로그인 후 세션 확인에 실패했습니다. "
            "(로그인 쿠키 NID_AUT/NID_SES 없음)"
        )
    logger.debug("로그인 쿠키(NID_AUT/NID_SES) 확인 완료")
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

        # 2. 아이디 입력 (사람 유사 입력 — 네이버 '자동입력 방지' 회피)
        #    fill()은 값을 직접 주입해 키 이벤트가 없으므로 봇으로 감지될 수 있다.
        #    press_sequentially()로 실제 키 입력 이벤트를 발생시킨다.
        id_locator = page.locator(LOGIN_ID_INPUT)
        await id_locator.click()
        await id_locator.fill("")
        await id_locator.press_sequentially(user_id, delay=80)

        # 3. 비밀번호 입력 (사람 유사 입력)
        await page.wait_for_selector(LOGIN_PW_INPUT, state="visible", timeout=5000)
        pw_locator = page.locator(LOGIN_PW_INPUT)
        await pw_locator.click()
        await pw_locator.fill("")
        await pw_locator.press_sequentially(password, delay=80)

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

        # 5. 로그인 완료 대기: 성공 시 발급되는 쿠키(NID_AUT/NID_SES)가 생길
        #    때까지 폴링한다. 로그인 성공 후 www.naver.com 등으로의 리다이렉트가
        #    여러 단계(중간 nid.naver.com 페이지, 기기 등록 등)를 거치므로, 단순
        #    load 대기 후 URL 판정만으로는 중간 페이지를 실패로 오판할 수 있다.
        login_ok = False
        for _ in range(15):
            if await _has_login_cookies(page):
                login_ok = True
                break
            await asyncio.sleep(1)

        if not login_ok:
            # 로그인 쿠키가 없으면 추가 인증(CAPTCHA/기기 인증) 또는 자격증명 오류.
            captcha_count = await page.locator("iframe[src*='captcha']").count()
            captcha_visible = (
                await page.locator("#rcapt").is_visible()
                or await page.locator("#captchaimg").is_visible()
            )
            if captcha_count > 0 or captcha_visible:
                if not headless:
                    await _wait_for_captcha_manual(page)
                    # 수동 처리 후 쿠키가 생겼는지 재확인
                    for _ in range(30):
                        if await _has_login_cookies(page):
                            login_ok = True
                            break
                        await asyncio.sleep(1)
                else:
                    raise CaptchaDetectedError(
                        "CAPTCHA가 감지되었습니다. "
                        "HEADLESS=false로 설정하고 수동으로 풀어주세요."
                    )

        if not login_ok:
            error_msg = await _check_login_error(page)
            if error_msg:
                raise InvalidCredentialsError(f"로그인 실패: {error_msg}")
            raise LoginError("로그인에 실패했습니다.")

        # 5-1. 로그인 직후 나타날 수 있는 '새로운 기기 등록' 페이지를 넘긴다.
        await _dismiss_device_registration(page)

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

        # 로그인 페이지로 리다이렉트되었으면 세션 만료
        if "nid.naver.com" in page.url:
            return False

        # 로그인 전용 쿠키(NID_AUT/NID_SES)로 판정한다.
        # NNB 등 비로그인 쿠키의 존재로 판정하면 로그아웃 상태를 '유효'로
        # 오탐하므로, 반드시 로그인 쿠키 존재 여부를 확인한다. (DEF-001)
        return await _has_login_cookies(page)
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
