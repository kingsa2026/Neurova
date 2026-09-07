"""
TTS 长文本契约测试（2026-09-07 更新：**取消字数上限**）

历史: 09-01 user 1727 字回复 TTS 500（>1000 整体拒绝）→ 改真截断 2000。
2026-09-07 用户要求 TTS **不限字数**（流式/非流式都不要限制）：
- sanitize_text 只清洗不截断（长文本由引擎内部按句切块合成）;
- EdgeTTS 对超长文本按句切块逐段合成、MP3 字节拼接;
- moss-nano 内部已有 75 token/块流水线切块, 天然支持任意长度。

契约:
1. sanitize_text: 只剥控制字符, 不截断（3000/10000 字原样保留）;
2. validate_text 仅校验非空;
3. 引擎级: MockTTS 长文本 synthesize 返回非空 WAV;
4. EdgeTTS 长文本: 分句切块逐段合成后拼接（离线单测, fake 通信对象）。
"""

import pytest

from neurova.tts.base import TTSBase
from neurova.tts.mock_tts_simple import MockTTSSimple


class _ProbeTTS(TTSBase):
    async def initialize(self) -> bool:
        self._initialized = True
        return True

    async def synthesize(self, text: str, **kwargs) -> bytes:
        return self.sanitize_text(text).encode()

    async def synthesize_stream(self, text: str):
        yield self.sanitize_text(text).encode()

    async def shutdown(self) -> None:
        self._initialized = False


def test_sanitize_never_truncates():
    """sanitize_text 只清洗不截断：任意长度原样保留（字数上限取消）。"""
    tts = _ProbeTTS()
    long_text = "长" * 3000
    sanitized = tts.sanitize_text(long_text)
    assert sanitized == long_text, "3000 字不得被截断"

    huge_text = "字" * 10000
    assert tts.sanitize_text(huge_text) == huge_text, "10000 字不得被截断"
    assert tts.validate_text(sanitized) is True


def test_sanitize_strips_control_chars():
    """控制字符仍剥离（\\r 归一为 \\n），换行/制表保留。"""
    tts = _ProbeTTS()
    text = "你好\x00\x01世界\r\n第二行\t制表"
    sanitized = tts.sanitize_text(text)
    assert "\x00" not in sanitized and "\x01" not in sanitized
    assert "\r" not in sanitized
    assert "\n" in sanitized and "\t" in sanitized


def test_validate_only_checks_nonempty():
    tts = _ProbeTTS()
    assert tts.validate_text("") is False
    assert tts.validate_text("   ") is False
    assert tts.validate_text("你好") is True


@pytest.mark.asyncio
async def test_mock_tts_synthesizes_long_text():
    engine = MockTTSSimple()
    assert await engine.initialize()
    audio = await engine.synthesize("长" * 1727)
    assert audio[:4] == b"RIFF", "mock 引擎对长文本应返回 WAV, 而非空字节"


# ---- EdgeTTS 长文本分句拼接（离线 fake，不打网络） ----


def _split_sentences_for_tts(text: str, max_len: int):
    """被测函数：从 edge_tts 导入（新契约）。

    这里间接引用——实现落在 neurova.tts.edge_tts 模块级，
    便于不启动 onnxruntime 的纯单测。
    """
    from neurova.tts.edge_tts import split_text_for_tts

    return split_text_for_tts(text, max_len)


def test_edge_split_text_by_sentence():
    """长文本按句边界切块：块不超 max_len，不把句子拦腰截断。"""
    text = "这是第一句话。这是第二句话！这是第三句话？" + "填充内容，" * 200
    chunks = _split_sentences_for_tts(text, 200)
    assert len(chunks) > 1
    assert all(len(c) <= 400 for c in chunks), "块内允许略超（单句超长时保句完整），但不得失控"
    joined = "".join(chunks)
    # 拼接还原（允许清洗差异）：所有句子边界标点必须保留
    for marker in ("这是第一句话。", "这是第二句话！", "这是第三句话？"):
        assert marker in joined


def test_edge_split_short_text_single_chunk():
    """短文本单块原样返回。"""
    chunks = _split_sentences_for_tts("你好世界。", 200)
    assert chunks == ["你好世界。"]


@pytest.mark.asyncio
async def test_edge_tts_long_text_concat(monkeypatch):
    """EdgeTTS 对超长文本分句逐段合成后拼接；单段失败跳过不拖垮整体。"""
    from neurova.tts.edge_tts import EdgeTTS

    engine = EdgeTTS()
    engine._initialized = True
    engine._edge_tts = object()  # 不走真 Communicate

    calls: list[str] = []

    class _FakeStream:
        def __init__(self, tag):
            self._tag = tag

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not getattr(self, "_sent", False):
                self._sent = True
                return {"type": "audio", "data": self._tag.encode()}
            raise StopAsyncIteration

    class _FakeCommunicate:
        def __init__(self, text, voice=None, rate=None, volume=None, pitch=None):
            calls.append(text)
            self.stream = lambda: _FakeStream(f"[{len(calls)}]")

    monkeypatch.setattr(engine, "_edge_tts", type("M", (), {"Communicate": _FakeCommunicate}))

    long_text = "这是第一句话。这是第二句话！" + "继续填充的内容，用来撑长文本。" * 200
    audio = await engine.synthesize(long_text)
    assert len(calls) > 1, "长文本必须分句多次合成"
    assert audio == b"".join(f"[{i}]".encode() for i in range(1, len(calls) + 1)), "按序拼接各段 MP3"
