"""
TTS Manager - TTS引擎管理器（简化版）
根据用户配置选择TTS引擎，支持自动下载模型
"""

import asyncio
import logging
from pathlib import Path
import typing

from pydantic import BaseModel, Field
from typing import Literal

from neurova.tts.base import TTSBase
from neurova.tts.edge_tts import EdgeTTS
from neurova.tts.moss_nano import MOSSNanTTS
from neurova.tts.mock_tts_simple import MockTTSSimple


class TTSConfig(BaseModel):
    """
    TTS 配置
    """
    engine: Literal["edge-tts", "moss-nano", "mock"] = "edge-tts"
    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    model_path: str = "models/tts/moss-nano"


class TTSManager:
    """
    TTS 引擎管理器
    
    根据配置选择合适的 TTS 引擎，并提供统一的接口。
    """
    
    def __init__(self, config: TTSConfig = None):
        """
        初始化 TTSManager
        
        Args:
            config: TTS 配置
        """
        self._config = config or TTSConfig()
        self._engine: typing.Optional[TTSBase] = None
        self._initialized = False
        self._logger = logging.getLogger("TTSManager")
    
    @property
    def is_initialized(self) -> bool:
        """是否已初始化"""
        return self._initialized and self._engine is not None and self._engine.is_initialized
    
    async def initialize(self) -> bool:
        """
        初始化 TTS 引擎
        
        Returns:
            bool: 初始化是否成功
        """
        try:
            # 根据配置选择引擎
            if self._config.engine == "edge-tts":
                self._engine = EdgeTTS(
                    voice=self._config.voice,
                    rate=self._config.rate,
                    volume=self._config.volume,
                )
            elif self._config.engine == "moss-nano":
                self._engine = MOSSNanTTS(model_path=self._config.model_path)
            elif self._config.engine == "mock":
                self._engine = MockTTSSimple()
            else:
                self._logger.error(f"不支持的 TTS 引擎: {self._config.engine}")
                return False
            
            # 初始化引擎
            success = await self._engine.initialize()
            if success:
                self._initialized = True
                self._logger.info(f"TTS 引擎初始化成功: {self._config.engine}")
            else:
                self._logger.error(f"TTS 引擎初始化失败: {self._config.engine}")
            
            return success
            
        except Exception as e:
            self._logger.error(f"TTSManager 初始化失败: {e}")
            return False
    
    async def synthesize(self, text: str) -> bytes:
        """
        合成语音
        
        Args:
            text: 要合成的文本
            
        Returns:
            bytes: 音频数据
        """
        if not self.is_initialized:
            self._logger.error("TTSManager 未初始化")
            return b""
        
        return await self._engine.synthesize(text)
    
    async def synthesize_stream(self, text: str) -> typing.AsyncGenerator[bytes, None]:
        """
        流式合成语音
        
        Args:
            text: 要合成的文本
            
        Yields:
            bytes: 音频数据块
        """
        if not self.is_initialized:
            self._logger.error("TTSManager 未初始化")
            return
        
        async for chunk in self._engine.synthesize_stream(text):
            yield chunk
    
    async def list_voices(self) -> typing.List[typing.Dict[str, str]]:
        """
        列出可用音色
        
        Returns:
            List[Dict[str, str]]: 音色列表
        """
        if not self.is_initialized:
            return []
        
        # 只有 EdgeTTS 支持列出音色
        if isinstance(self._engine, EdgeTTS):
            return await self._engine.list_voices()
        
        return []
    
    async def shutdown(self) -> None:
        """
        关闭 TTSManager
        """
        if self._engine:
            await self._engine.shutdown()
        
        self._initialized = False
        self._logger.info("TTSManager 已关闭")
    
    def get_engine_name(self) -> str:
        """
        获取当前引擎名称
        
        Returns:
            str: 引擎名称
        """
        return self._config.engine