"""네이버 로그인 자동화."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import Page, BrowserContext, TimeoutError as PlaywrightTimeout

from ..utils.error_handler import handle_playwright_error
from ..utils.exceptions import LoginError, CaptchaDetectedError, InvalidCredentialsError

logger = logging.getLogger(__name__)

from .selectors import LOGIN_ID_INPUT, LOGIN_PW_INPUT, LOGIN_BTN


async def login_to_naver(
    page: Page,
    user_id: str,
    password: str,
    storage_state_path: Optional[str] = None,
    headless: bool = True,
) -> dict:
    """
    네이버에 로그인하고 세션을 저장합니다.

    Args:
        page: Playwright Page 객체
        user_id: 네이버 아이디
        password: 네이버 비밀번호
        storage_state_path: 세션 저장 경로 (기본: playwright-state/auth.json)
        headless: 헤드리스 모드 여부

    Returns:
        로그인 결과 딕셔너리
        {
            "success": bool,
            "message": str,
            "storage_state_path": str (세션 저장 경로)
        }

    Raises:
        CaptchaDetectedError: CAPTCHA가 감지된 경우
        InvalidCredentialsError: 로그인 정보가 잘못된 경우
        LoginError: 기타 로그인 에러
    """
    if storage_state_path is None:
        storage_state_path = "playwright-state/auth.json"

    try:
        # 1. 로그인 페이지로 이동
        await page.goto("https://nid.naver.com/nidlogin.login", wait_until="networkidle")
        await asyncio.sleep(1)  # 페이지 로딩 대기

        # 2. 아이디 입력
        await page.fill(LOGIN_ID_INPUT, user_id)
        await asyncio.sleep(0.5)  # 자연스러운 타이핑 시뮬레이션

        # 3. 비밀번호 입력
        await page.fill(LOGIN_PW_INPUT, password)
        await asyncio.sleep(0.5)

        # 4. 로그인 버튼 클릭
        # 대체 셀렉터 시도
        login_clicked = False
        navigation_waiter = page.wait_for_navigation(wait_until="networkidle", timeout=10000)
        if isinstance(LOGIN_BTN, list):
            for selector in LOGIN_BTN:
                try:
                    await page.click(selector, timeout=3000)
                    login_clicked = True
                    break
                except PlaywrightTimeout:
                    continue
        else:
            await page.click(LOGIN_BTN)
            login_clicked = True

        if not login_clicked:
            raise LoginError("로그인 버튼을 찾을 수 없습니다.")

        # 5. 로그인 완료 대기 (네이버 메인 페이지 또는 에러 메시지)
        try:
            try:
                await navigation_waiter
            except PlaywrightTimeout:
                pass
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeout:
                pass

            current_url = page.url
            if "nid.naver.com" in current_url:
                # CAPTCHA 확인
                captcha_element = await page.locator("iframe[src*='captcha']").count()
                if captcha_element > 0:
                    if not headless:
                        await _wait_for_captcha_manual(page)
                    else:
                        raise CaptchaDetectedError(
                            "CAPTCHA가 감지되었습니다. HEADLESS=false로 설정하고 수동으로 풀어주세요."
                        )

                # 에러 메시지 확인
                login_error_selectors = [
                    ".error_message",
                    ".error_txt",
                    ".err_txt",
                    "#error",
                ]
                error_msg = None
                for selector in login_error_selectors:
                    try:
                        error_msg_element = page.locator(selector).first
                        if await error_msg_element.count() > 0:
                            text = await error_msg_element.text_content()
                            if text and text.strip():
                                error_msg = text.strip()
                                break
                    except Exception:
                        continue

                if error_msg:
                    raise InvalidCredentialsError(f"로그인 실패: {error_msg}")
                raise LoginError("로그인에 실패했습니다.")
        except PlaywrightTimeout:
            pass

        # 6. 세션 저장
        Path(storage_state_path).parent.mkdir(parents=True, exist_ok=True)
        storage_state = await page.context.storage_state(path=storage_state_path)

        # 7. 블로그 페이지로 이동하여 로그인 확인
        await page.goto("https://blog.naver.com", wait_until="load")
        await asyncio.sleep(2)  # 추가 로딩 대기

        # 로그인 상태 확인
        current_url = page.url

        # 방법 1: URL 확인 (로그인 페이지로 리다이렉트되지 않았는지)
        is_login_page = "nid.naver.com" in current_url
        if is_login_page:
            raise LoginError("로그인 페이지로 리다이렉트되었습니다.")

        # 방법 2: blog.naver.com 도메인에 있으면 로그인 성공으로 간주
        # (로그인하지 않았으면 nid.naver.com으로 리다이렉트됨)
        if "blog.naver.com" in current_url:
            print(f"   로그인 확인: blog.naver.com 도메인 접속 성공 ({current_url})")
            # 추가로 세션이 유효한지 확인 (쿠키 존재 여부)
            cookies = await page.context.cookies()
            naver_cookies = [c for c in cookies if 'naver.com' in c['domain']]
            if len(naver_cookies) > 0:
                print(f"   로그인 확인: 네이버 쿠키 {len(naver_cookies)}개 발견")
            else:
                raise LoginError("로그인 후 세션 확인에 실패했습니다. (쿠키 없음)")
        else:
            raise LoginError(f"예상치 못한 URL로 리다이렉트: {current_url}")

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
        raise LoginError(f"로그인 시간 초과: {str(e)}")
    except Exception as e:
        custom_error = await handle_playwright_error(e, page, "login")
        raise LoginError(f"로그인 중 오류 발생: {str(custom_error)}")


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
    except PlaywrightTimeout:
        raise LoginError("CAPTCHA 해결 시간 초과")


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
        await handle_playwright_error(e, page, "verify_login_session", save_screenshot=False)
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
        raise LoginError(f"로그아웃 중 오류 발생: {str(custom_error)}")
