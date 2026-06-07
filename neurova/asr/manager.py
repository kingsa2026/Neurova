"""
ASR Manager - ASR引擎管理器

支持多引擎自动切换和 fallback：
1. funasr: FunASR 本地推理（优先）
2. whisper: Whisper 本地推理（fallback）
3. mock: MockASR（测试用）
"""

import asyncio
import logging
from pathlib import Path
from typing import Literal, Optional, Dict, Any, List

from pydantic import BaseModel, Field

from neurova.asr.base import ASRBase

logger = logging.getLogger(__name__)

# Fallback 引擎优先级
FALLBACK_CHAIN = ["funasr", "whisper", "mock"]


class ASRConfig(BaseModel):
    """ASR 配置"""
    engine: Literal["funasr", "whisper", "mock", "auto"] = "auto"
    voice: str = "zh"
    model_path: str = "models/asr/funasr"
    auto_download: bool = True
    fallback_enabled: bool = True


class ASRManager:
    """
    ASR 引擎管理器
    
    根据配置选择 ASR 引擎，支持自动 fallback。
    当配置为 "auto" 时，按优先级尝试所有引擎。
    """
    
    def __init__(self, config: ASRConfig = None):
        self._config = config or ASRConfig()
        self._engine: Optional[ASRBase] = None
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
        初始化 ASR 引擎
        
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
            logger.info(f"尝试初始化 ASR 引擎: {engine_name}")
            success = await self._initialize_engine(engine_name)
            if success:
                self._fallback_index = FALLBACK_CHAIN.index(engine_name)
                return True
            self._available_engines[engine_name] = False
        
        logger.error("所有 ASR 引擎初始化失败")
        return False
    
    async def _initialize_engine(self, engine_name: str) -> bool:
        """初始化指定引擎"""
        try:
            if engine_name == "funasr":
                # 延迟导入，避免循环依赖
                from neurova.asr.funasr_engine import FunASREngine
                engine = FunASREngine(
                    model_dir=self._config.model_path,
                    auto_download=self._config.auto_download,
                )
            elif engine_name == "whisper":
                from neurova.asr.whisper_engine import WhisperEngine
                engine = WhisperEngine(
                    model_dir=self._config.model_path,
                    auto_download=self._config.auto_download,
                )
            elif engine_name == "mock":
                from neurova.asr.mock_asr import MockASREngine
                engine = MockASREngine()
            else:
                logger.error(f"未知引擎: {engine_name}")
                return False
            
            success = await engine.initialize()
            if success:
                self._engine = engine
                self._engine_name = engine_name
                self._initialized = True
                self._available_engines[engine_name] = True
                logger.info(f"ASR 引擎初始化成功: {engine_name}")
                return True
            else:
                self._available_engines[engine_name] = False
                logger.warning(f"ASR 引擎初始化失败: {engine_name}")
                return False
                
        except Exception as e:
            self._available_engines[engine_name] = False
            logger.error(f"ASR 引擎初始化异常: {engine_name} - {e}")
            return False
    

    
    async def transcribe(self, audio_bytes: bytes, **kwargs) -> dict:
        """
        语音识别
        
        如果当前引擎失败且 fallback 启用，自动切换到下一个引擎。
        """
        if not self.is_initialized:
            logger.error("ASRManager 未初始化")
            return {"text": "", "error": "ASRManager 未初始化"}
        
        result = await self._engine.transcribe(audio_bytes, **kwargs)
        
        # Fallback: 如果返回错误且启用 fallback
        if "error" in result and self._config.fallback_enabled:
            logger.warning(f"引擎 {self._engine_name} 识别失败，尝试 fallback")
            return await self._fallback_transcribe(audio_bytes, **kwargs)
        
        return result
    
    async def _fallback_transcribe(self, audio_bytes: bytes, **kwargs) -> dict:
        """fallback 识别"""
        current_index = FALLBACK_CHAIN.index(self._engine_name) if self._engine_name in FALLBACK_CHAIN else -1
        
        for engine_name in FALLBACK_CHAIN[current_index + 1:]:
            logger.info(f"Fallback 到: {engine_name}")
            success = await self._initialize_engine(engine_name)
            if success:
                result = await self._engine.transcribe(audio_bytes, **kwargs)
                if "error" not in result:
                    return result
        
        logger.error("所有 fallback 引擎识别失败")
        return {"text": "", "error": "所有 ASR 引擎识别失败"}
    
    async def understand(self, audio_bytes: bytes, query: str = "这段音频说了什么？") -> dict:
        """音频理解"""
        if not self.is_initialized:
            return {"answer": "", "error": "ASRManager 未初始化"}
        
        return await self._engine.understand(audio_bytes, query)
    
    async def caption(self, audio_bytes: bytes) -> dict:
        """音频描述"""
        if not self.is_initialized:
            return {"caption": "", "error": "ASRManager 未初始化"}
        
        return await self._engine.caption(audio_bytes)
    
    async def shutdown(self) -> None:
        """关闭 ASRManager"""
        if self._engine:
            await self._engine.shutdown()
        
        self._initialized = False
        self._engine = None
        self._engine_name = None
        logger.info("ASRManager 已关闭")
    
    def get_engine_name(self) -> str:
        return self._engine_name or "none"