"""Playwright Trace 관리 유틸리티."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import BrowserContext

logger = logging.getLogger(__name__)


class TraceManager:
    """Playwright Trace 녹화 및 관리."""

    def __init__(self, traces_dir: str = "playwright-state/traces"):
        """
        TraceManager 초기화.

        Args:
            traces_dir: Trace 파일 저장 디렉토리
        """
        self.traces_dir = Path(traces_dir)
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        # context별 진행 중인 trace 이름을 관리합니다 (멀티 계정/동시 호출 안전).
        self._active_traces: dict[int, str] = {}

    async def start_trace(
        self,
        context: BrowserContext,
        name: str = "trace",
        screenshots: bool = True,
        snapshots: bool = True,
        sources: bool = True,
    ) -> None:
        """
        Trace 녹화를 시작합니다.

        Args:
            context: BrowserContext 객체
            name: Trace 이름
            screenshots: 스크린샷 포함 여부
            snapshots: DOM 스냅샷 포함 여부
            sources: 소스 코드 포함 여부
        """
        if id(context) in self._active_traces:
            logger.warning("Trace is already running for this context")
            return

        try:
            await context.tracing.start(
                screenshots=screenshots,
                snapshots=snapshots,
                sources=sources,
            )
            self._active_traces[id(context)] = name
            logger.info(f"Started trace: {name}")
        except Exception as e:
            logger.error(f"Failed to start trace: {e}")

    async def stop_trace(
        self,
        context: BrowserContext,
        success: bool = True,
    ) -> Optional[str]:
        """
        Trace 녹화를 중지하고 저장합니다.

        Args:
            context: BrowserContext 객체
            success: 작업 성공 여부 (실패 시 파일명에 'error' 추가)

        Returns:
            저장된 Trace 파일 경로
        """
        trace_name = self._active_traces.get(id(context))
        if trace_name is None:
            logger.warning("No trace is running for this context")
            return None

        try:
            # 파일명 생성
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            status = "success" if success else "error"
            filename = f"{trace_name}_{status}_{timestamp}.zip"
            filepath = self.traces_dir / filename

            # Trace 저장
            await context.tracing.stop(path=str(filepath))

            logger.info(f"Trace saved: {filepath}")
            logger.info(f"View trace: playwright show-trace {filepath}")

            return str(filepath)
        except Exception as e:
            logger.error(f"Failed to stop trace: {e}")
            return None
        finally:
            self._active_traces.pop(id(context), None)

    async def trace_action(
        self,
        context: BrowserContext,
        action_name: str,
        action_func,
        *args,
        **kwargs,
    ):
        """
        특정 작업을 Trace와 함께 실행합니다.

        Args:
            context: BrowserContext 객체
            action_name: 작업 이름
            action_func: 실행할 비동기 함수
            *args: 함수 인자
            **kwargs: 함수 키워드 인자

        Returns:
            함수 실행 결과

        Example:
            result = await trace_manager.trace_action(
                context,
                "create_post",
                handle_create_post,
                page,
                title="테스트",
                content="내용"
            )
        """
        await self.start_trace(context, action_name)
        success = True

        try:
            result = await action_func(*args, **kwargs)
            return result
        except Exception as e:
            success = False
            raise e
        finally:
            await self.stop_trace(context, success=success)


# 전역 TraceManager 인스턴스
trace_manager = TraceManager()
