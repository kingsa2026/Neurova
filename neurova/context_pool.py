from __future__ import annotations

"""
上下文池 - Context Pool

提供上下文重组、精炼、转换能力，支持：
- 对话语义理解与重组
- 记忆检索结果整合
- 工具调用及结果处理
- 多模态能力转换
- 模型切换时的上下文适配
"""

import threading
import time
import weakref
from contextlib import contextmanager

from neurova.core.logger import get_logger
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)

# 进程内已创建池的弱引用登记表（Issue #65 埋点）：
# /metrics 抓取时需要枚举"活着的池"来暴露常驻条数/回收计数。弱引用保证
# 登记本身不延长池生命周期（池被回收即自动出表），与 observe_caches 的
# "只读已创建实例、绝不懒建"原则一致。
_LIVE_POOLS: "weakref.WeakSet" = weakref.WeakSet()
_LIVE_POOLS_LOCK = threading.Lock()


def iter_live_pools():
    """当前存活 ContextPool 的快照列表（弱引用，复制后返回防迭代期变更）。"""
    with _LIVE_POOLS_LOCK:
        return list(_LIVE_POOLS)


class ContextPool:
    """
    上下文池 - 核心组件

    提供上下文收集、重组、转换、压缩的统一接口。
    支持模型切换时的上下文适配。

    支持三层隔离机制：
    - 用户隔离：不同用户的上下文完全隔离
    - Agent隔离：不同Agent的上下文完全隔离
    - Session隔离：不同Session的上下文完全隔离

    回收契约（Issue #65 显式化；此前只有注释里的暗示）：

    1. **归档层（本池）语义是"永不丢失"**：不按容量驱逐。``max_size`` 自
       「无损归档」改造后**已失效**（保留参数仅为向后兼容），超过它不再驱逐，
       首次越界会 warning 一次以免误导。``max_tokens`` 只约束视图层预算。
    2. **常驻上限（可选）**：``resident_limit``（默认 None=不限制，零行为变化）。
       显式启用后，常驻条目超出上限即把最旧条目移出常驻列表（全文早已在持久
       台账里，见下条），``recall_evicted()`` 仍可召回 —— 无损性由持久台账承载。
       ⚠️ 未注入 ``ledger_db`` 时自动禁用（内存台账仅有界 500 条，会静默丢全文）。
    2b. **持久化（``ledger_db``，SQLite WAL+FTS5）**：写入咽喉 ``add_context``
       落常驻即写穿台账——**不**依赖驱逐（生产构造面下 ``resident_limit=None``
       且 ``ttl_seconds=0``，驱逐路径根本不可达）。这样"归档跨重启为真"才成立：
       进程退出后，新进程同库 ``recall_evicted()`` 取回原文。
       写失败不阻断内存归档，但经 ``get_retention_stats()["ledger_persistence"]``
       显式上报（计数 + 点名原因），不静默。
    3. **TTL**：``ttl_seconds>0`` 时过期条目经 ``cleanup_expired()`` / 查询过滤
       剔除（先归档再剔除）；``0`` = 永不过期（生产 orchestrator 走此档）。
    4. **视图预算**：``draw()`` / Drawer 决定"这次取多少"，与常驻规模解耦。

    契约可观测：``get_retention_stats()`` + ``/metrics`` 的
    ``neurova_context_pool_*`` 系列（读路径耗时直方图 / 常驻条数 / 回收计数）。
    """

    def __init__(
        self,
        user_id: str = None,
        agent_id: str = None,
        session_id: str = None,
        max_tokens: int = 16000,
        auto_tag: bool = False,
        max_size: int = 100,
        ttl_seconds: int = 3600,
        ledger_db=None,
        summarizer=None,
        resident_limit: Optional[int] = None,
    ):
        """
        初始化上下文池

        Args:
            user_id: 用户ID（必需）
            agent_id: Agent ID（必需）
            session_id: 会话ID（可选）
            max_tokens: 最大Token数量
            auto_tag: 是否启用自动标签生成
            max_size: **[已失效]** 历史容量参数（默认100）。「无损归档」改造后
                不再驱逐，保留仅为向后兼容（首越界 warning 一次）；新的常驻
                上限请用 ``resident_limit``。
            ttl_seconds: 上下文过期时间（秒，默认3600）；0=永不过期
            resident_limit: 常驻条数上限（默认 None=不限制）。显式启用且注入了
                ``ledger_db`` 时，超限的最旧条目从常驻列表移除
                （无损归档语义由持久台账承载，全文随入池即已落库）；未注入台账时
                自动禁用。

        Raises:
            ValueError: 如果 user_id 或 agent_id 未提供
        """
        # 验证隔离参数
        if user_id is None:
            raise ValueError("user_id is required")
        if agent_id is None:
            raise ValueError("agent_id is required")

        # 验证ID不包含分隔符
        separator = ":"
        if separator in user_id:
            raise ValueError("user_id 不能包含分隔符")
        if separator in agent_id:
            raise ValueError("agent_id 不能包含分隔符")
        if session_id and separator in session_id:
            raise ValueError("session_id 不能包含分隔符")

        self.user_id = user_id
        self.agent_id = agent_id
        self.session_id = session_id
        # P0-2：本轮会话作用域（"direct" / "room:<房间 id>"）。由编排层每轮在归档
        # 之前设置；`_inject_isolation_tags` 用它给**全部**写入方打 `chat_scope`
        # ——这是池的唯一写入咽喉，故 swarm / voice_context / 摘要回写 / merge
        # 等旁路写入方无需各自接线即可继承正确作用域。
        self.turn_scope: Optional[str] = None
        self.max_tokens = max_tokens
        self.auto_tag = auto_tag
        # [兼容保留] max_size 在「无损归档」改造后不再驱逐（见类文档"回收契约"）
        self.max_size = max_size
        self._max_size_warned = False
        # 常驻上限（默认 None=不限制，零行为变化）——显式启用才回收
        self.resident_limit = resident_limit if (resident_limit and resident_limit > 0) else None
        # 回收契约计数（get_retention_stats / /metrics 曝光；Issue #65 埋点）
        self._resident_evicted_total = 0
        self._ttl_evicted_total = 0
        self._replaced_total = 0
        self.ttl_seconds = ttl_seconds

        self._collector = ContextCollector(max_tokens)
        self._converter = ContextConverter()
        self._compressor = ContextCompressor(max_tokens)

        # 活水上下文池新增组件
        self._drawer = SemanticMatchDrawer(max_tokens)
        self._deduplicator = DriftSafeDeduplicator()

        # 自动标签生成器
        if auto_tag:
            self._auto_tagger = AutoTagger()

        # 缓存机制
        self._cache = {}
        self._cache_version = 0
        self._last_build_version = -1

        # Scroll Context 式被驱逐轮次台账（方案 P1-2.2）：
        # 容量/TTL 驱逐不再直接丢弃，而是归档到有界台账供按需召回
        self._eviction_ledger: List[Any] = []
        self._evicted_total = 0
        self._max_eviction_ledger = 500
        # D11：台账 GC 节流计数——触发点是**归档提交**（真有调用方），不再挂在
        # 生产不可达的驱逐路径上（改前 _LEDGER_GC_EVERY 只被 _archive_evicted
        # 递增，而它在生产构造面 resident_limit=None / ttl_seconds=0 下永不执行）。
        self._ledger_gc_counter = 0
        # D11：清理的可观测面（触发次数 / 清理条数 / 点名失败原因）。
        # 清理会改变库规模，静默执行等于"保留策略生效"无从核对。
        self._ledger_gc_runs = 0
        self._ledger_gc_removed = 0
        self._ledger_gc_last_error: Optional[str] = None

        # 并发保护：保护 _cache / _cache_version / _collector._contexts 等共享状态
        # 使用 RLock 因为 merge_with 等方法会重入调用 add_context
        # 遵循 AGENTS.md "Thread safety: use threading.RLock for shared state"
        self._lock = threading.RLock()

        # RES-P2-1：hash→条目索引——add 去重与 ack 标记此前是全池 O(n) 线性扫
        # （每条消息追加/每轮 ack 都扫一遍，池为永久归档只增不减，随历史线性劣化）。
        # 列表被整体重排（TTL/compress/dedup/clear）时须调用 _rebuild_indexes 同步。
        self._by_hash: Dict[str, Any] = {}
        # B-8：turn_id→条目列表索引——mark_turn_seen 此前同为全池 O(n) 线性扫。
        self._by_turn: Dict[str, List[Any]] = {}
        # Issue #65：source/session 分区索引——query() 此前是全池线性扫（读路径
        # 瓶颈，池只增不减时随历史劣化），现按分区直取 + 关键字匹配降本。
        self._read_index = PoolReadIndex()

        # P1-1③：驱逐台账持久层 + 摘要压缩器（可选注入；None=保持内存行为）
        self._ledger_db = ledger_db
        self._summarizer = summarizer
        # B4/001：写穿计数——写失败必须显式可见（get_retention_stats 上报 + 点名原因）
        self._ledger_written = 0
        self._ledger_write_failed = 0
        self._ledger_last_error: Optional[str] = None
        # B4/003：批量归档——批内条目先在内存攒着，批结束时**一次事务**写库；
        # 批内任一条失败即整批回滚，本批条数整批计入 failed（不谎报 written）。
        self._ledger_batch: Optional[List[Any]] = None
        self._ledger_batches = 0
        # B4/005（规格 D10）：启动**只登记一次**库内归档条数（`COUNT(*)`，常数次查询、
        # 零常驻内存），**不预载**——D1 要的是"取得到"，不是"开局全在内存"。
        # 登记后由本进程的写入/清理增量维护；重启时重新登记即自愈。
        self._ledger_rows = 0
        self._ledger_registered = False
        self._ledger_register_error: Optional[str] = None
        if ledger_db is not None:
            self._registerLedgerRows()

        # Issue #65：常驻回收契约显式化——resident_limit 只接受"有持久台账"
        # 的组合，否则回收会把全文静默丢进仅 500 条的内存台账（等于破坏
        # "永不丢失"硬约束）。此处不做静默降级：显式告警，让配置错误可见。
        if self.resident_limit is not None and ledger_db is None:
            logger.warning(
                "ContextPool resident_limit=%s 已禁用：未注入 ledger_db，"
                "回收会丢全文（违反无损归档硬约束）。请注入渐进持久台账后再启用",
                self.resident_limit,
            )
            self.resident_limit = None

        with _LIVE_POOLS_LOCK:
            _LIVE_POOLS.add(self)

    @property
    def isolation_key(self) -> str:
        """生成隔离键（P0-2：作用域优先于 session_id，避免恒 `:default`）。"""
        session_part = self.turn_scope or self.session_id or "default"
        return f"{self.user_id}:{self.agent_id}:{session_part}"

    def add_context(self, context):
        with self._lock:
            # 根因 A 修复: 自动注入 session_id/agent_id/user_id 到 chunk.metadata
            # (用户显式传入的字段优先,不被覆盖)
            self._inject_isolation_tags(context)

            if self.auto_tag and hasattr(self, "_auto_tagger"):
                context = self._auto_tagger.auto_tag(context)

            # [FIX] 添加时去重：已存在相同 hash 的条目则跳过
            # （RES-P2-1：经 _by_hash 索引 O(1) 查找，旧实现全池线性扫）
            if context.hash:
                existing_entry = self._by_hash.get(context.hash)
                if existing_entry is not None:
                    # 若新条目优先级更高则替换，否则跳过
                    if context.priority > existing_entry.priority:
                        idx = self._collector._contexts.index(existing_entry)
                        self._collector._contexts[idx] = context
                        self._by_hash[context.hash] = context
                        # B-8：turn 索引随替换同步（旧条目可能换了 turn）
                        self._turn_index_remove(existing_entry)
                        self._turn_index_add(context)
                        # #65：读索引随替换同步（source/metadata 可能都变了）
                        self._read_index.remove(existing_entry)
                        self._read_index.add(context)
                        self._replaced_total += 1
                        self._cache_version += 1
                        logger.debug("ContextPool 替换条目: hash=%s, priority=%s→%s",
                                     context.hash[:8], existing_entry.priority, context.priority)
                    else:
                        logger.debug("ContextPool 跳过重复: hash=%s, source=%s",
                                     context.hash[:8], context.source.value if context.source else "?")
                    return

            # [无损归档] 归档层不按容量驱逐——池的定位是永久归档，"永不丢失
            # 上下文"是硬约束；容量控制发生在视图层（Drawer 按预算整条选取）。
            # Issue #65：max_size 已失效，首次越界告警一次（否则"设了没生效"
            # 只会在压测里被发现）；常驻上限改由显式 resident_limit 承载。
            self._collector.add_context(context)
            if context.hash:
                self._by_hash[context.hash] = context
            self._turn_index_add(context)
            self._read_index.add(context)
            self._cache_version += 1
            # B4/001：落常驻即写穿持久台账——这是池的**唯一写入咽喉**，
            # 驱逐路径不可达（生产构造面下 resident_limit=None、ttl_seconds=0），
            # 归档"永不丢失"必须靠本条通路跨重启为真。
            self._persist_archived(context)

            if (
                not self._max_size_warned
                and self.max_size
                and len(self._collector._contexts) > self.max_size
            ):
                self._max_size_warned = True
                logger.warning(
                    "ContextPool max_size=%s 已失效（无损归档不驱逐）：当前常驻 %s 条，"
                    "仅首次告警。需要常驻上限请用 resident_limit + ledger_db",
                    self.max_size, len(self._collector._contexts),
                )

            if self.resident_limit and len(self._collector._contexts) > self.resident_limit:
                self._enforce_resident_limit()

    def _enforce_resident_limit(self) -> None:
        """常驻上限回收（调用方须持 _lock）。

        仅当显式启用 ``resident_limit`` **且**注入了持久台账时可达（构造期
        已把无台账的组合降级为 None）。语义：

        - 最旧（_contexts 头部，插入序）条目移出常驻列表（全文已在持久台账，
          见 ``_persist_archived``；回收不参与落盘判定）；
        - 索引（hash/turn/read）同步摘除；
        - 容量上限收敛为「总量 - resident_limit」，一次调用即达标（批量
          append 后不会残留超限状态）。
        """
        overflow = len(self._collector._contexts) - self.resident_limit
        if overflow <= 0:
            return
        victims = list(self._collector._contexts[:overflow])
        for entry in victims:
            self._archive_evicted(entry)  # 进内存台账（全文已随入池写穿持久台账）
        del self._collector._contexts[:overflow]
        for entry in victims:
            if entry.hash:
                self._by_hash.pop(entry.hash, None)
            self._turn_index_remove(entry)
            # 逐条摘除（不整表重建）：回收发生在 add 热路径上，O(被回收数)
            # 而不是 O(常驻数)；分区内其余条目的相对顺序不变
            self._read_index.remove(entry)
        self._resident_evicted_total += len(victims)
        self._cache_version += 1
        logger.info(
            "ContextPool 常驻回收 %d 条（resident_limit=%s，累计回收 %d）",
            len(victims), self.resident_limit, self._resident_evicted_total,
        )

    def resident_count(self) -> int:
        """当前常驻条目数（/metrics 用；只读不加锁）。"""
        return len(self._collector._contexts)

    def get_retention_stats(self) -> Dict[str, Any]:
        """回收契约可观测面（Issue #65）：常驻规模 + 各原因回收计数。"""
        archived = {
            "capacity": self._resident_evicted_total,
            "ttl": self._ttl_evicted_total,
            "replaced": self._replaced_total,
        }
        return {
            "resident_count": len(self._collector._contexts),
            "max_size": self.max_size,
            "max_size_effective": False,  # 无损归档：容量参数已失效（显式上报）
            "resident_limit": self.resident_limit,
            "ttl_seconds": self.ttl_seconds,
            "archived_by_reason": archived,
            "archived_total": sum(archived.values()),
            "eviction_ledger": {
                "size": len(self._eviction_ledger),
                "capacity": self._max_eviction_ledger,
                "total": self._evicted_total,
            },
            "read_index": self._read_index.stats(),
            # B4/005（A9）：持久库规模读数。启动只登记一次（常数次查询、零预载），
            # 之后由本进程写入/清理增量维护；重启重新登记即自愈。
            "ledger": {
                "enabled": self._ledger_db is not None,
                "rows": self._ledger_rows,
                "registered_at_startup": self._ledger_registered,
                "last_error": self._ledger_register_error,
            },
            "ledger_persistence": {
                "enabled": self._ledger_db is not None,
                "written": self._ledger_written,
                "failed": self._ledger_write_failed,
                "batches": self._ledger_batches,
                "pending": len(self._ledger_batch) if self._ledger_batch is not None else 0,
                "last_error": self._ledger_last_error,
            },
            # D11（A5）：保留策略的执行面。runs=触发次数、removed=清理条数；
            # 缺了它只能靠读库反推"超限有没有被清"，等于不可观测。
            "ledger_gc": {
                "runs": self._ledger_gc_runs,
                "removed": self._ledger_gc_removed,
                "keep_count": getattr(self._ledger_db, "keep_count", None),
                "keep_days": getattr(self._ledger_db, "keep_days", None),
                "last_error": self._ledger_gc_last_error,
            },
        }

    @staticmethod
    def _entry_turn_id(entry) -> Optional[str]:
        return (entry.metadata or {}).get("turn_id")

    def _turn_index_add(self, entry) -> None:
        tid = self._entry_turn_id(entry)
        if not tid:
            return
        self._by_turn.setdefault(tid, []).append(entry)

    def _turn_index_remove(self, entry) -> None:
        tid = self._entry_turn_id(entry)
        if not tid:
            return
        bucket = self._by_turn.get(tid)
        if bucket is None:
            return
        try:
            bucket.remove(entry)
        except ValueError:
            pass
        if not bucket:
            self._by_turn.pop(tid, None)

    def _rebuild_indexes(self) -> None:
        """整体重排 _contexts 后重建 hash/turn/read 三索引（调用方须持 _lock）。"""
        self._by_hash = {c.hash: c for c in self._collector._contexts if c.hash}
        self._by_turn = {}
        for c in self._collector._contexts:
            self._turn_index_add(c)
        # #65：source/session 分区随整体重排同步（顺序也被重建，故不保留旧分区）
        self._read_index.rebuild(self._collector._contexts)

    def _inject_isolation_tags(self, context) -> None:
        """把作用域与归属标签注入 chunk.metadata（池的唯一写入咽喉）。

        标签三件套 + 作用域：
        - `chat_scope`：读侧隔离闸口（`memory_scope.filter_by_scope`）的唯一判据。
          缺它则 `scope_from_metadata` 恒判 direct —— 隔离契约形同虚设。
        - `session_id` / `agent_id` / `user_id`：隔离键与查询分区用。

        用户显式传入的字段优先，不被覆盖（本轮显式作用域 > 池的轮次作用域）。
        """
        if context.metadata is None:
            context.metadata = {}
        # 仅在缺失时注入, 尊重用户显式传入的值
        if "chat_scope" not in context.metadata and self.turn_scope:
            context.metadata["chat_scope"] = self.turn_scope
        if "session_id" not in context.metadata and self.session_id is not None:
            context.metadata["session_id"] = self.session_id
        if "agent_id" not in context.metadata and self.agent_id is not None:
            context.metadata["agent_id"] = self.agent_id
        if "user_id" not in context.metadata and self.user_id is not None:
            context.metadata["user_id"] = self.user_id

    def query(
        self,
        query: str = None,
        source=None,
        session_id: str = None,
        tags: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Any]:
        """按需调取上下文(默认当前 session 优先)

        Args:
            query: 关键词过滤(不区分大小写, content 包含即可)
            source: 按 ContextSource 过滤
            session_id: 按 metadata.session_id 过滤(用于跨池/跨 session 调取)
            tags: 按 tags 列表过滤(任一匹配即可)
            limit: 最多返回条数

        默认行为:
            1. 若显式传 session_id → 只返回该 session 的 chunk
            2. 若未传 session_id 但 pool 有 session_id → 当前 session 优先,
               限流后剩余名额由跨 session chunk 兜底
            3. 若 pool 无 session_id → 按 priority 降序(向后兼容)

        Returns:
            List[ContextInput], 当前 session 优先, 同 session 内按 priority 降序

        Issue #65 读路径优化（语义与旧实现逐字等价，见 tests/unit/context/
        test_context_pool_query_index.py 的等价性穷举）：

        - **分区直取**：``source`` / ``session_id`` 走 ``_read_index``
          分区（O(k)），不再「全池遍历 + 逐条比较」；
        - **关键字降本**：无大小写差异的关键词（中文/数字/符号）直接
          ``needle in content``，省掉逐条 ``lower()`` 分配（旧实现的
          主要成本）；含大小写差异时仍走精确的小写比较；
        - 仍保留 TTL 过滤与「当前 session 优先 + priority 降序」语义。
        """
        explicit_session = session_id is not None
        partition_key = session_id if explicit_session else self.session_id
        # "当前 session 优先 + 跨 session 兜底"只在未显式指定 session 且池有
        # session 时成立；其余两条路径是单组取数。
        session_priority = (not explicit_session) and self.session_id is not None

        t0 = time.perf_counter()
        with self._lock:
            # 索引同步防线：_contexts 被绕过公开 API 直接增删时（测试/历史写法）
            # 计数漂移即重建，保证与"读实时列表"的旧语义一致。
            self._read_index.ensure_synced(self._collector._contexts)
            index = self._read_index

            if partition_key is None:
                # 池无 session 概念（且未显式指定）：全池候选（向后兼容路径）
                primary = list(self._collector._contexts)
            elif explicit_session:
                # 显式 session：严格限定该分区（跨池/跨 session 调取的既有语义）
                primary = list(index.session_entries(partition_key))
            else:
                # 未显式指定：取本池 session 分区（分区直取，不再全池遍历）
                primary = list(index.session_entries(partition_key))

            # source 过滤：source 分区与 session 分区取交（从较小一侧出发）
            if source is not None:
                primary = self._intersect_partitions(primary, index.source_entries(source))
        partition_seconds = time.perf_counter() - t0

        ttl_seconds = 0.0
        keyword_seconds = 0.0

        t1 = time.perf_counter()
        primary = self._filter_ttl(primary)
        ttl_seconds += time.perf_counter() - t1

        # 关键词过滤（语义与旧实现一致：不区分大小写的子串包含）
        t2 = time.perf_counter()
        if query:
            caseless = self._read_index.is_caseless(query)
            needle = query if caseless else query.lower()
            matcher = self._read_index.keyword_matches
            primary = [c for c in primary if matcher(c, needle, caseless)]
        keyword_seconds += time.perf_counter() - t2

        # tags 过滤
        if tags:
            tag_set = set(tags)
            primary = [c for c in primary if tag_set.intersection(set(c.tags or []))]

        # 单组路径：显式 session / 无 session 概念 → 按 priority 降序（向后兼容）
        if not session_priority:
            primary.sort(key=lambda c: c.priority, reverse=True)
            self._observe_query(partition_seconds, ttl_seconds, keyword_seconds)
            return primary[:limit]

        # 当前 session 优先 / 跨 session 兜底。
        # 短路：当前 session 侧已够填满 limit 时，兜底侧不可能进入结果——
        # 直接跳过"其余 session 分区"的组装与过滤（大池下这是主要成本）。
        primary.sort(key=lambda c: c.priority, reverse=True)
        if len(primary) >= limit:
            self._observe_query(partition_seconds, ttl_seconds, keyword_seconds)
            return primary[:limit]

        t3 = time.perf_counter()
        with self._lock:
            secondary = [
                entry
                for key, entries in self._read_index.session_partitions()
                if key != partition_key
                for entry in entries
            ]
            if source is not None:
                secondary = self._intersect_partitions(
                    secondary, self._read_index.source_entries(source)
                )
        partition_seconds += time.perf_counter() - t3

        t4 = time.perf_counter()
        secondary = self._filter_ttl(secondary)
        ttl_seconds += time.perf_counter() - t4

        t5 = time.perf_counter()
        if query:
            matcher = self._read_index.keyword_matches
            secondary = [c for c in secondary if matcher(c, needle, caseless)]
        if tags:
            tag_set = set(tags)
            secondary = [c for c in secondary if tag_set.intersection(set(c.tags or []))]
        keyword_seconds += time.perf_counter() - t5

        secondary.sort(key=lambda c: c.priority, reverse=True)
        merged = primary + secondary
        self._observe_query(partition_seconds, ttl_seconds, keyword_seconds)
        return merged[:limit]

    @staticmethod
    def _intersect_partitions(group: List[Any], source_entries: List[Any]) -> List[Any]:
        """两个分区列表取交（从元素更少的一侧出发，用 id 集合判定成员）。

        分区索引保证每个条目在每维度只出现一次，故交集即"既属该 session
        分区又属该 source 分区"的条目；顺序沿用作为遍历基准的那一侧
        （分区列表本身是插入序）。
        """
        if not group or not source_entries:
            return []
        if len(source_entries) < len(group):
            allowed = {id(c) for c in group}
            return [c for c in source_entries if id(c) in allowed]
        allowed = {id(c) for c in source_entries}
        return [c for c in group if id(c) in allowed]

    @staticmethod
    def _observe_query(partition_seconds: float, ttl_seconds: float, keyword_seconds: float) -> None:
        """读路径埋点（Issue #65：query() 耗时此前在观测面上完全空白）。

        直方图按阶段打点——分区直取持锁、TTL 过滤、关键词匹配的成本比例
        决定了下一轮优化方向。埋点本身绝不抛出（观测失败不得影响取数）。

        成本：每阶段一次 child.observe（实测 ~0.7µs，三次合计 ~2µs）——
        对毫秒级 query 可忽略；child 句柄惰性缓存，避免每阶段重做 label 查找。
        """
        try:
            from neurova.core.metrics import get_metrics

            metrics = get_metrics()
            metrics.observe_context_pool_query(
                partition_s=partition_seconds, ttl_s=ttl_seconds, keyword_s=keyword_seconds
            )
        except Exception:  # noqa: BLE001 - 观测面不可用时静默
            return

    # ── Scroll Context: 被驱逐轮次台账与召回（方案 P1-2.2） ──────

    @contextmanager
    def archiveBatch(self):
        """把一次归档调用收进**一个事务**（B4/003 判据 A2，规格 D8）。

        事务边界只能到"写调用返回"为止：批内条目在批结束前不落库、批结束时一次
        提交——不做异步/后台缓冲刷盘（那会把崩溃窗口内的内容连同"已归档"的承诺
        一起丢掉）。批内任一条失败 → 整批回滚，本批条数**整批**计入 `failed`
        并点名原因（不部分提交，也不谎报 `written`）。
        """
        if self._ledger_db is None:
            yield
            return
        with self._lock:
            self._ledger_batch = []
        try:
            yield
        finally:
            with self._lock:
                pending = self._ledger_batch
                self._ledger_batch = None
                self._ledger_batches += 1
            if pending:
                self._flushBatch(pending)

    def rehydrate(self, limit: int = 500) -> List:
        """显式把最近 `limit` 条归档回载进常驻（规格 D10：**默认不调用**）。

        启动不预载（D1 要的是"取得到"）；需要预热时由调用方显式发起。
        顺序取 `id DESC`（`recentRows`，前缀缓存契约要求稳定），
        重复回载同内容由 `add_context` 的去重挡掉——不产生第二份常驻条目，
        也不会在持久台账里多落一行。
        """
        if self._ledger_db is None or limit <= 0:
            return []
        from neurova.context.eviction_ledger_db import (
            resolveArchivedCreatedAt,
            resolveArchivedScope,
        )

        loaded: List = []
        for row in self._ledger_db.recentRows(limit):
            row = dict(row)
            item = ContextInput(
                source=ContextSource.CONVERSATION,
                content=row["content"],
                created_at=resolveArchivedCreatedAt(row),
                metadata={
                    "turn_id": row.get("turn_id"),
                    "session_id": row.get("session_id"),
                    "evicted_at": row.get("evicted_at"),
                    "chat_scope": resolveArchivedScope(row),
                    "recalled_from": "ledger_db",
                },
            )
            self.add_context(item)
            loaded.append(item)
        logger.info("热集回载完成：请求 %d 条，取回 %d 条（默认路径不调用本方法）", limit, len(loaded))
        return loaded

    def _registerLedgerRows(self) -> None:
        """启动登记：读一次库内归档条数（B4/005 判据 A9）。

        登记失败不阻断池构造（内存归档照常），但**不静默**：`get_retention_stats()`
        的 `ledger.registered_at_startup` 变为 False 并点名 `last_error`——
        "持久规模读不出来"必须是可见状态，不是看起来正常的 0。
        """
        try:
            self._ledger_rows = int(self._ledger_db.count())
            self._ledger_registered = True
            logger.debug("归档台账启动登记：本库已有 %d 条归档（仅登记，不预载）", self._ledger_rows)
        except Exception as exc:  # noqa: BLE001 - 登记失败不阻断池构造，但必须可见
            self._ledger_registered = False
            self._ledger_register_error = f"{type(exc).__name__}: {exc}"
            logger.warning("归档台账启动登记失败（持久规模读数不可用）：%s", self._ledger_register_error)

    def close(self) -> None:
        """释放池持有的持久层连接（幂等）；进程关闭时由 agent_shutdown 调用。

        常驻连接（B4/003）不释放会在 Windows 上让数据目录删除撞句柄占用。
        """
        ledger = self._ledger_db
        closer = getattr(ledger, "close", None)
        if closer is None:
            return
        try:
            closer()
        except Exception:  # noqa: BLE001 - 关闭失败不阻断 shutdown 其余步骤
            logger.warning("归档台账连接关闭失败", exc_info=True)

    def _flushBatch(self, pending: List[Any]) -> None:
        """把批内条目用一个事务写穿台账（失败整批回滚 + 整批计数）。"""
        try:
            self._ledger_db.beginBatch()
        except Exception as exc:  # noqa: BLE001 - 开批失败同"整批写失败"处理
            self._record_batch_failure(pending, exc)
            return
        inserted = 0
        try:
            for item in pending:
                if self._writeArchived(item):
                    inserted += 1
        except Exception as exc:  # noqa: BLE001 - 归档主流程不可被台账故障打断，但必须可见
            try:
                self._ledger_db.rollbackBatch()
            except Exception:  # noqa: BLE001 - 回滚失败另行上报，不掩盖原始失败
                logger.warning("批量回滚失败（原始失败见下条）", exc_info=True)
            self._record_batch_failure(pending, exc)
            return
        try:
            self._ledger_db.commitBatch()
        except Exception as exc:  # noqa: BLE001
            self._record_batch_failure(pending, exc)
            return
        self._ledger_written += len(pending)
        self._ledger_rows += inserted
        self._maybeGcLedger()

    def _record_batch_failure(self, pending: List[Any], exc: BaseException) -> None:
        self._ledger_write_failed += len(pending)
        self._ledger_last_error = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "归档批量写穿持久台账失败（整批 %d 条已回滚，仅驻内存，重启后不可召回）：%s",
            len(pending), self._ledger_last_error, exc_info=True,
        )

    def _persist_archived(self, item) -> None:
        """归档条目落常驻后写穿持久台账（B4/001 判据 A1 的唯一写入口）。

        批量上下文（``archiveBatch``）内只入批不落库，批结束时一次事务提交；
        批外单条立即提交（A1 的跨重启语义依赖"写完即可见"）。

        写失败不阻断归档主流程（本条仍驻内存、本进程内照常可召回），但**不静默**：
        计数与点名原因经 ``get_retention_stats()["ledger_persistence"]`` 上报。
        """
        if self._ledger_db is None:
            return
        if self._ledger_batch is not None:
            # 批内**不写库**：一次归档调用共用一个事务（A2）。库里还没写，
            # 所以这里也不得先记 written——计数在批结算时一次落定。
            self._ledger_batch.append(item)
            return
        try:
            inserted = self._writeArchived(item)
        except Exception as exc:  # noqa: BLE001 - 归档主流程不可被台账故障打断，但必须可见
            self._ledger_write_failed += 1
            self._ledger_last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "归档写穿持久台账失败（本条仅驻内存，重启后不可召回）：%s",
                self._ledger_last_error, exc_info=True,
            )
            return
        self._ledger_written += 1
        if inserted:
            self._ledger_rows += 1
        self._maybeGcLedger()

    def _writeArchived(self, item) -> bool:
        """单条写库调用（事务边界由调用方决定：批内不提交、批外立即提交）。

        Returns:
            本行是否真的落库（同内容已被归档时 False——登记值不重复计数）。
        """
        md = getattr(item, "metadata", None) or {}
        archived_at = getattr(item, "created_at", None)
        return self._ledger_db.record(
            content=str(getattr(item, "content", "")),
            turn_id=md.get("turn_id"),
            session_id=md.get("session_id") or self.session_id,
            source=getattr(getattr(item, "source", None), "value", None),
            metadata=getattr(item, "metadata", None),
            # B4/002：作用域与归档时刻落独立列（U1/U3 定案）。作用域取写入
            # 咽喉已打好的 metadata，不在这里另算一份判定。
            chat_scope=md.get("chat_scope"),
            created_at=archived_at.isoformat() if archived_at else None,
        )

    def _maybeGcLedger(self) -> None:
        """按节流触发一次保留策略清理（B4/007 判据 A5）。

        触发点是**归档提交**（批量结算 / 单条落库后）——这是持久层在生产真正
        被使用的那条路径。改前挂在 ``_archive_evicted`` 上，而该路径在生产构造面
        （``resident_limit=None``、``ttl_seconds=0``）永不执行，于是 GC 一次也
        不触发、"保留策略生效"落空，库只单调增长。

        清理失败不阻断归档主流程，但**不静默**：点名原因经
        ``get_retention_stats()["ledger_gc"]`` 上报（与 ``ledger_persistence`` 同口径）。
        """
        if self._ledger_db is None:
            return
        self._ledger_gc_counter += 1
        if self._ledger_gc_counter % _LEDGER_GC_EVERY:
            return
        try:
            removed = int(self._ledger_db.gc_stale() or 0)
        except Exception as exc:  # noqa: BLE001 - 清理失败不阻断归档，但必须可见
            self._ledger_gc_last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("归档台账 GC 失败（不影响归档）：%s", self._ledger_gc_last_error, exc_info=True)
            return
        self._ledger_gc_runs += 1
        self._ledger_gc_removed += removed
        if removed:
            # 登记读数随清理扣减——不然它会停在一个高于库内实况的旧值上。
            self._ledger_rows = max(0, self._ledger_rows - removed)

    def _archive_evicted(self, item) -> None:
        """把被驱逐条目归档进有界台账；台账满时淘汰最旧记录。

        B4/001：持久台账的写穿点在 ``add_context``（落常驻即落库），本方法
        **不再**写库——驱逐的条目必然先经 `add_context` 落过常驻，重复写会让
        同一条内容在台账里出现两行（同内容双份，破坏去重语义）。
        B4/007：本方法不再承担 GC 节流（那条节流在生产不可达），只维护内存台账。
        """
        self._eviction_ledger.append(item)
        self._evicted_total += 1
        overflow = len(self._eviction_ledger) - max(0, int(self._max_eviction_ledger))
        if overflow > 0:
            del self._eviction_ledger[:overflow]

    def _allowedRecallItems(self, items: List) -> List:
        """召回作用域闸口：本进程允许看到的作用域集（B4/008 判据 A8）。

        与视图路径**同源**：调 `collaboration.memory_scope.filter_by_scope`，
        判据取自各条 `metadata`。单聊/非协作轮只见 `direct`，群轮见
        `direct + 本群`——本方法不重写任何阈值或前缀规则（第二份规则就是第二份事实源）。

        本群/本房间的判定取 `self.turn_scope`（池的轮次作用域，由 orchestrator 每轮
        写入）：它是**写入侧打标与读侧放行的同一个值**，故不存在"写 room:A 读 room:B"
        的错配。`turn_scope` 缺失时按 `session_id` 的 `project_` 前缀回溯，
        与 `scope_from_metadata` 同规则（由该函数自身承担，不在此复刻）。
        """
        from neurova.collaboration.memory_scope import filter_by_scope

        turnScope = self.turn_scope or ""
        collab = turnScope.startswith("room:")
        roomId = turnScope.split(":", 1)[1] if collab else ""
        return filter_by_scope(
            items, lambda c: (getattr(c, "metadata", None) or {}), collab=collab, room_id=roomId
        )

    def recall_evicted(self, query: str = None, limit: int = 20) -> List:
        """
        按需召回被驱逐的上下文轮次。

        P1-1③：内存台账（重启即丢）+ 持久台账（SQLite FTS，重启后可召回）
        双源合并去重（按内容 hash），持久源覆盖重启前历史。

        B4/008：持久层是**第二条读路径**，与视图路径同样过作用域闸口
        （`_allowedRecallItems`，判据单源 `filter_by_scope`）。改前这条路径
        按 session 精确等值过滤——单聊池恒空、无会话池全放行，两个方向都不对。

        Args:
            query: 内容子串过滤（不区分大小写）；None 返回最近驱逐的条目
            limit: 最多返回条数

        Returns:
            ContextInput 列表，按驱逐时间倒序（最新优先）；
            只读操作，不影响活动池。
        """
        with self._lock:
            results: List = []
            seen_hashes = set()

            # 持久源优先（覆盖重启前历史），行 → ContextInput
            if self._ledger_db is not None:
                try:
                    # B4/002：归档事实（作用域 / 归档时刻）必须随召回还给调用方。
                    # 逐轮 import 太贵，但这两条判据**只此一份**（列优先 + 旧行兜底），
                    # 复制到本文件就是第二份作用域规则——故仍取台账模块的同源函数。
                    from neurova.context.eviction_ledger_db import (
                        resolveArchivedCreatedAt,
                        resolveArchivedScope,
                    )

                    # B4/008：不再按 session 精确等值过滤。D1 要的是"跨重启跨会话
                    # 取得到"，精确等值会把单聊池的召回变成恒空（改前实测 0 条）；
                    # 可见性由作用域闸口判定，不由 session 等值判定。
                    for row in self._ledger_db.search(query, session_id=None, limit=limit):
                        row = dict(row)  # sqlite3.Row 无 .get
                        h = ContextInput.compute_hash(ContextSource.CONVERSATION, row["content"])
                        if h in seen_hashes:
                            continue
                        seen_hashes.add(h)
                        results.append(
                            ContextInput(
                                source=ContextSource.CONVERSATION,
                                content=row["content"],
                                created_at=resolveArchivedCreatedAt(row),
                                metadata={
                                    "turn_id": row.get("turn_id"),
                                    "session_id": row.get("session_id"),
                                    "evicted_at": row.get("evicted_at"),
                                    "chat_scope": resolveArchivedScope(row),
                                    "recalled_from": "ledger_db",
                                },
                            )
                        )
                except Exception:
                    logger.warning("持久台账召回失败（回退内存台账）", exc_info=True)

            # 内存台账兜底
            snapshot = list(reversed(self._eviction_ledger))
            if query:
                needle = query.lower()
                snapshot = [c for c in snapshot if needle in str(c.content).lower()]
            for c in snapshot:
                h = getattr(c, "hash", None)
                if h and h in seen_hashes:
                    continue
                if h:
                    seen_hashes.add(h)
                results.append(c)
                if len(results) >= limit:
                    break
            # 闸口在两条源合并**之后**：只挡持久源等于半个闸口
            # （内存台账里的房间内容照样泄出）。
            return self._allowedRecallItems(results)[:limit]

    async def rollup_overflow_digest(self, folded_chunks, previous_summary: str = "") -> None:
        """P1-1③：对被折叠 chunk 生成/增量更新摘要并回写池（SUMMARY 源）。

        兼容两类条目：ContextInput（池归档）与原始 dict 消息（overflow 恢复
        路径传入的 folded_messages）——后者按 role+content 归一化。
        无摘要器（未注入/初始化失败）为 no-op——摘要停用不影响归档无损语义。
        """
        summarizer = getattr(self, "_summarizer", None)
        if summarizer is None or not folded_chunks:
            return
        normalized = []
        for item in folded_chunks:
            if isinstance(item, dict):
                role = item.get("role", "user")
                normalized.append(
                    ContextInput(
                        source=ContextSource.CONVERSATION,
                        content=item.get("content", ""),
                        metadata={"role": role},
                    )
                )
            else:
                normalized.append(item)
        folded_chunks = normalized
        try:
            summary = await summarizer.summarize(list(folded_chunks), previous_summary=previous_summary)
            if summary:
                self.archive_summary(
                    summary,
                    source_summary=previous_summary,
                )
        except Exception:
            logger.warning("溢出摘要回写失败（忽略）", exc_info=True)

    def archive_summary(self, summary: str, source_summary: str = "") -> None:
        """P1-1③：把折叠摘要以 SUMMARY 源回写池（高优先级，视图可调取）。

        归档无损语义不破坏——被折叠 chunk 仍保留，摘要只是压缩视图的入口。
        """
        if not (summary or "").strip():
            return
        self.add_context(
            ContextInput(
                source=ContextSource.SUMMARY,
                content=summary.strip(),
                priority=90,
                metadata={"source_summary": source_summary},
            )
        )

    def mark_turn_seen(self, turn_id: str) -> int:
        """P1-1④ ack 集：标记指定轮次的全部 chunk 为已读（模型请求成功后）。

        B-8：经 _by_turn 索引 O(k) 直取，旧实现全池 O(n) 线性扫。

        Returns:
            标记数量
        """
        with self._lock:
            count = 0
            for chunk in self._by_turn.get(turn_id, []):
                if not chunk.seen_confirmed:
                    chunk.seen_confirmed = True
                    count += 1
            return count

    def mark_hashes_seen(self, hashes) -> int:
        """ack 集：按内容 hash 标记已读（视图捕获路径）。

        RES-P2-1：经 _by_hash 索引 O(k) 直取，旧实现全池 O(n) 线性扫。
        """
        wanted = {h for h in (hashes or []) if h}
        if not wanted:
            return 0
        with self._lock:
            count = 0
            for h in wanted:
                chunk = self._by_hash.get(h)
                if chunk is not None and not chunk.seen_confirmed:
                    chunk.seen_confirmed = True
                    count += 1
            return count

    def select_fold_candidates(self, max_count: int = 50) -> List:
        """P1-1④ 分层剪枝：折叠候选 = 已确认读过（seen_confirmed）的 TOOL_CALL，
        最老优先（created_at 升序）。未读的工具结果绝不进入折叠候选——
        模型尚未看过，折叠会导致幻觉。

        消费方：溢出恢复/摘要压缩（compact 前 prior 调取）。
        """
        with self._lock:
            candidates = [
                c
                for c in self._collector._contexts
                if c.source == ContextSource.TOOL_CALL
                and c.seen_confirmed
                and (c.metadata or {}).get("turn_id") is not None
            ]
            candidates.sort(key=lambda c: c.created_at or datetime.datetime.min)
            return candidates[:max(0, int(max_count))]

    def get_eviction_stats(self) -> Dict[str, Any]:
        """驱逐台账统计。"""
        with self._lock:
            return {
                "evicted_total": self._evicted_total,
                "ledger_size": len(self._eviction_ledger),
                "ledger_capacity": self._max_eviction_ledger,
            }

    def _filter_ttl(self, items: List) -> List:
        """按 TTL 过滤条目（提取公共方法供 get_contexts 和 draw 复用）

        Issue #65 读路径优化：TTL 判定改用整数时间戳比较——旧实现每条
        ``(now - created_at).total_seconds()`` 都要构造 timedelta 再转 float
        （10k 条实测 ~5ms），是 query() 里比"关键词匹配"更贵的一段。
        语义等价性：``age <= ttl`` 等价于 ``created_at >= now - ttl``，
        唯一差异是边界上的亚微秒舍入（TTL 本身是秒级粗粒度参数）。

        本池 ``ttl_seconds<=0``（生产 orchestrator 走此档）为快速返回，
        零额外开销——"永不丢失"档案的热路径不承担 TTL 成本。
        """
        if not hasattr(self, "ttl_seconds") or self.ttl_seconds <= 0:
            return items
        cutoff = datetime.now() - timedelta(seconds=self.ttl_seconds)
        return [
            item
            for item in items
            if (not item.created_at) or item.created_at >= cutoff
        ]

    def get_contexts(self) -> List:
        with self._lock:
            contexts = self._collector.collect()
            return self._filter_ttl(contexts)

    def cleanup_expired(self) -> int:
        """清理过期条目，返回移除数量（过期条目归档进驱逐台账）"""
        with self._lock:
            if not hasattr(self, "ttl_seconds") or self.ttl_seconds <= 0:
                return 0

            valid = self._filter_ttl(self._collector._contexts)
            removed_items = [c for c in self._collector._contexts if c not in valid]
            original_count = len(self._collector._contexts)
            self._collector._contexts = valid
            self._rebuild_indexes()

            removed_count = original_count - len(valid)
            for item in removed_items:
                self._archive_evicted(item)

            if removed_count > 0:
                # #65 埋点：TTL 回收是"常驻规模"的另一条出口，此前无计数
                self._ttl_evicted_total += removed_count
                self._cache_version += 1
                logger.info(
                    "ContextPool TTL 回收 %d 条（ttl=%ss，常驻剩余 %d）",
                    removed_count, self.ttl_seconds, len(valid),
                )

            return removed_count

    # P1-1②：静态表降级用（provider 元数据不可用时的保守已知型号）
    _STATIC_MODEL_BUDGETS = {
        "gpt-4": 32000,
        "gpt-4-turbo": 32000,
        "gpt-4o": 32000,
        "gpt-3.5-turbo": 16000,
        "claude-3-opus": 200000,
        "claude-3-sonnet": 200000,
        "claude-3-haiku": 200000,
        "claude-2": 100000,
        "deepseek-chat": 32000,
        "deepseek-coder": 32000,
        "qwen-max": 32000,
        "qwen-turbo": 16000,
    }
    # 视图预算 = context_window × 视图安全系数（预留输出/系统提示/工具结果）
    _BUDGET_WINDOW_FACTOR = 0.6
    _BUDGET_MIN = 4000
    _BUDGET_MAX = 400000

    @staticmethod
    def get_token_budget_for_model(model_name: str, default_budget: int = 16000) -> int:
        """动态 Token 预算（P1-1②，2026-09-10 收敛 llmrouter 统一入口）。

        窗口查询委托 llm_router.resolve_model_context_window（provider 真实
        元数据 → 族级预埋 → model_limits 精确表 → 保守默认），本函数只做
        ×0.6 视图安全系数与钳位。llm_router 不可用时回退自有静态表。
        """
        needle = (model_name or "").strip().lower()

        # 1) llmrouter 统一入口（真实元数据优先）
        try:
            from neurova.llm.llm_router import resolve_model_context_window

            window = resolve_model_context_window(model_name)
            if window > 0:
                budget = int(window * ContextPool._BUDGET_WINDOW_FACTOR)
                return max(ContextPool._BUDGET_MIN, min(ContextPool._BUDGET_MAX, budget))
        except Exception:
            pass  # llm_router 不可用 → 静态表回退

        # 2) 静态已知型号表（llm_router 导入失败时的兜底）
        for model_pattern, budget in ContextPool._STATIC_MODEL_BUDGETS.items():
            if model_pattern in needle:
                return budget

        return default_budget

    def get_token_budget_for_capabilities(self, capabilities: list) -> int:
        try:
            from neurova.llm.llm_router import ModelCapability
        except ImportError:
            logger.debug("ModelCapability 延迟导入失败，使用默认预算")
            return 16000

        base_budget = 16000

        if ModelCapability.VISION in capabilities:
            base_budget += 16000
        if ModelCapability.AUDIO in capabilities:
            base_budget += 8000
        if ModelCapability.VIDEO in capabilities:
            base_budget += 32000
        if ModelCapability.MULTIMODAL in capabilities:
            base_budget += 16000

        return base_budget

    def build_context_for_model(self, model_name: str) -> List[Dict[str, Any]]:
        with self._lock:
            cache_key = f"{self.isolation_key}:{model_name}"
            if cache_key in self._cache and self._last_build_version == self._cache_version:
                return self._cache[cache_key]

            contexts = self.get_contexts()

            messages = []
            for ctx in contexts:
                msg = self._converter.convert_for_model(ctx, model_name)
                messages.append(msg)

            self._cache[cache_key] = messages
            self._last_build_version = self._cache_version

            return messages

    def convert_context_for_model(self, model_name: str) -> List[Dict[str, Any]]:
        return self.build_context_for_model(model_name)

    def compress_context(self):
        with self._lock:
            contexts = self.get_contexts()
            compressed = self._compressor.compress(contexts)
            self._collector._contexts = compressed
            self._rebuild_indexes()

    def merge_with(self, other_pool: "ContextPool"):
        with self._lock:
            other_contexts = other_pool.get_contexts()
            for ctx in other_contexts:
                # 重入 add_context（RLock 允许重入）
                self.add_context(ctx)

    def clear(self):
        with self._lock:
            self._collector._contexts.clear()
            self._by_hash.clear()
            self._by_turn.clear()
            self._read_index.clear()
            self._cache.clear()
            self._cache_version += 1

    def draw(self, need: str = None) -> List:
        with self._lock:
            all_drops = self._collector.collect()
            # [FIX] draw() 也应用 TTL 过期过滤（之前绕过 get_contexts() 的 TTL 检查）
            all_drops = self._filter_ttl(all_drops)
            deduped = self._deduplicator.dedup(all_drops, stage="output")
            selected = self._drawer.draw(deduped, need=need)
            # P1-1①（方案 §4.1）：视图出口配对完整性校验——预算/相关性选取
            # 可能产生孤儿 TOOL_CALL（其 pairs_with 目标未入选），剔除以避免
            # LLM 看到"无上下文的工具结果"；孤儿留在池中（归档无损语义不变）
            report = validate_pairing(selected)
            if report.orphans:
                logger.debug(
                    "ContextPool.draw 剔除 %d 个孤儿 TOOL_CALL（pairs_with 目标不在视图内）",
                    report.orphan_count,
                )
            return report.kept

    def dedup(self, stage: str = "input") -> int:
        with self._lock:
            all_drops = self._collector.collect()
            deduped = self._deduplicator.dedup(all_drops, stage=stage)
            self._collector._contexts = deduped
            self._rebuild_indexes()
            return len(deduped)


from neurova.context.pairing import validate_pairing

# D11：台账 GC 节流——每 N 次**归档提交**触发一次 gc_stale（触发点见
# _maybeGcLedger；改前挂在生产不可达的驱逐路径上）。与环境无关地写死，
# 不做运行时调参。
_LEDGER_GC_EVERY = 20
from neurova.context.pool_models import ContextSource, ContextInput
from neurova.context.pool_index import PoolReadIndex
from neurova.context.collector import ContextCollector
from neurova.context.converter import ContextConverter
from neurova.context.compressor import ContextCompressor
from neurova.context.utils import ContextPoolUtils
from neurova.context.dedup import DriftSafeDeduplicator
from neurova.context.semantic_drawer import SemanticMatchDrawer
from neurova.context.auto_tagger import AutoTagger

def poolIdentityOf(agent_ref, session_id: Optional[str] = None) -> tuple:
    """池身份三元组的**唯一派生处**（(user_id, agent_id, session_id)）。

    构造侧（编排器）与查询侧（端点 / 工作流节点）必须用同一份派生：各写一遍
    `getattr(...) or "default"` 就会出现"构造时用 default、查询时用 JWT user"
    这类查不到的静默失配——池明明活着，取池返回 None，消费方再各造一个
    （审计 P2-3 的形态）。
    """
    return (
        str(getattr(agent_ref, "user_id", None) or "default"),
        str(getattr(agent_ref, "agent_id", None) or "default"),
        session_id,
    )


def get_context_pool(
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    session_id: Optional[str] = None,
):
    """按身份取**已登记**的池（无则 None）。池的读侧唯一入口。

    改前本符号不存在：消费方（neurflow 的上下文节点）只能 `try: import ...`
    然后 `except ImportError` 静默降级——**符号缺失**在日志里只是个 DEBUG，
    于是"取不到池"与"池里没内容"再也分不开（审计 P2-1）。

    这里刻意**不造池**：取池路径能隐式造池的话，调用方拿到的是空池却以为
    拿到了真池（审计 P2-3 的形态就是各造各的池、写入即丢）。要池请走
    `ContextPoolRegistry.get_or_create`（显式创建）或从 Agent 的编排器取。

    身份归一（None 与 "" 同键）由注册表负责，避免"登记用 None、查询用 ''"的静默失配。
    """
    from neurova.context_pool_registry import get_registry

    return get_registry().get_pool(user_id or "", agent_id or "", session_id)


__all__ = [
    "ContextSource",
    "ContextInput",
    "ContextPool",
    "ContextCollector",
    "ContextConverter",
    "ContextCompressor",
    "ContextPoolUtils",
    "DriftSafeDeduplicator",
    "SemanticMatchDrawer",
    "AutoTagger",
    "get_context_pool",
]
