# -*- coding: utf-8 -*-
"""TTS 引擎 kwarg 契约与诚实初始化测试（2026-09-07）。

实测事故链（"TTS 不正常，音频为空"排查）：
1. moss-nano（默认链首位）synthosize 收紧签名 ``(text, voice_ref_audio,
   voice_ref_text)``，而 voice_pipeline/voice_adapter/generation.py/
   drama_nodes 均按 TTSBase 宽契约传 ``voice``/``speed`` 等语义 kwarg →
   TypeError。主调用被 manager 捕获，但 _fallback_synthesize 内部裸调
   无保护 → 一个 fallback 引擎抛异常就中断整链冒泡 500。
2. moss-nano._run_inference 只喂 input_ids，而 moss_tts_decode_step.onnx
   是带 KV-cache 的自回归图（要求 past_key_0..11 等输入）→ 推理必崩，
   引擎初始化却谎报成功（initialize() 文档承诺的"预热一次空推理"从未
   实现）→ 每次请求都白走一遍死引擎再 fallback，且空占 ~640MB 内存。

锁定契约：
- 引擎 synthesize 必须容忍语义 kwarg（TTSBase 宽契约，TypeError=违约）；
- fallback 链中任一引擎抛异常 → 跳过继续，不中断整链；
- initialize() 必须经能力自检门控：推理产不出音频 = 初始化失败，
  is_initialized 不许谎报（初始化为 True 蕴含真的能合成出音频）。
"""
from pathlib import Path

import numpy as np
import pytest

from neurova.tts import manager as tts_manager_mod
from neurova.tts.manager import TTSManager
from neurova.tts.moss_nano import MOSSNanTTS

# 仓库根下的本地模型目录（不入 git；缺失则跳过真实模型用例）
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MOSS_MODEL_DIR = _REPO_ROOT / "models" / "tts" / "moss-nano"


class _FakeEngine:
    """最小可插拔引擎：可配置产出/异常。"""

    def __init__(self, synth=b""):
        self._synth = synth
        self.is_initialized = True
        self.audio_media_type = "audio/wav"

    async def initialize(self):
        return True

    async def synthesize(self, text, **kwargs):
        return self._synth

    async def synthesize_stream(self, text, **kwargs):
        yield b""


@pytest.mark.asyncio
async def test_moss_synthesize_accepts_semantic_kwargs():
    """moss-nano 必须容忍 voice/speed 等语义 kwarg（TTSBase 宽契约）。

    未初始化时返回空字节即可——契约点在签名不许 TypeError：
    参数绑定发生在函数体之前，TypeError 会直接炸穿 manager fallback 链。
    """
    tts = MOSSNanTTS(model_dir=None, auto_download=False)
    result = await tts.synthesize("你好", voice="default", speed=1.0)
    assert result == b""


@pytest.mark.asyncio
async def test_moss_stream_accepts_semantic_kwargs():
    """moss-nano 流式签名同样不许对语义 kwarg 抛 TypeError。"""
    tts = MOSSNanTTS(model_dir=None, auto_download=False)
    chunks = [c async for c in tts.synthesize_stream("你好", voice="default", speed=1.0)]
    assert chunks == []


@pytest.mark.asyncio
async def test_fallback_chain_skips_raising_engine(monkeypatch):
    """fallback 链中某引擎抛异常 → 跳过继续下一引擎，不许中断整链冒泡。

    复刻真实事故：moss（voice kwarg TypeError）→ edge（此处模拟坏）→
    mock 正常产出。此前 _fallback_synthesize 内部裸调，mid 引擎一炸
    整条链 500。
    """
    broken_primary = _FakeEngine()
    broken_primary.synthesize = None  # 不会被调（primary 异常路径单独触发）

    class _RaisingEngine(_FakeEngine):
        def __init__(self, exc):
            super().__init__()
            self._exc = exc

        async def synthesize(self, text, **kwargs):
            raise self._exc

    mid_broken = _RaisingEngine(TypeError("unexpected keyword argument 'voice'"))
    good = _FakeEngine(synth=b"RIFF-DATA")

    mgr = TTSManager()
    mgr._initialized = True
    mgr._engine = _RaisingEngine(RuntimeError("moss inference broken"))
    mgr._engine_name = "moss-nano"
    monkeypatch.setattr(tts_manager_mod, "FALLBACK_CHAIN", ["moss-nano", "edge-tts", "mock"])

    async def _init(name):
        mapping = {"edge-tts": mid_broken, "mock": good}
        if name in mapping:
            mgr._engine = mapping[name]
            mgr._engine_name = name
            mgr._initialized = True
            return True
        return False

    monkeypatch.setattr(mgr, "_initialize_engine", _init)

    result = await mgr.synthesize("你好", voice="default")
    assert result == b"RIFF-DATA"
    assert mgr._engine_name == "mock"


def test_moss_probe_capability_false_when_inference_empty(monkeypatch):
    """能力自检：推理产出空音频 → False（不许谎报可用）。"""
    tts = MOSSNanTTS(model_dir=None, auto_download=False)
    tts._tts_session = object()
    monkeypatch.setattr(tts, "_run_inference", lambda *a, **k: np.zeros(0, dtype=np.float32))
    assert tts._probe_inference_capability() is False


def test_moss_probe_capability_false_when_inference_raises(monkeypatch):
    """能力自检：推理抛异常（如 KV-cache 输入缺失）→ False。"""
    tts = MOSSNanTTS(model_dir=None, auto_download=False)
    tts._tts_session = object()

    def _boom(*a, **k):
        raise ValueError("Required inputs (['past_key_0']) are missing from input feed")

    monkeypatch.setattr(tts, "_run_inference", _boom)
    assert tts._probe_inference_capability() is False


def test_moss_probe_capability_true_when_inference_produces_audio(monkeypatch):
    """能力自检：推理真产出非空音频 → True（未来推理修好后自检放行）。"""
    tts = MOSSNanTTS(model_dir=None, auto_download=False)
    tts._tts_session = object()
    monkeypatch.setattr(tts, "_run_inference", lambda *a, **k: np.ones(4800, dtype=np.float32))
    assert tts._probe_inference_capability() is True


@pytest.mark.skipif(not _MOSS_MODEL_DIR.exists(), reason="本地 moss-nano 模型未下载")
@pytest.mark.asyncio
async def test_moss_initialized_implies_real_synthesis():
    """诚实初始化不变量：initialize()=True 蕴含引擎真能合成出非空音频。

    当前推理实现无法驱动 KV-cache 自回归图 → initialize() 必须返回
    False（而非谎报 True 让每次请求白走死引擎）。未来推理修好后此
    不变量同样成立（True + 真合成）。
    """
    tts = MOSSNanTTS(model_dir=_MOSS_MODEL_DIR, tokenizer_dir=None, auto_download=False)
    ok = await tts.initialize()
    if ok:
        try:
            audio = await tts.synthesize("测试")
            assert audio, "initialize()=True 但合成 0 字节：is_initialized 谎报能力"
        finally:
            await tts.shutdown()
    else:
        # 自检失败必须诚实：不许留在"已初始化"状态
        assert tts.is_initialized is False
