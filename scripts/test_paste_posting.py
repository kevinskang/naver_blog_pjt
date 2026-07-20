import asyncio
import os
import re
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
import markdown
from playwright.async_api import async_playwright

# Setup project paths
project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")
sys.path.insert(0, str(project_root / "src"))

from naver_blog_mcp.automation.login import login_to_naver
from naver_blog_mcp.automation.post_actions import fill_post_title, navigate_to_post_write_page
from naver_blog_mcp.services.session_manager import SessionManager
from naver_blog_mcp.config import config

def parse_markdown_to_html(md_path: Path) -> tuple[str, str, list[str]]:
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Split Frontmatter
    frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', content, re.DOTALL)
    tags = ["기술지도사", "기출문제", "정보통신개론", "제41회"]
    body = content

    if frontmatter_match:
        fm_block = frontmatter_match.group(1)
        body = frontmatter_match.group(2)
        tag_match = re.search(r'tags:\s*\[(.*?)\]', fm_block)
        if tag_match:
            tags = [t.strip() for t in tag_match.group(1).split(",")]

    # Extract H1 title
    title_match = re.search(r'^#\s+(.*?)\s*\n', body)
    if title_match:
        post_title = title_match.group(1)
        body = body.replace(title_match.group(0), "", 1)
    else:
        post_title = "2026년도 제41회 기술지도사(정보기술관리) 2차 1교시 — 정보통신개론"

    # Convert body from Markdown to HTML
    html_body = markdown.markdown(body, extensions=['tables', 'nl2br'])
    return post_title, html_body, tags

async def main():
    md_path = Path("/home/testudo/second/Workplace/obsidian/my-vault/Personal/기술지도사/기출문제풀이/제41회/제41회_정보통신개론_기출풀이.md")
    
    print("1. Converting Markdown to HTML...")
    title, html_content, tags = parse_markdown_to_html(md_path)
    print(f"   [OK] Title: {title}")
    print(f"   [OK] HTML Content Length: {len(html_content)} characters")

    config.validate()
    headless = os.getenv("HEADLESS", "false").lower() == "true"
    
    print("\n2. Launching Playwright browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        session_manager = SessionManager(
            user_id=config.NAVER_BLOG_ID,
            password=config.NAVER_BLOG_PASSWORD
        )
        
        context = await session_manager.get_or_create_session(browser, headless=headless)
        page = await context.new_page()
        
        from naver_blog_mcp.automation.login import verify_login_session
        if not await verify_login_session(page):
            print("   Logging in...")
            await login_to_naver(
                page=page, 
                user_id=config.NAVER_BLOG_ID, 
                password=config.NAVER_BLOG_PASSWORD, 
                storage_state_path="playwright-state/auth.json",
                headless=headless
            )

        try:
            print("\n3. Navigating to post write page...")
            await navigate_to_post_write_page(page, None)
            await asyncio.sleep(3)
            
            # Target iframe
            iframe_element = await page.wait_for_selector("iframe#mainFrame", timeout=10000)
            main_frame = await iframe_element.content_frame()
            if not main_frame:
                raise Exception("Cannot access main editor iframe")
                
            # 3.0 Clean up initial popups BEFORE writing anything
            print("   Cleaning up initial popups and help panels...")
            await page.bring_to_front()
            await page.keyboard.press("Escape")
            await asyncio.sleep(1)
            
            # Close help panels on parent page
            help_close_selectors = [
                "button[class*='close']", 
                "[class*='help'] button[class*='close']",
                "button.se-help-close-btn",
                "button.btn_close",
                "button[aria-label='도움말 닫기']",
                ".se-help-panel-close-btn",
                "button:has-text('도움말 닫기')",
                "button.se-popup-button-cancel",
                "button:has-text('닫기')",
                ".se-help-panel-close"
            ]
            for close_sel in help_close_selectors:
                try:
                    loc = page.locator(close_sel)
                    count = await loc.count()
                    for i in range(count):
                        btn = loc.nth(i)
                        if await btn.is_visible():
                            await btn.click(timeout=1000)
                            print(f"   [OK] Closed top-level popup using: {close_sel}")
                            await asyncio.sleep(0.3)
                except Exception:
                    pass
            
            # Force close draft popup inside mainFrame (ALWAYS cancel/discard draft to start fresh)
            try:
                cancel_btn = main_frame.locator("button.se-popup-button-cancel").first
                if await cancel_btn.count() > 0 and await cancel_btn.is_visible():
                    await cancel_btn.click()
                    print("   [OK] Discarded previous draft prompt.")
                    await asyncio.sleep(1)
            except Exception as e:
                print(f"   No draft cancel popup detected: {e}")

            # Coordinate-based fallback click to close the Help Sidebar (Top-right corner of the panel)
            try:
                print("   Clicking top-right coordinate fallback to close help panel...")
                await page.mouse.click(1900, 35)
                await asyncio.sleep(1)
            except Exception as e:
                print(f"   Coordinate click failed: {e}")

            # 3.1 Write Title (With clearing)
            print("   Filling post title (clearing first)...")
            # We select title editor to clear it
            title_selectors = [
                "div[contenteditable='true'][data-placeholder='제목']",
                ".se-title-input",
                "input[placeholder*='제목']"
            ]
            
            cleared_title = False
            for sel in title_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        await loc.click()
                        await page.keyboard.press("Control+A")
                        await page.keyboard.press("Backspace")
                        await asyncio.sleep(0.5)
                        await loc.type(title, delay=40)
                        cleared_title = True
                        print("   [OK] Title cleared and written.")
                        break
                except Exception:
                    continue
                    
            if not cleared_title:
                await fill_post_title(page, title)
            await asyncio.sleep(1.5)

            # 3.2 Focus the editor body by clicking the contenteditable element (The second contenteditable)
            print("   Focusing editor body...")
            await main_frame.evaluate("""
                () => {
                    const editors = Array.from(document.querySelectorAll('div[contenteditable="true"]'));
                    let bodyEditor = null;
                    if (editors.length >= 2) {
                        bodyEditor = editors[1]; // Title is editors[0], Body is editors[1]
                    } else if (editors.length === 1) {
                        bodyEditor = editors[0];
                    }
                    if (bodyEditor) {
                        bodyEditor.focus();
                        bodyEditor.click();
                        // Clear body content
                        bodyEditor.innerHTML = "";
                    } else {
                        throw new Error("No contenteditable editors found");
                    }
                }
            """)
            await asyncio.sleep(0.5)
            
            # 4. Insert via virtual Clipboard Paste Event (Triggers React state update)
            print("   Injecting HTML content via mock Clipboard Paste Event...")
            start_time = time.time()
            
            # Plain text version for fallback
            plain_content = re.sub(r'<[^>]*>', '', html_content)
            
            await main_frame.evaluate("""
                ({html, plain}) => {
                    const editors = Array.from(document.querySelectorAll('div[contenteditable="true"]'));
                    let bodyEditor = null;
                    if (editors.length >= 2) {
                        bodyEditor = editors[1];
                    } else if (editors.length === 1) {
                        bodyEditor = editors[0];
                    }
                    if (!bodyEditor) throw new Error("Body editor contenteditable not found.");
                    
                    bodyEditor.focus();
                    
                    // Create clipboard data transfer object
                    const dataTransfer = new DataTransfer();
                    dataTransfer.setData('text/html', html);
                    dataTransfer.setData('text/plain', plain);
                    
                    // Create and dispatch Paste Event
                    const pasteEvent = new ClipboardEvent('paste', {
                        clipboardData: dataTransfer,
                        bubbles: true,
                        cancelable: true
                    });
                    
                    bodyEditor.dispatchEvent(pasteEvent);
                }
            """, {"html": html_content, "plain": plain_content})
            
            elapsed = time.time() - start_time
            print(f"   [OK] Paste event dispatched in {elapsed:.4f} seconds!")
            await asyncio.sleep(3)
            
            # 5. Publishing Process
            # 5-1. Ensure everything is focused and close any help overlays
            await page.bring_to_front()
            await page.keyboard.press("Escape")
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
            
            # Click empty area to dismiss option menus (X=100, Y=500 is a safe blank region)
            try:
                print("   Clicking safe blank area to dismiss any context menus...")
                await page.mouse.click(100, 500)
                await asyncio.sleep(0.5)
            except Exception:
                pass
                
            # Close help sidebar coordinates
            try:
                await page.mouse.click(1900, 35)
                await asyncio.sleep(0.5)
            except Exception:
                pass
                
            # Close helper panels on both top page and iframe
            for close_sel in help_close_selectors:
                try:
                    loc = page.locator(close_sel)
                    count = await loc.count()
                    for i in range(count):
                        btn = loc.nth(i)
                        if await btn.is_visible():
                            await btn.click(timeout=1000)
                            print(f"   [OK] Closed top helper: {close_sel}")
                            await asyncio.sleep(0.5)
                except Exception:
                    pass
                    
            for close_sel in help_close_selectors:
                try:
                    loc = main_frame.locator(close_sel)
                    count = await loc.count()
                    for i in range(count):
                        btn = loc.nth(i)
                        if await btn.is_visible():
                            await btn.click(timeout=1000)
                            print(f"   [OK] Closed iframe helper: {close_sel}")
                            await asyncio.sleep(0.5)
                except Exception:
                    pass
                    
            # 5-2. Click top-level main publish button (green background one)
            print("   Clicking top-level main publish button...")
            
            publish_selectors = [
                "button.btn_publish",
                "button[class*='publish']",
                ".publish_btn button",
                "button:has-text('발행')"
            ]
            
            clicked_publish = False
            for sel in publish_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        text = await loc.text_content()
                        if text and "발행" in text:
                            if "option" not in (await loc.get_attribute("class") or "").lower():
                                await loc.click()
                                clicked_publish = True
                                print(f"   [OK] Clicked publish button using selector: {sel}")
                                break
                except Exception:
                    continue
                    
            if not clicked_publish:
                # Fallback click
                await page.locator("button:has-text('발행')").first.click()
                print("   [OK] Clicked publish button using generic fallback.")
                
            await asyncio.sleep(2.5)
            
            # 5-3. Category Selection
            print("   Selecting category...")
            category_selectors = [
                ".blog2_series button",
                "button[class*='category']",
                "[class*='CategorySelect'] button",
                "button:has-text('카테고리')"
            ]
            
            category_selected = False
            for sel in category_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.click()
                        await asyncio.sleep(1.0)
                        
                        opt_loc = page.locator("li").filter(has_text=re.compile(r"^정보통신$")).first
                        if await opt_loc.count() == 0:
                            opt_loc = page.locator("li:has-text('정보통신')").first
                            
                        if await opt_loc.count() > 0:
                            await opt_loc.click()
                            print("   [OK] Category '정보통신' selected successfully.")
                            category_selected = True
                            await asyncio.sleep(0.5)
                            break
                except Exception as ce:
                    print(f"   Selector {sel} failed: {ce}")
                    continue
                    
            if not category_selected:
                print("   [WARNING] Fallback category selection trial...")
                from naver_blog_mcp.automation.post_actions import _select_category
                await _select_category(page, "정보통신")
                
            # 5-4. Tags insertion
            print("   Inserting tags...")
            tag_input = page.locator("input[placeholder*='태그'], .tag_input input, #tagInput").first
            if await tag_input.count() > 0:
                await tag_input.click()
                for tag in tags:
                    await tag_input.type(tag, delay=30)
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(0.3)
                print("   [OK] Tags set.")
                
            # 5-5. Click final Confirm Publish button
            print("   Confirming publication...")
            confirm_publish_btn = page.locator(".layer_popup__i0QOY button:has-text('발행'), button[class*='confirm']:has-text('발행'), .layer_popup__i0QOY button[class*='confirm']").first
            
            clicked_final = False
            try:
                if await confirm_publish_btn.count() > 0:
                    await confirm_publish_btn.click(force=True)
                    clicked_final = True
                    print("   [OK] Confirm button clicked.")
            except Exception as e:
                print(f"   Failed to click confirm button normally: {e}")
                
            if not clicked_final:
                result = await page.evaluate("""
                    () => {
                        const popups = document.querySelectorAll('.layer_popup__i0QOY, [class*="layer_popup"]');
                        for (let popup of popups) {
                            const buttons = popup.querySelectorAll('button');
                            for (let btn of buttons) {
                                if ((btn.textContent || '').trim() === '발행') {
                                    btn.click();
                                    return 'JS_CLICKED';
                                }
                            }
                        }
                        return 'NOT_FOUND';
                    }
                """)
                if result == "JS_CLICKED":
                    print("   [OK] Confirm button clicked via JS.")
                    clicked_final = True
                    
            # 5-6. Redirection wait
            if clicked_final:
                print("   Waiting for final post redirection...")
                await page.wait_for_url("**/blog.naver.com/*/**", timeout=25000)
                post_url = page.url
                print("\n" + "="*60)
                print("🎉 SUCCESS: Naver Blog Post Created successfully using HTML Paste!")
                print(f"📌 Post Title: {title}")
                print(f"🔗 Post URL: {post_url}")
                print("="*60)
            else:
                print("❌ FAILED: Post confirmation failed.")
                await page.screenshot(path="playwright-state/paste_error_confirm.png")
                
        except Exception as e:
            print(f"❌ Exception occurred: {e}")
            try:
                os.makedirs("playwright-state", exist_ok=True)
                await page.screenshot(path="playwright-state/paste_error.png")
                print("   Error screenshot saved to playwright-state/paste_error.png")
            except Exception as se:
                print(f"   Could not save screenshot: {se}")
        finally:
            await context.close()
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
