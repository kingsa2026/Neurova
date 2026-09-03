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
    tts._tts_session = object()
    monkeypatch.setattr(
        tts,
        "_run_inference",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("inference broken")),
    )

    with pytest.raises(RuntimeError, match="inference broken"):
        async for _ in tts.synthesize_stream("你好"):
            break
