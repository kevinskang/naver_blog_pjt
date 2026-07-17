---
name: blog-automation-dev
description: "네이버 블로그의 Playwright 브라우저 자동화 스크립트 작성 및 셀렉터 유지보수를 수행합니다. 스마트에디터 ONE iframe 처리, 로그인 세션 관리, CAPTCHA 대응, selectors.py 업데이트 작업을 할 때 이 스킬을 참조하십시오."
---

# Blog Automation Development — Playwright 자동화 스킬

이 스킬은 네이버 블로그 스마트에디터 ONE 및 로그인 페이지를 안정적으로 제어하기 위한 Playwright 코딩 지침을 정의합니다.

## 1. 스마트에디터 ONE iframe 및 도움말 팝업 제어
네이버 블로그 에디터 영역은 `iframe#mainFrame` 내부에서 동작하므로, 페이지 로드 후 즉시 iframe 컨텍스트를 획득해야 합니다. 또한, 글쓰기 진입 시 화면을 가리는 도움말 팝업을 사전에 닫아주어야 상호작용 실패가 발생하지 않습니다.

```python
async def get_editor_frame(page: Page) -> Frame:
    # mainFrame iframe이 나타날 때까지 대기
    iframe_element = await page.wait_for_selector("iframe#mainFrame")
    frame = await iframe_element.content_frame()
    if not frame:
        raise ElementNotFoundError("SmartEditor ONE iframe content_frame not found")
        
    # 도움말 팝업이 있는지 확인하고 닫기 버튼 클릭
    help_close_btn = frame.locator(".se-help-close-btn")
    if await help_close_btn.is_visible():
        await help_close_btn.click()
        
    return frame
```

## 2. 제목 및 본문 입력 자동화 규칙
- **제목 입력**: 제목 영역은 단순 셀렉터 포커스 지정이 오작동하기 쉽습니다. 좌표 클릭(`page.mouse.click(450, 250)`) 방식을 최우선 순위 헬퍼로 사용하고, 실패 시 Tab 네비게이션을 수행하십시오.
- **본문 입력**: iframe 컨텍스트 내의 `contenteditable` 영역에 직접 포커스를 주고 `type()` 또는 `fill()`을 수행해야 합니다.

```python
# 제목 입력 예시
await page.mouse.click(450, 250) # 에디터 제목 영역 대략적 위치 클릭
await page.keyboard.type(title)

# 본문 입력 예시 (iframe 내부)
editor_area = frame.locator(".se-component-content")
await editor_area.first.click()
await page.keyboard.type(content)
```

## 3. 세션 저장 및 우회 전략
- 네이버 자동 로그인은 24시간 동안 유효한 `storage_state` JSON 파일(`playwright-state/auth.json`)을 재사용합니다.
- 브라우저 초기화 시 `stealth` 자바스크립트를 세션에 주입하여 자동화 도구(`navigator.webdriver`) 감지를 방지해야 합니다.

```python
# session_manager.py 구조 예시
context = await browser.new_context(
    storage_state="playwright-state/auth.json" if os.path.exists("playwright-state/auth.json") else None,
    viewport={"width": 1280, "height": 800}
)
# stealth 스크립트 등록
await context.add_init_script(
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
)
```

## 4. 셀렉터 변경 및 대체(Fallback) 처리
- 네이버는 정기적으로 클래스명이나 ID를 변경합니다. `selectors.py`에 정의된 대체 리스트를 이용해 여러 셀렉터를 순차 시도하는 `selector_helper.py` 모듈을 연동하십시오.
- `click_with_alternatives` 및 `fill_with_alternatives` 헬퍼 함수를 사용하여 요소 탐색 복원력을 확보하십시오.
