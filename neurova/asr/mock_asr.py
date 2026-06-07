"""
Mock ASR Engine - 模拟 ASR 引擎

用于测试和开发的模拟 ASR 引擎。
"""

import logging
import time
from typing import Dict, Any

from neurova.asr.base import ASRBase

logger = logging.getLogger(__name__)


class MockASREngine(ASRBase):
    """
    Mock ASR 引擎

    用于测试和开发，返回模拟的识别结果。
    """

    def __init__(self, transcribe_text: str = "模拟识别结果", fail: bool = False):
        super().__init__()
        self._transcribe_text = transcribe_text
        self._fail = fail
        self._initialized = False
        self._total_requests = 0

    async def initialize(self) -> bool:
        if self._fail:
            return False
        self._initialized = True
        return True

    async def transcribe(
        self,
        audio_bytes: bytes,
        language: str = "zh",
    ) -> Dict[str, Any]:
        if not self._initialized:
            return {"text": "", "error": "MockASR 未初始化"}

        self._total_requests += 1

        # 模拟处理延迟
        await asyncio_sleep(0.01)

        return {
            "text": self._transcribe_text,
            "language": language,
            "duration_sec": round(len(audio_bytes) / 16000, 2) if audio_bytes else 0.0,
        }

    async def shutdown(self) -> None:
        self._initialized = False


# 异步 sleep（避免在同步上下文中使用 asyncio.sleep）
async def asyncio_sleep(seconds: float):
    import asyncio
    await asyncio.sleep(seconds)