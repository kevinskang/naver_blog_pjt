import asyncio
import sys
import os
import json
from pathlib import Path
from playwright.async_api import async_playwright

# 프로젝트 src 경로 추가
sys.path.insert(0, str(Path("/home/testudo/one/02.workspace/mcp_pjt/naver-blog-mcp/src")))

from naver_blog_mcp.config import config
from naver_blog_mcp.services.session_manager import SessionManager
from naver_blog_mcp.automation.post_actions import navigate_to_post_write_page
from naver_blog_mcp.automation.selectors import POST_WRITE_TITLE
from naver_blog_mcp.utils.selector_helper import dismiss_overlays

async def check_selector(page_or_frame, selector: str, name: str, timeout: int = 5000) -> bool:
    """특정 셀렉터의 생존 여부를 검증합니다."""
    try:
        locator = page_or_frame.locator(selector).first
        await locator.wait_for(state="attached", timeout=timeout)
        count = await locator.count()
        if count > 0:
            print(f"  [PASS] {name} ('{selector}') 발견 완료 (개수: {count})")
            return True
        else:
            print(f"  [FAIL] {name} ('{selector}') 미발견")
            return False
    except Exception as e:
        print(f"  [FAIL] {name} ('{selector}') 에러 발생: {e}")
        return False

async def main():
    try:
        config.validate()
    except Exception as e:
        print(f"[ERROR] 설정 유효성 검사 실패: {e}")
        sys.exit(1)

    print("=== 네이버 블로그 에디터 셀렉터 헬스체크 시작 ===")
    
    success = True
    report = {}

    async with async_playwright() as p:
        from naver_blog_mcp.config import get_browser_config
        browser = await p.chromium.launch(**get_browser_config())
        
        session_manager = SessionManager(
            user_id=config.NAVER_BLOG_ID,
            password=config.NAVER_BLOG_PASSWORD,
        )

        print("[1] 세션 복원 시도 중...")
        context = await session_manager.get_or_create_session(
            browser, headless=config.HEADLESS
        )

        page = await context.new_page()
        
        print("[2] 글쓰기 페이지 진입 시도...")
        try:
            await navigate_to_post_write_page(page, timeout=15000)
            print("  [PASS] 글쓰기 페이지 진입 성공")
            report["write_page_navigation"] = "PASS"
        except Exception as e:
            print(f"  [FAIL] 글쓰기 페이지 진입 실패: {e}")
            report["write_page_navigation"] = f"FAIL: {e}"
            await context.close()
            await browser.close()
            sys.exit(1)

        # iframe 프레임 확인
        main_frame = None
        try:
            iframe_element = await page.wait_for_selector("iframe#mainFrame", timeout=5000)
            if iframe_element:
                main_frame = await iframe_element.content_frame()
                print("  [PASS] iframe#mainFrame 로드 완료")
                report["main_frame_load"] = "PASS"
        except Exception as e:
            print(f"  [FAIL] iframe#mainFrame 로드 실패: {e}")
            report["main_frame_load"] = f"FAIL: {e}"
            success = False

        if main_frame:
            # 진입 후 도움말 팝업들 닫기 수행
            await dismiss_overlays(page)
            await dismiss_overlays(main_frame)
            await asyncio.sleep(1)

            # 1. 제목 입력 필드 검증 (상위 페이지 또는 iframe 내부)
            title_sel_list = POST_WRITE_TITLE if isinstance(POST_WRITE_TITLE, list) else [POST_WRITE_TITLE]
            title_found = False
            for t_sel in title_sel_list:
                if await check_selector(main_frame, t_sel, "제목 입력창(iframe)", timeout=3000):
                    title_found = True
                    report["title_input"] = "PASS"
                    break
            if not title_found:
                # 메인 페이지에서도 찾아봄
                for t_sel in title_sel_list:
                    if await check_selector(page, t_sel, "제목 입력창(page)", timeout=2000):
                        title_found = True
                        report["title_input"] = "PASS"
                        break
            if not title_found:
                print("  [FAIL] 제목 입력창 셀렉터 전부 실패")
                report["title_input"] = "FAIL"
                success = False

            # 2. 본문 입력 필드 검증
            body_sel = ".se-component.se-text .se-text-paragraph"
            if await check_selector(main_frame, body_sel, "본문 입력 영역", timeout=3000):
                report["body_input"] = "PASS"
            else:
                report["body_input"] = "FAIL"
                success = False

            # 3. 임시저장 버튼 검증
            save_btn_sel = "button.save_count_btn__ZTLNa"
            if await check_selector(main_frame, save_btn_sel, "임시저장 카운트 버튼", timeout=3000):
                report["draft_list_button"] = "PASS"
            else:
                report["draft_list_button"] = "FAIL"
                success = False

            # 4. 발행(등록) 버튼 검증
            publish_found = False
            for txt in ["발행", "글쓰기", "등록"]:
                sel = f"button:has-text('{txt}'):visible"
                # 프레임 내부 조사
                if await check_selector(main_frame, sel, f"발행 버튼 (텍스트 '{txt}' - frame)", timeout=2000):
                    publish_found = True
                    report["publish_button"] = "PASS"
                    break
                # 메인 페이지 조사
                if await check_selector(page, sel, f"발행 버튼 (텍스트 '{txt}' - page)", timeout=2000):
                    publish_found = True
                    report["publish_button"] = "PASS"
                    break
            if not publish_found:
                report["publish_button"] = "FAIL"
                success = False

            # 5. 발행 버튼 클릭 후 팝업 내부 요소 검증을 위한 클릭 시도
            if publish_found:
                print("[3] 발행 설정 팝업 트리거 중...")
                popup_triggered = False
                for txt in ["발행", "글쓰기", "등록"]:
                    try:
                        # frame 또는 page에서 보이는 버튼 클릭
                        for page_or_frame in [main_frame, page]:
                            sel = f"button:has-text('{txt}'):visible"
                            if await page_or_frame.locator(sel).count() > 0:
                                await page_or_frame.locator(sel).first.click(timeout=3000)
                                await asyncio.sleep(2.0) # 팝업 뜨는 시간 넉넉히 대기
                                popup_triggered = True
                                break
                        if popup_triggered:
                            break
                    except Exception:
                        continue
                
                if popup_triggered:
                    # 6. 태그 입력 필드 검증
                    tag_sel = "input#tag-input"
                    if await check_selector(main_frame, tag_sel, "태그 입력창(input#tag-input)", timeout=4000):
                        report["tag_input"] = "PASS"
                    else:
                        report["tag_input"] = "FAIL"
                        success = False
                else:
                    print("  [FAIL] 발행 설정 팝업을 열지 못해 태그 입력창 검증 스킵")
                    report["tag_input"] = "SKIPPED_POPUP_FAILED"
                    success = False
            else:
                report["tag_input"] = "SKIPPED_NO_PUBLISH_BTN"

        await context.close()
        await browser.close()

    # 헬스체크 리포트 파일 쓰기
    report_dir = Path("/home/testudo/one/02.workspace/mcp_pjt/naver-blog-mcp/playwright-state")
    os.makedirs(report_dir, exist_ok=True)
    report_path = report_dir / "selector_health.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n[결과] 헬스체크 리포트 저장 완료: {report_path}")

    if success:
        print("\n=== 모든 핵심 셀렉터 헬스체크 통과! ===")
        sys.exit(0)
    else:
        print("\n=== [경고] 일부 핵심 셀렉터가 깨졌거나 감지되지 않았습니다. ===")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
