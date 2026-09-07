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
    tts._prefill_session = object()
    monkeypatch.setattr(tts, "_run_inference", lambda *a, **k: np.zeros(0, dtype=np.float32))
    assert tts._probe_inference_capability() is False


def test_moss_probe_capability_false_when_inference_raises(monkeypatch):
    """能力自检：推理抛异常（如 KV-cache 输入缺失）→ False。"""
    tts = MOSSNanTTS(model_dir=None, auto_download=False)
    tts._prefill_session = object()

    def _boom(*a, **k):
        raise ValueError("Required inputs (['past_key_0']) are missing from input feed")

    monkeypatch.setattr(tts, "_run_inference", _boom)
    assert tts._probe_inference_capability() is False


@pytest.mark.skipif(not _MOSS_MODEL_DIR.exists(), reason="本地 moss-nano 模型未下载")
def test_moss_build_request_rows_shape():
    """请求行构造：row_width=17，slot 行/文本行填充 1024，通道 1..16 放 codes。

    前缀/后缀模板 token 来自 manifest，故需指向真实模型目录。
    """
    tts = MOSSNanTTS(model_dir=_MOSS_MODEL_DIR, tokenizer_dir=None, auto_download=False)
    text_ids = [100, 200]
    prompt_codes = [[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]]
    rows = tts._build_request_rows(text_ids, prompt_codes)
    pt = tts._prompt_templates()
    n_prefix = len(pt["user_prompt_prefix_token_ids"]) + 1  # + audio_start
    n_suffix_fixed = 1 + len(pt["user_prompt_after_reference_token_ids"])  # audio_end + 后缀
    n_asst = len(pt["assistant_prompt_prefix_token_ids"]) + 1  # + audio_start
    # 总行数 = 前缀 + code 行 + (固定后缀 + 2 文本) + 助手前缀
    assert len(rows) == n_prefix + 1 + n_suffix_fixed + 2 + n_asst
    for row in rows:
        assert len(row) == 17
    # 用户音频前缀行：slot=audio_user_slot_token_id(8)，code 进通道 1..16
    user_row = rows[n_prefix]
    assert user_row[0] == 8
    assert list(user_row[1:]) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
    # 文本行：通道 0 = token，其余 = audio_pad(1024)
    text_row = rows[n_prefix + 1 + n_suffix_fixed]
    assert text_row[0] == 100
    assert all(v == 1024 for v in text_row[1:])
    # 首行 = 用户前缀首个模板 token（文本行）；末行 = 助手 audio_start(6)
    assert rows[0][0] == pt["user_prompt_prefix_token_ids"][0]
    assert rows[-1][0] == 6


def test_moss_builtin_voice_prompt_codes_loaded():
    """本地 manifest 内置音色前缀 codes 可加载（voice-clone 无参考音频也能跑）。"""
    tts = MOSSNanTTS(model_dir=_MOSS_MODEL_DIR, tokenizer_dir=None, auto_download=False)
    prompt_codes = tts._load_builtin_prompt_codes()
    assert prompt_codes, "manifest.builtin_voices[0].prompt_audio_codes 加载失败"
    assert len(prompt_codes) >= 10
    assert all(len(row) == 16 for row in prompt_codes)


def test_moss_probe_capability_true_when_inference_produces_audio(monkeypatch):
    """能力自检：推理真产出非空音频 → True（未来推理修好后自检放行）。"""
    tts = MOSSNanTTS(model_dir=None, auto_download=False)
    tts._prefill_session = object()
    monkeypatch.setattr(tts, "_run_inference", lambda *a, **k: np.ones((4800, 2), dtype=np.float32))
    assert tts._probe_inference_capability() is True


def test_create_wav_bytes_empty_array_returns_header():
    """_create_wav_bytes 空数组必须返回 44 字节合法 WAV 头（不崩）。

    事故：流式路径用 zeros(0) 造头，np.max 空归约崩（zero-size array
    to reduction）——moss 流式打通后首帧必炸。
    """
    from neurova.tts.moss_nano import _create_wav_bytes

    header = _create_wav_bytes(np.zeros(0, dtype=np.float32))
    assert len(header) == 44
    assert header[:4] == b"RIFF" and header[8:12] == b"WAVE"
    # data chunk size = 0（小端 uint32，位于 40..44）
    import struct

    assert struct.unpack("<I", header[40:44])[0] == 0


@pytest.mark.skipif(not _MOSS_MODEL_DIR.exists(), reason="本地 moss-nano 模型未下载")
@pytest.mark.asyncio
async def test_moss_stream_real_synthesis():
    """moss 流式真合成：头部 + 数据块顺序产出，不能静默空/中途崩。"""
    tts = MOSSNanTTS(model_dir=_MOSS_MODEL_DIR, tokenizer_dir=None, auto_download=False)
    ok = await tts.initialize()
    try:
        assert ok, "模型齐全但 initialize() 失败"
        chunks = []
        async for c in tts.synthesize_stream("流式合成验证"):
            chunks.append(c)
        assert chunks, "流式零产出"
        assert chunks[0][:4] == b"RIFF", "首块必须是 WAV 头"
        body = b"".join(chunks[1:])
        assert len(body) > 48000, f"音频数据过短: {len(body)} bytes"
    finally:
        await tts.shutdown()


@pytest.mark.skipif(not _MOSS_MODEL_DIR.exists(), reason="本地 moss-nano 模型未下载")
@pytest.mark.asyncio
async def test_moss_initialized_implies_real_synthesis():
    """诚实初始化不变量：模型齐全时 initialize() 必须成功，且真能合成非空语音。

    09-07 推理流水线重写后的收口测试：模型文件在而 initialize() 失败 =
    推理链路未打通（此前 kv-cache 输入缺失，恒 0 字节）。
    """
    import io as _io

    import soundfile as sf

    tts = MOSSNanTTS(model_dir=_MOSS_MODEL_DIR, tokenizer_dir=None, auto_download=False)
    ok = await tts.initialize()
    try:
        assert ok, "模型齐全但 initialize() 失败：moss-nano 推理链路未打通"
        assert tts.is_initialized is True
        audio = await tts.synthesize("测试语音")
        assert audio, "initialize()=True 但合成 0 字节"
        assert audio[:4] == b"RIFF" and audio[8:12] == b"WAVE", "输出必须是合法 WAV"
        data, sr = sf.read(_io.BytesIO(audio), dtype="float32")
        assert sr == 16000, f"采样率应为 16000（16k 降载契约），实得 {sr}"
        duration = len(data) / sr
        assert duration >= 0.3, f"合成时长过短: {duration:.2f}s"
        flat = data.reshape(-1) if data.ndim > 1 else data
        rms = float((flat.astype("float64") ** 2).mean() ** 0.5)
        assert rms > 0.005, f"合成音频疑似静音: rms={rms:.5f}"
    finally:
        await tts.shutdown()


# ---- 2026-09-08 三修：16k 降采样 / 掐停顿 / 音色透传 ----


@pytest.mark.skipif(not _MOSS_MODEL_DIR.exists(), reason="本地 moss-nano 模型未下载")
@pytest.mark.asyncio
async def test_moss_output_16k_mono():
    """moss 输出契约：16kHz 单声道（降压力：48k 双声道→16k 单声道，体积/内存 -6x）。"""
    tts = MOSSNanTTS(model_dir=_MOSS_MODEL_DIR, tokenizer_dir=None, auto_download=False)
    ok = await tts.initialize()
    try:
        assert ok
        assert tts.sample_rate == 16000, f"输出采样率应 16000，实得 {tts.sample_rate}"
        assert tts.channels == 1, f"输出声道应 1，实得 {tts.channels}"
        audio = await tts.synthesize("采样率验证")
        assert audio[:4] == b"RIFF"
        import io as _io
        import struct
        data = audio
        # WAV fmt 块: sample_rate @ 24..28, channels @ 22..24
        sr = struct.unpack("<I", data[24:28])[0]
        ch = struct.unpack("<H", data[22:24])[0]
        assert sr == 16000 and ch == 1, f"WAV 头 sr={sr} ch={ch}"
    finally:
        await tts.shutdown()


def test_moss_silence_gap_capped():
    """块间停顿上限 0.12s（原 0.24s 且逗号自身停顿 0.4-0.6s 叠加致断续）。"""
    import numpy as np

    from neurova.tts import moss_nano as mm

    pause = mm._inter_chunk_pause(16000, 1)
    expect = int(0.12 * 16000)
    assert pause.shape[0] == expect, f"停顿应 {expect} 样本，实得 {pause.shape[0]}"


def test_synthesize_request_voice_speed_reach_stream():
    """流式端点必须透传 voice/speed（agent 音色生效链）。"""
    src = open("neurova/api/endpoints/audio.py", encoding="utf-8").read()
    assert "synthesize_stream(" in src and "voice=body.voice" in src and "speed=body.speed" in src, \
        "synthesize-stream 端点必须把 voice/speed 传给引擎链"


def test_compress_silence_caps_gap():
    """输出端静音压缩：>0.35s 的连续停顿裁到 0.3s（治逗号长停顿听感）。"""
    sr = 16000
    tone = (np.sin(np.linspace(0, 100, sr)) * 0.5).astype(np.float32)
    gap = np.zeros(int(0.6 * sr), dtype=np.float32)
    wave = np.concatenate([tone, gap, tone])
    from neurova.tts import moss_nano as mm

    out = mm._compress_silence(wave, sr)
    win = int(0.05 * sr)
    nf = len(out) // win
    en = [float(np.sqrt((out[i * win:(i + 1) * win].astype("float64") ** 2).mean())) for i in range(nf)]
    zero_run = mx = 0
    for x in en:
        if x < 0.005:
            zero_run += 1
            mx = max(mx, zero_run)
        else:
            zero_run = 0
    assert mx * 0.05 <= 0.35, f"压缩后最长停顿应 ≤0.35s，实得 {mx * 0.05:.2f}s"
    # 有声内容不丢
    assert len(out) > 2 * sr, "有声段不得被裁"


# ---- 2026-09-08 音色映射：moss 内置音色按名切换 + edge↔moss 双向近似 ----


@pytest.mark.skipif(not _MOSS_MODEL_DIR.exists(), reason="本地 moss-nano 模型未下载")
def test_moss_resolve_prompt_codes_by_voice_name():
    """voice 名匹配内置音色 → 对应 prompt codes；未知名 → 默认首个。"""
    tts = MOSSNanTTS(model_dir=_MOSS_MODEL_DIR, tokenizer_dir=None, auto_download=False)
    junhao = tts._resolve_prompt_codes(None, voice="Junhao")
    xiaoyu = tts._resolve_prompt_codes(None, voice="Xiaoyu")
    assert junhao and xiaoyu, "两个内置音色 codes 都应可解析"
    assert junhao != xiaoyu, "不同音色的参考 codes 必须不同（否则音色切换无效）"
    # 未知名回退默认（首个内置音色）
    unknown = tts._resolve_prompt_codes(None, voice="NotExists")
    assert unknown == tts._resolve_prompt_codes(None, voice=None)


@pytest.mark.skipif(not _MOSS_MODEL_DIR.exists(), reason="本地 moss-nano 模型未下载")
def test_moss_edge_voice_alias_maps_to_builtin():
    """edge 音色名（zh-CN-XiaoxiaoNeural）经别名表映射到 moss 近似内置音色。"""
    tts = MOSSNanTTS(model_dir=_MOSS_MODEL_DIR, tokenizer_dir=None, auto_download=False)
    aliased = tts._resolve_prompt_codes(None, voice="zh-CN-XiaoxiaoNeural")
    assert aliased, "edge 别名应映射到内置音色"
    default = tts._resolve_prompt_codes(None, voice=None)
    assert aliased != default, "XiaoxiaoNeural 应映射到 Xiaoyu 而非默认 Junhao"


def test_edge_request_params_maps_moss_voice_names():
    """edge 引擎收到 moss 音色名（Junhao）→ 反向映射到近似 edge 音色，不炸服务。"""
    from neurova.tts.edge_tts import EdgeTTS

    engine = EdgeTTS(voice="zh-CN-XiaoxiaoNeural")
    mapped = engine._request_params(voice="Junhao")
    assert mapped["voice"].startswith("zh-CN-"), f"moss 名应映射为 edge 音色，实得 {mapped['voice']}"
    # edge 名原样通过
    same = engine._request_params(voice="zh-CN-YunxiNeural")
    assert same["voice"] == "zh-CN-YunxiNeural"
    # 未知名回落实例默认（防 edge 服务拒绝未知 voice 导致合成失败）
    fallback = engine._request_params(voice="Gibberish")
    assert fallback["voice"] == "zh-CN-XiaoxiaoNeural"
