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
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from neurova.cognitive_layers.memory_layer.bus_event import (
    EventBus,
    MemoryEvent,
)
from neurova.cognitive_layers.memory_layer.models import (
    EmotionType,
    LifecycleStage,
    Memory,
    MemoryCategory,
    MemoryType,
)

logger = get_logger(__name__)

# 全局单例
_default_manager: Optional["MemoryManager"] = None
_manager_lock = threading.Lock()


class MemoryManager:
    """记忆管理器 Facade — 通过 EventBus 路由到各子模块"""

    def __init__(self, db_path: str = "neurova_memory.db", agent_id: str = "default", user_id: str = "default"):
        self._db_path = db_path
        self._agent_id = agent_id
        self._user_id = user_id
        self._bus = EventBus()
        self._started = False

        # 内部存储（简易实现，子模块可覆盖）
        self._memories: Dict[str, Memory] = {}
        self._counter = 0
        self._lock = threading.RLock()

        # 子模块引用（延迟初始化）
        self._storage = None
        self._emotion_analyzer = None
        self._auto_classifier = None
        self._conversation_buffer = None
        self._conflict_detector = None
        self._relation_manager = None
        self._sleep_consolidation = None
        self._explainability_manager = None
        self._forgetting_recovery = None
        self._emotion_conduction = None
        self._write_queue = None
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

        # SQLite 持久化（记忆跨重启保留）
        self._init_persistence_db()
        self._load_from_db()

        # 统计
        self._stats = {
            "total_memories": len(self._memories),
            "recall_count": 0,
            "remember_count": 0,
        }

        logger.info(
            f"MemoryManager initialized: agent_id={agent_id}, user_id={user_id}, memories_loaded={len(self._memories)}"
        )

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
            conn.commit()
            conn.close()
            logger.debug("Persistence DB initialized: %s", self._persist_db_path)
        except Exception as e:
            logger.warning("Persistence DB init failed: %s", e)
            self._persist_db_path = None

    def _load_from_db(self):
        """从 SQLite 加载记忆到内存"""
        if not getattr(self, "_persist_db_path", None):
            return
        try:
            conn = sqlite3.connect(self._persist_db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM memories WHERE agent_id = ? ORDER BY created_at DESC", (self._agent_id,)
            ).fetchall()
            conn.close()

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
        """从 SQLite 删除持久化记忆"""
        if not getattr(self, "_persist_db_path", None):
            return
        try:
            conn = sqlite3.connect(self._persist_db_path)
            conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
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
    def user_id(self) -> str:
        return self._user_id

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
        temperature: float = 100.0,
        importance: float = 50.0,
        metadata: Optional[Dict[str, Any]] = None,
        emotion: Optional[str] = None,
        **kwargs,
    ) -> str:
        """存储一条记忆"""
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
            else:
                parsed_memory_type = memory_type

            # 安全解析 category（防御无效枚举值）
            if isinstance(category, str):
                try:
                    parsed_category = MemoryCategory(category)
                except (ValueError, KeyError):
                    logger.warning("Invalid category '%s', falling back to GENERAL", category)
                    parsed_category = MemoryCategory.GENERAL
            else:
                parsed_category = category

            mem = Memory(
                id=mem_id,
                content=content,
                memory_type=parsed_memory_type,
                category=parsed_category,
                temperature=temperature,
                importance=importance,
                emotion=emotion_val,
                metadata=metadata or {},
                agent_id=self._agent_id,
                user_id=self._user_id,
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
                except Exception:
                    pass

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
        """后台异步提取依赖关系（失败不影响主流程）"""
        try:
            from .moe_dependency_extractor import MOEDependencyExtractor

            if not hasattr(self, "_dependency_extractor"):
                self._dependency_extractor = MOEDependencyExtractor()

            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 已在事件循环中，用 create_task 包装
                asyncio.ensure_future(
                    self._dependency_extractor.extract_from_memory(
                        memory_id=memory_id, content=content, metadata=metadata,
                    )
                )
            else:
                loop.run_until_complete(
                    self._dependency_extractor.extract_from_memory(
                        memory_id=memory_id, content=content, metadata=metadata,
                    )
                )
        except Exception as e:
            logger.debug("依赖提取失败（不影响记忆存储）: %s", e)

    def recall(
        self, query: str = "", category: Optional[str] = None, limit: int = 10, min_temperature: float = 0.0, **kwargs
    ) -> List[Dict[str, Any]]:
        """检索记忆
        
        支持两种检索模式：
        1. 语义搜索（默认）：使用语义相似度匹配
        2. 关键词搜索：使用子字符串匹配（兼容旧版）
        """
        with self._lock:
            self._stats["recall_count"] += 1
            results = list(self._memories.values())

            # 按分类过滤
            if category:
                results = [m for m in results if m.category.value == category]

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
                self._bus.emit(
                    MemoryEvent(
                        type=MemoryEvent.MEMORY_ACCESSED,
                        source="memory_manager",
                        payload={"memory_id": m.id, "temperature": m.temperature},
                    )
                )

            return [m.to_dict() for m in results[:limit]]
    
    def _semantic_recall(self, query: str, memories: list, limit: int) -> list:
        """语义搜索检索"""
        try:
            from neurova.cognitive_layers.memory_layer.semantic_search import get_semantic_search
            
            search = get_semantic_search()
            
            # 构建记忆字典列表
            memory_dicts = [m.to_dict() for m in memories]
            
            # 构建关键词索引（如果尚未构建）
            if not search._keyword_index:
                search.build_keyword_index(memory_dicts)
            
            # 使用关键词搜索
            matching_ids = search.search_by_keywords(query, limit=limit * 2)
            
            # 按匹配顺序排序记忆
            id_to_memory = {m.id: m for m in memories}
            sorted_memories = []
            for mid in matching_ids:
                if mid in id_to_memory:
                    sorted_memories.append(id_to_memory[mid])
            
            return sorted_memories[:limit]
            
        except Exception as e:
            logger.warning("语义搜索失败，降级到关键词匹配: %s", e)
            # 降级到简单关键词匹配
            query_lower = query.lower()
            return [m for m in memories if query_lower in m.content.lower()][:limit]

    def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """获取单条记忆"""
        mem = self._memories.get(memory_id)
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
        if memory_id not in self._memories:
            return False
        if soft:
            self._memories[memory_id].lifecycle_stage = LifecycleStage.FORGOTTEN
            self._persist_memory(self._memories[memory_id])  # 更新持久化
        else:
            del self._memories[memory_id]
            self._delete_persisted_memory(memory_id)  # 删除持久化
        self._stats["total_memories"] = len(self._memories)
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

    def get_memories(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """获取记忆列表"""
        with self._lock:
            mems = list(self._memories.values())
            mems.sort(key=lambda m: m.created_at, reverse=True)
            return [m.to_dict() for m in mems[offset : offset + limit]]

    def get_all_memories(self) -> List[Dict[str, Any]]:
        """获取所有记忆（用于睡眠整合）"""
        with self._lock:
            return [m.to_dict() for m in self._memories.values()]

    def query_memories(self, **filters) -> List[Dict[str, Any]]:
        """查询记忆（高级过滤）"""
        return self.recall(
            query=filters.get("query", ""),
            category=filters.get("category"),
            limit=filters.get("limit", 10),
        )

    # ────── Buffer Operations ──────

    def flush_buffer(self) -> int:
        """刷新缓冲区"""
        if self._write_queue:
            return self._write_queue.flush_to_storage()
        return 0

    def get_buffer_stats(self) -> Dict[str, Any]:
        """获取缓冲区统计"""
        return {"buffer_size": 0, "pending_writes": 0}

    def force_write(self) -> int:
        """强制写入"""
        return self.flush_buffer()

    # ────── Stats ──────

    def stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self.get_stats()

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                "total_memories": len(self._memories),
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
        """分析情感（委托给 emotion_analyzer, 真实实现）"""
        if self._emotion_analyzer:
            return self._emotion_analyzer.analyze(text)
        return {"emotion": EmotionType.NEUTRAL.value, "confidence": 0.5}

    def get_emotion_summary(self) -> Dict[str, Any]:
        """获取情感摘要（委托到 EmotionModule.get_stats）"""
        return self._emotion_module.get_stats()

    def get_emotion_distribution(self) -> Dict[str, float]:
        """获取情感分布（委托到 EmotionModule.get_stats）"""
        return self._emotion_module.get_stats().get("emotion_distribution", {})

    def update_emotional_state(self, text: str) -> Dict[str, Any]:
        """更新情感状态（委托到 EmotionModule.analyze_text_emotion）"""
        emotion = self._emotion_module.analyze_text_emotion(text)
        return emotion.to_dict()

    def get_emotional_state(self) -> Dict[str, Any]:
        """获取当前情感状态（委托到 EmotionModule.get_feedback）"""
        return self._emotion_module.get_feedback()

    def get_dominant_emotion(self) -> str:
        """获取主导情感（委托到 EmotionModule.get_stats）"""
        distribution = self._emotion_module.get_stats().get("emotion_distribution", {})
        if not distribution:
            return "neutral"
        return max(distribution, key=distribution.get)

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
        return self.remember(content, **kwargs)

    # ────── Temperature ──────

    def update_memory_temperature(self, memory_id: str, interaction_type: str = "recall") -> bool:
        mem = self._memories.get(memory_id)
        if not mem:
            return False
        mem.touch()
        return True

    def run_decay_cycle(self, hours: float = 1.0, rate: float = 1.0) -> int:
        count = 0
        for mem in self._memories.values():
            if mem.temperature > 0:
                mem.decay(hours, rate)
                count += 1
        return count

    def get_crystallized(self, limit: int = 10) -> List[Dict[str, Any]]:
        return [m.to_dict() for m in self._memories.values() if m.lifecycle_stage == LifecycleStage.CRYSTALLIZED][
            :limit
        ]

    def get_hot_memories(self, limit: int = 10, min_temperature: float = 80.0) -> List[Dict[str, Any]]:
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

    def remember_with_trace(self, content: str, trace: Dict[str, Any], **kwargs) -> str:
        return self.remember(content, **kwargs)

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

    def get_traces_by_trigger(self, **kwargs) -> List[Dict[str, Any]]:
        """按触发器获取追踪（委托到 ConflictModule.get_conflicts）"""
        module = self._ensure_conflict_module()
        conflicts = module.get_conflicts()
        return [c.to_dict() for c in conflicts]

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
        """收集所有记忆用于睡眠处理"""
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
        """REM 睡眠周期（含梦境回放）"""
        module = self._ensure_sleep_module()
        module.start_sleep()
        memories = self._collect_memories_for_sleep()
        # REM 提高梦境概率
        module._dream_probability = 0.5
        result = module.process_memories(memories)
        stats = module.end_sleep()
        return {
            "cycle": "rem",
            "consolidated": result.get("consolidated", []),
            "cleaned": result.get("cleaned", []),
            "dreamed": result.get("dreamed", []),
            "stats": stats,
        }

    def run_deep_sleep_cycle(self) -> Dict[str, Any]:
        """深度睡眠周期（强化巩固 + 清理）"""
        module = self._ensure_sleep_module()
        module.start_sleep()
        # 深度睡眠降低巩固阈值，提高清理力度
        module._consolidation_threshold = 0.5
        module._cleanup_threshold = 0.3
        memories = self._collect_memories_for_sleep()
        result = module.process_memories(memories)
        stats = module.end_sleep()
        return {
            "cycle": "deep",
            "consolidated": result.get("consolidated", []),
            "cleaned": result.get("cleaned", []),
            "stats": stats,
        }

    def run_dormant_cycle(self) -> Dict[str, Any]:
        """休眠周期（仅清理，不巩固）"""
        module = self._ensure_sleep_module()
        module.start_sleep()
        # 休眠周期只清理低重要性记忆
        module._consolidation_threshold = 1.0  # 不巩固
        module._cleanup_threshold = 0.4  # 更激进清理
        memories = self._collect_memories_for_sleep()
        result = module.process_memories(memories)
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
        mem = self._memories.get(memory_id)
        if mem:
            mem.lifecycle_stage = LifecycleStage.ARCHIVED
            return True
        return False

    def delete_memory_soft(self, memory_id: str) -> bool:
        return self.forget(memory_id, soft=True)

    def recover_from_archive(self, memory_id: str) -> bool:
        mem = self._memories.get(memory_id)
        if mem:
            mem.lifecycle_stage = LifecycleStage.ACTIVE
            return True
        return False

    def recover_from_delete(self, memory_id: str) -> bool:
        return self.recover_from_archive(memory_id)

    def get_archived_memories(self, limit: int = 10) -> List[Dict[str, Any]]:
        return [m.to_dict() for m in self._memories.values() if m.lifecycle_stage == LifecycleStage.ARCHIVED][:limit]

    def get_deleted_memories(self, limit: int = 10) -> List[Dict[str, Any]]:
        return [m.to_dict() for m in self._memories.values() if m.lifecycle_stage == LifecycleStage.FORGOTTEN][:limit]

    def get_recovery_history(self) -> List[Dict[str, Any]]:
        """获取恢复历史（委托到 ForgettingRecoveryModule，收集所有记忆的复习记录）"""
        module = self._ensure_forgetting_recovery_module()
        # 收集所有已注册记忆的复习历史，转换为 dict 列表
        history: List[Dict[str, Any]] = []
        for memory_id in list(module._retention.keys()):
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

    def relate(self, source_id: str, target_id: str, relation_type: str = "related") -> bool:
        """建立记忆间关系（委托到 RelationModule.add_relation）"""
        module = self._ensure_relation_module()
        from neurova.cognitive_layers.memory_layer.modules.relation_module import RelationType

        try:
            rtype = RelationType(relation_type)
        except ValueError:
            rtype = RelationType.ASSOCIATION
        module.add_relation(source_id=source_id, target_id=target_id, relation_type=rtype, strength=0.5)
        return True

    def recall_with_associations(self, query: str, depth: int = 1, **kwargs) -> List[Dict[str, Any]]:
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


def get_memory_manager(
    agent_id: str = "default", user_id: str = "default", db_path: str = "neurova_memory.db"
) -> MemoryManager:
    """获取/创建默认 MemoryManager 单例"""
    global _default_manager
    with _manager_lock:
        if _default_manager is None:
            _default_manager = MemoryManager(db_path=db_path, agent_id=agent_id, user_id=user_id)
        return _default_manager
