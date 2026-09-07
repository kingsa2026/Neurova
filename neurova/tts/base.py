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
        # 字数上限已取消（2026-09-07）：长文本由引擎内部分句切块合成。
        # 保留属性供引擎自行声明内部块大小（如 moss 的 token 预算）。
        self.max_text_length: int | None = None

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
        """清洗文本：剥离控制字符（\r 归一 \n），**不截断**。

        字数上限已取消（2026-09-07 用户要求不限字数）：长文本由引擎
        内部按句切块合成——moss-nano 75 token/块流水线、edge-tts 分句
        拼接。此前的截断/整体拒绝都曾把长回复变成静默丢字。
        """
        text = (text or "").replace("\r", "\n")
        return "".join(ch for ch in text if ch == "\n" or ch == "\t" or not (ord(ch) < 32 or ord(ch) == 127))

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
