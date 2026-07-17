---
name: mcp-server-dev
description: "Model Context Protocol(MCP) SDK 연동, Tool 등록, JSON Schema 명세 및 환경 변수 연동 작업을 수행합니다. server.py, tools.py, config.py를 개발하고 수정할 때 이 스킬을 활용하십시오."
---

# MCP Server Development — MCP 서버 및 인터페이스 연동 스킬

이 스킬은 네이버 블로그 MCP 서버의 구성, 도구 스키마 검증 및 예외 핸들러 연동에 대한 지침을 제공합니다.

## 1. MCP Tool 등록 및 메타데이터 정의
- 모든 MCP 도구는 `mcp/tools.py` 내의 `TOOLS_METADATA` 딕셔너리에 명세하고, `inputSchema`는 camelCase 표기법을 준수합니다.
- LLM이 올바른 파라미터 구조를 채울 수 있도록 상세한 묘사(`description`)를 스키마에 포함해야 합니다.

```python
# tools.py 구조 예시
TOOLS_METADATA = {
    "naver_blog_create_post": {
        "name": "naver_blog_create_post",
        "description": "네이버 블로그에 새로운 글을 작성하고 발행합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "글 제목"},
                "content": {"type": "string", "description": "본문 내용"},
                "category": {"type": "string", "description": "발행할 카테고리 명"},
                "images": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "업로드할 로컬 이미지 파일 경로 또는 Base64 문자열 배열"
                }
            },
            "required": ["title", "content"]
        }
    }
}
```

## 2. Server API 라우팅 및 Page 주입
- `server.py`는 `FastMCP` 또는 `Server` 인스턴스를 초기화하고, 각 Tool 이름에 해당하는 데코레이터를 바인딩합니다.
- 세션 관리 및 브라우저 컨텍스트(`Page`) 획득 함수(`get_page()`)를 호출하여 각 도구 실행에 알맞은 브라우저 페이지를 제공합니다.

```python
# server.py 구조 예시
@self.server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    # 세션 확보 및 페이지 획득
    page = await self.get_page()
    
    if name == "naver_blog_create_post":
        result = await handle_create_post(page, arguments)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
```

## 3. 예외 마스킹 및 에러 처리
- 도구 실행 도중 에러가 발생하면 raw 트레이스백이 Claude 클라이언트에 무작위로 출력되지 않도록 마스킹하고 정제된 에러 피드백을 전달하십시오.
- 모든 비즈니스 로직 및 에러 처리 과정은 `logger.error` 및 `logger.info`를 이용해 서버의 표준 에러(stderr) 혹은 로그 파일에 안전하게 분리하여 기록하십시오.
