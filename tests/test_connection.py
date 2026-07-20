import asyncio
import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv
from playwright.async_api import async_playwright

# 라이브 네이버 로그인이 필요한 테스트 — RUN_LIVE_TESTS=true 일 때만 실행
pytestmark = pytest.mark.e2e

# Project root setup
project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")
sys.path.insert(0, str(project_root / "src"))

async def test_http_connection():
    print("1. HTTP Connection Test (urllib)")
    import urllib.request
    try:
        # Request Naver homepage
        req = urllib.request.Request(
            "https://www.naver.com", 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            status = response.getcode()
            print(f"   [OK] Connected to naver.com. HTTP Status: {status}")
            return True
    except Exception as e:
        print(f"   [FAIL] Failed to connect to naver.com: {e}")
        return False

async def test_playwright_connection():
    print("\n2. Playwright Headless Connection Test")
    headless = os.getenv("HEADLESS", "true").lower() == "true"
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"]
            )
            page = await browser.new_page()
            print("   Navigating to https://www.naver.com ...")
            await page.goto("https://www.naver.com", timeout=15000)
            title = await page.title()
            print(f"   [OK] Page title is: '{title}'")
            await browser.close()
            return True
        except Exception as e:
            print(f"   [FAIL] Playwright navigation failed: {e}")
            return False

async def test_naver_login_connection():
    print("\n3. Naver Login Verification Test (using credentials in .env)")
    user_id = os.getenv("NAVER_BLOG_ID")
    password = os.getenv("NAVER_BLOG_PASSWORD")
    headless = os.getenv("HEADLESS", "true").lower() == "true"
    
    if not user_id or not password:
        print("   [SKIP] NAVER_BLOG_ID or NAVER_BLOG_PASSWORD is not set in .env")
        return False
        
    from naver_blog_mcp.automation.login import login_to_naver
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()
        try:
            print(f"   Attempting login with ID: {user_id}...")
            result = await login_to_naver(
                page=page,
                user_id=user_id,
                password=password,
                storage_state_path="playwright-state/test_connection_auth.json",
                headless=headless,
            )
            print(f"   [OK] Login status: {result.get('success', False)}")
            print(f"   Message: {result.get('message', 'No message')}")
            await browser.close()
            return result.get('success', False)
        except Exception as e:
            print(f"   [FAIL] Login test threw an exception: {e}")
            try:
                os.makedirs("playwright-state", exist_ok=True)
                await page.screenshot(path="playwright-state/test_connection_error.png")
                print("   Screenshot saved to playwright-state/test_connection_error.png")
            except Exception as se:
                print(f"   Could not save screenshot: {se}")
            await browser.close()
            return False

async def main():
    print("="*60)
    print("Starting NAVER Connection Test")
    print("="*60)
    
    http_ok = await test_http_connection()
    pw_ok = await test_playwright_connection()
    login_ok = await test_naver_login_connection()
    
    print("\n" + "="*60)
    print("Summary:")
    print(f"- HTTP Connection: {'SUCCESS' if http_ok else 'FAILED'}")
    print(f"- Playwright Page Load: {'SUCCESS' if pw_ok else 'FAILED'}")
    print(f"- Login Attempt: {'SUCCESS' if login_ok else 'FAILED'}")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())
