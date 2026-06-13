"""
ASR Base - ASR引擎基类

所有ASR引擎必须继承此类并实现抽象方法。
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict


class ASRBase(ABC):
    """
    ASR引擎基类

    支持语音识别（transcribe）、音频理解（understand）、音频描述（caption）。
    """

    def __init__(self):
        """初始化ASR引擎"""
        self._initialized = False
        self._logger = logging.getLogger(self.__class__.__name__)

    @property
    def is_initialized(self) -> bool:
        """是否已初始化"""
        return self._initialized

    @abstractmethod
    async def initialize(self) -> bool:
        """
        初始化ASR引擎

        Returns:
            bool: 初始化是否成功
        """
        ...

    @abstractmethod
    async def transcribe(
        self,
        audio_bytes: bytes,
        language: str = "zh",
    ) -> Dict[str, Any]:
        """
        语音识别（ASR）

        Args:
            audio_bytes: 音频字节数据
            language: 目标语言 (zh / en / auto)

        Returns:
            dict: {"text": "识别结果", "language": "zh", "duration_sec": float}
        """
        ...

    async def understand(
        self,
        audio_bytes: bytes,
        query: str = "这段音频说了什么？",
    ) -> Dict[str, Any]:
        """
         音频理解 + 问答

         默认实现：先转写，再用LLM处理查询。
        子类可以覆盖此方法提供原生理解能力。

         Args:
             audio_bytes: 音频字节数据
             query: 关于音频的问题

         Returns:
             dict: {"answer": "...", "duration_sec": float}
        """
        # 默认实现：转写后返回文本
        result = await self.transcribe(audio_bytes)
        if "error" in result:
            return {"answer": "", "error": result["error"]}

        return {
            "answer": result.get("text", ""),
            "duration_sec": result.get("duration_sec", 0.0),
            "language": result.get("language", "zh"),
        }

    async def caption(self, audio_bytes: bytes) -> Dict[str, Any]:
        """
        音频描述

        默认实现：转写后返回文本。
        子类可以覆盖此方法提供详细描述。

        Args:
            audio_bytes: 音频字节数据

        Returns:
            dict: {"caption": "音频描述", "duration_sec": float}
        """
        result = await self.transcribe(audio_bytes)
        if "error" in result:
            return {"caption": "", "error": result["error"]}

        return {
            "caption": result.get("text", ""),
            "duration_sec": result.get("duration_sec", 0.0),
        }

    @abstractmethod
    async def shutdown(self) -> None:
        """
        关闭ASR引擎，释放资源
        """
        ...

    def validate_audio(self, audio_bytes: bytes) -> bool:
        """
        验证音频数据是否有效

        Args:
            audio_bytes: 音频数据

        Returns:
            bool: 音频是否有效
        """
        if not audio_bytes or len(audio_bytes) == 0:
            return False

        # 检查音频大小（最大 100MB）
        max_size = 100 * 1024 * 1024
        if len(audio_bytes) > max_size:
            self._logger.warning("音频过大: %s 字节，超过 %s 字节限制", len(audio_bytes), max_size)
            return False

        return True

    async def save_audio(self, audio_data: bytes, output_path: Path) -> bool:
        """
        保存音频数据到文件

        Args:
            audio_data: 音频数据
            output_path: 输出文件路径

        Returns:
            bool: 保存是否成功
        """
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(audio_data)
            self._logger.info("音频已保存: %s", output_path)
            return True
        except Exception as e:
            self._logger.error("保存音频失败: %s", e)
            return False
