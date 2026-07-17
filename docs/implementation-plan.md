# 네이버 블로그 MCP 서버 구현 계획서 (Playwright 기반)

## 1. 프로젝트 개요

### 1.1 목표
Playwright 웹 브라우저 자동화를 활용하여 Model Context Protocol(MCP) 서버를 구현하고, AI 어시스턴트가 네이버 블로그에 글을 작성할 수 있도록 지원합니다.

### 1.2 핵심 요구사항
- ✅ 네이버 블로그에 글 작성 (제목, 내용, 카테고리, 태그)
- ✅ 작성된 글 수정
- ✅ 작성된 글 삭제
- ✅ 카테고리 목록 조회
- ✅ 최근 글 목록 조회
- ✅ 이미지 업로드 및 본문 삽입
- ✅ MCP 프로토콜 표준 준수
- ✅ 세션 관리 (로그인 상태 유지)

### 1.3 개발 기간
- **Phase 1 (Week 1-2)**: Playwright 기본 자동화 + 핵심 기능 구현
- **Phase 2 (Week 3)**: 고급 기능 및 안정성 개선
- **Phase 3 (Week 4)**: 테스트, 문서화, 배포

### 1.4 기술 선택 근거: Playwright vs Selenium

| 항목 | Playwright | Selenium |
|------|-----------|----------|
| 성능 | ✅ 30% 더 빠름 | ❌ 느림 |
| 자동 대기 | ✅ 내장 | ❌ 수동 설정 |
| MCP 호환성 | ✅ 비동기 네이티브 | ⚠️ 제한적 |
| 디버깅 | ✅ Inspector/Trace Viewer | ❌ 기본적 |

**결론**: Playwright 선택

---

## 2. 기술 스택

```yaml
언어: Python 3.13

핵심 라이브러리:
  - mcp[cli] >= 1.20.0
  - playwright >= 1.40.0
  - pydantic >= 2.5.0
  - python-dotenv >= 1.0.0
  - tenacity >= 8.2.0
  - aiofiles >= 23.0.0

패키지 관리: uv
```

---

## 3. 구현 단계별 계획

### Phase 1: Playwright 기본 자동화 + 핵심 기능 (Week 1-2)

#### Day 1: 프로젝트 초기 설정
- pyproject.toml 업데이트
- Playwright 설치 및 브라우저 다운로드
- 프로젝트 구조 생성
- 환경 변수 설정

#### Day 2: 로그인 자동화
```python
async def login_to_naver(page, user_id, password):
    await page.goto("https://nid.naver.com/nidlogin.login")
    await page.fill("#id", user_id)
    await page.fill("#pw", password)
    await page.click(".btn_login")
    await page.wait_for_url("**/naver.com**", timeout=10000)
    storage_state = await page.context.storage_state(
        path="playwright-state/auth.json"
    )
    return storage_state
```

#### Day 3: 글쓰기 페이지 자동화
- 글쓰기 페이지 네비게이션
- 제목/내용 입력 자동화
- iframe 처리 (스마트에디터)
- 발행 버튼 클릭

#### Day 5: MCP 서버 구조 설정
- NaverBlogMCPServer 클래스
- Playwright 브라우저 생명주기 관리
- 세션 관리자 통합

#### Day 6: 핵심 Tool 구현
- `naver_blog_create_post`
- `naver_blog_delete_post`
- `naver_blog_list_categories`

#### Day 8-10: 에러 처리 및 재시도 로직
- 커스텀 예외 클래스 (`NaverBlogError` 계층)
- tenacity 기반 지수 백오프 재시도 (2s → 4s → 8s)
- Playwright Trace Manager
- 대체 셀렉터 자동 전환 (`selector_helper.py`)

### Phase 2: 고급 기능 및 안정성 개선 (Week 3)

#### Day 11-12: 이미지 업로드
```python
async def upload_image(page, image_path):
    iframe_element = await page.wait_for_selector("iframe#mainFrame")
    main_frame = await iframe_element.content_frame()
    
    photo_button = main_frame.locator("button[data-name='image']")
    await photo_button.click()
    
    file_input = main_frame.locator("input[type='file']#hidden-file")
    await file_input.set_input_files(image_path)
```

지원 포맷: JPG, PNG, GIF, BMP, HEIC, HEIF, WebP
파일 크기 제한: 10MB

#### Day 13-14: Markdown 지원 (구현 불가)
- 네이버 블로그는 Markdown을 지원하지 않음
- 스마트에디터 ONE으로 통합되면서 HTML 편집 모드 제거됨

#### Day 15: 세션 관리 개선
- 24시간 자동 세션 갱신
- 세션 유효성 실시간 확인

### Phase 3: 테스트, 문서화, 배포 (Week 4)

#### 종합 테스트
```bash
uv run pytest tests/ -v
```

#### Claude Desktop 통합 테스트
```json
{
  "mcpServers": {
    "naver-blog": {
      "command": "uv",
      "args": ["--directory", "C:/workdir/naver-blog-mcp", "run", "naver-blog-mcp"],
      "env": {
        "NAVER_BLOG_ID": "your_id",
        "NAVER_BLOG_PASSWORD": "your_password",
        "HEADLESS": "true"
      }
    }
  }
}
```

---

## 4. 구현 우선순위

### 높음 (Must Have) - Week 1-2
1. ✅ Playwright 로그인 자동화
2. ✅ 세션 저장/복원
3. ✅ 글 작성 (제목, 내용)
4. ✅ MCP Tool 등록
5. ✅ 기본 에러 처리

### 중간 (Should Have) - Week 3
1. ✅ 이미지 업로드
2. ✅ 카테고리/태그
3. ✅ 재시도 로직
4. ✅ 자동화 감지 우회

### 낮음 (Nice to Have)
1. ⬜ 임시저장
2. ⬜ 예약 발행 (cron)
3. ⬜ 통계 조회
4. ⬜ 멀티 계정

---

## 5. 리스크 관리

### R1: 네이버 UI 변경
- **확률**: 높음 / **영향**: 높음
- **대응**: 셀렉터 중앙 관리, 대체 셀렉터 정의

### R2: CAPTCHA 발생
- **확률**: 중간 / **영향**: 높음
- **대응**: Stealth 모드 활성화, 적절한 딜레이

---

## 6. 성공 지표

- ✅ 모든 필수 Tool 구현 완료
- ✅ 네이버 블로그에 실제 포스팅 성공
- ✅ 테스트 커버리지 > 80%
- ✅ 글 작성 성공률 > 95%
- ✅ 세션 24시간 유지
