"""
TTS 长文本根因测试（2026-09-01）

根因: user 1727 字回复 TTS 500。
链: TTSBase.validate_text 对 >1000 字符**整体拒绝**(日志"将被截断"是假截断,
 实际直接 return False) → EdgeTTS 返回 b"" → manager fallback:
 sapi5(缺 comtypes) → mock(同样拒收) → 所有 fallback 引擎合成失败 → 500。

契约:
1. sanitize_text: 超限文本**真正截断**后可通过(不再整体拒绝);
   max_text_length 属性可配置(默认 2000, 覆盖 edge-tts 长文能力);
2. validate_text 仅校验非空(长度处理前置于 sanitize);
3. 引擎级: MockTTS 对 1727 字文本 synthesize 返回非空 WAV(b'RIFF' 头);
4. EdgeTTS 属于网络引擎(不在此单测访问网络), 但其入库文本经 sanitize 后
   不受 1000 上限拒绝。
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


def test_sanitize_truncates_instead_of_rejecting():
    tts = _ProbeTTS()
    # 1727 字在上限(2000)内: 不再被整体拒绝, 原样返回
    long_text = "x" * 1727
    sanitized = tts.sanitize_text(long_text)
    assert sanitized == long_text
    assert tts.validate_text(sanitized) is True

    # 真正超限: 截断到上限
    huge_text = "y" * 3000
    cut = tts.sanitize_text(huge_text)
    assert len(cut) == tts.max_text_length
    assert cut == huge_text[: tts.max_text_length]


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
    assert audio[:4] == b"RIFF", "mock 引擎对长文本应返回 WAV(截断后合成), 而非空字节"
