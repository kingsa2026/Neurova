# -*- coding: utf-8 -*-
"""流式 ASR 会话层（对照报告 B4-1 落地：实时听写通道的引擎侧）。

三层结构：
- TurnEndpointDetector：能量 VAD，服务端 turn 终结（说话后静默 ≥ 阈值切轮）。
- StreamingTurnSession 协议：feed(pcm)→partial 文本 / finish()→final 文本 / close()。
  两个实现：
  * FunASRStreamingTurnSession——paraformer-zh-streaming（真流式，模型单例懒加载）；
  * BatchTranscribeStreamingTurnSession——把任意批式转写器（ASRManager.transcribe）
    滑窗适配成流式（funasr 不可用时的通用兜底，引擎链不受限）。
- create_funasr_streaming_session()：funasr 不可用/模型加载失败一律诚实返回 None，
  由端点回落批式适配或报 asr_unavailable。
"""

import asyncio
import math
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "TurnEndpointDetector",
    "BatchTranscribeStreamingTurnSession",
    "FunASRStreamingTurnSession",
    "create_funasr_streaming_session",
    "reset_funasr_streaming_model",
]


# ────────────────────────── turn 终结检测 ──────────────────────────


class TurnEndpointDetector:
    """能量 VAD：逐 10ms 子帧判 RMS，说话后静默累计达阈值即判一轮结束。

    双 VAD 两级（Linger 对照 B4-6 的本仓落法——服务端终裁不变，快侧先行）：
    - **快侧（pause_ms，默认 350ms）**：说话后的短静默先标 ``pause_detected``
      （候选停顿）——消费方（流式端点）借此在自然停顿时**提前刷新 partial**，
      不必等满 700ms；说话恢复后本轮标记保持（每轮闩锁）。
    - **慢侧（silence_ms，默认 700ms）**：静默持续到阈值才真正切轮出 final
      （服务端终裁），防快侧误切短停顿。

    口径：
    - 开口前的静默不切轮（否则连接建立即被切）；
    - 连续说话不切轮；
    - 单轮时长 ≥ max_turn_ms 强制切轮（防长独白永不落 final）。
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_ms: int = 10,
        silence_ms: int = 700,
        min_speech_ms: int = 300,
        max_turn_ms: int = 60_000,
        energy_threshold: float = 200.0,
        pause_ms: int = 350,
    ):
        self._sample_rate = sample_rate
        self._frame_ms = frame_ms
        self._silence_ms = silence_ms
        self._min_speech_ms = min_speech_ms
        self._max_turn_ms = max_turn_ms
        self._threshold = energy_threshold
        self._pause_ms = max(0, int(pause_ms))
        self._samples_per_frame = max(1, int(sample_rate * frame_ms / 1000))
        self.reset()

    def reset(self) -> None:
        """新一轮从头计（服务端在每轮 final 后调用）。"""
        self._voiced_ms = 0
        self._total_ms = 0
        self._silence_run_ms = 0
        self._ended = False
        self._end_reason = ""
        self._pause_detected = False

    def feed(self, pcm: bytes) -> bool:
        """喂一帧 PCM16LE；返回 True 表示当前轮应终结（之后本实例保持 ended）。"""
        if self._ended:
            return True
        total_samples = len(pcm) // 2
        step = self._samples_per_frame
        for start in range(0, total_samples - step + 1, step):
            chunk = pcm[start * 2 : (start + step) * 2]
            if self._rms(chunk) > self._threshold:
                self._voiced_ms += self._frame_ms
                self._silence_run_ms = 0
            else:
                self._silence_run_ms += self._frame_ms
            self._total_ms += self._frame_ms
            # 快侧：短停顿先标记（不切轮——慢侧终裁）
            if (
                not self._pause_detected
                and self._voiced_ms >= self._min_speech_ms
                and self._silence_run_ms >= self._pause_ms
                and self._silence_run_ms < self._silence_ms
            ):
                self._pause_detected = True
            if self._should_end():
                self._ended = True
                return True
        return self._ended

    @property
    def pause_detected(self) -> bool:
        """快侧停顿标记（每轮闩锁；慢侧终裁前给消费方提前刷新的时机）。"""
        return self._pause_detected

    @property
    def end_reason(self) -> str:
        """最近一次判定的切轮原因：silence / max_duration（未切为空）。"""
        return self._end_reason

    @property
    def voiced_ms(self) -> int:
        return self._voiced_ms

    @property
    def total_ms(self) -> int:
        return self._total_ms

    def _should_end(self) -> bool:
        if self._total_ms >= self._max_turn_ms:
            self._end_reason = "max_duration"
            return True
        if self._voiced_ms >= self._min_speech_ms and self._silence_run_ms >= self._silence_ms:
            self._end_reason = "silence"
            return True
        return False

    @staticmethod
    def _rms(pcm: bytes) -> float:
        import array

        samples = array.array("h")
        samples.frombytes(pcm)
        if not samples:
            return 0.0
        acc = 0
        for v in samples:
            acc += v * v
        return math.sqrt(acc / len(samples))


# ────────────────────────── 流式会话协议 ──────────────────────────


class BatchTranscribeStreamingTurnSession:
    """把批式转写器滑窗适配成流式会话。

    partial：累计音频每过 partial_interval_ms 重转一次（首帧立即转）；
    final：finish 时对整轮音频转写一次。转写器是任意
    ``async (audio_bytes, language=...) -> {"text": ...}``（即 ASRManager.transcribe），
    因此本适配不绑定具体引擎——funasr/whisper/remote_whisper 谁在链上谁服务。
    """

    def __init__(
        self,
        transcribe: Callable[..., Any],
        language: str = "zh",
        partial_interval_ms: int = 1200,
    ):
        self._transcribe = transcribe
        self._language = language
        self._partial_interval_ms = max(0, partial_interval_ms)
        self._audio = bytearray()
        self._last_partial = ""
        self._last_transcribe_monotonic_ms: Optional[float] = None
        self._closed = False

    async def feed(self, pcm: bytes) -> str:
        if self._closed:
            raise RuntimeError("流式会话已结束")
        if not pcm:
            return self._last_partial
        self._audio += pcm
        now_ms = time.monotonic() * 1000
        if (
            self._last_transcribe_monotonic_ms is None
            or now_ms - self._last_transcribe_monotonic_ms >= self._partial_interval_ms
        ):
            self._last_transcribe_monotonic_ms = now_ms
            text = await self._transcribe_accumulated()
            if text:
                self._last_partial = text
        return self._last_partial

    async def flushPartial(self) -> str:
        """停顿触发的一次**立即**重转（双 VAD 快侧消费：自然停顿时字幕先更新，
        不必等 partial_interval_ms；慢侧 final 仍由端点终裁）。"""
        if self._closed or not self._audio:
            return self._last_partial
        self._last_transcribe_monotonic_ms = time.monotonic() * 1000
        text = await self._transcribe_accumulated()
        if text:
            self._last_partial = text
        return self._last_partial

    async def finish(self) -> str:
        if self._closed:
            raise RuntimeError("流式会话已结束")
        self._closed = True
        if not self._audio:
            return self._last_partial
        text = await self._transcribe_accumulated()
        return text or self._last_partial

    def close(self) -> None:
        self._closed = True
        self._audio = bytearray()

    async def _transcribe_accumulated(self) -> str:
        result = await self._transcribe(bytes(self._audio), language=self._language)
        if not isinstance(result, dict):
            return ""
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        return (result.get("text") or "").strip()


class FunASRStreamingTurnSession:
    """paraformer-zh-streaming 真流式会话：每连接独立 cache，逐帧增量转写。

    generate 的返回是**本次新解出的增量片段**（非累计），会话内拼接成
    单调增长的 partial/final 文本。
    """

    def __init__(self, model: Any, language: str = "zh"):
        self._model = model
        self._language = language
        self._cache: Dict[str, Any] = {}
        self._segments: List[str] = []

    async def feed(self, pcm: bytes) -> str:
        if not pcm:
            return "".join(self._segments)
        import numpy as np

        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, self._generate, samples, False)
        if text:
            self._segments.append(text)
        return "".join(self._segments)

    async def flushPartial(self) -> str:
        """真流式引擎逐帧即解，无积压可冲——停顿刷新=当前累计文本（协议齐平）。"""
        return "".join(self._segments)

    async def finish(self) -> str:
        import numpy as np

        empty = np.zeros(0, dtype=np.float32)
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, self._generate, empty, True)
        if text:
            self._segments.append(text)
        return "".join(self._segments)

    def close(self) -> None:
        self._cache = {}
        self._segments = []

    def _generate(self, samples: Any, is_final: bool) -> str:
        try:
            res = self._model.generate(
                input=samples,
                cache=self._cache,
                is_final=is_final,
                chunk_size=[0, 10, 5],
            )
        except Exception as e:
            logger.warning("FunASR 流式 generate 失败: %s", e)
            raise
        text = ""
        if isinstance(res, list) and res:
            text = (res[0].get("text") or "").strip()
        return text


# ────────────────────────── 模型单例（DCL） ──────────────────────────

_funasr_model_lock = threading.RLock()
_funasr_model: Any = None
_funasr_model_loaded = False


def get_funasr_streaming_model() -> Any:
    """懒加载 paraformer-zh-streaming 模型单例（DCL + RLock，仓规）。

    任何失败（未安装/下载失败/加载异常）诚实返回 None，不产假模型。
    """
    global _funasr_model, _funasr_model_loaded
    if _funasr_model_loaded:
        return _funasr_model
    with _funasr_model_lock:
        if _funasr_model_loaded:
            return _funasr_model
        try:
            import funasr

            device = "cpu"
            try:
                import torch

                if torch.cuda.is_available():
                    device = "cuda"
            except ImportError:
                pass
            _funasr_model = funasr.AutoModel(model="paraformer-zh-streaming", device=device)
            logger.info("FunASR 流式模型加载完成（paraformer-zh-streaming | %s）", device)
        except Exception as e:
            logger.warning("FunASR 流式模型不可用（流式通道将回落批式引擎链）: %s", e)
            _funasr_model = None
        _funasr_model_loaded = True
        return _funasr_model


def reset_funasr_streaming_model() -> None:
    """重置模型单例（测试专用）。"""
    global _funasr_model, _funasr_model_loaded
    with _funasr_model_lock:
        _funasr_model = None
        _funasr_model_loaded = False


def create_funasr_streaming_session(language: str = "zh") -> Optional[FunASRStreamingTurnSession]:
    """funasr 可用则建流式会话；不可用返回 None（调用方回落批式适配）。"""
    model = get_funasr_streaming_model()
    if model is None:
        return None
    return FunASRStreamingTurnSession(model, language=language)
