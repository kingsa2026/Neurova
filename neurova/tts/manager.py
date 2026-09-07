"""
TTS Manager - TTS 引擎管理器

支持多引擎自动切换和 fallback：
1. moss-nano: 本地 MOSS-TTS-Nano 推理（优先）
2. edge-tts: 在线 Edge TTS（fallback）
3. mock: 模拟 TTS（测试用）

按需加载 + TTL 释放（内存优化 H2-C，2026-09-08）：lazy_release=True 时
重引擎（moss 模型实测 +3.4GB RSS）在空闲超 TTL 且无进行中请求时被
shutdown 并丢弃实例缓存，当前引擎切 fallback 链下一轻量引擎保持服务；
后续请求由轻引擎立即服务。默认关闭，行为与历史完全一致。
"""

import time
from neurova.core.logger import get_logger
from typing import Any, Dict, List, Literal, Optional

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

# Fallback 引擎优先级（默认链；可用 TTSConfig.fallback_chain 覆盖，P1-12）
FALLBACK_CHAIN = ["moss-nano", "edge-tts", "sapi5", "mock"]

# 本地大模型引擎（GB 级常驻，TTL 释放的对象；在线/系统引擎零常驻成本不释放）
_HEAVY_ENGINES = frozenset({"moss-nano"})


class TTSConfig(BaseModel):
    """TTS 配置"""

    engine: Literal["edge-tts", "moss-nano", "sapi5", "mock", "auto"] = "auto"
    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"  # 音调调整（仅 edge-tts 消费；sapi5/moss 忽略）
    model_path: Optional[str] = None
    tokenizer_path: Optional[str] = None
    auto_download: bool = True
    fallback_enabled: bool = True
    # P1-12 有序 fallback 表（OpenClaw autoSelectOrder 启发）：显式指定
    # 引擎优先级顺序；None=用默认 FALLBACK_CHAIN。非法引擎名被过滤，
    # 全非法回退默认链。默认行为与历史完全一致。
    fallback_chain: Optional[List[str]] = None
    # H2-C 按需释放：True=空闲超 TTL 释放重引擎（moss）切轻量引擎顶班；
    # False（默认）=引擎常驻，行为与历史一致。
    lazy_release: bool = False
    release_ttl_sec: int = 600


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
        # H2-C：进行中请求计数（流式生成器体全程持有）与最近使用时钟
        self._active_requests = 0
        self._last_used_monotonic: Optional[float] = None
        self._ttl_task: Optional[Any] = None  # asyncio.Task（惰性启动，绑定运行循环）
        self._preheat_task: Optional[Any] = None  # 释放后链顶重引擎的预热任务

    def _ensure_ttl_task(self) -> None:
        """TTL 巡检协程惰性启动：首次合成后才需要（事件循环可用时）。"""
        if not self._config.lazy_release or self._ttl_task is not None:
            return
        try:
            import asyncio

            self._ttl_task = asyncio.create_task(self._ttl_loop())
        except RuntimeError:
            pass  # 无运行循环（同步测试等场景）——释放走显式 release_idle_engines

    async def _ttl_loop(self) -> None:
        import asyncio

        interval = max(5.0, min(60.0, self._config.release_ttl_sec / 4.0))
        while True:
            await asyncio.sleep(interval)
            try:
                await self.release_idle_engines()
            except Exception as e:  # noqa: BLE001 - 巡检失败不中断循环
                logger.warning("TTS TTL 巡检异常: %s", e)

    def _ensure_preheat(self) -> None:
        """释放换班后后台预热链顶重引擎（H2-C 方案 C：轻引擎立即服务，
        moss 就绪后自动换回链顶恢复音质）。去重：已有预热任务在跑则跳过。"""
        if not self._config.lazy_release or self._engine_name is None:
            return
        chain = self.fallback_chain
        top = chain[0] if chain else None
        if top is None or top == self._engine_name:
            return  # 已在链顶
        cached = self._engines.get(top)
        if cached is not None and getattr(cached, "is_initialized", False):
            return  # 已就绪未换回（罕见）
        if self._preheat_task is not None and not self._preheat_task.done():
            return  # 去重
        try:
            import asyncio

            self._preheat_task = asyncio.create_task(self._preheat_heavy(top))
        except RuntimeError:
            pass

    async def _preheat_heavy(self, heavy_name: str) -> None:
        """后台重建链顶重引擎；_initialize_engine 成功即换回当前引擎。"""
        try:
            if await self._initialize_engine(heavy_name):
                logger.info("TTS 后台预热完成：%s 已换回链顶", heavy_name)
        except Exception as e:  # noqa: BLE001 - 预热失败不阻断服务（轻引擎顶班）
            logger.warning("TTS 后台预热 %s 失败: %s", heavy_name, e)

    @property
    def fallback_chain(self) -> List[str]:
        """生效的有序 fallback 链（P1-12）。

        配置链过滤未知引擎名（注册表闭集）+ 去重保序；全非法或未配置
        回退默认 FALLBACK_CHAIN（fail-safe，不禁用 TTS）。
        """
        known = {"moss-nano", "edge-tts", "sapi5", "mock"}
        cfg_chain = self._config.fallback_chain
        if cfg_chain:
            seen: List[str] = []
            for name in cfg_chain:
                if name in known and name not in seen:
                    seen.append(name)
            if seen:
                return seen
        return list(FALLBACK_CHAIN)

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
        for engine_name in self.fallback_chain:
            logger.info("尝试初始化 TTS 引擎: %s", engine_name)
            success = await self._initialize_engine(engine_name)
            if success:
                self._fallback_index = self.fallback_chain.index(engine_name)
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
                        pitch=self._config.pitch,
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

    async def _ensure_ready(self) -> bool:
        """按需就绪（H2-C）：当前引擎可用直接用；否则按 fallback 链初始化。

        lazy_release 释放后 _initialized=False，此入口是所有合成的必经
        咽喉——首次调用重新走链（实例缓存未丢时零成本，丢弃后重载）。
        """
        if self.is_initialized:
            self._ensure_preheat()
            return True
        return await self.initialize()

    async def release_idle_engines(self, now_monotonic: Optional[float] = None) -> bool:
        """空闲超 TTL 且无进行中请求 → 释放当前重引擎，切轻量引擎顶班（H2-C）。

        仅 lazy_release=True 生效；返回是否发生了释放。被释放的引擎实例
        一并移出缓存——后续 _ensure_ready 经 fallback 链重建（moss 重载
        实测热缓存 ~7s）。
        """
        if not self._config.lazy_release:
            return False
        if self._config.engine != "auto":
            # 用户显式 pin 了引擎（非 auto）：音质选择优先于内存，不降级
            return False
        if self._active_requests > 0 or not self.is_initialized:
            return False
        now = now_monotonic if now_monotonic is not None else time.monotonic()
        if (
            self._last_used_monotonic is None
            or now - self._last_used_monotonic < self._config.release_ttl_sec
        ):
            return False

        chain = self.fallback_chain
        heavy_name = self._engine_name
        if heavy_name not in _HEAVY_ENGINES:
            return False  # 轻量引擎（edge/sapi5/mock）零常驻成本，不释放——
            # 否则 TTL 巡检会沿链逐级降级（实测曾把 edge 释放成 sapi5）
        if heavy_name not in chain or heavy_name == chain[-1]:
            return False  # 兜底（mock）引擎无释放收益

        released = False
        for name in chain[chain.index(heavy_name) + 1:]:
            if name == "mock":
                continue
            if await self._initialize_engine(name):
                released = True
                break
        if not released:
            return False

        heavy = self._engines.pop(heavy_name, None)
        if heavy is not None:
            try:
                await heavy.shutdown()
            except Exception as e:  # noqa: BLE001 - 释放失败不阻断切换
                logger.warning("重引擎 %s shutdown 异常: %s", heavy_name, e)
        logger.info(
            "TTS 空闲超 TTL(%ss)：重引擎 %s 已释放，当前引擎切换为 %s",
            self._config.release_ttl_sec,
            heavy_name,
            self._engine_name,
        )
        return True

    async def synthesize(self, text: str, **kwargs) -> bytes:
        """
        合成语音

        如果当前引擎失败且 fallback 启用，自动切换到下一个引擎。
        引擎抛异常视为失败（与空结果等价）——此前异常会裸传，
        引擎把失败吞成空结果同样导致 fallback 形同虚设。

        H2-C：入口经 _ensure_ready 按需就绪——lazy_release 释放后
        由 fallback 链重新初始化（轻量引擎顶班），不再直接报未初始化。
        """
        await self._ensure_ready()
        if not self.is_initialized:
            logger.error("TTSManager 未初始化")
            return b""

        self._active_requests += 1
        try:
            return await self._synthesize_with_fallback(text, **kwargs)
        finally:
            self._active_requests -= 1
            self._last_used_monotonic = time.monotonic()
            self._ensure_ttl_task()

    async def _synthesize_with_fallback(self, text: str, **kwargs) -> bytes:
        """历史 synthesize 主体（fallback 竞争逻辑），被按需咽喉包裹。"""

        # mock（最后兜底/哔声）作为当前引擎时等同"本引擎本轮不可用"——
        # 直接走 fallback 从链顶再竞争，否则它会"成功"产出哔声挡住回卷。
        is_last_resort = self._engine_name == self.fallback_chain[-1]
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
        current_index = self.fallback_chain.index(self._engine_name) if self._engine_name in self.fallback_chain else -1
        # mock（最后兜底）不长期霸占：上轮它是兜底幸存者时，本轮从链顶
        # 重新竞争（实例有缓存，重试不重复加载模型）。
        if current_index == len(self.fallback_chain) - 1:
            current_index = -1

        for engine_name in self.fallback_chain[current_index + 1:]:
            logger.info("Fallback 到: %s", engine_name)
            success = await self._initialize_engine(engine_name)
            if success:
                # 异常=该引擎本轮失败，跳过继续链（与主路径 try/except 同契约）：
                # 此前裸调，链中任一引擎抛错（如 kwarg 契约 TypeError）会中断
                # 整条 fallback 链直接冒泡 500。
                try:
                    result = await self._engine.synthesize(text, **kwargs)
                except Exception as e:
                    logger.warning("Fallback 引擎 %s 合成失败: %s", engine_name, e)
                    continue
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

        H2-C：全程计数 _active_requests（TTL 释放跳过进行中流的依据），
        入口经 _ensure_ready 按需就绪。
        """
        await self._ensure_ready()
        if not self.is_initialized:
            logger.error("TTSManager 未初始化")
            return

        self._active_requests += 1
        try:
            current_index = self.fallback_chain.index(self._engine_name) if self._engine_name in self.fallback_chain else -1
            # mock（最后兜底）不长期霸占：上轮它是兜底幸存者时，本轮候选从
            # 链顶重新竞争（实例有缓存，重试不重复加载模型）。
            if current_index == len(self.fallback_chain) - 1:
                candidates = list(self.fallback_chain)
            else:
                candidates = [self._engine_name] + self.fallback_chain[current_index + 1:] if current_index >= 0 else list(self.fallback_chain)

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
        finally:
            self._active_requests -= 1
            self._last_used_monotonic = time.monotonic()
            self._ensure_ttl_task()

    async def list_voices(self):
        """列出可用音色"""
        if not self.is_initialized:
            return []

        if isinstance(self._engine, EdgeTTS):
            return await self._engine.list_voices()

        return []

    async def shutdown(self) -> None:
        """关闭 TTSManager"""
        # H2-C：取消后台巡检/预热任务，防止 shutdown 后僵尸协程重建引擎
        for task in (self._ttl_task, self._preheat_task):
            if task is not None and not task.done():
                task.cancel()
        self._ttl_task = None
        self._preheat_task = None
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
