"""
Prometheus 指标注册表（P2-4）

单一事实源：全部 neurova_* 指标在此定义，/metrics 端点经
generate_latest() 输出（替换手拼文本格式）。埋点 API：
- Metrics.record_tool_execution(tool_name, success, duration_s)
- Metrics.record_llm_call(provider, model, success, duration_s)
- Metrics.record_memory_recall(source, latency_s)
- Metrics.record_pipeline_step(step_name, status, duration_ms)  # 后处理管线
- Metrics.record_pipeline_run(mode, duration_s)  # 整轮管线耗时（blocking/background）
- Metrics.observe_state(state)  # 运行态 gauges 快照（/metrics 抓取时）
- Metrics.observe_pools()  # 连接池 / 共享线程池 gauges 快照
- Metrics.record_db_connection_created/closed(db_path)  # 连接创建/销毁频率
- Metrics.record_index_snapshot(db, count, duration_ms)  # 索引快照（P0-3）
- Metrics.record_hot_query_plan(db, query_id, indexed, duration_ms)  # 热点查询计划
- Metrics.observe_caches()  # 缓存命中率 gauges 快照（P1-6）
- Metrics.record_http_request(method, route, status, duration_s)  # HTTP 时长（P1-6）
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

        # ── 索引可观测（P0-3：此前"索引命中"物理上不可测）──
        # snapshot 类 gauge 是"启动期采集结果"（每库一个值），不是"抓取时快照"：
        # 采集要跑 PRAGMA index_list/index_info + EXPLAIN QUERY PLAN，不适合挂在
        # /metrics 请求路径上（抓取频率无关地白烧）。
        self.db_indexes_total = Gauge(
            "neurova_db_indexes_total",
            "Indexes present in a database (startup snapshot)",
            ["db"],
        )
        self.db_index_snapshot_ms = Gauge(
            "neurova_db_index_snapshot_milliseconds",
            "Cost of collecting the index snapshot for a database",
            ["db"],
        )
        self.hot_query_indexed = Gauge(
            "neurova_hot_query_indexed",
            "Whether a whitelisted hot query uses an index (1/0)",
            ["db", "query_id"],
        )
        self.hot_query_explain_ms = Gauge(
            "neurova_hot_query_explain_milliseconds",
            "EXPLAIN QUERY PLAN cost per whitelisted hot query",
            ["db", "query_id"],
        )

        # ── HTTP 请求时长（P1-6：旧审计 §7 的 p50/p99 基线此前完全空白）──
        self.http_requests_total = Counter(
            "neurova_http_requests_total",
            "HTTP requests by method/route/status",
            ["method", "route", "status"],
        )
        self.http_request_seconds = Histogram(
            "neurova_http_request_seconds",
            "HTTP time to response headers in seconds",
            ["method", "route", "status"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
        )

        # ── 缓存命中率（P1-6：MemoryCache 有 hit_rate 但从未导出）──
        self.cache_hit_rate = Gauge(
            "neurova_cache_hit_rate",
            "Cache hit rate of registered in-process caches",
            ["cache"],
        )
        self.cache_entries = Gauge(
            "neurova_cache_entries",
            "Current entry count of registered in-process caches",
            ["cache"],
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

        # ── 对话后处理管线（PostChatPipeline）──
        # 尾延迟最大来源：20+ 步串行/后台步骤此前零埋点——无 histogram 无
        # 失败计数，优化收益无法验证。status 取 executed/skipped/failed/
        # degraded（StepStatus 值域），失败率与耗时分位均由此可得。
        self.pipeline_steps_total = Counter(
            "neurova_pipeline_steps_total",
            "Post-chat pipeline step executions",
            ["step_name", "status"],
        )
        self.pipeline_step_seconds = Histogram(
            "neurova_pipeline_step_seconds",
            "Post-chat pipeline step duration",
            ["step_name"],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
        )
        self.pipeline_run_seconds = Histogram(
            "neurova_pipeline_run_seconds",
            "Post-chat pipeline end-to-end duration",
            ["mode"],
            buckets=(0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
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

    # ── 后处理管线（Issue #55 P0）──

    def record_pipeline_step(
        self, step_name: str, status: str, duration_ms: float
    ) -> None:
        """后处理管线单步埋点（step_name × status 计数 + 耗时 histogram）。"""
        try:
            self.pipeline_steps_total.labels(
                step_name=step_name, status=str(status or "unknown")
            ).inc()
            self.pipeline_step_seconds.labels(step_name=step_name).observe(
                max(0.0, float(duration_ms or 0.0)) / 1000.0
            )
        except Exception:
            logger.debug("pipeline step metrics record failed", exc_info=True)

    def record_pipeline_run(self, mode: str, duration_s: float) -> None:
        """整轮管线耗时（mode=blocking/background，验证后台化收益）。"""
        try:
            self.pipeline_run_seconds.labels(mode=str(mode or "unknown")).observe(
                max(0.0, float(duration_s or 0.0))
            )
        except Exception:
            logger.debug("pipeline run metrics record failed", exc_info=True)

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

    # ── 索引可观测（P0-3）──

    def record_index_snapshot(self, db_path: str, index_count: int, duration_ms: float) -> None:
        """索引快照采集结果（dbx 维度）。"""
        try:
            self.db_indexes_total.labels(db=str(db_path)).set(int(index_count))
            self.db_index_snapshot_ms.labels(db=str(db_path)).set(float(duration_ms))
        except Exception:
            logger.debug("index snapshot metric failed", exc_info=True)

    def record_hot_query_plan(
        self, db_path: str, query_id: str, indexed: bool, duration_ms: float,
        available: bool = True,
    ) -> None:
        """热点查询走索引判定。available=False（表不存在等）时不写值——
        不把"测不出来"混成"没走索引"（那会让告警常年误报）。
        """
        if not available:
            return
        try:
            self.hot_query_indexed.labels(
                db=str(db_path), query_id=str(query_id)
            ).set(1 if indexed else 0)
            self.hot_query_explain_ms.labels(
                db=str(db_path), query_id=str(query_id)
            ).set(float(duration_ms))
        except Exception:
            logger.debug("hot query plan metric failed", exc_info=True)

    # ── HTTP 请求时长（P1-6）──

    def record_http_request(
        self, method: str, route: str, status: int, duration_s: float
    ) -> None:
        """HTTP 请求埋点。duration 为"响应头就绪"耗时（TTFB）：

        按"整个响应写完"计时会把 SSE/流式对话的流存活时间算成服务延迟
        （chat 流可挂数分钟），p99 直接被流长污染、失去诊断意义。
        """
        try:
            labels = {
                "method": str(method or "?"),
                "route": str(route or "__unmatched__"),
                "status": str(int(status)),
            }
            self.http_requests_total.labels(**labels).inc()
            self.http_request_seconds.labels(**labels).observe(max(0.0, float(duration_s or 0.0)))
        except Exception:
            logger.debug("http request metric failed", exc_info=True)

    # ── 缓存命中率（P1-6）──

    def observe_caches(self) -> None:
        """缓存命中率快照（/metrics 抓取时调用）。

        只读"已创建的"缓存实例——抓指标绝不懒建缓存（与 iter_pools 同一原则）。
        """
        try:
            # 单一注册表：memory/core/cache.py 持有，core/cache.py 的全局实例
            # 也登记进同一张表（两个生产者各自迭代会重复计数）
            from neurova.memory.core.cache import iter_caches

            for name, stats in iter_caches():
                try:
                    self.cache_hit_rate.labels(cache=str(name)).set(
                        float(stats.get("hit_rate", 0.0))
                    )
                    self.cache_entries.labels(cache=str(name)).set(
                        int(stats.get("size", 0))
                    )
                except Exception:  # noqa: BLE001 - 单缓存异常不影响其余
                    logger.debug("cache gauge failed: %s", name, exc_info=True)
        except Exception:
            logger.debug("cache gauges update failed", exc_info=True)

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
            from neurova.core.thread_pool import (
                DEFAULT_POOL_NAME,
                iter_pools as _iter_thread_pools,
            )

            for name, pool in _iter_thread_pools():
                try:
                    # 默认池沿用旧 label "shared"（抓取配置/告警按它写过，
                    # 改名会让面板静默失联）；具名池才用真实池名。
                    label = "shared" if str(name) == DEFAULT_POOL_NAME else str(name)
                    self.thread_pool_threads.labels(pool=label).set(
                        len(getattr(pool, "_threads", ()) or ())
                    )
                    queue = getattr(pool, "_work_queue", None)
                    self.thread_pool_queue_depth.labels(pool=label).set(
                        queue.qsize() if queue is not None else 0
                    )
                    self.thread_pool_max_workers.labels(pool=label).set(
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


def record_index_snapshot(db_path: str, index_count: int, duration_ms: float) -> None:
    """模块级便捷入口（索引快照埋点）。"""
    get_metrics().record_index_snapshot(db_path, index_count, duration_ms)


def record_hot_query_plan(
    db_path: str, query_id: str, indexed: bool, duration_ms: float, available: bool = True
) -> None:
    """模块级便捷入口（热点查询计划埋点）。"""
    get_metrics().record_hot_query_plan(db_path, query_id, indexed, duration_ms, available)


def generate_metrics_text() -> str:
    """输出 Prometheus 文本格式（/metrics 端点用；REGISTRY 含全部已注册指标）。"""
    from prometheus_client import generate_latest

    return generate_latest(REGISTRY).decode("utf-8")
