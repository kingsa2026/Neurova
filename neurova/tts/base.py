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

    # 流式输出的 MIME 类型（补课 4.3：edge-tts 产 MP3 裸字节，
    # moss/sapi5 产 wav——端点按引擎动态声明，原实现恒 audio/wav 是 bug）
    audio_media_type: str = "audio/wav"

    def __init__(self):
        """初始化 TTS 引擎"""
        self._initialized = False
        self._logger = logging.getLogger(self.__class__.__name__)
        # 单次合成文本上限(edge-tts 可处理 ~3000 字; 原 1000 过保守,
        # 且超限会被 validate_text 整体拒绝而非截断 → 长回复 TTS 500 根因)
        self.max_text_length = 2000

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
    async def synthesize(self, text: str, **kwargs) -> bytes:
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

    def sanitize_text(self, text: str) -> str:
        """清洗/截断文本: 超限**真正截断**(整体拒绝曾导致长回复 TTS 500),
        并剥离控制字符(换行保留)。"""
        text = (text or "").replace("\r", "\n")
        text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or not (ord(ch) < 32 or ord(ch) == 127))
        if len(text) > self.max_text_length:
            self._logger.warning(
                "文本过长: %s 字符，截断到 %s", len(text), self.max_text_length
            )
            return text[: self.max_text_length]
        return text

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
