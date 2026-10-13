# -*- coding: utf-8 -*-
"""TTSManager 流式 fallback 契约测试（2026-09-03）。

实测事故链：前端 POST /audio/synthesize-stream → 管理器/引擎层不空则无音，
本机 moss-nano 推理失败（onnxruntime 缺 KV 缓存输入）→ 引擎静默空产出 →
流式端点 200 + 0 字节 → 前端 blob() 得 0 字节 blob → <audio> Range 请求
416（ERR_REQUEST_RANGE_NOT_SATISFIABLE）。

非流式 synthesize 已有 fallback（空结果→切换引擎，edge-tts 实测产出 MP3），
但 **synthesize_stream 无 fallback** —— 本测试锁定：
1. 流式：当前引擎零产出/抛错 → 按 fallback 链切换，切换后从头新引擎产出；
2. 流式：已产出首个 chunk 后再失败 → 不切换（HTTP 200 已开始，无法改状态）；
3. synthesize：引擎抛异常 → 同样触发 fallback（与空结果等价）；
4. TTSManager 暴露当前引擎 audio_media_type（端点 MIME 声明依赖）；
5. moss-nano 推理失败不再静默吞掉（抛 RuntimeError 供上层决策）。
"""
import pytest

from neurova.tts import manager as tts_manager_mod
from neurova.tts.manager import TTSManager


class _FakeEngine:
    """最小可插拔引擎：可配置产出/异常。"""

    def __init__(self, stream=(), synth=b"", stream_exc=None, synth_exc=None):
        self._stream = list(stream)
        self._synth = synth
        self._stream_exc = stream_exc
        self._synth_exc = synth_exc
        self.is_initialized = True
        self.audio_media_type = "audio/wav"

    async def initialize(self):
        return True

    async def synthesize(self, text, **kwargs):
        if self._synth_exc:
            raise self._synth_exc
        return self._synth

    async def synthesize_stream(self, text, **kwargs):
        for chunk in self._stream:
            yield chunk
        if self._stream_exc:
            raise self._stream_exc


def _wire_fallback(monkeypatch, mgr, fallback_engines):
    """把 _initialize_engine 换成依次切换 fake 引擎的服务；链限定为 moss-nano→mock。"""
    chain = ["moss-nano", "mock"]
    monkeypatch.setattr(tts_manager_mod, "FALLBACK_CHAIN", chain)

    async def _init(name):
        if name in fallback_engines:
            mgr._engine = fallback_engines[name]
            mgr._engine_name = name
            mgr._initialized = True
            return True
        return False

    monkeypatch.setattr(mgr, "_initialize_engine", _init)


def _make_manager(first_engine, engine_name="moss-nano"):
    mgr = TTSManager()
    mgr._initialized = True
    mgr._engine = first_engine
    mgr._engine_name = engine_name
    return mgr


@pytest.mark.asyncio
async def test_stream_falls_back_when_engine_yields_nothing(monkeypatch):
    """流式：当前引擎零产出 → fallback 引擎的字节被全部下发。"""
    empty_engine = _FakeEngine(stream=[])
    real_engine = _FakeEngine(stream=[b"RIFF", b"audio-chunk"])
    mgr = _make_manager(empty_engine)
    _wire_fallback(monkeypatch, mgr, {"mock": real_engine})

    chunks = [c async for c in mgr.synthesize_stream("你好")]
    assert chunks == [b"RIFF", b"audio-chunk"]
    assert mgr._engine_name == "mock"


@pytest.mark.asyncio
async def test_stream_falls_back_when_engine_raises(monkeypatch):
    """流式：当前引擎抛错且未产出 → fallback。"""
    broken_engine = _FakeEngine(stream=[], stream_exc=RuntimeError("moss broken"))
    real_engine = _FakeEngine(stream=[b"RIFF", b"ok"])
    mgr = _make_manager(broken_engine)
    _wire_fallback(monkeypatch, mgr, {"mock": real_engine})

    chunks = [c async for c in mgr.synthesize_stream("你好")]
    assert chunks == [b"RIFF", b"ok"]


@pytest.mark.asyncio
async def test_stream_no_fallback_after_first_chunk(monkeypatch):
    """已产出 chunk 后引擎失败 → 不切换（200 已开始），已发字节保留。"""
    broken_engine = _FakeEngine(stream=[b"PART1"], stream_exc=RuntimeError("mid fail"))
    mgr = _make_manager(broken_engine)
    _wire_fallback(monkeypatch, mgr, {"mock": _FakeEngine(stream=[b"SHOULD-NOT-APPEAR"])})

    chunks = [c async for c in mgr.synthesize_stream("你好")]
    assert chunks == [b"PART1"]


@pytest.mark.asyncio
async def test_synthesize_falls_back_when_engine_raises(monkeypatch):
    """synthesize：引擎抛异常与空结果等价 → 触发 fallback（此前会裸抛）。"""
    broken_engine = _FakeEngine(synth_exc=RuntimeError("moss broken"))
    real_engine = _FakeEngine(synth=b"RIFF-data")
    mgr = _make_manager(broken_engine)
    _wire_fallback(monkeypatch, mgr, {"mock": real_engine})

    result = await mgr.synthesize("你好")
    assert result == b"RIFF-data"


def test_manager_exposes_engine_media_type():
    """端点 MIME 声明依赖 manager.audio_media_type（edge=mpeg 需透传）。"""
    mgr = TTSManager()
    mgr._engine = _FakeEngine()
    mgr._engine.audio_media_type = "audio/mpeg"
    assert mgr.audio_media_type == "audio/mpeg"

    mgr._engine = None
    assert mgr.audio_media_type == "audio/wav"


@pytest.mark.asyncio
async def test_synthesize_returns_empty_when_all_engines_fail(monkeypatch):
    """全链失败 → 返回空字节（上层端点负责 500/503，不裸抛）。"""
    broken_engine = _FakeEngine(synth_exc=RuntimeError("no engine works"))
    mgr = _make_manager(broken_engine)
    _wire_fallback(monkeypatch, mgr, {})

    result = await mgr.synthesize("你好")
    assert result == b""


@pytest.mark.asyncio
async def test_stream_recovers_from_mock_last_resort(monkeypatch):
    """mock（兜底/哔声）不会长期霸占：下一轮回升链顶真引擎重竞争。"""
    mock_engine = _FakeEngine(stream=[b"BEEP"])
    edge_engine = _FakeEngine(stream=[b"MP3-FRAME"])
    mgr = _make_manager(mock_engine, engine_name="mock")
    monkeypatch.setattr(tts_manager_mod, "FALLBACK_CHAIN", ["moss-nano", "edge-tts", "mock"])

    async def _init(name):
        if name == "moss-nano":
            return False
        if name == "edge-tts":
            mgr._engine = edge_engine
            mgr._engine_name = "edge-tts"
            return True
        return False

    monkeypatch.setattr(mgr, "_initialize_engine", _init)

    chunks = [c async for c in mgr.synthesize_stream("你好")]
    assert chunks == [b"MP3-FRAME"]
    assert mgr._engine_name == "edge-tts"


@pytest.mark.asyncio
async def test_synthesize_recovers_from_mock_last_resort(monkeypatch):
    """synthesize 同样不能卡在 mock 兜底（若上次是它兜底，此次从链顶竞争）。"""
    mock_engine = _FakeEngine(synth=b"BEEP-WAV")
    edge_engine = _FakeEngine(synth=b"MP3-DATA")
    mgr = _make_manager(mock_engine, engine_name="mock")
    monkeypatch.setattr(tts_manager_mod, "FALLBACK_CHAIN", ["moss-nano", "edge-tts", "mock"])

    async def _init(name):
        if name == "moss-nano":
            return False
        if name == "edge-tts":
            mgr._engine = edge_engine
            mgr._engine_name = "edge-tts"
            return True
        return False

    monkeypatch.setattr(mgr, "_initialize_engine", _init)

    result = await mgr.synthesize("你好")
    assert result == b"MP3-DATA"


@pytest.mark.asyncio
async def test_moss_stream_raises_on_inference_failure(monkeypatch):
    """moss-nano 推理失败必须抛 RuntimeError（不能静默空产出骗过流式端点）。"""
    from neurova.tts.moss_nano import MOSSNanTTS

    tts = MOSSNanTTS(model_dir=None, auto_download=False)
    tts._initialized = True
    tts._prefill_session = object()
    monkeypatch.setattr(
        tts,
        "_run_inference",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("inference broken")),
    )

    with pytest.raises(RuntimeError, match="inference broken"):
        async for _ in tts.synthesize_stream("你好"):
            break


@pytest.mark.asyncio
async def test_explicit_mock_engine_does_not_drag_the_whole_chain_into_offline_path(monkeypatch):
    """常驻判据：显式只给 mock 一条链时，合成不得去碰链上别的引擎。

    2026-10-12 实测（CI `unit-tests` 转红的那两格）：`TTSConfig(engine="mock")` 只
    声明"初始用 mock"，**没有**声明回退链 —— 默认链是
    `["moss-nano", "edge-tts", "sapi5", "mock"]`，而 `_synthesize_with_fallback`
    有一条生产上正确的规矩：当前引擎是链尾兜底时不算"本引擎产出"，回链顶重新竞争
    （免得兜底哔声永久顶班，这条由本文件 `test_synthesize_recovers_from_mock_last_resort`
    把守）。两件事叠加，`synthesize` 每次都会把 moss 重新拉起来一次
    ——`MOSSNanTTS.initialize()` 在 `auto_download=True` 下去**下载 GB 级模型**
    （`neurova/tts/moss_nano.py:261`），于是 `pytest-timeout` 的 30s 墙钟被吃满
    （`tests/media/test_tts_module.py` 两条用例报 `Timeout (>30.0s)`；本机同形态 127s）。
    判据在**联网**，而它要测的只是 mock 引擎的合成契约。

    本格把"链上只放 mock"这件事钉成不变量：moss 的 initialize 被换成必须被调用即红的
    探针，显式一条链时它一次都不该被碰。反向那一半（默认链确实会回卷）由上面那条
    last-resort 用例把守 —— 两条一起，防有人把 `_synthesize_with_fallback` 的规矩
    当成"多余"删掉，也防有人把测试里的链又改回默认。
    """
    from neurova.tts.manager import TTSConfig

    called: list = []

    async def _mustNotBeCalled(name):
        called.append(name)
        return False

    # 链收窄成 mock + 一个不存在的引擎名，且 **mock 放在链首**（不是链尾）：
    # 链尾那条 last-resort 规矩（当前引擎是兜底就回链顶重竞争）本格不触碰——
    # 它由上面 `test_synthesize_recovers_from_mock_last_resort` 把守。
    # 这里要证明的是另一半：mock 在链首、当前引擎就是它时，产出即返回；
    # 链尾那个名字一次都不该被初始化。
    mock_engine = _FakeEngine(synth=b"BEEP-WAV")
    mgr = TTSManager(TTSConfig(engine="mock", fallback_chain=["mock", "moss-nano"]))
    mgr._engine = mock_engine
    mgr._engine_name = "mock"
    mgr._initialized = True
    monkeypatch.setattr(mgr, "_initialize_engine", _mustNotBeCalled)

    assert await mgr.synthesize("你好") == b"BEEP-WAV"
    assert called == [], (
        f"链首引擎产出后仍去初始化链上别的引擎（每次合成都要付它的初始化代价，"
        f"MOSS 的 auto_download 会真联网）：{called}"
    )
