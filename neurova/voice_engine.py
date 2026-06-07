"""
VoiceEngine — 统一语音引擎接口

为 ASR 和 TTS 提供一致的 API，简化语音处理。
支持自动引擎选择和故障转移。
"""

import logging
from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Union

logger = logging.getLogger(__name__)


class VoiceEngineType(Enum):
    """语音引擎类型"""
    ASR = "asr"  # 语音识别
    TTS = "tts"  # 语音合成


@dataclass
class VoiceResult:
    """语音处理结果"""
    text: Optional[str] = None
    confidence: Optional[float] = None
    audio_data: Optional[bytes] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class VoiceEngine:
    """统一语音引擎接口
    
    为 ASR 和 TTS 提供一致的 API，简化语音处理。
    """
    
    def __init__(
        self,
        engine_type: VoiceEngineType,
        engine: Any
    ):
        """
        初始化语音引擎
        
        Args:
            engine_type: 引擎类型 (ASR 或 TTS)
            engine: 实际的引擎实例
        """
        self._engine_type = engine_type
        self._engine = engine
        self._logger = logging.getLogger(f"{self.__class__.__name__}.{engine_type.value}")
    
    @property
    def engine_type(self) -> VoiceEngineType:
        """获取引擎类型"""
        return self._engine_type
    
    def is_available(self) -> bool:
        """检查引擎是否可用"""
        return getattr(self._engine, "is_initialized", False)
    
    def get_info(self) -> Dict[str, Any]:
        """获取引擎信息"""
        return {
            "engine_type": self._engine_type.value,
            "is_initialized": self.is_available(),
            "engine_class": self._engine.__class__.__name__
        }
    
    async def process(
        self,
        input_data: Union[bytes, str],
        operation: str,
        **kwargs
    ) -> VoiceResult:
        """统一处理接口
        
        Args:
            input_data: 输入数据 (音频字节或文本)
            operation: 操作类型
            **kwargs: 额外参数
            
        Returns:
            VoiceResult: 处理结果
        """
        try:
            if self._engine_type == VoiceEngineType.ASR:
                return await self._process_asr(input_data, operation, **kwargs)
            elif self._engine_type == VoiceEngineType.TTS:
                return await self._process_tts(input_data, operation, **kwargs)
            else:
                return VoiceResult(error=f"不支持的引擎类型: {self._engine_type}")
        except Exception as e:
            self._logger.warning(f"语音处理失败: {e}")
            return VoiceResult(error=str(e))
    
    async def _process_asr(
        self,
        audio_data: bytes,
        operation: str,
        **kwargs
    ) -> VoiceResult:
        """处理 ASR 操作"""
        if operation == "transcribe":
            result = await self._engine.transcribe(audio_data, **kwargs)
            return VoiceResult(
                text=result.get("text"),
                confidence=result.get("confidence"),
                metadata=result
            )
        elif operation == "understand":
            result = await self._engine.understand(audio_data, **kwargs)
            return VoiceResult(
                metadata=result
            )
        elif operation == "caption":
            result = await self._engine.caption(audio_data, **kwargs)
            return VoiceResult(
                text=result,
                metadata={"operation": "caption"}
            )
        else:
            return VoiceResult(error=f"不支持的 ASR 操作: {operation}")
    
    async def _process_tts(
        self,
        text: str,
        operation: str,
        **kwargs
    ) -> VoiceResult:
        """处理 TTS 操作"""
        if operation == "synthesize":
            audio_data = await self._engine.synthesize(text, **kwargs)
            return VoiceResult(
                audio_data=audio_data,
                metadata={"operation": "synthesize"}
            )
        else:
            return VoiceResult(error=f"不支持的 TTS 操作: {operation}")


class VoiceEngineFactory:
    """语音引擎工厂"""
    
    @staticmethod
    def create_asr_engine(
        engine_class: type,
        **kwargs
    ) -> VoiceEngine:
        """创建 ASR 引擎"""
        engine = engine_class(**kwargs)
        return VoiceEngine(
            engine_type=VoiceEngineType.ASR,
            engine=engine
        )
    
    @staticmethod
    def create_tts_engine(
        engine_class: type,
        **kwargs
    ) -> VoiceEngine:
        """创建 TTS 引擎"""
        engine = engine_class(**kwargs)
        return VoiceEngine(
            engine_type=VoiceEngineType.TTS,
            engine=engine
        )


class AutoVoiceEngine:
    """支持自动选择和故障转移的语音引擎
    
    接受一组引擎实例，自动选择第一个可用的引擎。
    当当前引擎处理失败时，自动故障转移到下一个可用引擎。
    """
    
    def __init__(
        self,
        engine_type: VoiceEngineType,
        engines: List[Any],
    ):
        """初始化自动语音引擎
        
        Args:
            engine_type: 引擎类型 (ASR 或 TTS)
            engines: 引擎实例列表（按优先级排序）
        """
        self._engine_type = engine_type
        self._engines = engines
        self._current_index = 0
        self._logger = logging.getLogger(f"{self.__class__.__name__}.{engine_type.value}")
        
        # 自动选择第一个可用引擎
        self._select_first_available()
    
    def _select_first_available(self):
        """选择第一个可用的引擎"""
        self._current_index = -1
        for i, engine in enumerate(self._engines):
            if getattr(engine, "is_initialized", False):
                self._current_index = i
                self._logger.info(
                    f"自动选择引擎: {engine.__class__.__name__} (索引 {i})"
                )
                return
        
        self._logger.warning("没有可用的引擎")
    
    @property
    def current_engine(self) -> Optional[Any]:
        """获取当前引擎"""
        if 0 <= self._current_index < len(self._engines):
            return self._engines[self._current_index]
        return None
    
    @property
    def engine_type(self) -> VoiceEngineType:
        """获取引擎类型"""
        return self._engine_type
    
    def is_available(self) -> bool:
        """检查是否有可用引擎"""
        return self.current_engine is not None
    
    def get_info(self) -> Dict[str, Any]:
        """获取引擎信息"""
        available = sum(
            1 for e in self._engines
            if getattr(e, "is_initialized", False)
        )
        return {
            "engine_type": self._engine_type.value,
            "is_initialized": self.is_available(),
            "engine_class": self.current_engine.__class__.__name__ if self.current_engine else "None",
            "available_engines": available,
            "total_engines": len(self._engines),
        }
    
    async def process(
        self,
        input_data: Union[bytes, str],
        operation: str,
        **kwargs
    ) -> VoiceResult:
        """统一处理接口，支持自动故障转移
        
        Args:
            input_data: 输入数据 (音频字节或文本)
            operation: 操作类型
            **kwargs: 额外参数
            
        Returns:
            VoiceResult: 处理结果
        """
        if not self.is_available():
            return VoiceResult(error="没有可用的语音引擎")
        
        start_index = self._current_index
        
        # 尝试当前引擎和后续所有引擎
        for i in range(start_index, len(self._engines)):
            engine = self._engines[i]
            
            # 跳过不可用的引擎
            if not getattr(engine, "is_initialized", False):
                continue
            
            try:
                result = await self._process_with_engine(engine, operation, input_data, **kwargs)
                
                # 检查结果是否有效
                if self._is_result_valid(result):
                    # 成功：如果故障转移了，记录日志
                    if i != start_index:
                        self._logger.info(
                            f"故障转移成功: {engine.__class__.__name__} (索引 {i})"
                        )
                        self._current_index = i
                    return result
                
                # 结果无效（如空数据），尝试下一个引擎
                self._logger.warning(
                    f"引擎 {engine.__class__.__name__} 返回无效结果，尝试下一个"
                )
                
            except Exception as e:
                self._logger.warning(
                    f"引擎 {engine.__class__.__name__} 抛出异常: {e}，尝试下一个"
                )
                continue
        
        return VoiceResult(error="所有语音引擎均处理失败")
    
    async def _process_with_engine(
        self,
        engine: Any,
        operation: str,
        input_data: Union[bytes, str],
        **kwargs
    ) -> VoiceResult:
        """使用指定引擎处理请求"""
        # 创建临时 VoiceEngine 来处理
        temp = VoiceEngine(
            engine_type=self._engine_type,
            engine=engine,
        )
        return await temp.process(
            input_data=input_data,
            operation=operation,
            **kwargs,
        )
    
    def _is_result_valid(self, result: VoiceResult) -> bool:
        """检查结果是否有效"""
        if result.error:
            return False
        
        # TTS: 需要有音频数据
        if self._engine_type == VoiceEngineType.TTS:
            return bool(result.audio_data)
        
        # ASR: 需要有文本
        if self._engine_type == VoiceEngineType.ASR:
            return result.text is not None and result.text != ""
        
        return True