# -*- coding: utf-8 -*-
"""双 VAD 快侧（B4-6）：短停顿先标 pause_detected（不切轮），慢侧 silence_ms 终裁；
快侧上升沿驱动 flushPartial 立即重转（字幕早更新）。"""
import pytest

from neurova.asr.streaming import (
    BatchTranscribeStreamingTurnSession,
    FunASRStreamingTurnSession,
    TurnEndpointDetector,
)

LOUD = (1000).to_bytes(2, "little", signed=True)
QUIET = (0).to_bytes(2, "little", signed=True)


def _frame(value: bytes, samples: int = 160) -> bytes:
    return value * samples


def _feedMs(detector: TurnEndpointDetector, value: bytes, ms: int) -> bool:
    """按 10ms 帧粒度喂 ms 毫秒；返回 detector 的切轮判定。"""
    frames = ms // 10
    ended = False
    for _ in range(frames):
        ended = detector.feed(_frame(value))
        if ended:
            break
    return ended


class TestDualVadPauseStage:
    def test_short_pause_flags_without_ending(self):
        d = TurnEndpointDetector()
        assert _feedMs(d, LOUD, 400) is False  # 说话 400ms
        assert _feedMs(d, QUIET, 400) is False  # 静默 400ms：越过 350ms 快侧
        assert d.pause_detected is True, "快侧应标记候选停顿"
        assert d.end_reason == "", "慢侧未到 700ms 不得切轮"
        assert _feedMs(d, QUIET, 400) is True  # 静默累计 800ms：慢侧终裁
        assert d.end_reason == "silence"

    def test_speech_resumes_after_pause_keeps_turn(self):
        d = TurnEndpointDetector()
        _feedMs(d, LOUD, 400)
        _feedMs(d, QUIET, 400)  # 快侧停顿
        assert d.pause_detected is True
        _feedMs(d, LOUD, 400)  # 说话恢复：同一轮继续
        assert _feedMs(d, QUIET, 300) is False
        assert d.end_reason == ""

    def test_pause_never_flags_before_speech(self):
        d = TurnEndpointDetector()
        _feedMs(d, QUIET, 1000)  # 开口前静默：不标停顿也不切轮
        assert d.pause_detected is False
        assert d.end_reason == ""

    def test_reset_clears_pause_latch(self):
        d = TurnEndpointDetector()
        _feedMs(d, LOUD, 400)
        _feedMs(d, QUIET, 400)
        assert d.pause_detected is True
        d.reset()
        assert d.pause_detected is False


class TestFlushPartial:
    def test_batch_flush_forces_immediate_transcribe(self):
        calls = []

        async def transcribe(audio, language="zh"):
            calls.append(len(audio))
            return {"text": f"片段{len(calls)}"}

        session = BatchTranscribeStreamingTurnSession(transcribe, partial_interval_ms=10_000)

        async def run():
            await session.feed(_frame(LOUD, 1600))  # 首帧即转（calls=1）
            first = await session.feed(_frame(LOUD, 1600))  # 间隔未到：不重转
            assert len(calls) == 1
            flushed = await session.flushPartial()  # 停顿触发：立即重转
            assert len(calls) == 2, "flushPartial 必须立即重转"
            assert flushed == "片段2"
            return first

        import asyncio

        asyncio.run(run())

    def test_funasr_flush_returns_joined_segments(self):
        class StubModel:
            def __init__(self):
                self.n = 0

            def generate(self, input, cache, is_final, chunk_size):
                if len(input) == 0:
                    return ""
                self.n += 1
                return [{"text": f"seg{self.n}"}]

        session = FunASRStreamingTurnSession(StubModel())

        async def run():
            await session.feed(_frame(LOUD, 1600))
            await session.feed(_frame(LOUD, 1600))
            flushed = await session.flushPartial()
            assert flushed == "seg1seg2"

        import asyncio

        asyncio.run(run())
