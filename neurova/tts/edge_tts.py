"""
Edge TTS - 微软Edge TTS引擎（免费，中文效果好）

无需GPU，CPU即可运行，支持多种中文音色
"""

import re
import typing

from neurova.tts.base import TTSBase

# 单次请求 Edge 服务的文本块上限（字符）：超长按句切块逐段合成再拼接。
# edge 服务对超长文本有隐性失败率，分块同时让失败只损失单段。
EDGE_MAX_CHUNK_CHARS = 1800

# 句末标点（切块边界）
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？!?；;\n])")


def split_text_for_tts(text: str, max_len: int = EDGE_MAX_CHUNK_CHARS) -> typing.List[str]:
    """按句边界把文本切成 ≤max_len 的块（单句超长时保句完整硬切）。

    字数上限取消后由引擎内部切块：块边界永远落在句末标点之后，
    不把句子拦腰截断；单句超过 max_len 时按 max_len 硬切（罕见）。
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    sentences = [s for s in _SENTENCE_BOUNDARY_RE.split(text) if s]
    chunks: typing.List[str] = []
    current = ""
    for sentence in sentences:
        # 单句超限：先冲掉当前块，再把长句硬切
        if len(sentence) > max_len:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(sentence), max_len):
                piece = sentence[i : i + max_len]
                if i + max_len < len(sentence):
                    chunks.append(piece)
                else:
                    current = piece
            continue
        if len(current) + len(sentence) > max_len and current:
            chunks.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        chunks.append(current)
    return chunks


class EdgeTTS(TTSBase):

    # edge-tts Communicate.stream() 的 audio chunk 是 MP3 裸字节
    audio_media_type = "audio/mpeg"
    """
    微软 Edge TTS 引擎

    使用 edge-tts 库，免费且中文效果好。
    """

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural", rate: str = "+0%", volume: str = "+0%"):
        """
        初始化 EdgeTTS

        Args:
            voice: 音色名称
            rate: 语速调整
            volume: 音量调整
        """
        super().__init__()
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self._communicate = None

    async def initialize(self) -> bool:
        """
        初始化 EdgeTTS

        Returns:
            bool: 初始化是否成功
        """
        try:
            # 检查 edge_tts 是否可用
            import edge_tts

            self._edge_tts = edge_tts
            self._initialized = True
            self._logger.info("EdgeTTS 初始化完成，音色: %s", self.voice)
            return True
        except ImportError as e:
            self._logger.error("EdgeTTS 初始化失败: %s", e)
            return False

    async def _communicate_audio(self, text: str) -> bytes:
        """单段文本合成（Communicate.stream audio chunk 拼接）。"""
        communicate = self._edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            volume=self.volume,
        )
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return audio_data

    async def synthesize(self, text: str, **kwargs) -> bytes:
        """
        合成语音（长文本按句切块逐段合成、MP3 字节按序拼接）

        Args:
            text: 要合成的文本

        Returns:
            bytes: MP3 格式的音频数据
        """
        if not self._initialized:
            self._logger.error("EdgeTTS 未初始化")
            return b""

        if not self.validate_text(text):
            return b""
        text = self.sanitize_text(text)

        try:
            chunks = split_text_for_tts(text)
            audio_data = b""
            for i, chunk in enumerate(chunks):
                try:
                    audio_data += await self._communicate_audio(chunk)
                except Exception as e:
                    # 单段失败跳过，不拖垮整篇（长文切换比整体失败好）
                    self._logger.warning("EdgeTTS 第 %d/%d 段合成失败: %s", i + 1, len(chunks), e)

            self._logger.info("EdgeTTS 合成完成: %s 字符 %d 块, %s 字节", len(text), len(chunks), len(audio_data))
            return audio_data

        except Exception as e:
            self._logger.error("EdgeTTS 合成失败: %s", e)
            return b""

    async def synthesize_stream(self, text: str) -> typing.AsyncGenerator[bytes, None]:
        """
        流式合成语音（长文本按句切块，逐段流式下发）

        Args:
            text: 要合成的文本

        Yields:
            bytes: 音频数据块
        """
        if not self._initialized:
            self._logger.error("EdgeTTS 未初始化")
            return

        if not self.validate_text(text):
            return
        text = self.sanitize_text(text)

        try:
            for chunk_text in split_text_for_tts(text):
                # 创建 Communicate 对象
                communicate = self._edge_tts.Communicate(
                    text=chunk_text,
                    voice=self.voice,
                    rate=self.rate,
                    volume=self.volume,
                )

                # 流式合成音频
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        yield chunk["data"]

        except Exception as e:
            self._logger.error("EdgeTTS 流式合成失败: %s", e)

    async def list_voices(self) -> typing.List[typing.Dict[str, str]]:
        """
        列出可用音色

        Returns:
            List[Dict[str, str]]: 音色列表
        """
        if not self._initialized:
            return []

        try:
            voices = await self._edge_tts.list_voices()
            return voices
        except Exception as e:
            self._logger.error("获取音色列表失败: %s", e)
            return []

    async def shutdown(self) -> None:
        """
        关闭 EdgeTTS
        """
        self._initialized = False
        self._logger.info("EdgeTTS 已关闭")
