"""
TTS Manager - TTS 引擎管理器

支持多引擎自动切换和 fallback：
1. moss-nano: 本地 MOSS-TTS-Nano 推理（优先）
2. edge-tts: 在线 Edge TTS（fallback）
3. mock: 模拟 TTS（测试用）
"""

from neurova.core.logger import get_logger
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel

from neurova.tts.base import TTSBase
from neurova.tts.edge_tts import EdgeTTS
from neurova.tts.mock_tts_simple import MockTTSSimple

try:
    from neurova.tts.moss_nano import MOSSNanTTS
except ImportError:
    MOSSNanTTS = None

try:
    from neurova.tts.sapi5_tts import SAPI5TTS
except ImportError:
    SAPI5TTS = None

logger = get_logger(__name__)

# Fallback 引擎优先级
FALLBACK_CHAIN = ["moss-nano", "edge-tts", "sapi5", "mock"]


class TTSConfig(BaseModel):
    """TTS 配置"""

    engine: Literal["edge-tts", "moss-nano", "sapi5", "mock", "auto"] = "auto"
    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    model_path: Optional[str] = None
    tokenizer_path: Optional[str] = None
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
        self._engines: Dict[str, TTSBase] = {}  # 实例缓存：重试不重复加载模型

    @property
    def is_initialized(self) -> bool:
        return self._initialized and self._engine is not None and self._engine.is_initialized

    @property
    def engine_name(self) -> Optional[str]:
        return self._engine_name

    @property
    def audio_media_type(self) -> str:
        """当前引擎媒体类型（端点 MIME 声明依赖；edge=mpeg 需透传）。"""
        if self._engine is not None:
            return getattr(self._engine, "audio_media_type", "audio/wav")
        return "audio/wav"

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
            logger.info("尝试初始化 TTS 引擎: %s", engine_name)
            success = await self._initialize_engine(engine_name)
            if success:
                self._fallback_index = FALLBACK_CHAIN.index(engine_name)
                return True
            self._available_engines[engine_name] = False

        logger.error("所有 TTS 引擎初始化失败")
        return False

    async def _initialize_engine(self, engine_name: str) -> bool:
        """
        初始化指定引擎。

        实例带缓存：重复启用同一引擎复用已加载实例，不重复加载模型
        （moss 模型 ~640MB，逐请求重新加载不可接受）。
        """
        try:
            engine = self._engines.get(engine_name)
            if engine is None:
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
                elif engine_name == "sapi5":
                    if SAPI5TTS is None:
                        logger.warning("SAPI5TTS 不可用（缺少 comtypes）")
                        return False
                    engine = SAPI5TTS(
                        voice_name=self._config.voice,
                        rate=self._config.rate,
                        volume=self._config.volume,
                    )
                elif engine_name == "mock":
                    engine = MockTTSSimple()
                else:
                    logger.error("未知引擎: %s", engine_name)
                    return False
                self._engines[engine_name] = engine

            success = (
                True
                if getattr(engine, "is_initialized", False)
                else await engine.initialize()
            )
            if success:
                self._engine = engine
                self._engine_name = engine_name
                self._initialized = True
                self._available_engines[engine_name] = True
                logger.info("TTS 引擎初始化成功: %s", engine_name)
                return True
            else:
                self._available_engines[engine_name] = False
                logger.warning("TTS 引擎初始化失败: %s", engine_name)
                return False

        except Exception as e:
            self._available_engines[engine_name] = False
            logger.error("TTS 引擎初始化异常: %s - %s", engine_name, e)
            return False

    async def synthesize(self, text: str, **kwargs) -> bytes:
        """
        合成语音

        如果当前引擎失败且 fallback 启用，自动切换到下一个引擎。
        引擎抛异常视为失败（与空结果等价）——此前异常会裸传，
        引擎把失败吞成空结果同样导致 fallback 形同虚设。
        """
        if not self.is_initialized:
            logger.error("TTSManager 未初始化")
            return b""

        # mock（最后兜底/哔声）作为当前引擎时等同"本引擎本轮不可用"——
        # 直接走 fallback 从链顶再竞争，否则它会"成功"产出哔声挡住回卷。
        is_last_resort = bool(FALLBACK_CHAIN) and self._engine_name == FALLBACK_CHAIN[-1]
        result = b""
        if not is_last_resort:
            try:
                result = await self._engine.synthesize(text, **kwargs)
            except Exception as e:
                logger.warning("引擎 %s 合成失败: %s，尝试 fallback", self._engine_name, e)
                result = b""

        # Fallback: 如果返回空数据且启用 fallback
        if not result and self._config.fallback_enabled:
            logger.warning("引擎 %s 合成失败，尝试 fallback", self._engine_name)
            return await self._fallback_synthesize(text, **kwargs)

        return result

    async def _fallback_synthesize(self, text: str, **kwargs) -> bytes:
        """fallback 合成"""
        current_index = FALLBACK_CHAIN.index(self._engine_name) if self._engine_name in FALLBACK_CHAIN else -1
        # mock（最后兜底）不长期霸占：上轮它是兜底幸存者时，本轮从链顶
        # 重新竞争（实例有缓存，重试不重复加载模型）。
        if current_index == len(FALLBACK_CHAIN) - 1:
            current_index = -1

        for engine_name in FALLBACK_CHAIN[current_index + 1 :]:
            logger.info("Fallback 到: %s", engine_name)
            success = await self._initialize_engine(engine_name)
            if success:
                result = await self._engine.synthesize(text, **kwargs)
                if result:
                    return result

        logger.error("所有 fallback 引擎合成失败")
        return b""

    async def synthesize_stream(self, text: str, **kwargs):
        """
        流式合成语音

        与 synthesize 同契约：当前引擎零产出或抛错时按 fallback 链切换；
        但一旦任何引擎产出过 chunk（HTTP 200 已开始）就不再切换，
        后续失败只截断。此前流式完全无 fallback：引擎静默空产出时
        端点返回 200+0 字节，前端拿到 0 字节 blob 加载必 416。
        """
        if not self.is_initialized:
            logger.error("TTSManager 未初始化")
            return

        current_index = FALLBACK_CHAIN.index(self._engine_name) if self._engine_name in FALLBACK_CHAIN else -1
        # mock（最后兜底）不长期霸占：上轮它是兜底幸存者时，本轮候选从
        # 链顶重新竞争（实例有缓存，重试不重复加载模型）。
        if current_index == len(FALLBACK_CHAIN) - 1:
            candidates = list(FALLBACK_CHAIN)
        else:
            candidates = [self._engine_name] + FALLBACK_CHAIN[current_index + 1 :] if current_index >= 0 else list(FALLBACK_CHAIN)

        for engine_name in candidates:
            if engine_name != self._engine_name:
                if not self._config.fallback_enabled:
                    return
                if not await self._initialize_engine(engine_name):
                    continue
            produced = False
            try:
                async for chunk in self._engine.synthesize_stream(text, **kwargs):
                    produced = True
                    yield chunk
            except Exception as e:
                logger.warning("引擎 %s 流式合成失败: %s", self._engine_name, e)
            if produced:
                return

        logger.error("所有 TTS 引擎流式合成失败")

    async def list_voices(self):
        """列出可用音色"""
        if not self.is_initialized:
            return []

        if isinstance(self._engine, EdgeTTS):
            return await self._engine.list_voices()

        return []

    async def shutdown(self) -> None:
        """关闭 TTSManager"""
        for engine in list(self._engines.values()):
            try:
                await engine.shutdown()
            except Exception as e:
                logger.warning("引擎 shutdown 异常: %s", e)
        self._engines.clear()
        if self._engine:
            await self._engine.shutdown()

        self._initialized = False
        self._engine = None
        self._engine_name = None
        logger.info("TTSManager 已关闭")

    def get_audio_media_type(self) -> str:
        """当前引擎流式输出的 MIME 类型（补课 4.3）。"""
        return getattr(self._engine, "audio_media_type", "audio/wav")

    def get_engine_name(self) -> str:
        return self._engine_name or "none"
