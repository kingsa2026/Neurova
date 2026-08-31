"""
Prometheus 指标注册表（P2-4）

单一事实源：全部 neurova_* 指标在此定义，/metrics 端点经
generate_latest() 输出（替换手拼文本格式）。埋点 API：
- Metrics.record_tool_execution(tool_name, success, duration_s)
- Metrics.record_llm_call(provider, model, success, duration_s)
- Metrics.record_memory_recall(source, latency_s)
- Metrics.observe_updater(state)  # gauges 快照
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from prometheus_client import (
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
)

logger = logging.getLogger(__name__)


class _Metrics:
    """neurova 指标集（进程级单例，惰性定义防重复注册）。"""

    def __init__(self) -> None:
        # ── 运行态 gauges ──
        self.uptime_seconds = Gauge(
            "neurova_uptime_seconds", "Neurova uptime in seconds"
        )
        self.agents_total = Gauge(
            "neurova_agents_total", "Total number of agents"
        )
        self.voice_engines_total = Gauge(
            "neurova_voice_engines_total", "Total number of voice engines"
        )
        self.voice_tts_available = Gauge(
            "neurova_voice_tts_available", "TTS engine availability (1/0)"
        )
        self.voice_asr_available = Gauge(
            "neurova_voice_asr_available", "ASR engine availability (1/0)"
        )
        self.channels_total = Gauge(
            "neurova_channels_total", "Total number of registered channels"
        )

        # ── 工具执行 ──
        self.tool_executions_total = Counter(
            "neurova_tool_executions_total",
            "Total tool executions",
            ["tool_name", "source", "success"],
        )
        self.tool_execution_seconds = Histogram(
            "neurova_tool_execution_seconds",
            "Tool execution duration",
            ["tool_name"],
            buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
        )

        # ── LLM 调用 ──
        self.llm_calls_total = Counter(
            "neurova_llm_calls_total",
            "Total LLM calls",
            ["provider", "model", "success"],
        )
        self.llm_call_seconds = Histogram(
            "neurova_llm_call_seconds",
            "LLM call duration",
            ["provider", "model"],
            buckets=(0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
        )
        self.circuit_breaker_rejected_total = Counter(
            "neurova_circuit_breaker_rejected_total",
            "Requests rejected by open circuit breakers",
            ["provider"],
        )

        # ── 记忆检索 ──
        self.memory_recall_total = Counter(
            "neurova_memory_recall_total",
            "Total memory recalls",
            ["source", "hit"],
        )
        self.memory_recall_seconds = Histogram(
            "neurova_memory_recall_seconds",
            "Memory recall duration",
            ["source"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5),
        )

    # ── 埋点 API ──

    def record_tool_execution(
        self, tool_name: str, source: str, success: bool, duration_s: float
    ) -> None:
        try:
            self.tool_executions_total.labels(
                tool_name=tool_name, source=source, success=str(bool(success)).lower()
            ).inc()
            self.tool_execution_seconds.labels(tool_name=tool_name).observe(duration_s)
        except Exception:
            logger.debug("tool metrics record failed", exc_info=True)

    def record_llm_call(
        self, provider: str, model: str, success: bool, duration_s: float
    ) -> None:
        try:
            self.llm_calls_total.labels(
                provider=provider, model=model, success=str(bool(success)).lower()
            ).inc()
            self.llm_call_seconds.labels(provider=provider, model=model).observe(duration_s)
        except Exception:
            logger.debug("llm metrics record failed", exc_info=True)

    def record_circuit_rejection(self, provider: str) -> None:
        try:
            self.circuit_breaker_rejected_total.labels(provider=provider).inc()
        except Exception:
            logger.debug("circuit metrics record failed", exc_info=True)

    def record_memory_recall(self, source: str, hit: bool, latency_s: float) -> None:
        try:
            self.memory_recall_total.labels(
                source=source, hit=str(bool(hit)).lower()
            ).inc()
            self.memory_recall_seconds.labels(source=source).observe(latency_s)
        except Exception:
            logger.debug("memory metrics record failed", exc_info=True)

    def observe_state(self, state: Any) -> None:
        """运行态 gauge 快照（/metrics 请求时调用）。"""
        try:
            self.uptime_seconds.set(state.get_uptime() if state else 0)
            self.agents_total.set(len(state.agents) if state else 0)
            self.voice_engines_total.set(len(state.voice_engines) if state else 0)
            tts = state.voice_engines.get("tts") if state else None
            self.voice_tts_available.set(
                1 if tts and tts.is_available() else 0
            )
            asr = state.voice_engines.get("asr") if state else None
            self.voice_asr_available.set(
                1 if asr and asr.is_available() else 0
            )
            channels = (
                len(state.channel_manager._adapters)
                if state and state.channel_manager
                else 0
            )
            self.channels_total.set(channels)
        except Exception:
            logger.debug("state gauges update failed", exc_info=True)


_metrics: Optional[_Metrics] = None


def get_metrics() -> _Metrics:
    """进程级单例（重复调用返回同实例，防 prometheus 重复注册）。"""
    global _metrics
    if _metrics is None:
        _metrics = _Metrics()
    return _metrics


def generate_metrics_text() -> str:
    """输出 Prometheus 文本格式（/metrics 端点用；REGISTRY 含全部已注册指标）。"""
    from prometheus_client import generate_latest

    return generate_latest(REGISTRY).decode("utf-8")
