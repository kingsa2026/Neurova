"""
Mock TTS - 简单模拟TTS引擎（用于测试）
当Edge TTS或MOSS-TTS不可用时，使用模拟引擎
"""

import asyncio
import math
import struct
import typing

from neurova.tts.base import TTSBase


class MockTTSSimple(TTSBase):
    """
    简单的模拟 TTS 引擎

    生成简单的正弦波音频数据，用于测试。
    """

    def __init__(self, sample_rate: int = 16000, frequency: float = 440.0):
        """
        初始化 MockTTS

        Args:
            sample_rate: 采样率
            frequency: 正弦波频率 (Hz)
        """
        super().__init__()
        self.sample_rate = sample_rate
        self.frequency = frequency
        self._duration_per_char = 0.1  # 每个字符 0.1 秒

    async def initialize(self) -> bool:
        """
        初始化 MockTTS

        Returns:
            bool: 总是返回 True
        """
        self._initialized = True
        self._logger.info("MockTTS 初始化完成")
        return True

    async def synthesize(self, text: str, **kwargs) -> bytes:
        """
        合成语音（生成正弦波）

        Args:
            text: 要合成的文本

        Returns:
            bytes: WAV 格式的音频数据
        """
        if not self.validate_text(text):
            return b""

        # 计算持续时间
        duration = len(text) * self._duration_per_char
        duration = max(0.5, min(duration, 10.0))  # 限制在 0.5-10 秒之间

        # 生成正弦波数据
        num_samples = int(self.sample_rate * duration)
        samples = []

        for i in range(num_samples):
            t = i / self.sample_rate
            # 生成正弦波，振幅为 0.3
            sample = 0.3 * math.sin(2 * math.pi * self.frequency * t)
            # 转换为 16 位整数
            sample_int = int(sample * 32767)
            samples.append(sample_int)

        # 转换为字节
        audio_data = b""
        for sample in samples:
            audio_data += struct.pack("<h", sample)

        # 生成 WAV 文件头
        wav_data = self._create_wav_header(len(audio_data)) + audio_data

        self._logger.info("MockTTS 合成完成: %.1f 字符, %s 秒", len(text), duration)
        return wav_data

    async def synthesize_stream(self, text: str) -> typing.AsyncGenerator[bytes, None]:
        """
        流式合成语音

        Args:
            text: 要合成的文本

        Yields:
            bytes: 音频数据块
        """
        if not self.validate_text(text):
            return

        # 分块生成音频
        chunk_size = 1024  # 每个 chunk 的采样数
        total_samples = int(self.sample_rate * len(text) * self._duration_per_char)
        total_samples = max(int(self.sample_rate * 0.5), min(total_samples, int(self.sample_rate * 10.0)))

        # 先生成 WAV 头
        audio_data_size = total_samples * 2  # 16 位采样
        wav_header = self._create_wav_header(audio_data_size)
        yield wav_header

        # 生成音频数据块
        for start in range(0, total_samples, chunk_size):
            end = min(start + chunk_size, total_samples)
            chunk_samples = []

            for i in range(start, end):
                t = i / self.sample_rate
                sample = 0.3 * math.sin(2 * math.pi * self.frequency * t)
                sample_int = int(sample * 32767)
                chunk_samples.append(sample_int)

            chunk_data = b""
            for sample in chunk_samples:
                chunk_data += struct.pack("<h", sample)

            yield chunk_data
            await asyncio.sleep(0.01)  # 模拟延迟

    def _create_wav_header(self, data_size: int) -> bytes:
        """
        创建 WAV 文件头

        Args:
            data_size: 音频数据大小（字节）

        Returns:
            bytes: WAV 文件头
        """
        # WAV 文件头结构
        header = bytearray()

        # RIFF 头
        header.extend(b"RIFF")
        header.extend(struct.pack("<I", 36 + data_size))  # 文件大小 - 8
        header.extend(b"WAVE")

        # fmt 子块
        header.extend(b"fmt ")
        header.extend(struct.pack("<I", 16))  # 子块大小
        header.extend(struct.pack("<H", 1))  # PCM 格式
        header.extend(struct.pack("<H", 1))  # 单声道
        header.extend(struct.pack("<I", self.sample_rate))  # 采样率
        header.extend(struct.pack("<I", self.sample_rate * 2))  # 字节率
        header.extend(struct.pack("<H", 2))  # 块对齐
        header.extend(struct.pack("<H", 16))  # 位深度

        # data 子块
        header.extend(b"data")
        header.extend(struct.pack("<I", data_size))  # 数据大小

        return bytes(header)

    async def shutdown(self) -> None:
        """
        关闭 MockTTS
        """
        self._initialized = False
        self._logger.info("MockTTS 已关闭")
