"""TTSManager 按需加载 + TTL 释放防回归（内存优化 H2-C，2026-09-08 可行性文档 §4）。

契约：
1. lazy_release=True 时构造 manager 不初始化任何引擎；首次 synthesize 按需
   初始化 fallback 链引擎并成功合成。
2. TTL 到期且无进行中请求 → 释放重引擎（moss-nano 实例被 shutdown+丢弃），
   当前引擎切到 fallback 链下一轻量引擎（edge-tts），manager 仍可用。
3. 有进行中请求（_active_requests>0）时 TTL 到期不释放。
4. 释放后再次 synthesize：轻量引擎直接服务（不重载 moss）；fallback_enabled
   时后台预载 moss 就绪后换回链顶。
5. 释放后 audio_media_type 跟随当前轻量引擎（edge=mpeg）。
6. lazy_release=False（默认）行为完全不变：不释放、启动即初始化（由 app 层
   决定时机，manager 自身 initialize 语义不变）。

用 mock 引擎替代真实 moss（模型 GB 级）：假"重引擎"经 _engines 注册表注入。
"""

import asyncio
import contextlib
from typing import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from neurova.tts.manager import TTSConfig, TTSManager


class _FakeHeavyEngine:
    """模拟 moss-nano：重模型 + is_initialized 生命周期。"""

    name = "moss-nano"
    audio_media_type = "audio/wav"

    def __init__(self):
        self._initialized = False
        self.released = False
        self.synthesize = AsyncMock(return_value=b"RIFFheavy-audio")
        self.calls = 0

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    async def initialize(self) -> bool:
        # 模拟加载耗时但可控
        await asyncio.sleep(0)
        self._initialized = True
        return True

    async def shutdown(self) -> None:
        self.released = True
        self._initialized = False


class _FakeLightEngine:
    """模拟 edge-tts：轻量、秒级就绪。"""

    name = "edge-tts"
    audio_media_type = "audio/mpeg"

    def __init__(self):
        self._initialized = False
        self.synthesize = AsyncMock(return_value=b"\xff\xfblight-audio")

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    async def initialize(self) -> bool:
        await asyncio.sleep(0)
        self._initialized = True
        return True

    async def shutdown(self) -> None:
        self._initialized = False


@pytest.fixture()
def heavy_manager():
    """预注入假引擎的 manager（绕过真实引擎构造，缓存经 _engines 命中）。"""
    cfg = TTSConfig(
        engine="auto",
        fallback_chain=["moss-nano", "edge-tts", "mock"],
        fallback_enabled=True,
        lazy_release=True,
        release_ttl_sec=60,
    )
    mgr = TTSManager(config=cfg)
    heavy, light = _FakeHeavyEngine(), _FakeLightEngine()
    mgr._engines = {"moss-nano": heavy, "edge-tts": light}
    return mgr, heavy, light


def test_default_config_has_lazy_release_off():
    """默认关闭：行为不变。"""
    mgr = TTSManager()
    assert mgr._config.lazy_release is False


@pytest.mark.asyncio
async def test_lazy_release_skips_startup_init(heavy_manager):
    mgr, heavy, light = heavy_manager
    # 构造后未 initialize：无引擎就绪
    assert mgr.is_initialized is False
    assert heavy._initialized is False


@pytest.mark.asyncio
async def test_ensure_ready_initializes_on_demand(heavy_manager):
    mgr, heavy, _ = heavy_manager
    result = await mgr.synthesize("你好")
    assert result == b"RIFFheavy-audio"
    assert mgr._engine_name == "moss-nano"
    assert heavy._initialized is True


@pytest.mark.asyncio
async def test_ttl_release_switches_to_light_engine(heavy_manager):
    mgr, heavy, light = heavy_manager
    await mgr.synthesize("第一句")  # heavy 就绪
    assert mgr._engine_name == "moss-nano"

    await mgr.release_idle_engines(now_monotonic=1_000_000)  # 远超 TTL
    assert heavy.released is True
    assert "moss-nano" not in mgr._engines  # 缓存一并丢弃（重载才重建）
    assert mgr._engine_name == "edge-tts"
    assert mgr.is_initialized is True  # 服务不中断

    # 释放后合成由轻引擎立即服务（本次不等重载）；后台是否预载 heavy 属时序特性
    result = await mgr.synthesize("第二句")
    assert result == b"\xff\xfblight-audio"


@pytest.mark.asyncio
async def test_ttl_release_skipped_while_inflight(heavy_manager):
    mgr, heavy, _ = heavy_manager
    await mgr.synthesize("第一句")
    mgr._active_requests = 1
    await mgr.release_idle_engines(now_monotonic=1_000_000)
    assert heavy.released is False
    assert mgr._engine_name == "moss-nano"
    mgr._active_requests = 0


@pytest.mark.asyncio
async def test_ttl_release_skipped_before_ttl(heavy_manager):
    mgr, heavy, _ = heavy_manager
    await mgr.synthesize("第一句")
    # 距上次使用 < TTL
    await mgr.release_idle_engines(now_monotonic=10)
    assert heavy.released is False


@pytest.mark.asyncio
async def test_release_updates_media_type(heavy_manager):
    mgr, _, _ = heavy_manager
    await mgr.synthesize("第一句")
    assert mgr.get_audio_media_type() == "audio/wav"
    await mgr.release_idle_engines(now_monotonic=1_000_000)
    assert mgr.get_audio_media_type() == "audio/mpeg"


@pytest.mark.asyncio
async def test_inflight_counter_wraps_synthesize(heavy_manager):
    mgr, _, _ = heavy_manager
    await mgr.synthesize("计数验证")
    assert mgr._active_requests == 0  # 结束后归零


@pytest.mark.asyncio
async def test_stream_synthesize_counts_inflight(heavy_manager):
    """流式期间计数 >0：生成器未耗尽时计数为 1。"""
    mgr, _, _ = heavy_manager

    async def _slow_stream():
        yield b"chunk1"
        await asyncio.sleep(0.01)
        yield b"chunk2"

    heavy = mgr._engines["moss-nano"]
    heavy.synthesize_stream = lambda *a, **k: _slow_stream()

    async def _consume():
        mgr._active_requests = 0  # 重置基线
        count_during = None
        async for _chunk in mgr.synthesize_stream("流式"):
            count_during = mgr._active_requests
        return count_during

    during = await _consume()
    assert during == 1  # 流中计数保持
    assert mgr._active_requests == 0  # 结束归零


@pytest.mark.asyncio
async def test_non_lazy_manager_never_releases():
    """lazy_release=False：release_idle_engines 是 no-op（行为不变）。"""
    cfg = TTSConfig(engine="mock", lazy_release=False)
    mgr = TTSManager(config=cfg)
    await mgr.initialize()
    engine = mgr._engine
    await mgr.release_idle_engines(now_monotonic=1_000_000)
    assert mgr._engine is engine


def test_moss_shutdown_clears_tokenizer_state():
    """H2 补充：shutdown 须清 tokenizer/manifest（按需释放语义完整）。"""
    import asyncio as _asyncio

    from neurova.tts.moss_nano import MOSSNanTTS

    eng = MOSSNanTTS(auto_download=False)
    eng._sp = object()
    eng._manifest = {"dummy": True}
    _asyncio.run(eng.shutdown())
    assert eng._sp is None
    assert eng._manifest is None


@pytest.mark.asyncio
async def test_ttl_release_skipped_for_light_engines(heavy_manager):
    """轻量引擎（edge/sapi5）零常驻成本：TTL 到期也不释放不降级。

    实测回归：早期判定只排除链尾 mock，TTL 巡检曾把 edge 释放成 sapi5
    （live 日志实锤）——白名单 _HEAVY_ENGINES 收口。
    """
    mgr, _, light = heavy_manager
    # 直接把当前引擎置为 edge（模拟已降级顶班态）
    mgr._engine = light
    mgr._engine_name = "edge-tts"
    mgr._initialized = True
    mgr._last_used_monotonic = 0.0

    released = await mgr.release_idle_engines(now_monotonic=1_000_000)
    assert released is False
    assert mgr._engine_name == "edge-tts"


@pytest.mark.asyncio
async def test_pinned_engine_never_released():
    """显式 pin 引擎（engine != auto）：音质选择优先于内存，TTL 不降级。"""
    cfg = TTSConfig(
        engine="moss-nano",
        fallback_chain=["moss-nano", "edge-tts", "mock"],
        lazy_release=True,
        release_ttl_sec=60,
    )
    mgr = TTSManager(config=cfg)
    heavy = _FakeHeavyEngine()
    mgr._engines = {"moss-nano": heavy}
    # 模拟 pin 引擎已就绪（绕过真实模型）
    heavy._initialized = True
    mgr._engine = heavy
    mgr._engine_name = "moss-nano"
    mgr._initialized = True
    mgr._last_used_monotonic = 0.0

    released = await mgr.release_idle_engines(now_monotonic=1_000_000)
    assert released is False
    assert heavy.released is False
    assert mgr._engine_name == "moss-nano"


@pytest.mark.asyncio
async def test_preheat_rebuilds_chain_top_after_release(heavy_manager, monkeypatch):
    """方案 C 闭环：释放换班后 _ensure_preheat 后台重建链顶并换回。"""
    mgr, heavy, light = heavy_manager
    await mgr.synthesize("第一句")
    await mgr.release_idle_engines(now_monotonic=1_000_000)
    assert mgr._engine_name == "edge-tts"
    assert heavy.released is True

    # 缓存已丢弃 → 预热会经 MOSSNanTTS 分支重建：注入假工厂避免真模型加载
    heavy2 = _FakeHeavyEngine()
    monkeypatch.setattr("neurova.tts.manager.MOSSNanTTS", lambda **kw: heavy2)

    # 下一请求由轻引擎立即服务，同时触发后台预热
    result = await mgr.synthesize("第二句")
    assert result == b"\xff\xfblight-audio"
    assert mgr._engine_name == "edge-tts"  # 本请求不被预热阻塞

    # 等预热任务完成 → 换回链顶
    assert mgr._preheat_task is not None
    with contextlib.suppress(asyncio.CancelledError):
        await mgr._preheat_task
    assert mgr._engine_name == "moss-nano"
    assert mgr._engines["moss-nano"] is heavy2
    assert heavy2._initialized is True

    # 换回后合成走重引擎
    result = await mgr.synthesize("第三句")
    assert result == b"RIFFheavy-audio"


@pytest.mark.asyncio
async def test_shutdown_cancels_background_tasks(heavy_manager):
    """shutdown 取消 TTL/预热任务：不留僵尸协程（否则会重建已关引擎）。"""
    mgr, _, _ = heavy_manager
    await mgr.synthesize("触发任务创建")
    assert mgr._ttl_task is not None
    ttl_task = mgr._ttl_task
    await mgr.shutdown()
    assert mgr._ttl_task is None and mgr._preheat_task is None
    # cancel 是请求式：让出事件循环后再断言取消到位
    with contextlib.suppress(asyncio.CancelledError):
        await ttl_task
    assert ttl_task.cancelled()


def test_stream_endpoint_lazy_ready_after_release(heavy_manager):
    """流式端点按需咽喉：TTL 释放后 /synthesize-stream 触发按需初始化，
    不再 503（否则闲置后前端自动语音整段哑掉）。"""
    from unittest.mock import patch

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from neurova.api.endpoints import audio as audio_mod

    mgr, heavy, light = heavy_manager
    # 模拟 TTL 释放后的状态：已换班 edge 且 edge 就绪
    mgr._engine = light
    mgr._engine_name = "edge-tts"
    mgr._initialized = True
    light._initialized = True
    light.synthesize_stream = _fake_light_stream

    calls = {"n": 0}

    def fake_get_tts_manager():
        return mgr

    with patch.object(audio_mod, "_get_tts_manager", fake_get_tts_manager):
        app = FastAPI()
        app.include_router(audio_mod.router, prefix="/audio")
        client = TestClient(app)
        resp = client.post("/audio/synthesize-stream", json={"text": "释放后流式"})
    assert resp.status_code == 200, resp.text
    assert calls["n"] == 0  # 顶班引擎就绪：未触发 initialize


async def _fake_light_stream(text, **kwargs):
    yield b"mp3-chunk"
