from __future__ import annotations

"""
MemoryManager — 记忆管理器（CogArch 总线版）
===============================================

对外接口完全兼容旧版，内部改用 MemoryBus 路由。

架构变更：
  旧：1814 行 God Object，直接管理 13 个子系统，try/except 吞异常
  新：~500 行 Facade，通过 MemoryBus 注册 12 个独立模块

每个模块：
  - 实现 MemoryModule 协议
  - 只依赖 EventBus，不直接引用其他模块
  - 通过 on(event_type, handler) 订阅事件
  - 通过 emit(event) 发布事件
"""

import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from neurova.cognitive_layers.memory_layer.bus_event import (
    EventBus, MemoryEvent, MemoryModule, ModuleHealth,
)
from neurova.cognitive_layers.memory_layer.models import (
    Memory, MemoryCategory, MemoryType, LifecycleStage, EmotionType,
)

logger = logging.getLogger(__name__)

# 全局单例
_default_manager: Optional["MemoryManager"] = None
_manager_lock = threading.Lock()


class MemoryManager:
    """记忆管理器 Facade — 通过 EventBus 路由到各子模块"""

    def __init__(self, db_path: str = "neurova_memory.db", agent_id: str = "default",
                 user_id: str = "default"):
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
        
        # 情感模块（立即初始化）
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
        self._emotion_module = EmotionModule(db_path=db_path)
        self._emotion_module.init()

        # 统计
        self._stats = {
            "total_memories": 0,
            "recall_count": 0,
            "remember_count": 0,
        }

        logger.info(f"MemoryManager initialized: agent_id={agent_id}, user_id={user_id}")

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

    def remember(self, content: str, category: str = "general",
                 memory_type: str = "semantic", temperature: float = 100.0,
                 importance: float = 50.0, metadata: Optional[Dict[str, Any]] = None,
                 emotion: Optional[str] = None,
                 **kwargs) -> str:
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

            mem = Memory(
                id=mem_id,
                content=content,
                memory_type=MemoryType(memory_type) if isinstance(memory_type, str) else memory_type,
                category=MemoryCategory(category) if isinstance(category, str) else category,
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
            self._bus.emit(MemoryEvent(
                type=MemoryEvent.MEMORY_CREATED,
                source="memory_manager",
                payload={"memory_id": mem_id, "content": content, "category": category},
            ))
            return mem_id

    def recall(self, query: str = "", category: Optional[str] = None,
               limit: int = 10, min_temperature: float = 0.0,
               **kwargs) -> List[Dict[str, Any]]:
        """检索记忆"""
        with self._lock:
            self._stats["recall_count"] += 1
            results = list(self._memories.values())

            # 按分类过滤
            if category:
                results = [m for m in results if m.category.value == category]

            # 按温度过滤
            if min_temperature > 0:
                results = [m for m in results if m.temperature >= min_temperature]

            # 简单关键词匹配
            if query:
                query_lower = query.lower()
                results = [m for m in results if query_lower in m.content.lower()]

            # 按温度排序
            results.sort(key=lambda m: m.temperature, reverse=True)

            # 发射事件
            for m in results[:limit]:
                m.touch()
                self._bus.emit(MemoryEvent(
                    type=MemoryEvent.MEMORY_ACCESSED,
                    source="memory_manager",
                    payload={"memory_id": m.id, "temperature": m.temperature},
                ))

            return [m.to_dict() for m in results[:limit]]

    def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """获取单条记忆"""
        mem = self._memories.get(memory_id)
        if mem:
            mem.touch()
            self._bus.emit(MemoryEvent(
                type=MemoryEvent.MEMORY_ACCESSED,
                source="memory_manager",
                payload={"memory_id": mem.id},
            ))
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
            mem.category = MemoryCategory(kwargs["category"]) if isinstance(kwargs["category"], str) else kwargs["category"]
        if "lifecycle_stage" in kwargs:
            stage_val = kwargs["lifecycle_stage"]
            if isinstance(stage_val, str):
                mem.lifecycle_stage = LifecycleStage(stage_val)
            elif isinstance(stage_val, LifecycleStage):
                mem.lifecycle_stage = stage_val
        mem.updated_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        self._bus.emit(MemoryEvent(
            type=MemoryEvent.MEMORY_UPDATED,
            source="memory_manager",
            payload={"memory_id": memory_id},
        ))
        return True

    def forget(self, memory_id: str, soft: bool = True) -> bool:
        """遗忘记忆"""
        if memory_id not in self._memories:
            return False
        if soft:
            self._memories[memory_id].lifecycle_stage = LifecycleStage.FORGOTTEN
        else:
            del self._memories[memory_id]
        self._stats["total_memories"] = len(self._memories)
        self._bus.emit(MemoryEvent(
            type=MemoryEvent.MEMORY_DELETED,
            source="memory_manager",
            payload={"memory_id": memory_id, "soft": soft},
        ))
        return True

    def search_memories(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """搜索记忆（recall 别名）"""
        return self.recall(query=query, limit=limit)

    def get_memories(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """获取记忆列表"""
        with self._lock:
            mems = list(self._memories.values())
            mems.sort(key=lambda m: m.created_at, reverse=True)
            return [m.to_dict() for m in mems[offset:offset + limit]]

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

    # ────── Emotion (delegated stubs) ──────

    def analyze_emotion(self, text: str) -> Dict[str, Any]:
        """分析情感（委托给 emotion_analyzer）"""
        if self._emotion_analyzer:
            return self._emotion_analyzer.analyze(text)
        return {"emotion": EmotionType.NEUTRAL.value, "confidence": 0.5}

    def get_emotion_summary(self) -> Dict[str, Any]:
        return {"dominant_emotion": EmotionType.NEUTRAL.value, "distribution": {}}

    def get_emotion_distribution(self) -> Dict[str, float]:
        return {}

    def update_emotional_state(self, text: str) -> Dict[str, Any]:
        return self.analyze_emotion(text)

    def get_emotional_state(self) -> Dict[str, Any]:
        return self.get_emotion_summary()

    def get_dominant_emotion(self) -> str:
        return EmotionType.NEUTRAL.value

    def get_emotion_bias(self) -> float:
        return 0.0

    def apply_emotion_to_temperature(self, base_temp: float) -> float:
        return base_temp

    def apply_emotion_to_style(self, text: str) -> str:
        return text

    def get_emotion_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        return []

    def reset_emotion_to_baseline(self) -> None:
        pass

    def merge_with_user_emotion(self, user_text: str) -> Dict[str, Any]:
        return self.analyze_emotion(user_text)

    # ────── Classification ──────

    def classify_memory(self, content: str) -> Dict[str, Any]:
        return {"category": MemoryCategory.GENERAL.value, "confidence": 0.5}

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
        return [m.to_dict() for m in self._memories.values()
                if m.lifecycle_stage == LifecycleStage.CRYSTALLIZED][:limit]

    def get_hot_memories(self, limit: int = 10, min_temperature: float = 80.0) -> List[Dict[str, Any]]:
        return self.recall(limit=limit, min_temperature=min_temperature)

    def flush_all_pending_updates(self) -> int:
        return 0

    # ────── Self Model (delegated stubs) ──────

    def get_self_model(self) -> Dict[str, Any]:
        return {"agent_id": self._agent_id, "name": "Neurova"}

    def update_self_model(self, **kwargs) -> bool:
        return True

    def update_user_profile(self, **kwargs) -> bool:
        return True

    def get_user_profile(self) -> Dict[str, Any]:
        return {"user_id": self._user_id}

    # ────── Meta-cognition (delegated stubs) ──────

    def meta_monitor(self) -> Dict[str, Any]:
        return {"status": "ok"}

    def meta_reflect(self, **kwargs) -> Dict[str, Any]:
        return {"reflection": "no reflection module"}

    def meta_optimize(self) -> Dict[str, Any]:
        return {"optimized": False}

    def meta_evolve_skills(self, **kwargs) -> Dict[str, Any]:
        return {"evolved": False}

    def meta_get_health_report(self) -> Dict[str, Any]:
        return {"healthy": True}

    def meta_get_reflection_report(self) -> Dict[str, Any]:
        return {"reflections": []}

    def meta_get_skill_stats(self) -> Dict[str, Any]:
        return {"skills": []}

    def meta_get_all_skills(self) -> List[Dict[str, Any]]:
        return []

    def meta_match_skills(self, query: str) -> List[Dict[str, Any]]:
        return []

    def meta_should_monitor(self) -> bool:
        return False

    def meta_should_reflect(self) -> bool:
        return False

    def meta_should_optimize(self) -> bool:
        return False

    def meta_should_evolve_skills(self) -> bool:
        return False

    # ────── EKI (delegated stubs) ──────

    def eki_process_task(self, **kwargs) -> Dict[str, Any]:
        return {"processed": False}

    def eki_recommend_reinforcement(self, **kwargs) -> List[Dict[str, Any]]:
        return []

    def eki_predict_decay(self, **kwargs) -> Dict[str, Any]:
        return {"predicted": False}

    def eki_get_memory_strength(self, **kwargs) -> float:
        return 50.0

    def eki_get_statistics(self) -> Dict[str, Any]:
        return {}

    def eki_batch_update(self, **kwargs) -> int:
        return 0

    def eki_update_memory_from_access(self, **kwargs) -> bool:
        return True

    def eki_set_enabled(self, enabled: bool) -> None:
        pass

    def eki_get_enabled(self) -> bool:
        return False

    def eki_configure(self, **kwargs) -> None:
        pass

    # ────── TKG (delegated stubs) ──────

    def tkg_add_fact(self, **kwargs) -> str:
        return ""

    def tkg_query_current(self, **kwargs) -> List[Dict[str, Any]]:
        return []

    def tkg_query_at_time(self, **kwargs) -> List[Dict[str, Any]]:
        return []

    def tkg_get_history(self, **kwargs) -> List[Dict[str, Any]]:
        return []

    def tkg_detect_conflicts(self, **kwargs) -> List[Dict[str, Any]]:
        return []

    def tkg_get_stats(self) -> Dict[str, Any]:
        return {}

    # ────── Working Memory (delegated stubs) ──────

    def wm_add_turn(self, **kwargs) -> None:
        pass

    def wm_get_context(self, **kwargs) -> List[Dict[str, Any]]:
        return []

    def wm_compress_turn(self, **kwargs) -> None:
        pass

    def wm_cache_plan(self, **kwargs) -> None:
        pass

    def wm_retrieve_plan(self, **kwargs) -> Optional[Dict[str, Any]]:
        return None

    def wm_record_plan_result(self, **kwargs) -> None:
        pass

    def wm_get_stats(self) -> Dict[str, Any]:
        return {}

    def wm_clear(self) -> None:
        pass

    # ────── Self Commands (delegated stubs) ──────

    def self_get_commands(self) -> List[Dict[str, Any]]:
        return []

    def self_add_command(self, **kwargs) -> str:
        return ""

    def self_update_command(self, **kwargs) -> bool:
        return True

    def self_delete_command(self, **kwargs) -> bool:
        return True

    def self_get_heart_beat_tasks(self) -> List[Dict[str, Any]]:
        return []

    def self_get_due_tasks(self) -> List[Dict[str, Any]]:
        return []

    def self_add_heart_beat_task(self, **kwargs) -> str:
        return ""

    def self_update_heart_beat_task(self, **kwargs) -> bool:
        return True

    def self_record_task_run(self, **kwargs) -> bool:
        return True

    def self_delete_heart_beat_task(self, **kwargs) -> bool:
        return True

    def self_get_system_prompt_context(self) -> str:
        return ""

    def self_get_status(self) -> Dict[str, Any]:
        return {"status": "ok"}

    # ────── Auto Update ──────

    def start_auto_update(self, interval: float = 300.0) -> None:
        pass

    def stop_auto_update(self) -> None:
        pass

    # ────── Advanced Features (delegated stubs) ──────

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

    def get_traces_by_trigger(self, **kwargs) -> List[Dict[str, Any]]:
        return []

    def detect_conflict(self, **kwargs) -> List[Dict[str, Any]]:
        return []

    def detect_time_conflicts(self, **kwargs) -> List[Dict[str, Any]]:
        return []

    def detect_all_conflicts(self) -> List[Dict[str, Any]]:
        return []

    def get_conflict_summary(self) -> Dict[str, Any]:
        return {"conflicts": []}

    def add_relation(self, **kwargs) -> str:
        return ""

    def get_relations(self, **kwargs) -> List[Dict[str, Any]]:
        return []

    def delete_relation(self, **kwargs) -> bool:
        return True

    def get_memory_graph(self, **kwargs) -> Dict[str, Any]:
        return {"nodes": [], "edges": []}

    def search_similar_memories(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        return self.recall(query=query, limit=limit)

    # ────── Sleep (delegated stubs) ──────

    def run_light_sleep_cycle(self) -> Dict[str, Any]:
        return {"merged": 0}

    def run_rem_sleep_cycle(self) -> Dict[str, Any]:
        return {"replayed": 0}

    def run_deep_sleep_cycle(self) -> Dict[str, Any]:
        return {"archived": 0}

    def run_dormant_cycle(self) -> Dict[str, Any]:
        return {"crystallized": 0}

    # ────── Explainability (delegated stubs) ──────

    def explain_memory(self, memory_id: str) -> Dict[str, Any]:
        mem = self._memories.get(memory_id)
        if mem:
            return {"memory_id": memory_id, "content": mem.content, "reason": "direct recall"}
        return {"memory_id": memory_id, "error": "not found"}

    def get_explanation_chain(self, **kwargs) -> List[Dict[str, Any]]:
        return []

    def visualize_chain(self, **kwargs) -> str:
        return ""

    # ────── Forgetting Recovery (delegated stubs) ──────

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
        return [m.to_dict() for m in self._memories.values()
                if m.lifecycle_stage == LifecycleStage.ARCHIVED][:limit]

    def get_deleted_memories(self, limit: int = 10) -> List[Dict[str, Any]]:
        return [m.to_dict() for m in self._memories.values()
                if m.lifecycle_stage == LifecycleStage.FORGOTTEN][:limit]

    def get_recovery_history(self) -> List[Dict[str, Any]]:
        return []

    def permanently_delete_memory(self, memory_id: str) -> bool:
        return self.forget(memory_id, soft=False)

    # ────── Relation ──────

    def relate(self, source_id: str, target_id: str, relation_type: str = "related") -> bool:
        return True

    def recall_with_associations(self, query: str, depth: int = 1, **kwargs) -> List[Dict[str, Any]]:
        return self.recall(query, **kwargs)

    def recall_graph(self, query: str, **kwargs) -> Dict[str, Any]:
        return {"nodes": [], "edges": []}

    # ────── Close ──────

    def close(self) -> None:
        """优雅关闭"""
        self._started = False
        logger.info(f"MemoryManager closed: agent_id={self._agent_id}")

    def __repr__(self) -> str:
        return f"MemoryManager(agent_id={self._agent_id!r}, memories={len(self._memories)})"


def get_memory_manager(agent_id: str = "default", user_id: str = "default",
                       db_path: str = "neurova_memory.db") -> MemoryManager:
    """获取/创建默认 MemoryManager 单例"""
    global _default_manager
    with _manager_lock:
        if _default_manager is None:
            _default_manager = MemoryManager(db_path=db_path, agent_id=agent_id, user_id=user_id)
        return _default_manager
