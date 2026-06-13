"""
TTS Base - TTS引擎基类
"""

import logging
import typing
from abc import ABC, abstractmethod
from pathlib import Path


class TTSBase(ABC):
    """
    TTS 引擎基类

    所有 TTS 引擎必须继承此类并实现抽象方法。
    """

    def __init__(self):
        """初始化 TTS 引擎"""
        self._initialized = False
        self._logger = logging.getLogger(self.__class__.__name__)

    @property
    def is_initialized(self) -> bool:
        """是否已初始化"""
        return self._initialized

    @abstractmethod
    async def initialize(self) -> bool:
        """
        初始化 TTS 引擎

        Returns:
            bool: 初始化是否成功
        """
        ...

    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """
        合成语音

        Args:
            text: 要合成的文本

        Returns:
            bytes: 音频数据 (WAV 格式)
        """
        ...

    @abstractmethod
    async def synthesize_stream(self, text: str) -> typing.AsyncGenerator[bytes, None]:
        """
        流式合成语音

        Args:
            text: 要合成的文本

        Yields:
            bytes: 音频数据块
        """
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """
        关闭 TTS 引擎，释放资源
        """
        ...

    def validate_text(self, text: str) -> bool:
        """
        验证文本是否有效

        Args:
            text: 要验证的文本

        Returns:
            bool: 文本是否有效
        """
        if not text or not text.strip():
            return False

        # 检查文本长度（最大 1000 字符）
        if len(text) > 1000:
            self._logger.warning("文本过长: %s 字符，将被截断", len(text))
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
