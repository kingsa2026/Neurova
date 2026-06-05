"""
Edge TTS - 微软Edge TTS引擎（免费，中文效果好）

无需GPU，CPU即可运行，支持多种中文音色
"""

import asyncio
import io
import logging
from pathlib import Path
import typing

from neurova.tts.base import TTSBase


class EdgeTTS(TTSBase):
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
            self._logger.info(f"EdgeTTS 初始化完成，音色: {self.voice}")
            return True
        except ImportError as e:
            self._logger.error(f"EdgeTTS 初始化失败: {e}")
            return False
    
    async def synthesize(self, text: str) -> bytes:
        """
        合成语音
        
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
        
        try:
            # 创建 Communicate 对象
            communicate = self._edge_tts.Communicate(
                text=text,
                voice=self.voice,
                rate=self.rate,
                volume=self.volume,
            )
            
            # 合成音频
            audio_data = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data += chunk["data"]
            
            self._logger.info(f"EdgeTTS 合成完成: {len(text)} 字符, {len(audio_data)} 字节")
            return audio_data
            
        except Exception as e:
            self._logger.error(f"EdgeTTS 合成失败: {e}")
            return b""
    
    async def synthesize_stream(self, text: str) -> typing.AsyncGenerator[bytes, None]:
        """
        流式合成语音
        
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
        
        try:
            # 创建 Communicate 对象
            communicate = self._edge_tts.Communicate(
                text=text,
                voice=self.voice,
                rate=self.rate,
                volume=self.volume,
            )
            
            # 流式合成音频
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]
            
        except Exception as e:
            self._logger.error(f"EdgeTTS 流式合成失败: {e}")
    
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
            self._logger.error(f"获取音色列表失败: {e}")
            return []
    
    async def shutdown(self) -> None:
        """
        关闭 EdgeTTS
        """
        self._initialized = False
        self._logger.info("EdgeTTS 已关闭")