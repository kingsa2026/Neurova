"""
VoiceEngineAdapter — 语音引擎适配器

解决 VoiceEngine 与 TTSManager/ASRManager 接口不对齐的问题：
1. 统一 synthesize/transcribe 接口到 VoiceEngine 的 process() 方法
2. 适配不同的参数格式和返回值格式
3. 提供故障转移和回退机制

设计原则：
- 适配器模式：在接缝处创建适配器
- 深模块：小接口（adapt_process），深实现（参数转换、错误处理）
- 开闭原则：新增引擎只需实现 VoiceEngineAdapter 接口，无需修改 VoiceEngine

注意：本模块中的 VoiceEngineAdapter 与 channels/voice.py 中的 VoiceAdapter 不同。
- VoiceEngineAdapter：适配 VoiceEngine 的通用 process() 方法到具体引擎（TTSManager/ASRManager）
- VoiceAdapter：实现 ChannelAdapter 接口，用于 Twilio 语音通话渠道
"""

from neurova.core.logger import get_logger
from abc import ABC, abstractmethod
from typing import Any, Dict, Union

logger = get_logger(__name__)


class VoiceEngineAdapter(ABC):
    """语音引擎适配器抽象基类

    深模块：小接口，深实现

    接口：
    - adapt_process() - 适配处理请求到目标引擎
    - adapt_result() - 适配引擎结果到 VoiceResult

    实现细节：
    - 处理参数格式转换
    - 处理返回值格式转换
    - 错误处理和日志记录
    """

    @abstractmethod
    async def adapt_process(self, input_data: Union[bytes, str], operation: str, **kwargs) -> Any:
        """
        适配处理请求到目标引擎

        Args:
            input_data: 输入数据（音频字节或文本）
            operation: 操作类型（transcribe/synthesize等）
            **kwargs: 额外参数

        Returns:
            目标引擎的原始返回值
        """
        ...

    @abstractmethod
    def adapt_result(self, raw_result: Any, operation: str) -> Dict[str, Any]:
        """
        适配引擎结果到统一格式

        Args:
            raw_result: 引擎原始返回值
            operation: 操作类型

        Returns:
            统一格式的结果字典
        """
        ...

    def get_info(self) -> Dict[str, Any]:
        """获取适配器信息"""
        return {
            "adapter_class": self.__class__.__name__,
            "engine_type": getattr(self, "_engine_type", "unknown"),
        }


class TTSManagerAdapter(VoiceEngineAdapter):
    """TTSManager 适配器

    适配 TTSManager 的 synthesize() 方法到 VoiceEngine 的 process() 接口
    """

    def __init__(self, tts_manager: Any):
        """
        初始化 TTS 适配器

        Args:
            tts_manager: TTSManager 实例
        """
        self._tts_manager = tts_manager
        self._engine_type = "tts"

    async def adapt_process(self, input_data: Union[bytes, str], operation: str, **kwargs) -> Any:
        """
        适配 TTS 处理请求

        Args:
            input_data: 文本输入
            operation: 操作类型（synthesize）
            **kwargs: 额外参数（voice, rate, volume等）

        Returns:
            音频字节数据
        """
        if operation != "synthesize":
            raise ValueError(f"TTSManager 不支持的操作: {operation}")

        # 确保输入是字符串
        text = input_data if isinstance(input_data, str) else input_data.decode("utf-8")

        # 提取 TTS 特定参数
        tts_kwargs = {}
        if "voice" in kwargs:
            tts_kwargs["voice"] = kwargs["voice"]
        if "rate" in kwargs:
            tts_kwargs["rate"] = kwargs["rate"]
        if "volume" in kwargs:
            tts_kwargs["volume"] = kwargs["volume"]

        # 调用 TTSManager
        audio_data = await self._tts_manager.synthesize(text, **tts_kwargs)
        return audio_data

    def adapt_result(self, raw_result: Any, operation: str) -> Dict[str, Any]:
        """
        适配 TTS 结果

        Args:
            raw_result: 音频字节数据
            operation: 操作类型

        Returns:
            统一格式的结果字典
        """
        return {
            "audio_data": raw_result,
            "operation": operation,
            "engine": getattr(self._tts_manager, "engine_name", "unknown"),
        }

    def get_info(self) -> Dict[str, Any]:
        """获取适配器信息"""
        base_info = super().get_info()
        base_info.update(
            {
                "engine_name": getattr(self._tts_manager, "engine_name", "unknown"),
                "is_initialized": getattr(self._tts_manager, "is_initialized", False),
            }
        )
        return base_info


class ASRManagerAdapter(VoiceEngineAdapter):
    """ASRManager 适配器

    适配 ASRManager 的 transcribe() 方法到 VoiceEngine 的 process() 接口
    """

    def __init__(self, asr_manager: Any):
        """
        初始化 ASR 适配器

        Args:
            asr_manager: ASRManager 实例
        """
        self._asr_manager = asr_manager
        self._engine_type = "asr"

    async def adapt_process(self, input_data: Union[bytes, str], operation: str, **kwargs) -> Any:
        """
        适配 ASR 处理请求

        Args:
            input_data: 音频字节数据
            operation: 操作类型（transcribe/understand/caption）
            **kwargs: 额外参数（language等）

        Returns:
            ASR 结果字典
        """
        # 确保输入是字节
        audio_data = input_data if isinstance(input_data, bytes) else input_data.encode("utf-8")

        # 提取 ASR 特定参数
        asr_kwargs = {}
        if "language" in kwargs:
            asr_kwargs["language"] = kwargs["language"]

        # 根据操作类型调用不同方法
        if operation == "transcribe":
            result = await self._asr_manager.transcribe(audio_data, **asr_kwargs)
        elif operation == "understand":
            query = kwargs.get("query", "")
            result = await self._asr_manager.understand(audio_data, query=query, **asr_kwargs)
        elif operation == "caption":
            result = await self._asr_manager.caption(audio_data, **asr_kwargs)
        else:
            raise ValueError(f"ASRManager 不支持的操作: {operation}")

        return result

    def adapt_result(self, raw_result: Any, operation: str) -> Dict[str, Any]:
        """
        适配 ASR 结果

        Args:
            raw_result: ASR 引擎返回的字典
            operation: 操作类型

        Returns:
            统一格式的结果字典
        """
        if operation == "transcribe":
            return {
                "text": raw_result.get("text", ""),
                "confidence": raw_result.get("confidence", 0.0),
                "operation": operation,
                "engine": getattr(self._asr_manager, "engine_name", "unknown"),
                "metadata": raw_result,
            }
        elif operation == "understand":
            return {
                "text": raw_result.get("text", ""),
                "confidence": raw_result.get("confidence", 0.0),
                "operation": operation,
                "engine": getattr(self._asr_manager, "engine_name", "unknown"),
                "metadata": raw_result,
            }
        elif operation == "caption":
            return {
                "text": raw_result if isinstance(raw_result, str) else str(raw_result),
                "confidence": 1.0,  # caption 通常没有置信度
                "operation": operation,
                "engine": getattr(self._asr_manager, "engine_name", "unknown"),
                "metadata": {"operation": "caption"},
            }
        else:
            return {
                "text": str(raw_result),
                "confidence": 0.0,
                "operation": operation,
                "engine": getattr(self._asr_manager, "engine_name", "unknown"),
                "metadata": {},
            }

    def get_info(self) -> Dict[str, Any]:
        """获取适配器信息"""
        base_info = super().get_info()
        base_info.update(
            {
                "engine_name": getattr(self._asr_manager, "engine_name", "unknown"),
                "is_initialized": getattr(self._asr_manager, "is_initialized", False),
            }
        )
        return base_info


class VoiceAdapterFactory:
    """语音适配器工厂

    创建适合 VoiceEngine 的适配器实例
    """

    @staticmethod
    def create_tts_adapter(tts_manager: Any) -> TTSManagerAdapter:
        """
        创建 TTS 适配器

        Args:
            tts_manager: TTSManager 实例

        Returns:
            TTSManagerAdapter 实例
        """
        return TTSManagerAdapter(tts_manager)

    @staticmethod
    def create_asr_adapter(asr_manager: Any) -> ASRManagerAdapter:
        """
        创建 ASR 适配器

        Args:
            asr_manager: ASRManager 实例

        Returns:
            ASRManagerAdapter 实例
        """
        return ASRManagerAdapter(asr_manager)

    @staticmethod
    def create_adapter_for_engine(engine_type: str, engine_manager: Any) -> VoiceEngineAdapter:
        """
        为指定引擎类型创建适配器

        Args:
            engine_type: 引擎类型（"tts" 或 "asr"）
            engine_manager: 引擎管理器实例

        Returns:
            适配器实例
        """
        if engine_type.lower() == "tts":
            return VoiceAdapterFactory.create_tts_adapter(engine_manager)
        elif engine_type.lower() == "asr":
            return VoiceAdapterFactory.create_asr_adapter(engine_manager)
        else:
            raise ValueError(f"不支持的引擎类型: {engine_type}")


# 便捷函数
def adapt_voice_process(engine_type: str, engine_manager: Any, input_data: Union[bytes, str], operation: str, **kwargs):
    """
    便捷函数：适配语音处理请求

    Args:
        engine_type: 引擎类型（"tts" 或 "asr"）
        engine_manager: 引擎管理器实例
        input_data: 输入数据
        operation: 操作类型
        **kwargs: 额外参数

    Returns:
        适配后的处理结果
    """
    adapter = VoiceAdapterFactory.create_adapter_for_engine(engine_type, engine_manager)
    return adapter.adapt_process(input_data, operation, **kwargs)


# 向后兼容别名（保留旧名称，避免破坏现有代码）
VoiceAdapter = VoiceEngineAdapter
