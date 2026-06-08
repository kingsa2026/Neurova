"""
TTS Manager - TTS 引擎管理器

支持多引擎自动切换和 fallback：
1. moss-nano: 本地 MOSS-TTS-Nano 推理（优先）
2. edge-tts: 在线 Edge TTS（fallback）
3. mock: 模拟 TTS（测试用）
"""

import asyncio
import logging
from pathlib import Path
from typing import Literal, Optional, Dict, Any

from pydantic import BaseModel, Field

from neurova.tts.base import TTSBase
from neurova.tts.edge_tts import EdgeTTS
from neurova.tts.mock_tts_simple import MockTTSSimple

try:
    from neurova.tts.moss_nano import MOSSNanTTS
except ImportError:
    MOSSNanTTS = None

logger = logging.getLogger(__name__)

# Fallback 引擎优先级
FALLBACK_CHAIN = ["moss-nano", "edge-tts", "mock"]


class TTSConfig(BaseModel):
    """TTS 配置"""
    engine: Literal["edge-tts", "moss-nano", "mock", "auto"] = "auto"
    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    model_path: str = "models/tts/moss-nano"
    tokenizer_path: str = "models/tts/moss-tokenizer"
    auto_download: bool = True
    fallback_enabled: bool = True


class TTSManager:
    """
    TTS 引擎管理器

    根据配置选择 TTS 引擎，支持自动 fallback。
    当配置为 "auto" 时，按优先级尝试所有引擎。
    """

    def __init__(self, config: TTSConfig = None):
        self._config = config or TTSConfig()
        self._engine: Optional[TTSBase] = None
        self._engine_name: Optional[str] = None
        self._initialized = False
        self._fallback_index = 0
        self._available_engines: Dict[str, bool] = {}

    @property
    def is_initialized(self) -> bool:
        return self._initialized and self._engine is not None and self._engine.is_initialized

    @property
    def engine_name(self) -> Optional[str]:
        return self._engine_name

    @property
    def stats(self) -> Dict[str, Any]:
        """当前引擎统计"""
        result = {
            "engine": self._engine_name,
            "initialized": self._initialized,
            "available_engines": self._available_engines.copy(),
        }
        if self._engine and hasattr(self._engine, "stats"):
            result["engine_stats"] = self._engine.stats
        return result

    async def initialize(self) -> bool:
        """
        初始化 TTS 引擎

        策略：
        1. 如果 engine 是 "auto"，按优先级尝试
        2. 如果指定引擎，直接初始化
        3. 失败时自动 fallback
        """
        if self._config.engine == "auto":
            return await self._initialize_with_fallback()
        else:
            return await self._initialize_engine(self._config.engine)

    async def _initialize_with_fallback(self) -> bool:
        """按 fallback 链初始化"""
        for engine_name in FALLBACK_CHAIN:
            logger.info(f"尝试初始化 TTS 引擎: {engine_name}")
            success = await self._initialize_engine(engine_name)
            if success:
                self._fallback_index = FALLBACK_CHAIN.index(engine_name)
                return True
            self._available_engines[engine_name] = False

        logger.error("所有 TTS 引擎初始化失败")
        return False

    async def _initialize_engine(self, engine_name: str) -> bool:
        """初始化指定引擎"""
        try:
            if engine_name == "moss-nano":
                if MOSSNanTTS is None:
                    logger.warning("MOSSNanTTS 不可用（缺少 numpy 或 onnxruntime）")
                    return False
                engine = MOSSNanTTS(
                    model_dir=self._config.model_path,
                    tokenizer_dir=self._config.tokenizer_path,
                    auto_download=self._config.auto_download,
                )
            elif engine_name == "edge-tts":
                engine = EdgeTTS(
                    voice=self._config.voice,
                    rate=self._config.rate,
                    volume=self._config.volume,
                )
            elif engine_name == "mock":
                engine = MockTTSSimple()
            else:
                logger.error(f"未知引擎: {engine_name}")
                return False

            success = await engine.initialize()
            if success:
                self._engine = engine
                self._engine_name = engine_name
                self._initialized = True
                self._available_engines[engine_name] = True
                logger.info(f"TTS 引擎初始化成功: {engine_name}")
                return True
            else:
                self._available_engines[engine_name] = False
                logger.warning(f"TTS 引擎初始化失败: {engine_name}")
                return False

        except Exception as e:
            self._available_engines[engine_name] = False
            logger.error(f"TTS 引擎初始化异常: {engine_name} - {e}")
            return False

    async def synthesize(self, text: str, **kwargs) -> bytes:
        """
        合成语音

        如果当前引擎失败且 fallback 启用，自动切换到下一个引擎。
        """
        if not self.is_initialized:
            logger.error("TTSManager 未初始化")
            return b""

        result = await self._engine.synthesize(text, **kwargs)

        # Fallback: 如果返回空数据且启用 fallback
        if not result and self._config.fallback_enabled:
            logger.warning(f"引擎 {self._engine_name} 合成失败，尝试 fallback")
            return await self._fallback_synthesize(text, **kwargs)

        return result

    async def _fallback_synthesize(self, text: str, **kwargs) -> bytes:
        """fallback 合成"""
        current_index = FALLBACK_CHAIN.index(self._engine_name) if self._engine_name in FALLBACK_CHAIN else -1

        for engine_name in FALLBACK_CHAIN[current_index + 1:]:
            logger.info(f"Fallback 到: {engine_name}")
            success = await self._initialize_engine(engine_name)
            if success:
                result = await self._engine.synthesize(text, **kwargs)
                if result:
                    return result

        logger.error("所有 fallback 引擎合成失败")
        return b""

    async def synthesize_stream(self, text: str, **kwargs):
        """流式合成语音"""
        if not self.is_initialized:
            logger.error("TTSManager 未初始化")
            return

        async for chunk in self._engine.synthesize_stream(text, **kwargs):
            yield chunk

    async def list_voices(self):
        """列出可用音色"""
        if not self.is_initialized:
            return []

        if isinstance(self._engine, EdgeTTS):
            return await self._engine.list_voices()

        return []

    async def shutdown(self) -> None:
        """关闭 TTSManager"""
        if self._engine:
            await self._engine.shutdown()

        self._initialized = False
        self._engine = None
        self._engine_name = None
        logger.info("TTSManager 已关闭")

    def get_engine_name(self) -> str:
        return self._engine_name or "none"
