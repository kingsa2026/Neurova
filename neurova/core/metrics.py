"""
Prometheus 指标注册表（P2-4）

单一事实源：全部 neurova_* 指标在此定义，/metrics 端点经
generate_latest() 输出（替换手拼文本格式）。埋点 API：
- Metrics.record_tool_execution(tool_name, success, duration_s)
- Metrics.record_llm_call(provider, model, success, duration_s)
- Metrics.record_memory_recall(source, latency_s)
- Metrics.observe_state(state)  # 运行态 gauges 快照（/metrics 抓取时）
- Metrics.observe_pools()  # 连接池 / 共享线程池 gauges 快照
- Metrics.record_db_connection_created/closed(db_path)  # 连接创建/销毁频率
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

        # ── 连接池（P0-2：池此前零指标，"连接创建/销毁频率""并发连接数"不可测）──
        self.db_pool_connections = Gauge(
            "neurova_db_pool_connections",
            "SQLite pool connection count by state",
            ["db", "state"],
        )
        self.db_connections_created_total = Counter(
            "neurova_db_connections_created_total",
            "SQLite connections created",
            ["db"],
        )
        self.db_connections_closed_total = Counter(
            "neurova_db_connections_closed_total",
            "SQLite connections closed",
            ["db"],
        )

        # ── 共享线程池（P0-2：线程数/队列深度此前不可测）──
        self.thread_pool_threads = Gauge(
            "neurova_thread_pool_threads",
            "Live worker threads in shared thread pools",
            ["pool"],
        )
        self.thread_pool_queue_depth = Gauge(
            "neurova_thread_pool_queue_depth",
            "Pending tasks queued in shared thread pools",
            ["pool"],
        )
        self.thread_pool_max_workers = Gauge(
            "neurova_thread_pool_max_workers",
            "Configured max workers of shared thread pools",
            ["pool"],
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

    # ── 连接池 / 线程池（P0-2）──

    def record_db_connection_created(self, db_path: str) -> None:
        """连接创建计数（池内新建连接；启动后可算创建/销毁频率）。"""
        try:
            self.db_connections_created_total.labels(db=str(db_path)).inc()
        except Exception:
            logger.debug("db connection created metric failed", exc_info=True)

    def record_db_connection_closed(self, db_path: str) -> None:
        """连接销毁计数。"""
        try:
            self.db_connections_closed_total.labels(db=str(db_path)).inc()
        except Exception:
            logger.debug("db connection closed metric failed", exc_info=True)

    def observe_pools(self) -> None:
        """连接池 / 共享线程池 gauge 快照（/metrics 请求时调用）。

        数据源是运行态对象（连接池队列、线程池内部状态），故与
        observe_state 一样走"抓取时快照"而非常驻埋点。
        """
        try:
            from neurova.core.connection_pool import iter_pools

            for db_path, pool in iter_pools():
                try:
                    self.db_pool_connections.labels(
                        db=str(db_path), state="idle"
                    ).set(pool.pool_size)
                    self.db_pool_connections.labels(
                        db=str(db_path), state="active"
                    ).set(pool.active_count)
                    self.db_pool_connections.labels(
                        db=str(db_path), state="total"
                    ).set(pool.total_count)
                except Exception:  # noqa: BLE001 - 单个池异常不影响其它池
                    logger.debug("db pool gauge failed: %s", db_path, exc_info=True)
        except Exception:
            logger.debug("db pool gauges update failed", exc_info=True)

        try:
            from neurova.core.thread_pool import iter_pools as _iter_thread_pools

            for name, pool in _iter_thread_pools():
                try:
                    self.thread_pool_threads.labels(pool=str(name)).set(
                        len(getattr(pool, "_threads", ()) or ())
                    )
                    queue = getattr(pool, "_work_queue", None)
                    self.thread_pool_queue_depth.labels(pool=str(name)).set(
                        queue.qsize() if queue is not None else 0
                    )
                    self.thread_pool_max_workers.labels(pool=str(name)).set(
                        getattr(pool, "_max_workers", 0) or 0
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("thread pool gauge failed: %s", name, exc_info=True)
        except Exception:
            logger.debug("thread pool gauges update failed", exc_info=True)

    def observe_state(self, state: Any) -> None:
        """运行态 gauge 快照（/metrics 请求时调用）。

        逐项隔离异常：单个引擎/组件取值失败只让该 gauge 停在旧值，
        不得连带清空其余指标（/metrics 是唯一事实源，整体静默失败
        等于观测面塌陷）。
        """
        self._safe_set(
            self.uptime_seconds, lambda: state.get_uptime() if state else 0, "uptime"
        )
        self._safe_set(
            self.agents_total, lambda: len(state.agents) if state else 0, "agents"
        )
        self._safe_set(
            self.voice_engines_total,
            lambda: len(state.voice_engines) if state else 0,
            "voice_engines",
        )
        self._safe_set(
            self.voice_tts_available,
            lambda: self._voice_available(state, "tts"),
            "tts_available",
        )
        self._safe_set(
            self.voice_asr_available,
            lambda: self._voice_available(state, "asr"),
            "asr_available",
        )
        self._safe_set(
            self.channels_total,
            lambda: (
                len(state.channel_manager._adapters)
                if state and state.channel_manager
                else 0
            ),
            "channels",
        )

    @staticmethod
    def _voice_available(state: Any, kind: str) -> int:
        engine = state.voice_engines.get(kind) if state else None
        return 1 if engine and engine.is_available() else 0

    @staticmethod
    def _safe_set(gauge: Any, producer, label: str) -> None:
        try:
            gauge.set(producer())
        except Exception:  # noqa: BLE001 - 单项失败不影响其它 gauge
            logger.debug("gauge %s update failed", label, exc_info=True)


_metrics: Optional[_Metrics] = None


def get_metrics() -> _Metrics:
    """进程级单例（重复调用返回同实例，防 prometheus 重复注册）。"""
    global _metrics
    if _metrics is None:
        _metrics = _Metrics()
    return _metrics


def record_db_connection_created(db_path: str) -> None:
    """模块级便捷入口（连接池埋点，避免各模块持有 metrics 单例引用）。"""
    get_metrics().record_db_connection_created(db_path)


def record_db_connection_closed(db_path: str) -> None:
    """模块级便捷入口（连接池埋点）。"""
    get_metrics().record_db_connection_closed(db_path)


def generate_metrics_text() -> str:
    """输出 Prometheus 文本格式（/metrics 端点用；REGISTRY 含全部已注册指标）。"""
    from prometheus_client import generate_latest

    return generate_latest(REGISTRY).decode("utf-8")
