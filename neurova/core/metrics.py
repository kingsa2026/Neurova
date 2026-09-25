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
- Metrics.observe_context_pools()  # 上下文池常驻/回收 gauges 快照
- Metrics.record_db_connection_created/closed(db_path)  # 连接创建/销毁频率
- Metrics.record_index_snapshot(db, count, duration_ms)  # 索引快照（P0-3）
- Metrics.record_hot_query_plan(db, query_id, indexed, duration_ms)  # 热点查询计划
- Metrics.observe_caches()  # 缓存命中率 gauges 快照（P1-6）
- Metrics.record_http_request(method, route, status, duration_s)  # HTTP 时长（P1-6）
- Metrics.record_tool_turn_provider_reject(reason)  # 工具轮配对非法 400（T-10d 归零判据）
- Metrics.observe_context_health(state)  # 上下文域健康读数快照（T-10d）
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

        # ── 能力缺口（T-03）──
        # "自主造能力的入口"由用户措辞改挂到能力缺口之后，缺口本身必须可测：
        # 没有这个计数，"入口没被触发"与"入口根本没接电"在观测上同形。
        self.capability_gap_total = Counter(
            "neurova_capability_gap_total",
            "Capability-gap signals observed by the agent turn",
            ["kind"],
        )

        # T-10d（工单 §11.5）：工具轮进视图的**唯一硬失败信号** —— 灰度期
        # provider 400（配对非法）必须归零。此前该信号完全不可观测：连"发生了
        # 几次配对非法导致的 400"都无从回答，归零判据便无从成立。
        self.tool_turn_provider_rejects_total = Counter(
            "neurova_tool_turn_provider_rejects_total",
            "Provider 400 rejections caused by illegal tool-turn pairing",
            ["reason"],
        )
        # 上下文域健康读数（ledger/summarizer/fold_integrity/turn_identity/
        # microcompact/tool_turns）。抓取时按 agent 快照，不常驻埋点。
        # 此前 `get_context_health()` 在**生产代码里零读者**（只在测试与 manual
        # 脚本里被读）——"写了但没人读"正是协作红线点名的断点形态。
        self.context_health_value = Gauge(
            "neurova_context_health_value",
            "Context-domain health readout (scrape-time snapshot by agent)",
            ["agent", "kind", "field"],
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

        # ── 上下文池（Issue #65：池是永久归档只增不减，此前"常驻规模/回收
        # 计数/读路径耗时"在观测面上完全空白——内存随会话时长单调累积无人可见）──
        # gauge 是运行态快照（/metrics 抓取时经 observe_context_pools() 刷新）；
        # 读路径直方图是常驻埋点（在 ContextPool.query 内 observe）。
        self.context_pool_entries = Gauge(
            "neurova_context_pool_entries",
            "Resident entries of live context pools (scrape-time snapshot)",
            ["pool"],
        )
        self.context_pool_evicted_total = Gauge(
            "neurova_context_pool_evicted_total",
            "Entries archived out of resident set by capacity/TTL",
            ["pool", "reason"],
        )
        # B4/005（判据 A9）：持久归档规模。启动只登记一次（常数次查询、零预载），
        # 之后由本进程写入/清理增量维护——"磁盘上躺了多少归档"此前在观测面上空白。
        self.context_pool_ledger_rows = Gauge(
            "neurova_context_pool_ledger_rows",
            "Archived rows in the persistent ledger of live context pools",
            ["pool"],
        )
        self.context_pool_query_seconds = Histogram(
            "neurova_context_pool_query_seconds",
            "ContextPool.query() duration by phase",
            ["phase"],
            buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5),
        )
        # 热点路径 child 句柄缓存（惰性构造，见 observe_context_pool_query）
        self._context_pool_query_children = None

        # ── 链路完整性读数（工单 010 / 006 残留）──
        # 两个计数器此前只写不读：`creation_governance.missing_context_count` 在
        # `neurova/` 内零生产消费方、`SkillRegistry._name_collision_count` 只见于
        # 日志。抓取时快照（与池/缓存同款，不新开端点）把它们接到既有观测面。
        self.ticket_context_missing = Gauge(
            "neurova_ticket_context_missing",
            "Tool executions dropped because no turn ticket context existed",
        )
        self.skill_name_collisions = Gauge(
            "neurova_skill_name_collisions",
            "Registry entries shadowed by another skill registering the same name",
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

    def observe_context_pool_query(
        self, partition_s: float = 0.0, ttl_s: float = 0.0, keyword_s: float = 0.0
    ) -> None:
        """ContextPool.query() 阶段耗时（Issue #65）。

        热点路径，故 child 句柄惰性缓存：实测 ``labels().observe()`` 每次
        ~1.8µs，缓存后 ~0.7µs——三次打点从 ~5.4µs 降到 ~2µs。
        """
        try:
            children = self._context_pool_query_children
            if children is None:
                children = {
                    phase: self.context_pool_query_seconds.labels(phase=phase)
                    for phase in ("partition", "ttl", "keyword")
                }
                self._context_pool_query_children = children
            children["partition"].observe(max(0.0, float(partition_s)))
            children["ttl"].observe(max(0.0, float(ttl_s)))
            children["keyword"].observe(max(0.0, float(keyword_s)))
        except Exception:  # noqa: BLE001 - 观测失败不得影响取数
            logger.debug("context pool query metric failed", exc_info=True)

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

    def observe_capability_gap(self, kinds) -> None:
        """能力缺口命中埋点（按类别累加）。"""
        try:
            for kind in kinds or []:
                self.capability_gap_total.labels(kind=str(kind)).inc()
        except Exception:  # noqa: BLE001 - 观测失败不得影响对话主链
            logger.debug("capability gap metric failed", exc_info=True)

    def record_tool_turn_provider_reject(self, reason: str) -> None:
        """工具轮配对非法导致的 provider 400 计数（归零判据的唯一读数）。"""
        try:
            self.tool_turn_provider_rejects_total.labels(reason=str(reason)).inc()
        except Exception:  # noqa: BLE001 - 观测失败不得影响错误上抛路径
            logger.debug("tool turn reject metric failed", exc_info=True)

    def observe_context_health(self, state: Any = None) -> None:
        """上下文域健康读数快照（/metrics 抓取时调用）。

        逐 agent 读它自己的编排器（`agent.context_orchestrator.get_context_health()`）
        —— 读数是编排器**单源**持有的那份，不在这里重算、也不新造一份账。
        只读已存在的编排器（与 `observe_caches` 同原则：抓取绝不懒建对象）。

        非数值字段（`last_error` 之类的点名串）不落 gauge：把它们塞进数字会让
        读数变成不可判读的编码。故这里只搬数值，异常一律隔离（单个 agent 失败
        不影响其余）。

        **`bool` 是数值**（`bool` 是 `int` 的子类）：`enabled` 这类降级位天然是
        0/1 gauge，必须照搬。改前过滤条件把布尔与字符串合成了一条
        （`isinstance(value, bool) or not isinstance(value, (int, float))`），
        副作用是**所有降级位在生产读数上消失** —— 健康 agent 与装配失败的 agent
        在 `/metrics` 上长得一模一样（都只有 `attempts=1`），P2-5 的"能力被关掉
        与这轮本来不需要长得一样"于是换了一层皮（Issue #90 探针 P10）。
        真正要排除的是字符串，那一条判据本身没错；收窄的只是布尔。
        """
        agents = getattr(state, "agents", None) if state is not None else None
        if not isinstance(agents, dict):
            return
        for agent_id, agent in list(agents.items()):
            orchestrator = getattr(agent, "context_orchestrator", None)
            if orchestrator is None or not hasattr(orchestrator, "get_context_health"):
                continue
            try:
                health = orchestrator.get_context_health()
            except Exception:  # noqa: BLE001 - 读数失败不影响其它 agent
                logger.debug("context health readout failed: %s", agent_id, exc_info=True)
                continue
            for kind, slot in (health or {}).items():
                if not isinstance(slot, dict):
                    continue
                for field, value in slot.items():
                    # 只排除非数值（点名串）。布尔**不排除** —— 它是 int 的子类，
                    # 降级位（enabled）正是 0/1 gauge 的标准形态。
                    if not isinstance(value, (int, float)):
                        continue
                    try:
                        self.context_health_value.labels(
                            agent=str(agent_id), kind=str(kind), field=str(field)
                        ).set(float(value))
                    except Exception:  # noqa: BLE001
                        logger.debug("context health gauge failed: %s", field, exc_info=True)

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

    def observe_context_pools(self) -> None:
        """上下文池运行态 gauge 快照（/metrics 抓取时调用）。

        只读"已创建的"池实例（与 observe_caches 同原则：抓指标绝不懒建池）。
        标签用池隔离键（user:agent:session）——池是永久归档、条数不再受
        max_size 约束，唯一能反映"内存是否无界增长"的就是这个 gauge。
        """
        try:
            from neurova.context_pool import iter_live_pools
        except Exception:  # pragma: no cover - 模块不可用时指标保持空
            logger.debug("context pool gauges skipped (import failed)", exc_info=True)
            return

        seen = set()
        for pool in iter_live_pools():
            try:
                key = str(getattr(pool, "isolation_key", None) or id(pool))
                seen.add(key)
                self.context_pool_entries.labels(pool=key).set(
                    int(pool.resident_count())
                )
                stats = pool.get_retention_stats()
                for reason, value in (stats.get("archived_by_reason") or {}).items():
                    self.context_pool_evicted_total.labels(pool=key, reason=str(reason)).set(int(value))
                self.context_pool_ledger_rows.labels(pool=key).set(
                    int((stats.get("ledger") or {}).get("rows") or 0)
                )
            except Exception:  # noqa: BLE001 - 单个池异常不影响其它池
                logger.debug("context pool gauge failed", exc_info=True)

        # 池销毁后不留陈旧时间线（只增的 gauge 系列会误导容量判断）
        try:
            for label_set in list(self.context_pool_entries._metrics.keys()):  # noqa: SLF001
                if str(label_set) not in seen:
                    self.context_pool_entries.remove(label_set)
        except Exception:  # noqa: BLE001
            logger.debug("context pool gauge cleanup failed", exc_info=True)

    def observe_chain_integrity(self) -> None:
        """链路完整性读数快照（/metrics 抓取时调用）。

        数值一律取自计数器本体（单一事实源），抓取时绝不为了读数而创建对象：
        技能注册表尚未创建时读数保持 0，不懒建注册表。
        """
        try:
            from neurova.skills.creation_governance import missing_context_count

            self._safe_set(self.ticket_context_missing, missing_context_count,
                           "ticket_context_missing")
        except Exception:  # noqa: BLE001 - 单读数失败不影响另一个
            logger.debug("ticket context gauge failed", exc_info=True)

        def _collisions() -> int:
            from neurova.skill_system import registered_collision_count

            return registered_collision_count()

        self._safe_set(self.skill_name_collisions, _collisions, "skill_name_collisions")

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


def observe_capability_gap(kinds) -> None:
    """模块级埋点入口（与 `record_db_connection_created` 等同形式）。"""
    get_metrics().observe_capability_gap(kinds)


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


def record_tool_turn_provider_reject(reason: str) -> None:
    """模块级便捷入口（工具轮配对非法 400 埋点）。"""
    get_metrics().record_tool_turn_provider_reject(reason)


def record_hot_query_plan(
    db_path: str, query_id: str, indexed: bool, duration_ms: float, available: bool = True
) -> None:
    """模块级便捷入口（热点查询计划埋点）。"""
    get_metrics().record_hot_query_plan(db_path, query_id, indexed, duration_ms, available)


def generate_metrics_text() -> str:
    """输出 Prometheus 文本格式（/metrics 端点用；REGISTRY 含全部已注册指标）。"""
    from prometheus_client import generate_latest

    return generate_latest(REGISTRY).decode("utf-8")
