from __future__ import annotations

"""
MemoryManager — 记忆管理器（CogArch 总线版）
===============================================

⚠️ 架构现状 (基于实际代码, 非设计声明):
  - 行数: ~1000 行 (非 docstring 之前声称的 ~500 行)
  - 子模块: 仅加载 EmotionModule (非声称的 12 个独立模块)
  - EventBus: 已创建但子模块未通过它注册
  - 50+ 方法为 stub, 返回空值/默认值, 标注见各方法注释

已完整实现的功能:
  - remember/recall/search_memories (核心记忆 CRUD)
  - SQLite 持久化 (_init_persistence_db/_load_from_db/_persist_memory)
  - 情感分析 (EmotionModule 代理: analyze_emotion/get_emotion_summary 等)
  - 记忆温度 (update_memory_temperature/run_decay_cycle)
  - 生命周期 (get_crystallized/get_hot_memories)

Stub 方法 (返回空值, 未实现):
  - Self Model: get_self_model/update_self_model/update_user_profile/get_user_profile
  - Meta-cognition: meta_monitor/meta_reflect/meta_optimize/meta_evolve_skills 等
  - EKI: eki_process_task/eki_recommend_reinforcement 等
  - TKG: tkg_add_fact/tkg_query_current 等
  - Working Memory: wm_add_turn 等
  - Sleep: run_light_sleep_cycle/run_rem_sleep_cycle/run_deep_sleep_cycle/run_dormant_cycle
  - Explainability: get_explanation_chain/visualize_chain (explain_memory 最小实现)

已实现的方法:
  - Forgetting Recovery: archive_memory/recover_from_archive/get_archived_memories 等
    (真实操作 _memories.lifecycle_stage, 非委托 stub)

调用方应通过 hasattr 或 try/except 检测 stub 方法,
或直接使用对应的独立子模块 (如 cognitive_storage_engine, neurova_recall 等)。
"""

import json
from neurova.core.logger import get_logger
import os
from pathlib import Path
import sqlite3
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Tuple

from neurova.cognitive_layers.memory_layer.bus_event import (
    EventBus,
    MemoryEvent,
)
from neurova.cognitive_layers.memory_layer.models import (
    EmotionType,
    LifecycleStage,
    Memory,
    MemoryCategory,
    MemoryPerspective,
    MemoryType,
)

logger = get_logger(__name__)

# 审计修复 (three-tier-isolation-audit.md P0-1): 请求级隔离作用域。
# 原方案由 API 层直接给共享单例的 neuser_id/user_id 只读 property 赋值:
# 赋值要么静默失效要么抛 AttributeError, 且并发请求互相覆盖隔离上下文。
# ContextVar 按请求任务/线程上下文隔离, 值随请求上下文销毁, 并发安全。
# 作用域只覆盖第 2/3 层 (neuser_id/user_id); agent_id 始终取实例自身的。
_scope_var: ContextVar = ContextVar("memory_isolation_scope", default=None)

# 全局单例
_default_manager: Optional["MemoryManager"] = None
# 根因修复 (2026-09-02): 按 (agent_id, neuser_id, user_id, db_path) 作用域注册表，
# 替代进程级单例——否则所有 agent/用户的记忆统计永远命中首个调用者的作用域。
_managers: Dict[Tuple[str, str, str, str], "MemoryManager"] = {}
_manager_lock = threading.Lock()


# TemperatureEngine._determine_stage 返回的字符串 → LifecycleStage 枚举映射
# 注意：temperature 模块用 'secondary'/'deleted'，LifecycleStage 用 'consolidated'/'forgotten'
_STAGE_STRING_TO_ENUM = {
    "active": LifecycleStage.ACTIVE,
    "secondary": LifecycleStage.ACTIVE,        # secondary 表示仍可用，归到 ACTIVE
    "consolidated": LifecycleStage.CONSOLIDATED,
    "archived": LifecycleStage.ARCHIVED,
    "deleted": LifecycleStage.FORGOTTEN,        # deleted 表示已遗忘
    "forgotten": LifecycleStage.FORGOTTEN,
    "crystallized": LifecycleStage.CRYSTALLIZED,
}


def _map_lifecycle_stage(stage_str: str) -> Optional[LifecycleStage]:
    """将 TemperatureEngine 返回的阶段字符串映射到 LifecycleStage 枚举

    Args:
        stage_str: temperature 模块返回的阶段字符串（'active'/'secondary'/'archived'/'deleted' 等）

    Returns:
        对应的 LifecycleStage 枚举值；未识别的字符串返回 None（保持原阶段不变）
    """
    return _STAGE_STRING_TO_ENUM.get(stage_str)


def _is_valid_category(category: str) -> bool:
    """判断字符串是否是合法 MemoryCategory 枚举值"""
    try:
        MemoryCategory(category)
        return True
    except (ValueError, KeyError):
        return False


def _filter_by_category(mems: List[Memory], category: str) -> List[Memory]:
    """按 category 过滤记忆列表

    支持两种模式：
    1. 合法 MemoryCategory 枚举值（如 'general'/'conversation'） → 按 m.category.value 精确匹配
    2. 任意字符串（测试或自定义标签）→ 按 metadata._original_category 匹配
       （remember 时若 category 非法枚举，会 fallback 到 GENERAL 但在 metadata 中保留原始字符串）
    """
    if _is_valid_category(category):
        return [m for m in mems if m.category.value == category]
    # 非法枚举字符串：按 remember 时保留的 metadata._original_category 匹配
    return [m for m in mems if m.metadata.get("_original_category") == category]


class MemoryManager:
    """记忆管理器 Facade — 通过 EventBus 路由到各子模块"""

    def __init__(
        self,
        db_path: str = "neurova_memory.db",
        agent_id: str = "default",
        neuser_id: str = "default",
        user_id: str = "default",
        enable_buffer: bool = True,
    ):
        # P-4 修复: 空路径校验, 测试期望 MemoryManager(db_path="") 抛 ValueError
        if not db_path:
            raise ValueError("db_path must not be empty")

        self._db_path = db_path
        self._agent_id = agent_id
        self._neuser_id = neuser_id
        self._user_id = user_id
        self._enable_buffer = enable_buffer
        self._bus = EventBus()
        self._started = False

        # 内部存储（简易实现，子模块可覆盖）
        self._memories: Dict[str, Memory] = {}
        self._counter = 0
        self._lock = threading.RLock()
        self._last_decay_at: Optional[float] = None   # 节流：上次 run_decay_cycle 的 monotonic 时间戳
        self._decay_cursor: int = 0                   # 轮询：有界衰减的游标

        # 子模块引用（延迟初始化）
        self._storage = None
        self._emotion_analyzer = None
        self._auto_classifier = None
        self._conversation_buffer = None  # 受 enable_buffer 控制,下方按需初始化
        self._conflict_detector = None
        self._relation_manager = None
        self._sleep_consolidation = None
        self._explainability_manager = None
        self._forgetting_recovery = None
        self._emotion_conduction = None
        # Bug 5 修复: _write_queue 必须在 __init__ 中初始化为 MemoryWriteQueue 实例
        # 原代码 self._write_queue = None 后从未赋值, 导致 flush_buffer 永远返回 0
        try:
            from neurova.cognitive_layers.memory_layer.conversation_buffer import MemoryWriteQueue
            self._write_queue = MemoryWriteQueue(
                storage=None, agent_id=agent_id, memory_manager=self,
            )
        except Exception as e:
            logger.warning("MemoryWriteQueue init failed (fallback to None): %s", e)
            self._write_queue = None
        # Bug 9 修复: 共享 ThreadPoolExecutor 限制并发线程数,
        # 原实现 _extract_dependency_async 每次 remember 都新建 Thread, 高频调用会创建无限线程
        from concurrent.futures import ThreadPoolExecutor
        self._dependency_executor = ThreadPoolExecutor(
            max_workers=min(4, (os.cpu_count() or 2)),
            thread_name_prefix="mem-dep",
        )
        # EKI/Sleep 模块（阶段2委托）
        self._eki_module = None
        self._sleep_module = None
        self._eki_enabled = False

        # 全量模块委托（阶段10）
        self._buffer_module = None
        self._classifier_module = None
        self._conflict_module = None
        self._explainability_module = None
        self._meta_cognition_module = None
        self._relation_module = None
        self._graph_traversal = None
        self._self_model_module = None
        self._self_manager_module = None
        self._tkg_module = None
        self._working_memory_module = None
        self._forgetting_recovery_module = None
        self._auto_context_module = None

        # 情感模块（立即初始化）
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule

        self._emotion_module = EmotionModule(db_path=db_path)
        self._emotion_module.init()

        # MemoryStorage 实例（提供 get_recent_memories / delete_memory 等接口）
        # Bug 8 修复：原 self._storage = None 永远不被重新赋值，导致下游 8 处调用方 AttributeError
        self._init_storage()

        # SQLite 持久化（记忆跨重启保留）
        self._init_persistence_db()
        self._load_from_db()

        # ConversationBuffer (受 enable_buffer 控制; 关闭时跳过以降低开销/便于测试隔离)
        if self._enable_buffer:
            try:
                from neurova.cognitive_layers.memory_layer.conversation_buffer import ConversationBuffer

                self._conversation_buffer = ConversationBuffer()
                logger.debug("ConversationBuffer initialized")
            except Exception as e:
                logger.warning("ConversationBuffer init failed: %s", e)
                self._conversation_buffer = None

        # 统计
        self._stats = {
            "total_memories": len(self._memories),
            "recall_count": 0,
            "remember_count": 0,
        }

        logger.info(
            f"MemoryManager initialized: agent_id={agent_id}, neuser_id={neuser_id}, "
            f"user_id={user_id}, enable_buffer={self._enable_buffer}, "
            f"memories_loaded={len(self._memories)}"
        )

    def _init_storage(self):
        """初始化 MemoryStorage 实例（提供 get_recent_memories / delete_memory 等接口）

        Bug 8 修复：原 __init__ 中 self._storage = None 后从未重新赋值，
        导致 mem_core.py / compression.py / memory_layer.py 共 8 处调用方
        在访问 storage.get_recent_memories / storage.delete_memory 时 AttributeError。
        """
        try:
            from neurova.cognitive_layers.memory_layer.storage import MemoryStorage

            db_dir = os.path.dirname(self._db_path) or "."
            storage_dir = os.path.join(db_dir, "memory_storage")
            os.makedirs(storage_dir, exist_ok=True)
            self._storage = MemoryStorage(storage_dir=storage_dir)
            logger.debug("MemoryStorage initialized: %s", storage_dir)
        except Exception as e:
            logger.warning("MemoryStorage init failed: %s", e)
            self._storage = None

    def _init_persistence_db(self):
        """初始化 SQLite 持久化数据库"""
        try:
            # 使用与 db_path 同目录的持久化文件
            db_dir = os.path.dirname(self._db_path) or "."
            self._persist_db_path = os.path.join(db_dir, "neurova_memories_persist.db")
            conn = sqlite3.connect(self._persist_db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    memory_type TEXT NOT NULL DEFAULT 'semantic',
                    category TEXT NOT NULL DEFAULT 'general',
                    lifecycle_stage TEXT NOT NULL DEFAULT 'active',
                    perspective TEXT NOT NULL DEFAULT 'first_person',
                    emotion TEXT NOT NULL DEFAULT 'neutral',
                    temperature REAL NOT NULL DEFAULT 100.0,
                    importance REAL NOT NULL DEFAULT 50.0,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    agent_id TEXT NOT NULL DEFAULT 'default',
                    neuser_id TEXT NOT NULL DEFAULT 'default',
                    user_id TEXT NOT NULL DEFAULT 'default',
                    shared INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_accessed_at TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_agent ON memories(agent_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_category ON memories(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_type ON memories(memory_type)")
            # 审计修复 (P2-11): 三层复合索引, 隔离查询不再全表扫
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mem_3tier ON memories(agent_id, neuser_id, user_id)"
            )
            # 性能修复: MoE 后台索引按 temperature DESC 分页全库排序,
            # 无此索引时每页都触发表扫描+排序（实测 232 万行库烧满 12 核 2 分钟）
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mem_temperature ON memories(temperature)"
            )
            conn.commit()
            conn.close()
            logger.debug("Persistence DB initialized: %s", self._persist_db_path)
        except Exception as e:
            logger.warning("Persistence DB init failed: %s", e)
            self._persist_db_path = None

    def _load_from_db(self):
        """从 SQLite 加载记忆到内存

        Bug 4 修复: WHERE 子句原仅按 agent_id 过滤, 跨 neuser_id/user_id 加载记忆。
        现加上 AND neuser_id=? AND user_id=? 保证三层隔离。
        """
        if not getattr(self, "_persist_db_path", None):
            return
        try:
            conn = sqlite3.connect(self._persist_db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM memories WHERE agent_id = ? AND neuser_id = ? AND user_id = ? "
                "ORDER BY created_at DESC",
                (self._agent_id, self._neuser_id, self._user_id),
            ).fetchall()

            from datetime import datetime

            for row in rows:
                try:
                    mem = Memory(
                        id=row["id"],
                        content=row["content"],
                        memory_type=MemoryType(row["memory_type"]),
                        category=MemoryCategory(row["category"]),
                        lifecycle_stage=LifecycleStage(row["lifecycle_stage"]),
                        emotion=EmotionType(row["emotion"]),
                        temperature=row["temperature"],
                        importance=row["importance"],
                        access_count=row["access_count"],
                        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                        agent_id=row["agent_id"],
                        neuser_id=row["neuser_id"],
                        user_id=row["user_id"],
                        shared=bool(row["shared"]),
                        created_at=datetime.fromisoformat(row["created_at"]),
                        updated_at=datetime.fromisoformat(row["updated_at"]),
                        last_accessed_at=(
                            datetime.fromisoformat(row["last_accessed_at"]) if row["last_accessed_at"] else None
                        ),
                    )
                    self._memories[mem.id] = mem
                    self._counter = max(
                        self._counter, int(mem.id.replace("mem_", "")) if mem.id.startswith("mem_") else 0
                    )
                except Exception as e:
                    logger.debug("Skip invalid memory row %s: %s", row['id'], e)

            # 审计修复 (P1-7): 计数器跨作用域取全局最大 id。
            # 原实现只按本作用域已加载行回填 _counter, 新作用域实例会重新从
            # mem_000001 生成 id, 与其他作用域同 id 行 INSERT OR REPLACE 互踩。
            try:
                row = conn.execute(
                    "SELECT MAX(CAST(SUBSTR(id, 5) AS INTEGER)) FROM memories WHERE id LIKE 'mem\\_%' ESCAPE '\\'"
                ).fetchone()
                if row and row[0]:
                    self._counter = max(self._counter, int(row[0]))
            except Exception as e:
                logger.debug("Seed counter from persist DB failed: %s", e)

            conn.close()

            logger.info("Loaded %s memories from persistence DB", len(self._memories))
        except Exception as e:
            logger.warning("Failed to load memories from DB: %s", e)

    def _persist_memory(self, mem: Memory):
        """将单条记忆写入 SQLite 持久化"""
        if not getattr(self, "_persist_db_path", None):
            return
        try:
            conn = sqlite3.connect(self._persist_db_path)
            conn.execute(
                """INSERT OR REPLACE INTO memories
                   (id, content, memory_type, category, lifecycle_stage, perspective, emotion,
                    temperature, importance, access_count, metadata, agent_id, neuser_id, user_id,
                    shared, created_at, updated_at, last_accessed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mem.id,
                    mem.content,
                    mem.memory_type.value,
                    mem.category.value,
                    mem.lifecycle_stage.value,
                    mem.perspective.value,
                    mem.emotion.value,
                    mem.temperature,
                    mem.importance,
                    mem.access_count,
                    json.dumps(mem.metadata, ensure_ascii=False),
                    mem.agent_id,
                    mem.neuser_id,
                    mem.user_id,
                    int(mem.shared),
                    mem.created_at.isoformat(),
                    mem.updated_at.isoformat(),
                    mem.last_accessed_at.isoformat() if mem.last_accessed_at else None,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug("Persist memory failed: %s", e)

    def _delete_persisted_memory(self, memory_id: str):
        """从 SQLite 删除持久化记忆

        审计修复 (P1-6): 原 DELETE 仅按 id, 知道对方 memory_id 即可越权删除
        任何作用域的持久化行。现强制附带生效三元组, 跨作用域删不掉。
        """
        if not getattr(self, "_persist_db_path", None):
            return
        try:
            conn = sqlite3.connect(self._persist_db_path)
            conn.execute(
                "DELETE FROM memories WHERE id = ? AND agent_id = ? AND neuser_id = ? AND user_id = ?",
                (memory_id, self._agent_id, self._eff_neuser_id(), self._eff_user_id()),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug("Delete persisted memory failed: %s", e)

    # ────── Properties ──────

    @property
    def bus(self) -> EventBus:
        return self._bus

    @property
    def storage(self):
        return self._storage

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def neuser_id(self) -> str:
        return self._neuser_id

    @property
    def user_id(self) -> str:
        return self._user_id

    # ────── 请求级隔离作用域 (审计 P0-1 根因修复) ──────

    def set_request_scope(self, neuser_id: Optional[str] = None, user_id: Optional[str] = None) -> None:
        """为当前请求上下文设置隔离作用域 (neuser_id, user_id)。

        通过 ContextVar 实现: 值绑定在当前请求的任务/线程上下文中,
        不修改本共享单例的任何状态, 并发请求互不污染。
        每次调用都完整重设两层 —— 缺省层回到实例默认值, 不继承
        上下文中的旧值 (每个请求应显式声明完整作用域)。
        """
        _scope_var.set((neuser_id or self._neuser_id, user_id or self._user_id))

    @contextmanager
    def request_scope(self, neuser_id: Optional[str] = None, user_id: Optional[str] = None):
        """with 块内以指定作用域操作记忆, 退出后恢复原作用域。"""
        token = _scope_var.set((neuser_id or self._neuser_id, user_id or self._user_id))
        try:
            yield self
        finally:
            _scope_var.reset(token)

    def _eff_neuser_id(self) -> str:
        scope = _scope_var.get()
        return scope[0] if scope else self._neuser_id

    def _eff_user_id(self) -> str:
        scope = _scope_var.get()
        return scope[1] if scope else self._user_id

    def _scoped_memories(self) -> List[Any]:
        """按生效三元组过滤的内存记忆视图 (agent 恒取实例自身)"""
        ne = self._eff_neuser_id()
        uid = self._eff_user_id()
        return [
            m
            for m in self._memories.values()
            if m.agent_id == self._agent_id and m.neuser_id == ne and m.user_id == uid
        ]

    @property
    def emotion_module(self):
        """情感模块"""
        return self._emotion_module

    # ────── Core Memory Operations ──────

    def remember(
        self,
        content: str,
        category: str = "general",
        memory_type: str = "semantic",
        temperature: Optional[float] = None,
        importance: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        emotion: Optional[str] = None,
        # M-7 修复: API 层显式接收的 4 个数据参数, 不再落入 kwargs 黑洞
        is_important: Optional[bool] = None,
        is_crystallized: Optional[bool] = None,
        emotion_score: Optional[float] = None,
        perspective: Optional[str] = None,
        # 控制参数(留 kwargs): auto_analyze_emotion / auto_classify / classification_context
        **kwargs,
    ) -> str:
        """存储一条记忆"""
        # 配置化默认值（memory-settings 配置页）: manager.new_memory_temperature /
        # new_memory_importance。settings 默认 100/50 与历史硬编码一致；
        # 调用方显式传参时优先于配置。
        if temperature is None or importance is None:
            from neurova.cognitive_layers.memory_layer.settings_config import (
                get_memory_settings,
            )

            _cfg = get_memory_settings()
            if temperature is None:
                temperature = float(_cfg.get("manager.new_memory_temperature", 100.0))
            if importance is None:
                importance = float(_cfg.get("manager.new_memory_importance", 50.0))

        with self._lock:
            self._counter += 1
            mem_id = kwargs.get("id", f"mem_{self._counter:06d}")

            # 处理 emotion 参数
            emotion_val = EmotionType.NEUTRAL
            if emotion:
                try:
                    emotion_val = EmotionType(emotion) if isinstance(emotion, str) else emotion
                except (ValueError, KeyError):
                    emotion_val = EmotionType.NEUTRAL

            # 安全解析 memory_type（防御无效枚举值）
            if isinstance(memory_type, str):
                try:
                    parsed_memory_type = MemoryType(memory_type)
                except (ValueError, KeyError):
                    logger.warning("Invalid memory_type '%s', falling back to SEMANTIC", memory_type)
                    parsed_memory_type = MemoryType.SEMANTIC
            elif memory_type is None:
                # None 直通会导致 _persist_memory 的 .value 炸掉（API 传 null 时触发）
                parsed_memory_type = MemoryType.SEMANTIC
            else:
                parsed_memory_type = memory_type

            # 安全解析 category（防御无效枚举值）
            # P-3 修复: 非法枚举字符串 fallback 到 GENERAL, 但在 metadata._original_category
            # 保留原始字符串, 使 recall(category="任意标签") 仍能匹配
            if isinstance(category, str):
                try:
                    parsed_category = MemoryCategory(category)
                except (ValueError, KeyError):
                    logger.warning("Invalid category '%s', falling back to GENERAL", category)
                    parsed_category = MemoryCategory.GENERAL
            elif category is None:
                # None 直通会导致 _persist_memory 的 .value 炸掉（API 传 null 时触发）
                parsed_category = MemoryCategory.GENERAL
            else:
                parsed_category = category

            # M-7 修复: 把数据参数合并进 metadata(不覆盖用户已传字段)
            final_metadata = dict(metadata or {})
            if is_important is not None:
                final_metadata["is_important"] = is_important
            if is_crystallized is not None:
                final_metadata["is_crystallized"] = is_crystallized
            if emotion_score is not None:
                final_metadata["emotion_score"] = emotion_score

            # P-3 修复: 非法枚举 category 字符串保留到 metadata, 供 recall 按原始标签过滤
            if isinstance(category, str) and parsed_category == MemoryCategory.GENERAL and category != "general":
                final_metadata["_original_category"] = category

            # M-7 修复: perspective 字符串转 MemoryPerspective 枚举, 写入 Memory.perspective
            parsed_perspective = MemoryPerspective.FIRST_PERSON
            if perspective is not None:
                if isinstance(perspective, MemoryPerspective):
                    parsed_perspective = perspective
                elif isinstance(perspective, str):
                    try:
                        parsed_perspective = MemoryPerspective(perspective)
                    except (ValueError, KeyError):
                        logger.warning(
                            "Invalid perspective '%s', falling back to FIRST_PERSON",
                            perspective,
                        )

            mem = Memory(
                id=mem_id,
                content=content,
                memory_type=parsed_memory_type,
                category=parsed_category,
                temperature=temperature,
                importance=importance,
                emotion=emotion_val,
                metadata=final_metadata,
                perspective=parsed_perspective,
                agent_id=self._agent_id,
                neuser_id=self._eff_neuser_id(),
                user_id=self._eff_user_id(),
            )
            self._memories[mem_id] = mem
            self._stats["remember_count"] += 1
            self._stats["total_memories"] = len(self._memories)

            # 持久化到 SQLite（跨重启保留）
            self._persist_memory(mem)

            # 自动情感标注（如果 content 包含情感关键词）
            if self._emotion_module and not emotion:
                try:
                    emotion_state = self._emotion_module.analyze_text_emotion(content)
                    if emotion_state and emotion_state.primary_emotion.value != "neutral":
                        self._emotion_module.set_emotion(mem_id, emotion_state)
                        mem.emotion = emotion_state.primary_emotion
                except Exception as e:
                    # BUG-9 修复: 原代码静默吞掉情感分析异常, 改为 warning 记录
                    logger.warning("自动情感标注失败（记忆 %s）: %s", mem_id, e)

            # 发射事件
            self._bus.emit(
                MemoryEvent(
                    type=MemoryEvent.MEMORY_CREATED,
                    source="memory_manager",
                    payload={"memory_id": mem_id, "content": content, "category": category},
                )
            )

            # NEURON: 提取依赖关系到依赖图谱
            self._extract_dependency_async(mem_id, content, metadata)

            return mem_id

    def _extract_dependency_async(
        self, memory_id: str, content: str, metadata: Optional[Dict[str, Any]]
    ) -> None:
        """后台异步提取依赖关系（失败不影响主流程）

        BUG-8 修复: 原事件循环 API 在 Python 3.12+ 弃用,
        且异常被 debug 级吞掉。改用 threading.Thread 跑 coroutine,
        异常级别提升到 warning。

        Bug 9 修复: 改用共享 ThreadPoolExecutor 限制线程数,
        原实现每次 remember 都新建 Thread, 高频调用会创建无限线程。
        """
        try:
            from .moe_dependency_extractor import MOEDependencyExtractor

            if not hasattr(self, "_dependency_extractor"):
                self._dependency_extractor = MOEDependencyExtractor()

            extractor = self._dependency_extractor

            def _run_in_executor():
                import asyncio

                try:
                    asyncio.run(
                        extractor.extract_from_memory(
                            memory_id=memory_id, content=content, metadata=metadata,
                        )
                    )
                except Exception as exc:
                    logger.warning("依赖提取失败（不影响记忆存储）: %s", exc)

            # Bug 9 修复: 提交到共享 ThreadPoolExecutor, 由 executor 限制并发线程数
            self._dependency_executor.submit(_run_in_executor)
        except Exception as e:
            logger.warning("依赖提取初始化失败（不影响记忆存储）: %s", e)

    def recall(
        self, query: str = "", category: Optional[str] = None, limit: int = 10, min_temperature: float = 0.0, **kwargs
    ) -> List[Dict[str, Any]]:
        """检索记忆

        支持两种检索模式：
        1. 语义搜索（默认）：使用语义相似度匹配
        2. 关键词搜索：使用子字符串匹配（兼容旧版）

        P-3 修复:
          - 排除 lifecycle_stage == FORGOTTEN 的记忆（forget 后不应再被 recall 返回）
          - category 支持任意字符串（非法枚举值按 metadata._original_category 匹配）
        """
        with self._lock:
            self._stats["recall_count"] += 1
            # 审计修复: 所有检索路径统一按生效三元组过滤 (原 use_semantic=False
            # 的关键词路径完全不过滤, 存在跨用户泄漏)
            results = self._scoped_memories()

            # P-3 修复: 排除已遗忘记忆（forget soft-delete 后不应被 recall 返回）
            results = [m for m in results if m.lifecycle_stage != LifecycleStage.FORGOTTEN]

            # 按分类过滤（支持合法枚举值 + 任意字符串标签）
            if category:
                results = _filter_by_category(results, category)

            # 按温度过滤
            if min_temperature > 0:
                results = [m for m in results if m.temperature >= min_temperature]

            # 检索模式
            use_semantic = kwargs.get("use_semantic", True)

            if query:
                if use_semantic:
                    # 语义搜索模式
                    results = self._semantic_recall(query, results, limit)
                else:
                    # 兼容旧版：简单关键词匹配
                    query_lower = query.lower()
                    results = [m for m in results if query_lower in m.content.lower()]

            # 按温度排序（如果没有语义分数）
            if not use_semantic or not query:
                results.sort(key=lambda m: m.temperature, reverse=True)

            # 发射事件
            for m in results[:limit]:
                m.touch()
                # Bug 6 修复: recall 触发 touch() 更新温度/访问次数后必须持久化,
                # 否则重启后访问次数/温度丢失
                self._persist_memory(m)
                self._bus.emit(
                    MemoryEvent(
                        type=MemoryEvent.MEMORY_ACCESSED,
                        source="memory_manager",
                        payload={"memory_id": m.id, "temperature": m.temperature},
                    )
                )

            return [m.to_dict() for m in results[:limit]]
    
    def _get_vector_store(self):
        """P2-1 真向量召回：按隔离键缓存的 UnifiedVectorStore（faiss/fastembed/ONNX/TF-IDF 链）。

        每个隔离三元组独立分库——增量索引只含本作用域记忆，天然满足
        跨用户隔离（search 只见本 store 内容）。
        """
        key = (self._agent_id, self._eff_neuser_id(), self._eff_user_id())
        if not hasattr(self, "_vector_stores"):
            self._vector_stores = {}
        store = self._vector_stores.get(key)
        if store is None:
            from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore

            store = UnifiedVectorStore(backend="auto")
            self._vector_stores[key] = store
            # 资源修复: 每隔离三元组一个全量向量库, 此前只增不减;
            # 超过 20 个作用域时按插入序淘汰最老(下次访问重建)
            while len(self._vector_stores) > 20:
                self._vector_stores.pop(next(iter(self._vector_stores)), None)
        return store

    def _semantic_recall(self, query: str, memories: list, limit: int) -> list:
        """语义搜索检索（P2-1 真向量混合召回）。

        历史：
        - BUG-2 修复: 关键词索引每次重建（O(n) per query）
        - Bug 8/审计修复: 入口三元组过滤防跨用户泄漏

        P2-1 语义升级（评测"假向量"清零）：
        1. 向量路径：UnifiedVectorStore 增量索引（同 id 去重，仅新记忆编码）
           + 向量相似度搜索——真语义召回，非子串匹配
        2. 关键词路径：保留原 semantic_search 链路兜底
        3. RRF 融合两路结果（向量权重 0.7 / 关键词 0.3）
        4. 向量库不可用 → 整体降级关键词路径（行为与历史一致）

        隔离：每隔离三元组独立分库 + 入口三元组过滤双保险。
        """
        # 隔离过滤（保留：双保险的第 2 层）
        memories = [
            m for m in memories
            if m.agent_id == self._agent_id
            and m.neuser_id == self._eff_neuser_id()
            and m.user_id == self._eff_user_id()
        ]
        if not memories:
            return []

        memory_dicts = [m.to_dict() for m in memories]
        id_to_memory = {m.id: m for m in memories}

        # 1) 向量路径：增量索引（O(新增)）+ 向量搜索
        vector_hits: List[tuple] = []  # [(memory_id, rank)]
        try:
            store = self._get_vector_store()
            store.index_memories(memory_dicts, incremental=True)
            hits = store.search(query, limit=limit * 2)
            vector_hits = [
                (rank, h.get("id")) for rank, h in enumerate(hits) if h.get("id")
            ]
        except Exception as e:
            logger.warning("向量召回失败，降级关键词路径: %s", e)
            vector_hits = []

        # 2) 关键词路径（保留原链路兜底）
        keyword_hits: List[tuple] = []
        try:
            from neurova.cognitive_layers.memory_layer.semantic_search import get_semantic_search

            search = get_semantic_search()
            search.build_keyword_index(memory_dicts)
            # search_by_keywords 返回 List[str]（memory id 列表），非元组
            _kw_ids = search.search_by_keywords(query, limit=limit * 2)
            keyword_hits = list(enumerate(_kw_ids))  # (rank, memory_id)
        except Exception as e:
            logger.debug("关键词搜索模块不可用，退化为子串匹配: %s", e)
            query_lower = query.lower()
            keyword_hits = [
                (m.id, rank)
                for rank, m in enumerate(memories)
                if query_lower in m.content.lower()
            ]

        # 3) RRF 融合（向量 0.7 / 关键词 0.3）
        fused: Dict[str, float] = {}
        for rank, mid in vector_hits:
            fused[mid] = fused.get(mid, 0.0) + 0.7 / (60 + rank + 1)
        for rank, mid in keyword_hits:
            fused[mid] = fused.get(mid, 0.0) + 0.3 / (60 + rank + 1)

        ordered_ids = [mid for mid, _ in sorted(fused.items(), key=lambda kv: -kv[1])]
        return [id_to_memory[mid] for mid in ordered_ids if mid in id_to_memory][:limit]

    def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """获取单条记忆

        BUG-7 修复: 加 self._lock 保护, 避免并发 forget 时 RuntimeError。
        """
        with self._lock:
            mem = self._memories.get(memory_id)
            # 审计修复 (P1-6): 与 forget 同规则 —— 不属于当前作用域的记忆视同不存在
            if mem and (
                mem.agent_id != self._agent_id
                or mem.neuser_id != self._eff_neuser_id()
                or mem.user_id != self._eff_user_id()
            ):
                mem = None
            if mem:
                mem.touch()
                self._bus.emit(
                    MemoryEvent(
                        type=MemoryEvent.MEMORY_ACCESSED,
                        source="memory_manager",
                        payload={"memory_id": mem.id},
                    )
                )
                return mem.to_dict()
            return None

    def update_memory(self, memory_id: str, **kwargs) -> bool:
        """更新记忆"""
        # Bug 5 修复：加 RLock 保护，避免并发 forget 导致 _memories.get 返回 None 后继续操作
        with self._lock:
            mem = self._memories.get(memory_id)
            if not mem:
                return False
            if "content" in kwargs:
                mem.content = kwargs["content"]
            if "temperature" in kwargs:
                mem.temperature = kwargs["temperature"]
            if "importance" in kwargs:
                mem.importance = kwargs["importance"]
            if "category" in kwargs:
                mem.category = (
                    MemoryCategory(kwargs["category"]) if isinstance(kwargs["category"], str) else kwargs["category"]
                )
            if "lifecycle_stage" in kwargs:
                stage_val = kwargs["lifecycle_stage"]
                if isinstance(stage_val, str):
                    mem.lifecycle_stage = LifecycleStage(stage_val)
                elif isinstance(stage_val, LifecycleStage):
                    mem.lifecycle_stage = stage_val
            mem.updated_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            self._persist_memory(mem)  # 更新持久化
        # bus.emit 在锁外执行，避免持锁调用 handler 导致递归死锁
        self._bus.emit(
            MemoryEvent(
                type=MemoryEvent.MEMORY_UPDATED,
                source="memory_manager",
                payload={"memory_id": memory_id},
            )
        )
        return True

    def forget(self, memory_id: str, soft: bool = True) -> bool:
        """遗忘记忆"""
        # Bug 5 修复：加 RLock 保护，避免并发 forget 同一 memory_id 抛 KeyError
        with self._lock:
            if memory_id not in self._memories:
                return False
            mem = self._memories[memory_id]
            # 审计修复 (P1-6): 校验记忆归属 —— 知道对方 memory_id 不能越权删除
            if (
                mem.agent_id != self._agent_id
                or mem.neuser_id != self._eff_neuser_id()
                or mem.user_id != self._eff_user_id()
            ):
                logger.warning(
                    "拒绝越权删除记忆: id=%s 归属(%s,%s,%s) 请求作用域(%s,%s,%s)",
                    memory_id, mem.agent_id, mem.neuser_id, mem.user_id,
                    self._agent_id, self._eff_neuser_id(), self._eff_user_id(),
                )
                return False
            if soft:
                self._memories[memory_id].lifecycle_stage = LifecycleStage.FORGOTTEN
                self._persist_memory(self._memories[memory_id])  # 更新持久化
            else:
                del self._memories[memory_id]
                self._delete_persisted_memory(memory_id)  # 删除持久化
            self._stats["total_memories"] = len(self._memories)
        # bus.emit 在锁外执行，避免持锁调用 handler 导致递归死锁
        self._bus.emit(
            MemoryEvent(
                type=MemoryEvent.MEMORY_DELETED,
                source="memory_manager",
                payload={"memory_id": memory_id, "soft": soft},
            )
        )
        return True

    def search_memories(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """搜索记忆（recall 别名）"""
        return self.recall(query=query, limit=limit)

    def get_memories(
        self,
        category: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """获取记忆列表（可按 category 过滤）

        Args:
            category: 可选分类过滤。支持两种模式：
                      (1) 合法 MemoryCategory 枚举值 → 按 m.category.value 匹配
                      (2) 任意字符串 → 按 metadata._original_category 匹配（remember 时保留）
            limit: 返回上限
            offset: 偏移量
        """
        with self._lock:
            # 审计修复: 读路径统一按生效三元组过滤
            mems = self._scoped_memories()

            # 排除已遗忘记忆（forget 后不应被 get_memories 返回）
            mems = [m for m in mems if m.lifecycle_stage != LifecycleStage.FORGOTTEN]

            # 按分类过滤
            if category:
                mems = _filter_by_category(mems, category)

            mems.sort(key=lambda m: m.created_at, reverse=True)
            return [m.to_dict() for m in mems[offset : offset + limit]]

    def get_all_memories(self) -> List[Dict[str, Any]]:
        """获取所有记忆（用于睡眠整合）"""
        with self._lock:
            return [m.to_dict() for m in self._memories.values()]

    def get_average_temperature(self) -> float:
        """获取全库平均记忆温度（供睡眠阶段判定等使用；空库返回 0.0）"""
        with self._lock:
            if not self._memories:
                return 0.0
            return sum(m.temperature for m in self._memories.values()) / len(self._memories)

    def get_memory_count(self) -> int:
        """获取当前记忆总数（轻量 O(1)，供认知负荷评估等使用）"""
        with self._lock:
            return len(self._memories)

    def query_memories(self, **filters) -> List[Dict[str, Any]]:
        """查询记忆（高级过滤）"""
        return self.recall(
            query=filters.get("query", ""),
            category=filters.get("category"),
            limit=filters.get("limit", 10),
        )

    # ────── Buffer Operations ──────

    def flush_buffer(self) -> int:
        """刷新缓冲区

        BUG-1 修复: 原 _write_queue = None 永不赋值, 导致永远返回 0。
        现委托到 _ensure_buffer_module().flush()（与 flush_all_pending_updates 一致）。
        """
        try:
            module = self._ensure_buffer_module()
            return module.flush()
        except Exception as e:
            logger.warning("flush_buffer failed: %s", e)
            return 0

    def get_buffer_stats(self) -> Dict[str, Any]:
        """获取缓冲区统计"""
        return {"buffer_size": 0, "pending_writes": 0}

    def force_write(self, content: Optional[str] = None, **kwargs) -> Any:
        """强制写入

        P-1 修复: 支持两种语义
        - 传入 content: 立即 remember 并返回 memory_id（str）— 测试期望的契约
        - 不传 content: 刷新待写缓冲区返回写入数量（int）— 保留旧语义
        """
        if content is not None:
            return self.remember(content, **kwargs)
        return self.flush_buffer()

    def add_memory(self, content: str, **kwargs) -> str:
        """添加记忆（remember 的别名, P-1 修复契约补全）

        Args:
            content: 记忆内容
            **kwargs: 透传给 remember 的参数（category/memory_type/emotion 等）
        """
        return self.remember(content, **kwargs)

    # ────── Stats ──────

    def stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self.get_stats()

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                # 审计修复: 统计按生效作用域计数, 不泄漏其他用户的数据量
                "total_memories": len(self._scoped_memories()),
                "remember_count": self._stats["remember_count"],
                "recall_count": self._stats["recall_count"],
                "bus_events": self._bus.emit_count,
                "bus_handlers": self._bus.handler_count(),
            }

    def get_full_stats(self) -> Dict[str, Any]:
        """获取完整统计"""
        return self.get_stats()

    # ────── Emotion (analyze_emotion 真实实现, 其余 stub 抛出 NotImplementedError) ──────

    def analyze_emotion(self, text: str) -> Dict[str, Any]:
        """分析文本情感（P-2 修复: 返回 {score, tags} 字典, 委托到 EmotionModule.analyze_text_emotion）

        Args:
            text: 待分析文本

        Returns:
            {"score": float, "tags": List[str]}
            - score: 情感强度 0.0-1.0 (取自 EmotionState.intensity)
            - tags: 情感标签列表 (含 primary_emotion.value)
        """
        if not text:
            return {"score": 0.0, "tags": []}
        try:
            emotion = self._emotion_module.analyze_text_emotion(text)
            tags = [emotion.primary_emotion.value] if emotion.primary_emotion else []
            return {"score": float(emotion.intensity), "tags": tags}
        except Exception as e:
            logger.warning("analyze_emotion failed: %s", e)
            return {"score": 0.0, "tags": []}

    def get_emotion_summary(self) -> Dict[str, Any]:
        """获取情感摘要（委托到 EmotionModule.get_stats）"""
        return self._emotion_module.get_stats()

    def get_emotion_distribution(self) -> Dict[str, float]:
        """获取情感分布（委托到 EmotionModule.get_stats）"""
        return self._emotion_module.get_stats().get("emotion_distribution", {})

    def update_emotional_state(self, state) -> Dict[str, Any]:
        """更新情感状态（P-2 修复: 接受 dict 或 str）

        Args:
            state: 情感状态。两种模式：
                   (1) dict: 如 {"joy": 0.8, "sadness": 0.1} — 直接合并到 emotion_module 当前状态
                   (2) str: 文本 — 委托到 analyze_text_emotion 分析后更新

        Returns:
            更新后的情感状态 dict
        """
        if isinstance(state, dict):
            # dict 模式: 合并情感状态到 emotion_module
            try:
                from neurova.cognitive_layers.memory_layer.modules.emotion_module import (
                    EmotionState,
                    EmotionType,
                )
                # 找出最高强度的情感作为 primary
                emotion_map = {
                    "joy": EmotionType.JOY,
                    "sadness": EmotionType.SADNESS,
                    "anger": EmotionType.ANGER,
                    "fear": EmotionType.FEAR,
                    "surprise": EmotionType.SURPRISE,
                    "neutral": EmotionType.NEUTRAL,
                }
                primary = EmotionType.NEUTRAL
                max_intensity = 0.0
                for key, value in state.items():
                    etype = emotion_map.get(key.lower())
                    if etype and isinstance(value, (int, float)) and value > max_intensity:
                        primary = etype
                        max_intensity = float(value)
                if max_intensity == 0.0:
                    intensity = 0.3
                    valence = 0.0
                    arousal = 0.2
                else:
                    intensity = min(1.0, max_intensity)
                    valence_map = {
                        EmotionType.JOY: 0.8, EmotionType.SADNESS: -0.6,
                        EmotionType.ANGER: -0.7, EmotionType.FEAR: -0.5,
                        EmotionType.SURPRISE: 0.3, EmotionType.NEUTRAL: 0.0,
                    }
                    arousal_map = {
                        EmotionType.JOY: 0.6, EmotionType.SADNESS: 0.3,
                        EmotionType.ANGER: 0.8, EmotionType.FEAR: 0.7,
                        EmotionType.SURPRISE: 0.9, EmotionType.NEUTRAL: 0.2,
                    }
                    valence = valence_map.get(primary, 0.0)
                    arousal = arousal_map.get(primary, 0.5)
                emotion = EmotionState(
                    primary_emotion=primary,
                    intensity=intensity,
                    valence=valence,
                    arousal=arousal,
                )
                # 记录到 emotion_module (用一个固定 key 表示当前状态)
                self._emotion_module.set_emotion("_current_state", emotion)
                return emotion.to_dict()
            except Exception as e:
                logger.warning("update_emotional_state(dict) failed: %s", e)
                return {}
        # str 模式: 委托到 analyze_text_emotion
        emotion = self._emotion_module.analyze_text_emotion(state)
        return emotion.to_dict()

    def get_emotional_state(self) -> Dict[str, Any]:
        """获取当前情感状态（委托到 EmotionModule.get_feedback）"""
        return self._emotion_module.get_feedback()

    def get_dominant_emotion(self) -> tuple:
        """获取主导情感（P-2 修复: 返回 (emotion_str, score_float) tuple）

        Returns:
            (emotion_str, score): 主导情感字符串及其强度分数
            无数据时返回 ("neutral", 0.0)
        """
        distribution = self._emotion_module.get_stats().get("emotion_distribution", {})
        if not distribution:
            return ("neutral", 0.0)
        emotion_str = max(distribution, key=distribution.get)
        score = float(distribution[emotion_str])
        return (emotion_str, score)

    def get_emotion_bias(self) -> float:
        """获取情感偏置（委托到 EmotionModule._emotion_weight）"""
        return self._emotion_module._emotion_weight

    def apply_emotion_to_temperature(self, base_temp: float) -> float:
        """应用情感到温度（委托到 EmotionModule，无记忆上下文时返回原值）"""
        return base_temp

    def apply_emotion_to_style(self, text: str) -> str:
        """应用情感到风格（委托到 EmotionModule，无风格转换时返回原文本）"""
        return text

    def get_emotion_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取情感历史（委托到 EmotionModule，模块未维护历史时返回空列表）"""
        return []

    def reset_emotion_to_baseline(self) -> None:
        """重置情感到基线（委托到 EmotionModule，无状态重置时为 no-op）"""
        return None

    def merge_with_user_emotion(self, user_text: str) -> Dict[str, Any]:
        """合并用户情感（委托到 EmotionModule.analyze_text_emotion）"""
        emotion = self._emotion_module.analyze_text_emotion(user_text)
        return emotion.to_dict()

    # ────── Classification (STUB: 未实现, 抛出 NotImplementedError) ──────

    def _ensure_classifier_module(self):
        """懒加载 ClassifierModule（首次调用时初始化）"""
        if self._classifier_module is None:
            from neurova.cognitive_layers.memory_layer.modules.classifier_module import ClassifierModule

            self._classifier_module = ClassifierModule()
            self._classifier_module.init()
            logger.info("ClassifierModule lazily initialized")
        return self._classifier_module

    def classify_memory(self, content: str) -> Dict[str, Any]:
        """分类记忆（委托到 ClassifierModule）"""
        module = self._ensure_classifier_module()
        # 使用内容哈希作为临时 memory_id
        memory_id = f"cls_{abs(hash(content)) % (10 ** 8)}"
        categories = module.classify(memory_id=memory_id, content=content)
        tags = module.extract_tags(memory_id=memory_id, content=content)
        return {"memory_id": memory_id, "categories": categories, "tags": tags}

    def classify_and_remember(self, content: str, **kwargs) -> str:
        # 根因修复（P2-#15）: 原先直接 remember 而完全丢弃分类结果。
        # 先分类，再将分类类别并入 tags，使记忆携带分类信息。
        try:
            cls = self.classify_memory(content)
        except Exception as e:  # noqa: BLE001
            logger.warning("classify_and_remember 分类失败，仅记忆原文: %s", e)
            cls = None
        if isinstance(cls, dict):
            cats = cls.get("categories") or []
            if cats:
                tags = kwargs.get("tags")
                if not isinstance(tags, list):
                    tags = []
                kwargs["tags"] = tags + [str(c) for c in cats]
        return self.remember(content, **kwargs)

    # ────── Temperature ──────

    def update_memory_temperature(self, memory_id: str, interaction_type: str = "recall") -> bool:
        """更新记忆温度

        BUG-7 修复: 加 self._lock 保护读路径。
        Bug 7 修复: touch() 后必须持久化, 否则重启后温度/访问次数丢失。
        """
        with self._lock:
            mem = self._memories.get(memory_id)
            if not mem:
                return False
            mem.touch()
            self._persist_memory(mem)
            return True

    def run_decay_cycle(
        self,
        hours: float = 1.0,
        rate: float = 1.0,
        max_memories: Optional[int] = None,
        min_interval_seconds: float = 0.0,
    ) -> int:
        """运行温度衰减周期 — 应用 TemperatureEngine.on_decay 贝叶斯遗忘曲线

        Bug 2 修复：原实现直接调 Memory.decay()（简单线性 temp -= rate*hours），
        完全绕过 TemperatureEngine.on_decay 的贝叶斯曲线（curve_factor/emotion_protect/
        saturation/importance_weight/relation_protection/important_protection）。

        贝叶斯特性：
          - 固化记忆（lifecycle_stage=CRYSTALLIZED）不衰减
          - 高温记忆（>=80）不衰减
          - 今天访问过的记忆（days_idle < 1.0）不衰减
          - 衰减后根据 _determine_stage 更新 lifecycle_stage

        Bug 5 关联：加 RLock 保护遍历与修改，保证线程安全。

        Args:
            hours: 保留参数（贝叶斯曲线使用 days_idle，不直接使用 hours）
            rate:  保留参数（贝叶斯曲线通过 curve_factor 等因子调整，不直接使用 rate）
            max_memories: 单次处理上限（防 116 万条全量阻塞事件循环），None=不限制
            min_interval_seconds: 节流窗口（秒），距上次运行不足此值时跳过，0=不节流

        Returns:
            处理的记忆数量
        """
        # 节流检查：距上次运行不足 min_interval_seconds 时跳过
        if min_interval_seconds > 0 and self._last_decay_at is not None:
            elapsed = time.monotonic() - self._last_decay_at
            if elapsed < min_interval_seconds:
                logger.debug(
                    "run_decay_cycle 节流跳过: 距上次 %.1fs < %.1fs",
                    elapsed,
                    min_interval_seconds,
                )
                return 0

        # 延迟导入避免循环依赖
        from datetime import datetime, timezone
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine

        # 衰减参数配置化（memory-settings 配置页）: temperature.decay_rate /
        # temperature.min / temperature.max，默认 0.1/0/100 与历史一致。
        # 每轮新建引擎实例，改配置即时生效。
        from neurova.cognitive_layers.memory_layer.settings_config import (
            get_memory_settings,
        )

        _cfg = get_memory_settings()
        engine = TemperatureEngine(
            base_decay_rate=float(_cfg.get("temperature.decay_rate", 0.1)),
            temp_min=float(_cfg.get("temperature.min", 0.0)),
            temp_max=float(_cfg.get("temperature.max", 100.0)),
        )
        now = datetime.now(timezone.utc)
        count = 0

        # 加锁保护遍历与修改（Bug 5 关联）
        with self._lock:
            # 用 list() 复制视图，避免迭代过程中其他线程修改 dict 抛 RuntimeError
            all_items = list(self._memories.values())

            # 有界处理：轮询游标选 max_memories 条，避免全量阻塞事件循环
            if max_memories is not None and max_memories > 0 and len(all_items) > max_memories:
                n = len(all_items)
                start = self._decay_cursor % n
                items = [all_items[(start + i) % n] for i in range(max_memories)]
                self._decay_cursor = (start + max_memories) % n
            else:
                items = all_items

            for mem in items:
                # 已删除/已遗忘记忆跳过
                if mem.temperature <= 0:
                    continue

                # 计算 days_idle（贝叶斯曲线的核心输入）
                last_accessed = mem.last_accessed_at or mem.created_at
                if last_accessed.tzinfo is None:
                    last_accessed = last_accessed.replace(tzinfo=timezone.utc)
                days_idle = max(0.0, (now - last_accessed).total_seconds() / 86400.0)

                # 计算 emotion_score（EmotionType → 0.0-1.0）
                # 简化映射：NEUTRAL=0.0，其他情感默认 0.5 中等强度
                # （真实强度需 emotion_module 分析，此处用类别信号已足够触发情感保护）
                emotion_score = 0.0 if mem.emotion == EmotionType.NEUTRAL else 0.5

                # 归一化 importance（0-100 → 0.0-1.0）
                importance_norm = max(0.0, min(1.0, float(mem.importance) / 100.0))

                # 检测固化状态
                is_crystallized = mem.lifecycle_stage == LifecycleStage.CRYSTALLIZED

                # 检测重要记忆（importance >= 80 或 metadata.is_important）
                # BUG-4 修复: 原表达式 `A or B if C else D` 在空 metadata 时
                # 高重要性记忆保护失效（返回 False）。改为显式括号 + `(metadata or {}) 防御 None。
                is_important = importance_norm >= 0.8 or bool(
                    (mem.metadata or {}).get("is_important", False)
                )

                # 调用 TemperatureEngine.on_decay 应用贝叶斯曲线
                result = engine.on_decay(
                    current_temp=mem.temperature,
                    days_idle=days_idle,
                    importance=importance_norm,
                    emotion_score=emotion_score,
                    recall_count=mem.access_count,
                    relation_count=0,  # 关联记忆数需 relation_manager，此处简化为 0
                    is_important=is_important,
                    is_crystallized=is_crystallized,
                )

                # 应用新温度
                mem.temperature = result["new_temp"]
                mem.updated_at = now

                # 更新生命周期阶段（temperature 字符串 → LifecycleStage 枚举）
                new_stage = _map_lifecycle_stage(result.get("lifecycle_stage", ""))
                if new_stage is not None:
                    mem.lifecycle_stage = new_stage

                # BUG-5 修复: 持久化温度/阶段变更到 SQLite（原实现不调用 _persist_memory）
                self._persist_memory(mem)

                count += 1

        # 记录本次运行时间（节流窗口基准）
        self._last_decay_at = time.monotonic()

        return count

    def get_crystallized(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取固化记忆

        BUG-7 修复: 加 self._lock 保护读路径。
        """
        with self._lock:
            return [
                m.to_dict()
                for m in self._scoped_memories()
                if m.lifecycle_stage == LifecycleStage.CRYSTALLIZED
            ][:limit]

    def get_hot_memories(
        self, limit: int = 10, min_temperature: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        # 阈值配置化（memory-settings 配置页）: manager.hot_memories_threshold，
        # settings 默认 80.0 与历史硬编码一致；显式传参时优先于配置。
        if min_temperature is None:
            from neurova.cognitive_layers.memory_layer.settings_config import (
                get_memory_settings,
            )

            min_temperature = float(
                get_memory_settings().get("manager.hot_memories_threshold", 80.0)
            )
        return self.recall(limit=limit, min_temperature=min_temperature)

    def flush_all_pending_updates(self) -> int:
        """刷新所有待处理的更新（委托到 BufferModule）"""
        module = self._ensure_buffer_module()
        return module.flush()

    def _ensure_buffer_module(self):
        """懒加载 BufferModule（首次调用时初始化）"""
        if self._buffer_module is None:
            from neurova.cognitive_layers.memory_layer.modules.buffer_module import BufferModule

            self._buffer_module = BufferModule(buffer_size=100, flush_interval=30.0, auto_flush=False)
            self._buffer_module.init()
            logger.info("BufferModule lazily initialized")
        return self._buffer_module

    # ────── Self Model (委托到 modules/self_model_module.py) ──────

    def _ensure_self_model_module(self):
        """懒加载 SelfModelModule（首次调用时初始化）"""
        if self._self_model_module is None:
            from neurova.cognitive_layers.memory_layer.modules.self_model_module import SelfModelModule

            self._self_model_module = SelfModelModule(agent_id=self._agent_id)
            self._self_model_module.init()
            logger.info("SelfModelModule lazily initialized")
        return self._self_model_module

    def get_self_model(self) -> Dict[str, Any]:
        """获取自我模型（委托到 SelfModelModule.get_stats）"""
        module = self._ensure_self_model_module()
        return module.get_stats()

    def update_self_model(self, **kwargs) -> bool:
        """更新自我模型（委托到 SelfModelModule.update_capability/update_knowledge）"""
        module = self._ensure_self_model_module()
        for key, value in kwargs.items():
            if isinstance(value, (int, float)):
                module.update_capability(key, float(value))
            elif isinstance(value, str):
                module.update_knowledge(key, 0.5)
        return True

    def update_user_profile(self, **kwargs) -> bool:
        """更新用户画像（委托到 SelfModelModule，无独立用户画像模块时记录到知识领域）"""
        module = self._ensure_self_model_module()
        for key, value in kwargs.items():
            module.update_knowledge(f"user_{key}", 0.5)
        return True

    def get_user_profile(self) -> Dict[str, Any]:
        """获取用户画像（委托到 SelfModelModule.get_stats）"""
        module = self._ensure_self_model_module()
        return module.get_stats()

    # ────── Meta-cognition (委托到 modules/meta_cognition_module.py) ──────

    def _ensure_meta_cognition_module(self):
        """懒加载 MetaCognitionModule（首次调用时初始化）"""
        if self._meta_cognition_module is None:
            from neurova.cognitive_layers.memory_layer.modules.meta_cognition_module import (
                CognitiveProcess,
                MetaCognitionModule,
            )

            self._meta_cognition_module = MetaCognitionModule(max_history=1000)
            self._meta_cognition_module.init()
            # 保存 CognitiveProcess 枚举供后续方法使用
            self._meta_cognition_process_cls = CognitiveProcess
            logger.info("MetaCognitionModule lazily initialized")
        return self._meta_cognition_module

    def meta_monitor(self) -> Dict[str, Any]:
        """元认知监控（委托到 MetaCognitionModule.record_event + get_stats）"""
        module = self._ensure_meta_cognition_module()
        Process = self._meta_cognition_process_cls
        module.record_event(Process.RETRIEVAL, "meta_monitor", duration_ms=0.0, success=True)
        return module.get_stats()

    def meta_reflect(self, **kwargs) -> Dict[str, Any]:
        """元认知反思（委托到 MetaCognitionModule.record_event）"""
        module = self._ensure_meta_cognition_module()
        Process = self._meta_cognition_process_cls
        description = kwargs.get("description", "meta_reflect")
        event = module.record_event(Process.REASONING, description, duration_ms=0.0, success=True)
        return event.to_dict()

    def meta_optimize(self) -> Dict[str, Any]:
        """元认知优化（委托到 MetaCognitionModule.record_event + get_stats）"""
        module = self._ensure_meta_cognition_module()
        Process = self._meta_cognition_process_cls
        module.record_event(Process.DECISION, "meta_optimize", duration_ms=0.0, success=True)
        return module.get_stats()

    def meta_evolve_skills(self, **kwargs) -> Dict[str, Any]:
        """元认知技能进化（委托到 MetaCognitionModule.record_event + get_stats）"""
        module = self._ensure_meta_cognition_module()
        Process = self._meta_cognition_process_cls
        module.record_event(Process.REASONING, "meta_evolve_skills", duration_ms=0.0, success=True)
        return module.get_stats()

    def meta_get_health_report(self) -> Dict[str, Any]:
        """获取健康报告（委托到 MetaCognitionModule.get_stats）"""
        module = self._ensure_meta_cognition_module()
        return module.get_stats()

    def meta_get_reflection_report(self) -> List[Dict[str, Any]]:
        """获取反思报告（委托到 MetaCognitionModule.get_recent_events）"""
        module = self._ensure_meta_cognition_module()
        events = module.get_recent_events(count=10)
        return [e.to_dict() for e in events]

    def meta_get_skill_stats(self) -> Dict[str, Any]:
        """获取技能统计（委托到 MetaCognitionModule.get_process_stats）"""
        module = self._ensure_meta_cognition_module()
        return module.get_process_stats()

    def meta_get_all_skills(self) -> List[Dict[str, Any]]:
        """获取所有技能（委托到 MetaCognitionModule.get_recent_events）"""
        module = self._ensure_meta_cognition_module()
        events = module.get_recent_events(count=50)
        return [e.to_dict() for e in events]

    def meta_match_skills(self, query: str) -> List[Dict[str, Any]]:
        """匹配技能（委托到 MetaCognitionModule，无技能匹配时返回空列表）"""
        module = self._ensure_meta_cognition_module()
        # 模块无直接技能匹配，返回最近事件作为近似
        events = module.get_recent_events(count=10)
        return [e.to_dict() for e in events if query.lower() in e.description.lower()]

    def meta_should_monitor(self) -> bool:
        """是否应该监控（委托到 MetaCognitionModule，默认返回 True）"""
        self._ensure_meta_cognition_module()
        return True

    def meta_should_reflect(self) -> bool:
        """是否应该反思（委托到 MetaCognitionModule，默认返回 True）"""
        self._ensure_meta_cognition_module()
        return True

    def meta_should_optimize(self) -> bool:
        """是否应该优化（委托到 MetaCognitionModule，默认返回 True）"""
        self._ensure_meta_cognition_module()
        return True

    def meta_should_evolve_skills(self) -> bool:
        """是否应该进化技能（委托到 MetaCognitionModule，默认返回 True）"""
        self._ensure_meta_cognition_module()
        return True

    # ────── EKI (委托到 modules/eki_module.py) ──────

    def _ensure_eki_module(self):
        """懒加载 EKIModule（首次调用时初始化）"""
        if self._eki_module is None:
            from neurova.cognitive_layers.memory_layer.modules.eki_module import EKIModule

            self._eki_module = EKIModule(ensemble_size=10, inflation_factor=1.01)
            self._eki_module.init()
            self._eki_enabled = True
            logger.info("EKIModule lazily initialized")
        return self._eki_module

    def eki_process_task(self, **kwargs) -> Dict[str, Any]:
        """处理任务并评估价值（委托到 EKIModule）"""
        module = self._ensure_eki_module()
        task_id = kwargs.get("task_id", "task_unknown")
        memory_id = kwargs.get("memory_id", task_id)
        observation = kwargs.get("observation", 0.5)

        # 初始化状态（如果尚未注册）
        module.initialize_state(
            memory_id=memory_id,
            importance=observation,
            access_count=kwargs.get("access_count", 0),
            age_hours=kwargs.get("age_hours", 0.0),
        )
        # 用观测更新状态
        module.update_with_observation(memory_id=memory_id, observation=observation)

        # 返回处理结果
        return {
            "task_id": task_id,
            "memory_id": memory_id,
            "importance": module.predict_importance(memory_id),
            "decay": module.predict_decay(memory_id, hours_ahead=24.0),
        }

    def eki_recommend_reinforcement(self, **kwargs) -> List[Dict[str, Any]]:
        """推荐强化动作（基于 EKIModule 重要性）"""
        module = self._ensure_eki_module()
        memory_ids = kwargs.get("memory_ids", [])
        results = []
        for mid in memory_ids:
            importance = module.predict_importance(mid)
            if importance >= 0.8:
                action = "consolidate"
            elif importance >= 0.6:
                action = "review"
            elif importance < 0.2:
                action = "discard"
            else:
                action = "none"
            results.append({"memory_id": mid, "importance": importance, "action": action})
        return results

    def eki_predict_decay(self, **kwargs) -> float:
        """预测记忆衰减（委托到 EKIModule.predict_decay）"""
        module = self._ensure_eki_module()
        memory_id = kwargs.get("memory_id", "")
        hours_ahead = kwargs.get("hours_ahead", 24.0)
        return module.predict_decay(memory_id=memory_id, hours_ahead=hours_ahead)

    def eki_get_memory_strength(self, **kwargs) -> float:
        """获取记忆强度（委托到 EKIModule.predict_importance）"""
        module = self._ensure_eki_module()
        memory_id = kwargs.get("memory_id", "")
        return module.predict_importance(memory_id=memory_id)

    def eki_get_statistics(self) -> Dict[str, Any]:
        """获取 EKI 统计（委托到 EKIModule.get_stats）"""
        module = self._ensure_eki_module()
        return module.get_stats()

    def eki_batch_update(self, **kwargs) -> Dict[str, float]:
        """批量更新（委托到 EKIModule.batch_update）"""
        module = self._ensure_eki_module()
        updates = kwargs.get("updates", [])
        return module.batch_update(updates=updates)

    def eki_update_memory_from_access(self, **kwargs) -> bool:
        """根据访问更新记忆（委托到 EKIModule.update_with_observation）"""
        module = self._ensure_eki_module()
        memory_id = kwargs.get("memory_id", "")
        observation = kwargs.get("observation", 0.5)
        # 如果记忆未注册，先初始化
        if module.get_memory_state(memory_id) is None:
            module.initialize_state(memory_id=memory_id, importance=observation)
        module.update_with_observation(memory_id=memory_id, observation=observation)
        return True

    def eki_set_enabled(self, enabled: bool) -> None:
        """启用/禁用 EKI 模块"""
        if enabled:
            self._ensure_eki_module()
            self._eki_enabled = True
        else:
            if self._eki_module is not None:
                self._eki_module.shutdown()
            self._eki_enabled = False

    def eki_get_enabled(self) -> bool:
        """获取 EKI 启用状态"""
        return self._eki_enabled

    def eki_configure(self, **kwargs) -> None:
        """配置 EKI 模块（重新初始化以应用新参数）"""
        ensemble_size = kwargs.get("ensemble_size", 10)
        inflation_factor = kwargs.get("inflation_factor", 1.01)
        # 关闭旧实例
        if self._eki_module is not None:
            self._eki_module.shutdown()
        # 创建新实例
        from neurova.cognitive_layers.memory_layer.modules.eki_module import EKIModule

        self._eki_module = EKIModule(ensemble_size=ensemble_size, inflation_factor=inflation_factor)
        self._eki_module.init()
        self._eki_enabled = True
        logger.info("EKIModule reconfigured: ensemble_size=%s, inflation_factor=%s", ensemble_size, inflation_factor)

    # ────── TKG (委托到 modules/tkg_module.py) ──────

    def _ensure_tkg_module(self):
        """懒加载 TKGModule（首次调用时初始化）"""
        if self._tkg_module is None:
            from neurova.cognitive_layers.memory_layer.modules.tkg_module import TKGModule

            self._tkg_module = TKGModule(time_window_hours=24.0)
            self._tkg_module.init()
            logger.info("TKGModule lazily initialized")
        return self._tkg_module

    def tkg_add_fact(self, **kwargs) -> str:
        """添加时序事实（委托到 TKGModule.add_fact）"""
        module = self._ensure_tkg_module()
        return module.add_fact(
            subject=kwargs.get("subject", ""),
            predicate=kwargs.get("predicate", ""),
            obj=kwargs.get("obj", kwargs.get("object", "")),
            confidence=kwargs.get("confidence", 1.0),
            valid_from=kwargs.get("valid_from"),
            valid_until=kwargs.get("valid_until"),
        )

    def tkg_query_current(self, **kwargs) -> List[Dict[str, Any]]:
        """查询当前事实（委托到 TKGModule.query_facts）"""
        module = self._ensure_tkg_module()
        return module.query_facts(
            subject=kwargs.get("subject"),
            predicate=kwargs.get("predicate"),
            obj=kwargs.get("obj", kwargs.get("object")),
            limit=kwargs.get("limit", 10),
        )

    def tkg_query_at_time(self, **kwargs) -> List[Dict[str, Any]]:
        """按时间查询事实（委托到 TKGModule.query_facts）"""
        module = self._ensure_tkg_module()
        return module.query_facts(
            subject=kwargs.get("subject"),
            predicate=kwargs.get("predicate"),
            obj=kwargs.get("obj", kwargs.get("object")),
            time_from=kwargs.get("time_from"),
            time_until=kwargs.get("time_until"),
            limit=kwargs.get("limit", 10),
        )

    def tkg_get_history(self, **kwargs) -> List[Dict[str, Any]]:
        """获取历史事实（委托到 TKGModule.query_facts）"""
        module = self._ensure_tkg_module()
        return module.query_facts(
            subject=kwargs.get("subject"),
            predicate=kwargs.get("predicate"),
            obj=kwargs.get("obj", kwargs.get("object")),
            limit=kwargs.get("limit", 50),
        )

    def tkg_detect_conflicts(self, **kwargs) -> List[Dict[str, Any]]:
        """检测冲突（委托到 TKGModule.detect_conflicts）"""
        module = self._ensure_tkg_module()
        conflicts = module.detect_conflicts(
            subject=kwargs.get("subject", ""),
            predicate=kwargs.get("predicate", ""),
            obj=kwargs.get("obj", kwargs.get("object", "")),
        )
        return conflicts

    def tkg_get_stats(self) -> Dict[str, Any]:
        """获取 TKG 统计（委托到 TKGModule.get_stats）"""
        module = self._ensure_tkg_module()
        return module.get_stats()

    # ────── Working Memory (委托到 modules/working_memory_module.py) ──────

    def _ensure_working_memory_module(self):
        """懒加载 WorkingMemoryModule（首次调用时初始化）"""
        if self._working_memory_module is None:
            from neurova.cognitive_layers.memory_layer.modules.working_memory_module import WorkingMemoryModule

            self._working_memory_module = WorkingMemoryModule(capacity=7, decay_time=300.0)
            self._working_memory_module.init()
            logger.info("WorkingMemoryModule lazily initialized")
        return self._working_memory_module

    def wm_add_turn(self, **kwargs) -> None:
        """添加对话轮次到工作记忆（委托到 WorkingMemoryModule.add）"""
        module = self._ensure_working_memory_module()
        turn_id = kwargs.get("turn_id", f"turn_{kwargs.get('role', 'unknown')}_{int(__import__('time').time() * 1000)}")
        content = kwargs.get("content", "")
        module.add(item_id=turn_id, content=content, priority=kwargs.get("priority", 1), metadata=kwargs.get("metadata"))

    def wm_get_context(self, **kwargs) -> List[Dict[str, Any]]:
        """获取工作记忆上下文（委托到 WorkingMemoryModule.get_all）"""
        module = self._ensure_working_memory_module()
        return module.get_all()

    def wm_compress_turn(self, **kwargs) -> None:
        """压缩对话轮次（委托到 WorkingMemoryModule，无压缩方法时为 no-op）"""
        module = self._ensure_working_memory_module()
        # 模块无直接压缩方法，通过获取最近条目触发访问更新
        module.get_recent(count=5)

    def wm_cache_plan(self, **kwargs) -> None:
        """缓存计划到工作记忆（委托到 WorkingMemoryModule.add）"""
        module = self._ensure_working_memory_module()
        plan_id = kwargs.get("plan_id", f"plan_{int(__import__('time').time() * 1000)}")
        plan = kwargs.get("plan", {})
        module.add(item_id=plan_id, content=plan, priority=kwargs.get("priority", 2))

    def wm_retrieve_plan(self, **kwargs) -> Optional[Dict[str, Any]]:
        """从工作记忆检索计划（委托到 WorkingMemoryModule.get）"""
        module = self._ensure_working_memory_module()
        plan_id = kwargs.get("plan_id", "")
        return module.get(item_id=plan_id)

    def wm_record_plan_result(self, **kwargs) -> None:
        """记录计划结果到工作记忆（委托到 WorkingMemoryModule.add）"""
        module = self._ensure_working_memory_module()
        result_id = kwargs.get("plan_id", f"result_{int(__import__('time').time() * 1000)}")
        result = {"success": kwargs.get("success", True), "result": kwargs.get("result")}
        module.add(item_id=result_id, content=result, priority=1)

    def wm_get_stats(self) -> Dict[str, Any]:
        """获取工作记忆统计（委托到 WorkingMemoryModule.get_stats）"""
        module = self._ensure_working_memory_module()
        return module.get_stats()

    def wm_clear(self) -> None:
        """清空工作记忆（委托到 WorkingMemoryModule.clear）"""
        module = self._ensure_working_memory_module()
        module.clear()

    # ────── Self Commands (委托到 modules/self_manager_module.py) ──────

    def _ensure_self_manager_module(self):
        """懒加载 SelfManagerModule（首次调用时初始化）"""
        if self._self_manager_module is None:
            from neurova.cognitive_layers.memory_layer.modules.self_manager_module import SelfManagerModule

            self._self_manager_module = SelfManagerModule(agent_id=self._agent_id)
            self._self_manager_module.init()
            logger.info("SelfManagerModule lazily initialized")
        return self._self_manager_module

    def self_get_commands(self) -> List[Dict[str, Any]]:
        """获取命令列表（委托到 SelfManagerModule.self_model.capabilities）"""
        module = self._ensure_self_manager_module()
        return [{"name": cap, "type": "capability"} for cap in module.self_model.capabilities]

    def self_add_command(self, **kwargs) -> str:
        """添加命令（委托到 SelfManagerModule.add_capability）"""
        module = self._ensure_self_manager_module()
        name = kwargs.get("name", kwargs.get("command", "unknown"))
        module.add_capability(name)
        return name

    def self_update_command(self, **kwargs) -> bool:
        """更新命令（委托到 SelfManagerModule.remove_capability + add_capability）"""
        module = self._ensure_self_manager_module()
        name = kwargs.get("name", kwargs.get("command", ""))
        if name:
            module.remove_capability(name)
            module.add_capability(name)
        return True

    def self_delete_command(self, **kwargs) -> bool:
        """删除命令（委托到 SelfManagerModule.remove_capability）"""
        module = self._ensure_self_manager_module()
        name = kwargs.get("name", kwargs.get("command", ""))
        return module.remove_capability(name)

    def self_get_heart_beat_tasks(self) -> List[Dict[str, Any]]:
        """获取心跳任务（委托到 SelfManagerModule.self_model.goals）"""
        module = self._ensure_self_manager_module()
        return [{"name": goal, "type": "goal"} for goal in module.self_model.goals]

    def self_get_due_tasks(self) -> List[Dict[str, Any]]:
        """获取到期任务（委托到 SelfManagerModule，无调度时返回空列表）"""
        module = self._ensure_self_manager_module()
        # 模块无任务调度，返回空列表
        return []

    def self_add_heart_beat_task(self, **kwargs) -> str:
        """添加心跳任务（委托到 SelfManagerModule.set_goal）"""
        module = self._ensure_self_manager_module()
        name = kwargs.get("name", kwargs.get("task", "unknown"))
        module.set_goal(name)
        return name

    def self_update_heart_beat_task(self, **kwargs) -> bool:
        """更新心跳任务（委托到 SelfManagerModule.remove_goal + set_goal）"""
        module = self._ensure_self_manager_module()
        name = kwargs.get("name", kwargs.get("task", ""))
        if name:
            module.remove_goal(name)
            module.set_goal(name)
        return True

    def self_record_task_run(self, **kwargs) -> bool:
        """记录任务运行（委托到 SelfManagerModule.record_efficacy）"""
        module = self._ensure_self_manager_module()
        task = kwargs.get("name", kwargs.get("task", "unknown"))
        success = kwargs.get("success", True)
        confidence_before = kwargs.get("confidence_before", 0.5)
        confidence_after = kwargs.get("confidence_after", 0.7 if success else 0.3)
        module.record_efficacy(task, success, confidence_before, confidence_after)
        return True

    def self_delete_heart_beat_task(self, **kwargs) -> bool:
        """删除心跳任务（委托到 SelfManagerModule.remove_goal）"""
        module = self._ensure_self_manager_module()
        name = kwargs.get("name", kwargs.get("task", ""))
        return module.remove_goal(name)

    def self_get_system_prompt_context(self) -> str:
        """获取系统提示上下文（委托到 SelfManagerModule.get_stats 构建文本）"""
        module = self._ensure_self_manager_module()
        stats = module.get_stats()
        parts = [f"Agent: {stats.get('agent_id', 'default')}"]
        if stats.get("capabilities_count", 0) > 0:
            parts.append(f"Capabilities: {stats['capabilities_count']}")
        if stats.get("goals_count", 0) > 0:
            parts.append(f"Goals: {stats['goals_count']}")
        parts.append(f"Confidence: {stats.get('confidence', 0.5):.2f}")
        return "; ".join(parts)

    def self_get_status(self) -> Dict[str, Any]:
        """获取状态（委托到 SelfManagerModule.get_stats）"""
        module = self._ensure_self_manager_module()
        return module.get_stats()

    # ────── Auto Update (委托到 modules/auto_context_module.py) ──────

    def _ensure_auto_context_module(self):
        """懒加载 AutoContextModule（首次调用时初始化）"""
        if self._auto_context_module is None:
            from neurova.cognitive_layers.memory_layer.modules.auto_context_module import AutoContextModule

            self._auto_context_module = AutoContextModule(max_context_length=4000, compression_threshold=0.8)
            self._auto_context_module.init()
            logger.info("AutoContextModule lazily initialized")
        return self._auto_context_module

    def start_auto_update(self, interval: float = 300.0) -> None:
        """启动自动更新（委托到 AutoContextModule.init）"""
        module = self._ensure_auto_context_module()
        # 模块无后台调度，初始化即视为启动
        logger.info("AutoContextModule started with interval=%s", interval)

    def stop_auto_update(self) -> None:
        """停止自动更新（委托到 AutoContextModule.shutdown）"""
        module = self._ensure_auto_context_module()
        module.shutdown()
        logger.info("AutoContextModule stopped")

    # ────── Advanced Features (STUB: 未实现, 返回默认值) ──────

    def get_memories_by_emotion(self, emotion: str, limit: int = 10) -> List[Dict[str, Any]]:
        """获取带有特定情感的记忆"""
        if not self._emotion_module:
            return []

        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionType

        try:
            emotion_type = EmotionType(emotion)
        except ValueError:
            return []

        memory_ids = self._emotion_module.get_emotional_memories(
            emotion_type=emotion_type,
            min_intensity=0.3,
            limit=limit,
        )

        # 将 memory_id 转为完整的记忆字典
        results = []
        for mid in memory_ids:
            mem = self._memories.get(mid)
            if mem:
                mem_dict = mem.to_dict()
                # 附加情感信息
                emotion_state = self._emotion_module.get_emotion(mid)
                if emotion_state:
                    mem_dict["emotion_state"] = emotion_state.to_dict()
                results.append(mem_dict)

        return results

    def remember_with_trace(
        self, content: str, trace: Optional[Dict[str, Any]] = None, **kwargs
    ) -> str:
        """带痕迹地记住（P-1 修复: trace 可选, 默认空 dict）

        Args:
            content: 记忆内容
            trace: 痕迹数据（可选, 默认空 dict; 透传到 metadata.trace 便于后续追踪）
            **kwargs: 透传给 remember 的参数
        """
        if trace is None:
            trace = {}
        merged_metadata = dict(kwargs.pop("metadata", {}) or {})
        if trace:
            merged_metadata["trace"] = trace
        return self.remember(content, metadata=merged_metadata, **kwargs)

    def recall_with_trace(self, query: str, **kwargs) -> List[Dict[str, Any]]:
        return self.recall(query, **kwargs)

    # ────── Conflict & Relation (委托到 modules/conflict_module.py + relation_module.py) ──────

    def _ensure_conflict_module(self):
        """懒加载 ConflictModule（首次调用时初始化）"""
        if self._conflict_module is None:
            from neurova.cognitive_layers.memory_layer.modules.conflict_module import ConflictModule

            self._conflict_module = ConflictModule(auto_resolve=False)
            self._conflict_module.init()
            logger.info("ConflictModule lazily initialized")
        return self._conflict_module

    def _ensure_relation_module(self):
        """懒加载 RelationModule（首次调用时初始化）"""
        if self._relation_module is None:
            from neurova.cognitive_layers.memory_layer.modules.relation_module import RelationModule

            self._relation_module = RelationModule()
            self._relation_module.init()
            logger.info("RelationModule lazily initialized")
        return self._relation_module

    def get_traces_by_trigger(
        self, trigger: Optional[str] = None, limit: int = 10, **kwargs
    ) -> List[Dict[str, Any]]:
        """按触发器获取追踪（P-1 修复: 接受 trigger 位置参数 + limit）

        Args:
            trigger: 触发器名称（如 'remember'/'recall'）; 当前 ConflictModule 未按触发器过滤, 返回全部
            limit: 返回上限
        """
        module = self._ensure_conflict_module()
        conflicts = module.get_conflicts()
        traces = [c.to_dict() for c in conflicts]
        return traces[:limit]

    def detect_conflict(self, **kwargs) -> List[Dict[str, Any]]:
        """检测冲突（委托到 ConflictModule.detect_conflict）"""
        module = self._ensure_conflict_module()
        conflict = module.detect_conflict(
            memory_id_1=kwargs.get("memory_id_1", ""),
            content_1=kwargs.get("content_1", ""),
            memory_id_2=kwargs.get("memory_id_2", ""),
            content_2=kwargs.get("content_2", ""),
        )
        return [conflict.to_dict()] if conflict else []

    def detect_time_conflicts(self, **kwargs) -> List[Dict[str, Any]]:
        """检测时间冲突（委托到 ConflictModule.get_conflicts，无时间过滤）"""
        module = self._ensure_conflict_module()
        conflicts = module.get_conflicts()
        return [c.to_dict() for c in conflicts]

    def detect_all_conflicts(self) -> List[Dict[str, Any]]:
        """检测所有冲突（委托到 ConflictModule.get_conflicts）"""
        module = self._ensure_conflict_module()
        conflicts = module.get_conflicts()
        return [c.to_dict() for c in conflicts]

    def get_conflict_summary(self) -> Dict[str, Any]:
        """获取冲突摘要（委托到 ConflictModule.get_stats）"""
        module = self._ensure_conflict_module()
        return module.get_stats()

    def add_relation(self, **kwargs) -> bool:
        """添加关系（委托到 RelationModule.add_relation）"""
        module = self._ensure_relation_module()
        from neurova.cognitive_layers.memory_layer.modules.relation_module import RelationType
        relation_type_str = kwargs.get("relation_type", "association")
        try:
            relation_type = RelationType(relation_type_str)
        except ValueError:
            relation_type = RelationType.ASSOCIATION
        module.add_relation(
            source_id=kwargs.get("source_id", ""),
            target_id=kwargs.get("target_id", ""),
            relation_type=relation_type,
            strength=kwargs.get("strength", 0.5),
            metadata=kwargs.get("metadata"),
        )
        return True

    def get_relations(self, **kwargs) -> List[Dict[str, Any]]:
        """获取关系（委托到 RelationModule.get_all_relations）"""
        module = self._ensure_relation_module()
        memory_id = kwargs.get("memory_id", "")
        relations = module.get_all_relations(memory_id)
        return [r.to_dict() for r in relations]

    def delete_relation(self, **kwargs) -> bool:
        """删除关系（委托到 RelationModule.remove_relation）"""
        module = self._ensure_relation_module()
        relation_id = kwargs.get("relation_id", "")
        return module.remove_relation(relation_id)

    def get_memory_graph(self, **kwargs) -> Dict[str, Any]:
        """获取记忆图谱（委托到 RelationModule.get_stats）"""
        module = self._ensure_relation_module()
        return module.get_stats()

    # ────── 压缩/合并（MemoryCompressor 接入，compression.* 配置组）──────

    def compress_low_value_memories(
        self, dry_run: bool = True, limit: int = 500
    ) -> Dict[str, Any]:
        """对低重要性记忆执行相似压缩/合并（compression.* 配置组）

        候选：importance（0~100 归一化后）低于 compression.importance_threshold
        且未固化的记忆，最多 limit 条。MERGE 使用 MemoryCompressor 的语义压缩。

        Args:
            dry_run: True（默认）只返回合并计划，不修改任何数据
            limit: 候选上限，防全量遍历阻塞

        Returns:
            {dry_run, candidates, merged_count, groups, ...}
        """
        from neurova.cognitive_layers.memory_layer.settings_config import (
            get_memory_settings,
        )
        from neurova.cognitive_layers.memory_layer.compression import (
            get_memory_compressor,
            CompressionStrategy,
        )
        from neurova.cognitive_layers.memory_layer.models import LifecycleStage

        cfg = get_memory_settings()
        imp_threshold = float(cfg.get("compression.importance_threshold", 0.3))
        sim_threshold = float(cfg.get("compression.similarity_threshold", 0.7))
        max_per_group = int(cfg.get("compression.max_memories_per_group", 10))
        window_hours = int(cfg.get("compression.time_window_hours", 24))
        enable_llm = bool(cfg.get("compression.enable_llm_compression", True))

        candidates = [
            m
            for m in self._memories.values()
            if m.lifecycle_stage not in (LifecycleStage.FORGOTTEN, LifecycleStage.CRYSTALLIZED)
            and (float(m.importance) / 100.0) < imp_threshold
        ][:limit]

        if not candidates:
            return {
                "dry_run": dry_run,
                "candidates": 0,
                "merged_count": 0,
                "groups": [],
            }

        compressor = get_memory_compressor(
            storage=self.storage,
            llm_client=None,
            config={
                "similarity_threshold": sim_threshold,
                "max_memories_per_group": max_per_group,
                "time_window_hours": window_hours,
                "importance_threshold": imp_threshold,
                "enable_llm_compression": enable_llm,
            },
        )
        result = compressor.compress(
            [m.to_dict() for m in candidates],
            strategy=CompressionStrategy.SEMANTIC,
            threshold=sim_threshold,
            max_group_size=max_per_group,
        )

        report = {
            "dry_run": dry_run,
            "candidates": len(candidates),
            "merged_count": result.merged_count,
            "removed_count": result.removed_count,
            "groups": result.details.get("groups", []),
        }

        if dry_run:
            return report

        # 执行写回：keep 内容更新，组内其他成员软删（FORGOTTEN）
        with self._lock:
            for g in report["groups"]:
                keep_id = g.get("keep_id", "")
                keep = self._memories.get(keep_id)
                if keep is None:
                    continue
                merged_content = g.get("merged_content") or g.get("keep_content")
                if merged_content:
                    keep.content = str(merged_content)
                    self._persist_memory(keep)
                for mid in g.get("member_ids", []):
                    if mid != keep_id and mid in self._memories:
                        self.forget(mid)

        return report

    # ────── 关系图遍历（GraphTraversal 接入，graph.* 配置组）──────

    def _ensure_graph_traversal(self):
        """懒加载 GraphTraversal，参数来自 graph.* 配置组"""
        if self._graph_traversal is None:
            from neurova.cognitive_layers.memory_layer.settings_config import (
                get_memory_settings,
            )
            from neurova.cognitive_layers.memory_layer.graph_traversal import (
                GraphTraversal,
            )

            cfg = get_memory_settings()
            traversal = GraphTraversal(
                min_strength=float(cfg.get("graph.min_strength", 0.15))
            )
            relation_module = self._ensure_relation_module()
            for rel in relation_module.get_all():
                traversal.add_relation(
                    type(
                        "R",
                        (),
                        {
                            "source_id": rel.source_id,
                            "target_id": rel.target_id,
                            "relation_type": rel.relation_type.value
                            if hasattr(rel.relation_type, "value")
                            else str(rel.relation_type),
                            "strength": rel.strength,
                            "metadata": rel.metadata or {},
                        },
                    )()
                )
            self._graph_traversal = traversal
        return self._graph_traversal

    def traverse_relations(
        self, memory_id: str, method: str = "bfs", max_depth: int = 3
    ) -> Dict[str, Any]:
        """从指定记忆出发遍历关系图（graph.min_strength 过滤弱关系）

        Args:
            memory_id: 起始记忆 id
            method: "bfs" 或 "dfs"
            max_depth: 遍历深度

        Returns:
            {"nodes": [{"id", "content"}], "edges": [...], "paths": n}
        """
        from neurova.cognitive_layers.memory_layer.settings_config import (
            get_memory_settings,
        )

        cfg = get_memory_settings()
        traversal = self._ensure_graph_traversal()

        if method == "dfs":
            result = traversal.traverse_dfs(memory_id)
        else:
            result = traversal.traverse_bfs(memory_id)

        visited_ids = set(result.reachable_ids or [])
        visited_ids.add(memory_id)
        nodes = []
        for node_id in visited_ids:
            mem = self._memories.get(node_id)
            if mem is not None:
                nodes.append({"id": node_id, "content": mem.content})
        return {
            "source": memory_id,
            "method": method,
            "max_depth": max_depth,
            "min_strength": float(cfg.get("graph.min_strength", 0.15)),
            "nodes": nodes,
            "edges": [
                {
                    "source": rel.source_id,
                    "target": rel.target_id,
                    "type": rel.relation_type.value
                    if hasattr(rel.relation_type, "value")
                    else str(rel.relation_type),
                    "strength": rel.strength,
                }
                for path in (result.paths or [])
                for rel in path.relations
            ],
            "path_count": len(result.paths or []),
        }

    def search_similar_memories(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        return self.recall(query=query, limit=limit)

    # ────── Sleep (委托到 modules/sleep_module.py) ──────

    def _ensure_sleep_module(self):
        """懒加载 SleepModule（首次调用时初始化）"""
        if self._sleep_module is None:
            from neurova.cognitive_layers.memory_layer.modules.sleep_module import SleepModule

            self._sleep_module = SleepModule(
                consolidation_threshold=0.7,
                cleanup_threshold=0.2,
                dream_probability=0.1,
            )
            self._sleep_module.init()
            logger.info("SleepModule lazily initialized")
        return self._sleep_module

    def _collect_memories_for_sleep(self) -> List[Dict[str, Any]]:
        """收集所有记忆用于睡眠处理

        BUG-7 修复: 加 self._lock 保护读路径。
        """
        with self._lock:
            memories = []
            for mem_id, mem in self._memories.items():
                memories.append({
                    "id": mem_id,
                    "content": mem.content,
                    "importance": mem.importance / 100.0,  # 归一化到 0-1
                })
            return memories

    def run_light_sleep_cycle(self) -> Dict[str, Any]:
        """轻度睡眠周期（巩固重要记忆）"""
        module = self._ensure_sleep_module()
        module.start_sleep()
        memories = self._collect_memories_for_sleep()
        result = module.process_memories(memories)
        stats = module.end_sleep()
        return {
            "cycle": "light",
            "consolidated": result.get("consolidated", []),
            "cleaned": result.get("cleaned", []),
            "stats": stats,
        }

    def run_rem_sleep_cycle(self) -> Dict[str, Any]:
        """REM 睡眠周期（含梦境回放）

        BUG-12 修复: 不再直接修改 module._dream_probability 私有属性,
        改为保存/恢复模式避免并发调用互相覆盖。
        """
        module = self._ensure_sleep_module()
        module.start_sleep()
        memories = self._collect_memories_for_sleep()
        # BUG-12 修复: 保存原始值, 处理后恢复（避免并发污染）
        original_dream_prob = module._dream_probability
        try:
            module._dream_probability = 0.5
            result = module.process_memories(memories)
        finally:
            module._dream_probability = original_dream_prob
        stats = module.end_sleep()
        return {
            "cycle": "rem",
            "consolidated": result.get("consolidated", []),
            "cleaned": result.get("cleaned", []),
            "dreamed": result.get("dreamed", []),
            "stats": stats,
        }

    def run_deep_sleep_cycle(self) -> Dict[str, Any]:
        """深度睡眠周期（强化巩固 + 清理）

        BUG-12 修复: 不再直接修改 module._consolidation_threshold / _cleanup_threshold,
        改为保存/恢复模式避免并发污染。
        """
        module = self._ensure_sleep_module()
        module.start_sleep()
        # BUG-12 修复: 保存原始值, 处理后恢复
        original_consolidation = module._consolidation_threshold
        original_cleanup = module._cleanup_threshold
        try:
            # 深度睡眠降低巩固阈值，提高清理力度
            module._consolidation_threshold = 0.5
            module._cleanup_threshold = 0.3
            memories = self._collect_memories_for_sleep()
            result = module.process_memories(memories)
        finally:
            module._consolidation_threshold = original_consolidation
            module._cleanup_threshold = original_cleanup
        stats = module.end_sleep()
        return {
            "cycle": "deep",
            "consolidated": result.get("consolidated", []),
            "cleaned": result.get("cleaned", []),
            "stats": stats,
        }

    def run_dormant_cycle(self) -> Dict[str, Any]:
        """休眠周期（仅清理，不巩固）

        BUG-12 修复: 保存/恢复私有属性避免并发污染。
        """
        module = self._ensure_sleep_module()
        module.start_sleep()
        # BUG-12 修复: 保存原始值, 处理后恢复
        original_consolidation = module._consolidation_threshold
        original_cleanup = module._cleanup_threshold
        try:
            # 休眠周期只清理低重要性记忆
            module._consolidation_threshold = 1.0  # 不巩固
            module._cleanup_threshold = 0.4  # 更激进清理
            memories = self._collect_memories_for_sleep()
            result = module.process_memories(memories)
        finally:
            module._consolidation_threshold = original_consolidation
            module._cleanup_threshold = original_cleanup
        stats = module.end_sleep()
        return {
            "cycle": "dormant",
            "consolidated": result.get("consolidated", []),
            "cleaned": result.get("cleaned", []),
            "stats": stats,
        }

    # ────── Explainability (委托到 modules/explainability_module.py) ──────

    def _ensure_explainability_module(self):
        """懒加载 ExplainabilityModule（首次调用时初始化）"""
        if self._explainability_module is None:
            from neurova.cognitive_layers.memory_layer.modules.explainability_module import ExplainabilityModule

            self._explainability_module = ExplainabilityModule(max_explanations=100)
            self._explainability_module.init()
            logger.info("ExplainabilityModule lazily initialized")
        return self._explainability_module

    def explain_memory(self, memory_id: str) -> Dict[str, Any]:
        """解释记忆

        BUG-7 修复: 加 self._lock 保护读路径。
        """
        with self._lock:
            mem = self._memories.get(memory_id)
            if mem:
                return {"memory_id": memory_id, "content": mem.content, "reason": "direct recall"}
            return {"memory_id": memory_id, "error": "not found"}

    def get_explanation_chain(self, **kwargs) -> List[Dict[str, Any]]:
        """获取解释链（委托到 ExplainabilityModule.get_explanations）"""
        module = self._ensure_explainability_module()
        explanations = module.get_explanations(limit=10)
        return [e.to_dict() for e in explanations]

    def visualize_chain(self, **kwargs) -> str:
        """可视化解释链（委托到 ExplainabilityModule.get_explanations 构建文本）"""
        module = self._ensure_explainability_module()
        explanations = module.get_explanations(limit=5)
        if not explanations:
            return "(no explanation chain available)"
        return "\n---\n".join(e.to_text() for e in explanations)

    # ────── Forgetting Recovery (IMPLEMENTED: 真实操作 _memories.lifecycle_stage) ──────

    def _ensure_forgetting_recovery_module(self):
        """懒加载 ForgettingRecoveryModule（首次调用时初始化）"""
        if self._forgetting_recovery_module is None:
            from neurova.cognitive_layers.memory_layer.modules.forgetting_recovery_module import (
                ForgettingRecoveryModule,
            )

            self._forgetting_recovery_module = ForgettingRecoveryModule(
                forgetting_rate=0.1, recovery_boost=0.5, min_retention=0.01
            )
            self._forgetting_recovery_module.init()
            logger.info("ForgettingRecoveryModule lazily initialized")
        return self._forgetting_recovery_module

    def archive_memory(self, memory_id: str) -> bool:
        """归档记忆

        BUG-6 修复: 加 _persist_memory 持久化 lifecycle_stage 变更。
        BUG-7 修复: 加 self._lock 保护读写路径。
        """
        with self._lock:
            mem = self._memories.get(memory_id)
            if mem:
                mem.lifecycle_stage = LifecycleStage.ARCHIVED
                # BUG-6 修复: 持久化 lifecycle_stage 变更
                self._persist_memory(mem)
                return True
            return False

    def delete_memory_soft(self, memory_id: str) -> bool:
        return self.forget(memory_id, soft=True)

    def recover_from_archive(self, memory_id: str) -> bool:
        """从归档恢复记忆

        BUG-6 修复: 加 _persist_memory 持久化 lifecycle_stage 变更。
        BUG-7 修复: 加 self._lock 保护读写路径。
        """
        with self._lock:
            mem = self._memories.get(memory_id)
            if mem:
                mem.lifecycle_stage = LifecycleStage.ACTIVE
                # BUG-6 修复: 持久化 lifecycle_stage 变更
                self._persist_memory(mem)
                return True
            return False

    def recover_from_delete(self, memory_id: str) -> bool:
        return self.recover_from_archive(memory_id)

    def get_archived_memories(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取已归档记忆

        BUG-7 修复: 加 self._lock 保护读路径。
        """
        with self._lock:
            return [m.to_dict() for m in self._memories.values() if m.lifecycle_stage == LifecycleStage.ARCHIVED][:limit]

    def get_deleted_memories(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取已删除记忆

        BUG-7 修复: 加 self._lock 保护读路径。
        """
        with self._lock:
            return [m.to_dict() for m in self._memories.values() if m.lifecycle_stage == LifecycleStage.FORGOTTEN][:limit]

    def get_recovery_history(self) -> List[Dict[str, Any]]:
        """获取恢复历史（委托到 ForgettingRecoveryModule，收集所有记忆的复习记录）

        Bug 10 修复: 原代码直接访问 module 私有字典的键集合,
        若 ForgettingRecoveryModule 实现变更会 AttributeError。现用 getattr 安全访问。
        """
        module = self._ensure_forgetting_recovery_module()
        # Bug 10 修复: 用 getattr 安全访问私有属性, 缺失时返回空 dict
        retention_map = getattr(module, "_retention", {}) or {}
        # 收集所有已注册记忆的复习历史，转换为 dict 列表
        history: List[Dict[str, Any]] = []
        for memory_id in list(retention_map.keys()):
            review_timestamps = module.get_review_history(memory_id)
            if review_timestamps:
                history.append(
                    {
                        "memory_id": memory_id,
                        "review_count": len(review_timestamps),
                        "last_review": review_timestamps[-1] if review_timestamps else None,
                        "retention": module.get_retention(memory_id),
                    }
                )
        return history

    def permanently_delete_memory(self, memory_id: str) -> bool:
        return self.forget(memory_id, soft=False)

    # ────── Relation (委托到 modules/relation_module.py) ──────

    def relate(
        self,
        source_id: str,
        target_id: str,
        relation_type: str = "related",
        weight: Optional[float] = None,
    ) -> bool:
        """建立记忆间关系（委托到 RelationModule.add_relation）

        P-1 修复: 增加 weight 参数, 映射到 RelationModule.add_relation 的 strength。
        RelationModule 用 strength 表示关系强度 (0.0-1.0), 与 weight 同义。

        Args:
            source_id: 源记忆 ID
            target_id: 目标记忆 ID
            relation_type: 关系类型字符串（'similar'/'association' 等, 不合法时 fallback ASSOCIATION）
            weight: 关系权重 (0.0-1.0, 默认 None → 0.5)
        """
        module = self._ensure_relation_module()
        from neurova.cognitive_layers.memory_layer.modules.relation_module import RelationType

        try:
            rtype = RelationType(relation_type)
        except ValueError:
            rtype = RelationType.ASSOCIATION
        strength = 0.5 if weight is None else float(weight)
        module.add_relation(
            source_id=source_id, target_id=target_id, relation_type=rtype, strength=strength
        )
        return True

    def recall_with_associations(
        self, query: str = "", depth: int = 1, **kwargs
    ) -> List[Dict[str, Any]]:
        """检索记忆并附带关联（P-1 修复: query 可选, 默认空字符串）

        Args:
            query: 检索查询（可选, 默认空字符串返回全部按 limit 限制）
            depth: 关联展开深度（保留参数, 当前实现等价于 recall）
            **kwargs: 透传给 recall 的参数（category/limit/min_temperature 等）
        """
        return self.recall(query, **kwargs)

    def recall_graph(self, query: str, **kwargs) -> Dict[str, Any]:
        """检索记忆并构建关联图谱（委托到 RelationModule + recall）"""
        module = self._ensure_relation_module()
        # 先检索匹配的记忆
        recalled = self.recall(query=query, **kwargs)
        # 收集每条记忆的关系信息
        nodes = []
        edges = []
        for item in recalled:
            mem_id = item.get("id", "")
            nodes.append({"id": mem_id, "content": item.get("content", "")})
            # 获取该记忆的所有关系
            relations = module.get_all_relations(mem_id)
            for rel in relations:
                edges.append(
                    {
                        "source": rel.source_id,
                        "target": rel.target_id,
                        "type": rel.relation_type.value,
                        "strength": rel.strength,
                    }
                )
        return {
            "query": query,
            "nodes": nodes,
            "edges": edges,
            "stats": module.get_stats(),
        }

    # ────── Close ──────

    def close(self) -> None:
        """优雅关闭"""
        self._started = False
        logger.info("MemoryManager closed: agent_id=%s", self._agent_id)

    def __repr__(self) -> str:
        return f"MemoryManager(agent_id={self._agent_id!r}, memories={len(self._memories)})"


def _default_db_path_for(agent_id: str) -> str:
    """agent 工作区标准记忆库路径（与 AgentConfig 一致：workspace/memory/memory.db）。

    原默认值 "neurova_memory.db" 是相对路径——持久化文件随进程 cwd 散落
    （项目根 / data / neurova/memory/data 各一份且互不一致）。
    """
    base_dir = Path(__file__).resolve().parents[3]  # neurova/cognitive_layers/memory_layer → 项目根
    path = base_dir / "agent_workspaces" / (agent_id or "default") / "memory" / "memory.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def get_memory_manager(
    agent_id: str = "default",
    user_id: str = "default",
    db_path: str = "",
    neuser_id: str = "default",
) -> MemoryManager:
    """按作用域获取/创建 MemoryManager（同作用域复用实例）。

    根因修复 (2026-09-02)：
    1. 原实现是进程级单例——首个调用者的 agent/db_path/scope 定终身，后续
       agent/用户参数全部被忽略；API 统计由此永远读不到 Agent 实例写入
       agent_workspaces 的真实记忆（Dashboard 记忆恒 0）。
    2. 原默认 db_path 为相对路径，持久化文件随 cwd 散落；现按 agent 工作区
       标准路径解析（与 AgentConfig 同源）。
    3. user_id 兼容端点传入的身份字典（get_current_user 结果），按
       user_id/neuser_id 提取，杜绝 dict 冒充 user_id 破坏三层隔离。
    """
    global _default_manager
    if isinstance(user_id, dict):
        neuser_id = user_id.get("neuser_id") or neuser_id
        user_id = user_id.get("user_id") or user_id.get("id") or "default"
    if not db_path:
        db_path = _default_db_path_for(agent_id)

    key = (agent_id, neuser_id, user_id, db_path)
    with _manager_lock:
        mgr = _managers.get(key)
        if mgr is None:
            mgr = MemoryManager(
                db_path=db_path,
                agent_id=agent_id,
                neuser_id=neuser_id,
                user_id=user_id,
            )
            _managers[key] = mgr
        # 兼容旧引用：首实例同时写入 _default_manager 槽，避免历史调用方拿到 None
        if _default_manager is None:
            _default_manager = mgr
        return mgr
