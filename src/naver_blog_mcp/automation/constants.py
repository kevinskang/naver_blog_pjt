"""자동화 계층 공용 상수 (타임아웃·크기 제한).

의미가 분명하고 여러 곳에서 반복되는 매직 넘버만 중앙화한다.
국소적 pacing 용도의 ``asyncio.sleep`` 값은 의미가 지역적이므로
각 호출부에 그대로 둔다(별도 조건부 대기 전환은 후속 과제).
"""

# 업로드 이미지 최대 크기 (바이트) — 네이버 제한 10MB
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024

# iframe#mainFrame(스마트에디터 ONE) 등 에디터 프레임 대기 타임아웃 (ms)
IFRAME_WAIT_MS = 10000

# 페이지 네비게이션(goto/wait_for_url) 타임아웃 (ms)
PAGE_NAV_TIMEOUT_MS = 15000

# 이미지 업로드 완료 대기 타임아웃 (ms)
UPLOAD_COMPLETE_TIMEOUT_MS = 10000
