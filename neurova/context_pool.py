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

from neurova.core.logger import get_logger
from datetime import datetime
from typing import Any, Dict, List, Optional

from neurova.context.token_estimator import EstimationStrategy, TokenEstimator

logger = get_logger(__name__)


class ContextPool:
    """
    上下文池 - 核心组件

    提供上下文收集、重组、转换、压缩的统一接口。
    支持模型切换时的上下文适配。

    支持三层隔离机制：
    - 用户隔离：不同用户的上下文完全隔离
    - Agent隔离：不同Agent的上下文完全隔离
    - Session隔离：不同Session的上下文完全隔离
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
    ):
        """
        初始化上下文池

        Args:
            user_id: 用户ID（必需）
            agent_id: Agent ID（必需）
            session_id: 会话ID（可选）
            max_tokens: 最大Token数量
            auto_tag: 是否启用自动标签生成
            max_size: 池最大大小限制（默认100）
            ttl_seconds: 上下文过期时间（秒，默认3600）

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
        self.max_tokens = max_tokens
        self.auto_tag = auto_tag
        self.max_size = max_size
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

        # 并发保护：保护 _cache / _cache_version / _collector._contexts 等共享状态
        # 使用 RLock 因为 merge_with 等方法会重入调用 add_context
        # 遵循 AGENTS.md "Thread safety: use threading.RLock for shared state"
        self._lock = threading.RLock()

        # P1-1③：驱逐台账持久层 + 摘要压缩器（可选注入；None=保持内存行为）
        self._ledger_db = ledger_db
        self._summarizer = summarizer

    @property
    def isolation_key(self) -> str:
        """生成隔离键"""
        session_part = self.session_id if self.session_id else "default"
        return f"{self.user_id}:{self.agent_id}:{session_part}"

    def add_context(self, context):
        with self._lock:
            # 根因 A 修复: 自动注入 session_id/agent_id/user_id 到 chunk.metadata
            # (用户显式传入的字段优先,不被覆盖)
            self._inject_isolation_tags(context)

            if self.auto_tag and hasattr(self, "_auto_tagger"):
                context = self._auto_tagger.auto_tag(context)

            # [FIX] 添加时去重：已存在相同 hash 的条目则跳过
            if context.hash:
                existing = [c for c in self._collector._contexts if c.hash == context.hash]
                if existing:
                    # 若新条目优先级更高则替换，否则跳过
                    existing_entry = existing[0]
                    if context.priority > existing_entry.priority:
                        idx = self._collector._contexts.index(existing_entry)
                        self._collector._contexts[idx] = context
                        self._cache_version += 1
                        logger.debug("ContextPool 替换条目: hash=%s, priority=%s→%s",
                                     context.hash[:8], existing_entry.priority, context.priority)
                    else:
                        logger.debug("ContextPool 跳过重复: hash=%s, source=%s",
                                     context.hash[:8], context.source.value if context.source else "?")
                    return

            # [无损归档] 不再按 max_size 驱逐最旧条目——池的定位是永久归档，
            # "永不丢失上下文"是硬约束；容量控制只发生在视图层（Drawer 按预算
            # 整条选取）。驱逐台账（_archive_evicted）保留兼容，主流程不再触发。
            self._collector.add_context(context)
            self._cache_version += 1

    def _inject_isolation_tags(self, context) -> None:
        """根因 A 修复: 把 session_id/agent_id/user_id 注入到 chunk.metadata

        用户显式传入的字段优先, 不会被覆盖。
        """
        if context.metadata is None:
            context.metadata = {}
        # 仅在缺失时注入, 尊重用户显式传入的值
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
        """
        with self._lock:
            candidates = self._filter_ttl(list(self._collector._contexts))

        # 关键词过滤
        if query:
            q = query.lower()
            candidates = [c for c in candidates if q in c.content.lower()]

        # source 过滤
        if source is not None:
            candidates = [c for c in candidates if c.source == source]

        # 显式 session_id 过滤: 严格限定
        if session_id is not None:
            candidates = [
                c for c in candidates
                if (c.metadata or {}).get("session_id") == session_id
            ]
            candidates.sort(key=lambda c: c.priority, reverse=True)
            return candidates[:limit]

        # tags 过滤
        if tags:
            tag_set = set(tags)
            candidates = [c for c in candidates if tag_set.intersection(set(c.tags or []))]

        # 当前 session 优先策略:
        # 1) 分离当前 session 的 chunk 和跨 session 的 chunk
        # 2) 当前 session 排在最前(按 priority 降序)
        # 3) 跨 session 兜底(按 priority 降序)
        # 4) 合并后按 limit 截断
        if self.session_id is not None:
            current_session = [
                c for c in candidates
                if (c.metadata or {}).get("session_id") == self.session_id
            ]
            other_sessions = [
                c for c in candidates
                if (c.metadata or {}).get("session_id") != self.session_id
            ]
            current_session.sort(key=lambda c: c.priority, reverse=True)
            other_sessions.sort(key=lambda c: c.priority, reverse=True)
            merged = current_session + other_sessions
            return merged[:limit]

        # 无 session 概念: 按 priority 降序(向后兼容)
        candidates.sort(key=lambda c: c.priority, reverse=True)
        return candidates[:limit]

    # ── Scroll Context: 被驱逐轮次台账与召回（方案 P1-2.2） ──────

    def _archive_evicted(self, item) -> None:
        """把被驱逐条目归档进有界台账；台账满时淘汰最旧记录。

        P1-1③：同时写穿持久化台账（SQLite WAL+FTS5）——重启后经
        recall_evicted 仍可召回（内存台账重启即丢）。
        """
        self._eviction_ledger.append(item)
        self._evicted_total += 1
        overflow = len(self._eviction_ledger) - max(0, int(self._max_eviction_ledger))
        if overflow > 0:
            del self._eviction_ledger[:overflow]
        if self._ledger_db is not None:
            try:
                self._ledger_db.record(
                    content=str(getattr(item, "content", "")),
                    turn_id=(item.metadata or {}).get("turn_id"),
                    session_id=self.session_id,
                    source=getattr(item.source, "value", None),
                    metadata=getattr(item, "metadata", None),
                )
            except Exception:
                logger.warning("驱逐台账持久化失败（不影响内存归档）", exc_info=True)

    def recall_evicted(self, query: str = None, limit: int = 20) -> List:
        """
        按需召回被驱逐的上下文轮次。

        P1-1③：内存台账（重启即丢）+ 持久台账（SQLite FTS，重启后可召回）
        双源合并去重（按内容 hash），持久源覆盖重启前历史。

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
                    for row in self._ledger_db.search(query, session_id=self.session_id, limit=limit):
                        row = dict(row)  # sqlite3.Row 无 .get
                        h = ContextInput.compute_hash(ContextSource.CONVERSATION, row["content"])
                        if h in seen_hashes:
                            continue
                        seen_hashes.add(h)
                        results.append(
                            ContextInput(
                                source=ContextSource.CONVERSATION,
                                content=row["content"],
                                metadata={
                                    "turn_id": row.get("turn_id"),
                                    "session_id": row.get("session_id"),
                                    "evicted_at": row.get("evicted_at"),
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
            return results[:limit]

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

        Returns:
            标记数量
        """
        with self._lock:
            count = 0
            for chunk in self._collector._contexts:
                if (chunk.metadata or {}).get("turn_id") == turn_id and not chunk.seen_confirmed:
                    chunk.seen_confirmed = True
                    count += 1
            return count

    def mark_hashes_seen(self, hashes) -> int:
        """ack 集：按内容 hash 标记已读（视图捕获路径）。"""
        wanted = {h for h in (hashes or []) if h}
        if not wanted:
            return 0
        with self._lock:
            count = 0
            for chunk in self._collector._contexts:
                if chunk.hash in wanted and not chunk.seen_confirmed:
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
        """按 TTL 过滤条目（提取公共方法供 get_contexts 和 draw 复用）"""
        if not hasattr(self, "ttl_seconds") or self.ttl_seconds <= 0:
            return items
        now = datetime.now()
        valid = []
        for item in items:
            if item.created_at:
                age = (now - item.created_at).total_seconds()
                if age <= self.ttl_seconds:
                    valid.append(item)
            else:
                valid.append(item)
        return valid

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

            removed_count = original_count - len(valid)
            for item in removed_items:
                self._archive_evicted(item)

            if removed_count > 0:
                self._cache_version += 1

            return removed_count

    @staticmethod
    def get_token_budget_for_model(model_name: str, default_budget: int = 16000) -> int:
        model_budgets = {
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

        for model_pattern, budget in model_budgets.items():
            if model_pattern in model_name.lower():
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

    def merge_with(self, other_pool: "ContextPool"):
        with self._lock:
            other_contexts = other_pool.get_contexts()
            for ctx in other_contexts:
                # 重入 add_context（RLock 允许重入）
                self.add_context(ctx)

    def clear(self):
        with self._lock:
            self._collector._contexts.clear()
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
            return len(deduped)


from neurova.context.pairing import validate_pairing
from neurova.context.pool_models import ContextSource, ContextInput
from neurova.context.collector import ContextCollector
from neurova.context.converter import ContextConverter
from neurova.context.compressor import ContextCompressor
from neurova.context.utils import ContextPoolUtils
from neurova.context.dedup import DriftSafeDeduplicator
from neurova.context.semantic_drawer import SemanticMatchDrawer
from neurova.context.auto_tagger import AutoTagger

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
]
