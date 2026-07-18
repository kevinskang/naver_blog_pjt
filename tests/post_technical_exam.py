import asyncio
import os
import re
import sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

# Setup project paths
project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")
sys.path.insert(0, str(project_root / "src"))

from naver_blog_mcp.automation.login import login_to_naver
from naver_blog_mcp.automation.post_actions import fill_post_title, fill_post_content, navigate_to_post_write_page
from naver_blog_mcp.services.session_manager import SessionManager
from naver_blog_mcp.config import config

# 1. Parse and format Markdown tables & math notations to block-style text
def format_md_table_to_text(table_content: str) -> str:
    """Converts a markdown table block into readable bullet points."""
    lines = [line.strip() for line in table_content.strip().split("\n") if line.strip()]
    if len(lines) < 2:
        return table_content

    # Extract headers
    headers = [h.strip() for h in lines[0].split("|")[1:-1]]
    
    formatted_blocks = []
    # Skip header separator line (lines[1])
    for line in lines[2:]:
        cols = [c.strip() for c in line.split("|")[1:-1]]
        if len(cols) == len(headers):
            item_desc = []
            # Make the first column the key/header
            key = f"▶ {cols[0]}"
            for h, v in zip(headers[1:], cols[1:]):
                item_desc.append(f"  • {h}: {v}")
            formatted_blocks.append(f"{key}\n" + "\n".join(item_desc))
            
    return "\n\n".join(formatted_blocks)

def clean_math_notation(text: str) -> str:
    """Cleans LaTeX math formulas (e.g. $2^n-1$) to plain text."""
    text = re.sub(r'\$([^\$]+)\$', r'\1', text)
    return text

def parse_and_convert_markdown(md_path: Path) -> tuple[str, str, list[str]]:
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Split Frontmatter
    frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', content, re.DOTALL)
    tags = ["기술지도사", "기출문제", "정보통신개론", "제41회"]
    body = content

    if frontmatter_match:
        fm_block = frontmatter_match.group(1)
        body = frontmatter_match.group(2)
        
        # Extract tags
        tag_match = re.search(r'tags:\s*\[(.*?)\]', fm_block)
        if tag_match:
            tags = [t.strip() for t in tag_match.group(1).split(",")]

    # Remove main H1 header from body since it will be the post title
    title_match = re.search(r'^#\s+(.*?)\s*\n', body)
    if title_match:
        post_title = title_match.group(1)
        # Strip the H1 title from body
        body = body.replace(title_match.group(0), "", 1)
    else:
        post_title = "2026년도 제41회 기술지도사(정보기술관리) 2차 1교시 — 정보통신개론"

    # Preprocess tables in the markdown body
    table_pattern = re.compile(r'((?:\|[^\n]+\|\s*\n)+)')
    
    def table_replacer(match):
        return "\n" + format_md_table_to_text(match.group(1)) + "\n"
        
    body = table_pattern.sub(table_replacer, body)
    body = clean_math_notation(body)
    
    # Prettify list dividers (---) to make them look like styled blog sections
    body = re.sub(r'\n---\n', r'\n--------------------------------------------------\n', body)
    
    # Prepend introductory paragraph
    intro = (
        "안녕하세요! 기술지도사(정보기술관리) 2차 시험을 준비하시는 분들을 위해,\n"
        "2026년도 제41회 기술지도사 2차 1교시 '정보통신개론' 기출문제의 모범답안을 공유합니다.\n"
        "기출문제를 꼼꼼히 확인하시어 시험 준비에 도움이 되시기를 바랍니다.\n\n"
    )
    
    final_content = intro + body.strip()
    return post_title, final_content, tags

async def main():
    md_path = Path("/home/testudo/second/Workplace/obsidian/my-vault/Personal/기술지도사/기출문제풀이/제41회/제41회_정보통신개론_기출풀이.md")
    
    print("1. Parsing and preparing Markdown note...")
    if not md_path.exists():
        print(f"❌ Error: Source file not found at {md_path}")
        sys.exit(1)
        
    title, content, tags = parse_and_convert_markdown(md_path)
    print(f"   [OK] Parsed Title: {title}")
    print(f"   [OK] Parsed Tags: {tags}")
    print(f"   [OK] Processed Content Length: {len(content)} characters")

    # Validate config
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
        
        print("   Checking session or logging in...")
        context = await session_manager.get_or_create_session(browser, headless=headless)
        page = await context.new_page()
        
        # Verify active login session
        from naver_blog_mcp.automation.login import verify_login_session
        is_valid = await verify_login_session(page)
        if not is_valid:
            print("   [WARNING] Session invalid. Logging in...")
            await login_to_naver(
                page=page,
                user_id=config.NAVER_BLOG_ID,
                password=config.NAVER_BLOG_PASSWORD,
                storage_state_path="playwright-state/auth.json",
                headless=headless
            )
            
        print("\n3. Navigating to editor and writing post...")
        try:
            # 3.1 Write Title and Content
            await navigate_to_post_write_page(page, None)
            await fill_post_title(page, title)
            await fill_post_content(page, content, False)
            print("   [OK] Title and content typed.")
            await asyncio.sleep(2)

            # 3.2 Close any potential popup helpers (like the search overlay or help sidebar)
            await page.bring_to_front()
            await page.keyboard.press("Escape")
            await asyncio.sleep(1)
            
            help_close_selectors = [
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
                            print(f"   [OK] Closed popup/help using selector: {close_sel}")
                            await asyncio.sleep(0.5)
                except Exception:
                    pass
            
            # 3.3 Click the top-level main publish button (ignore iframe buttons)
            print("   Clicking top-level main publish button...")
            publish_btn = page.locator("button:has-text('발행')").first
            await publish_btn.click()
            await asyncio.sleep(2)
            
            # 3.4 Category Selection
            print("   Selecting category...")
            category_selectors = [
                ".blog2_series button",
                "button[class*='category']",
                "[class*='CategorySelect'] button",
                "button:has-text('카테고리')",
                ".blog2_series"
            ]
            
            category_selected = False
            for sel in category_selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.click()
                        await asyncio.sleep(1.0)
                        
                        # Find "정보통신" list item
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
            
            # 3.5 Tags insertion
            print("   Inserting tags...")
            tag_input = page.locator("input[placeholder*='태그'], .tag_input input, #tagInput").first
            if await tag_input.count() > 0:
                await tag_input.click()
                for tag in tags:
                    await tag_input.type(tag, delay=30)
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(0.3)
                print("   [OK] Tags set.")
            else:
                print("   [WARNING] Could not locate tag input field.")

            # 3.6 Click final Confirm Publish button inside the popup modal
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
                # JavaScript fallback click
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
                    print("   [OK] Confirm button clicked via JS fallback.")
                    clicked_final = True
                else:
                    print("   [ERROR] Could not find final publish button inside overlay.")
            
            # 3.7 Redirection wait
            if clicked_final:
                print("   Waiting for final post redirection...")
                await page.wait_for_url("**/blog.naver.com/*/**", timeout=20000)
                post_url = page.url
                
                print("\n" + "="*60)
                print("🎉 SUCCESS: Naver Blog Post Created successfully!")
                print(f"📌 Post Title: {title}")
                print(f"🔗 Post URL: {post_url}")
                print("="*60)
            else:
                print("❌ FAILED: Post confirmation failed.")
                await page.screenshot(path="playwright-state/posting_confirm_error.png")
                
        except Exception as e:
            print(f"❌ Exception occurred: {e}")
            try:
                os.makedirs("playwright-state", exist_ok=True)
                await page.screenshot(path="playwright-state/posting_error.png")
                print("   Error screenshot saved to playwright-state/posting_error.png")
            except Exception as se:
                print(f"   Could not save screenshot: {se}")
        finally:
            await context.close()
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
