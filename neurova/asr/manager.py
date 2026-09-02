"""
ASR Manager - ASR引擎管理器

支持多引擎自动切换和 fallback：
1. funasr: FunASR 本地推理（优先）
2. whisper: Whisper 本地推理（fallback）
3. mock: MockASR（测试用）
"""

import asyncio
import os

from neurova.core.logger import get_logger
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel

from neurova.asr.base import ASRBase

logger = get_logger(__name__)

# 项目根目录（neurova/asr/manager.py -> neurova/asr/ -> neurova/ -> ROOT）
_ROOT_DIR = Path(__file__).parent.parent.parent.resolve()

# Fallback 引擎优先级
# 生产默认链不含 mock（补课 4.1：mock 引擎返回假识别会污染上层）——
# mock 仅在显式 engine="mock" 或 NEUROVA_ENV=test 时追加
FALLBACK_CHAIN = ["funasr", "remote_whisper", "whisper"]


class ASRConfig(BaseModel):
    """ASR 配置"""

    engine: Literal["funasr", "remote_whisper", "whisper", "mock", "auto"] = "auto"
    voice: str = "zh"
    model_path: Optional[str] = None
    auto_download: bool = True
    fallback_enabled: bool = True
    # 本地 Whisper 下载安装同意门（补课：管理员 opt-in）——False 时本地
    # whisper 引擎在链中跳过（模型 ~140MB+torch），同意后置 True 才参与
    local_whisper_consent: bool = False


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
            # 补课 4.1：测试态追加 mock 到链尾——生产 mock 返回假识别会污染上层
            if os.environ.get("NEUROVA_ENV") == "test" and "mock" not in FALLBACK_CHAIN:
                FALLBACK_CHAIN.append("mock")
            return await self._initialize_with_fallback()
        else:
            # 显式指定本地 whisper 同样过同意门（拒绝优于静默下载）
            if (
                self._config.engine == "whisper"
                and not self._config.local_whisper_consent
            ):
                logger.warning("本地 whisper 未获用户同意（管理员设置页），拒绝初始化")
                return False
            return await self._initialize_engine(self._config.engine)

    async def _initialize_with_fallback(self) -> bool:
        """按 fallback 链初始化。

        本地 whisper 是管理员 opt-in（local_whisper_consent）：未同意时
        链中跳过（模型 ~140MB+torch 下载需用户知情同意），同意后自动参与。
        """
        chain = list(FALLBACK_CHAIN)
        if not self._config.local_whisper_consent and "whisper" in chain:
            chain.remove("whisper")
            logger.info("本地 whisper 未获用户同意，链中跳过（funasr→remote_whisper）")
        for engine_name in chain:
            logger.info("尝试初始化 ASR 引擎: %s", engine_name)
            outcome = self._initialize_engine(engine_name)
            success = await outcome if asyncio.iscoroutine(outcome) else bool(outcome)
            if success:
                self._fallback_index = chain.index(engine_name)
                # 统一由链层设置状态（重跑同意链时引擎实例来自新构造，
                # _initialize_engine 已赋值——此处兜底保证 _engine_name/
                # _initialized 与链结果一致）
                if self._engine_name != engine_name or not self._initialized:
                    self._engine_name = engine_name
                    self._initialized = True
                return True
            self._available_engines[engine_name] = False

        logger.error("所有 ASR 引擎初始化失败")
        self._engine_name = None
        self._initialized = False
        return False

    def grant_local_whisper_consent(self) -> bool:
        """管理员同意本地 whisper 下载安装——重跑链使其参与。

        Returns:
            同意后任一引擎初始化成功（通常即 whisper）。
        """
        self._config.local_whisper_consent = True
        self._initialized = False
        self._engine = None
        self._engine_name = None

        # 首次下载（~140MB+torch 依赖检查）+ 重跑链可能耗时数分钟；
        # 本方法为同步入口（FastAPI def 端点在线程池运行），直接
        # asyncio.run 新建事件循环执行——不与调用方 loop 交互
        import concurrent.futures

        async def _rerun():
            return await self._initialize_with_fallback()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _rerun()).result(timeout=600)

    def get_consent_status(self) -> dict:
        """本地 whisper 同意门状态（前端设置页消费）。"""
        from neurova.asr.model_downloader import get_asr_model_dir, is_model_ready

        return {
            "consent": self._config.local_whisper_consent,
            "model_ready": is_model_ready("base"),
            "model_dir": str(get_asr_model_dir()),
            "active_engine": self._engine_name,
            "available": {k: v for k, v in self._available_engines.items()},
            "chain": list(FALLBACK_CHAIN),
        }

    async def _initialize_engine(self, engine_name: str) -> bool:
        """初始化指定引擎"""
        try:
            # 解析模型路径：None 使用项目根目录下的默认路径
            model_path = self._config.model_path
            if model_path is None:
                if engine_name == "funasr":
                    model_path = str(_ROOT_DIR / "models" / "asr" / "funasr")
                elif engine_name == "whisper":
                    model_path = str(_ROOT_DIR / "models" / "asr" / "whisper")
                else:
                    model_path = str(_ROOT_DIR / "models" / "asr")

            if engine_name == "funasr":
                # 延迟导入，避免循环依赖
                from neurova.asr.funasr_engine import FunASREngine

                engine = FunASREngine(
                    model_dir=model_path,
                    auto_download=self._config.auto_download,
                )
            elif engine_name == "remote_whisper":
                from neurova.asr.remote_whisper_engine import RemoteWhisperEngine

                engine = RemoteWhisperEngine()
            elif engine_name == "whisper":
                if not self._config.local_whisper_consent:
                    logger.warning("本地 whisper 未获用户同意（管理员设置页），跳过")
                    return False
                from neurova.asr.whisper_engine import WhisperEngine

                engine = WhisperEngine(
                    model_dir=model_path,
                    auto_download=self._config.auto_download,
                )
            elif engine_name == "mock":
                from neurova.asr.mock_asr import MockASREngine

                engine = MockASREngine()
            else:
                logger.error("未知引擎: %s", engine_name)
                return False

            success = await engine.initialize()
            if success:
                self._engine = engine
                self._engine_name = engine_name
                self._initialized = True
                self._available_engines[engine_name] = True
                logger.info("ASR 引擎初始化成功: %s", engine_name)
                return True
            else:
                self._available_engines[engine_name] = False
                logger.warning("ASR 引擎初始化失败: %s", engine_name)
                return False

        except Exception as e:
            self._available_engines[engine_name] = False
            logger.error("ASR 引擎初始化异常: %s - %s", engine_name, e)
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
            logger.warning("引擎 %s 识别失败，尝试 fallback", self._engine_name)
            return await self._fallback_transcribe(audio_bytes, **kwargs)

        return result

    async def _fallback_transcribe(self, audio_bytes: bytes, **kwargs) -> dict:
        """fallback 识别"""
        current_index = FALLBACK_CHAIN.index(self._engine_name) if self._engine_name in FALLBACK_CHAIN else -1

        for engine_name in FALLBACK_CHAIN[current_index + 1 :]:
            logger.info("Fallback 到: %s", engine_name)
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
