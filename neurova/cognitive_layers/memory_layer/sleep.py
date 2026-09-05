"""
睡眠整合模块

在"睡眠"阶段对记忆进行整合：
- 语义相似度聚类
- 合并高度相似的记忆（减少冗余）
- 温度衰减（遗忘低价值记忆）
- 压缩和归档
"""

from neurova.core.logger import get_logger
from neurova.core.sleep_settings_store import SleepSettingsStore
import json
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from .isolation import IsolationContext

logger = get_logger(__name__)


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """计算两个向量的余弦相似度"""
    if len(vec_a) != len(vec_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


@dataclass
class MemoryRecord:
    """记忆记录"""

    id: str
    content: str
    embedding: List[float] = field(default_factory=list)
    temperature: float = 50.0
    importance: float = 0.5
    emotion_score: float = 0.0
    recall_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    categories: List[str] = field(default_factory=list)
    is_archived: bool = False
    merged_from: List[str] = field(default_factory=list)
    # 三层隔离字段
    agent_id: str = "default"
    neuser_id: str = "default"
    user_id: str = "default"
    shared: bool = False  # 跨 agent 共享开关

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryRecord":
        """从字典创建MemoryRecord（兼容Memory.to_dict()格式）"""
        # 处理日期时间
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except ValueError:
                created_at = datetime.now()
        elif not isinstance(created_at, datetime):
            created_at = datetime.now()

        # 映射MemoryManager的字段到MemoryRecord
        return cls(
            id=data.get("id", ""),
            content=data.get("content", ""),
            embedding=data.get("embedding", []),
            temperature=data.get("temperature", 50.0),
            importance=data.get("importance", 0.5),
            emotion_score=data.get("emotion_score", 0.0),
            recall_count=data.get("recall_count", data.get("access_count", 0)),
            created_at=created_at,
            categories=data.get("categories", []),
            is_archived=data.get("is_archived", False),
            merged_from=data.get("merged_from", []),
            agent_id=data.get("agent_id", "default"),
            neuser_id=data.get("neuser_id", "default"),
            user_id=data.get("user_id", "default"),
            shared=data.get("shared", False),
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（兼容Memory.from_dict()格式）"""
        return {
            "id": self.id,
            "content": self.content,
            "embedding": self.embedding,
            "temperature": self.temperature,
            "importance": self.importance,
            "emotion_score": self.emotion_score,
            "recall_count": self.recall_count,
            "created_at": (
                self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at)
            ),
            "categories": self.categories,
            "is_archived": self.is_archived,
            "merged_from": self.merged_from,
            "agent_id": self.agent_id,
            "neuser_id": self.neuser_id,
            "user_id": self.user_id,
            "shared": self.shared,
        }


@dataclass
class MergeResult:
    """合并结果"""

    merged_id: str
    merged_content: str
    source_ids: List[str]
    avg_temperature: float
    avg_importance: float
    combined_categories: List[str]


class SleepConsolidation:
    """睡眠整合引擎

    模拟睡眠期间的记忆整合过程：
    1. 语义相似度聚类
    2. 高相似度记忆合并
    3. 温度衰减（遗忘）
    4. 归档低活跃度记忆
    """

    def __init__(
        self,
        similarity_threshold: float = 0.7,
        archive_threshold: float = 20.0,
        decay_rate: float = 0.1,
        memory_manager=None,
        storage=None,
        settings_store: Optional["SleepSettingsStore"] = None,
    ):
        """初始化睡眠整合引擎

        Args:
            similarity_threshold: 语义相似度阈值（高于此值的记忆合并）
            archive_threshold: 归档温度阈值
            decay_rate: 睡眠期间的温度衰减率
            memory_manager: 记忆管理器实例（可选）
            storage: 存储实例（可选）
            settings_store: 设置持久化存储（可选）。提供时 update_settings
                落盘、初始化时加载 —— 此前设置仅存内存，agent 重启即丢
        """
        self.similarity_threshold = similarity_threshold
        self.archive_threshold = archive_threshold
        self.decay_rate = decay_rate
        self.base_decay_rate = decay_rate  # RSI 可优化参数别名
        self.merge_threshold = similarity_threshold  # RSI 可优化参数别名
        self.memory_manager = memory_manager
        self.storage = storage
        self._state: Dict[str, Any] = {}
        self._settings_lock = threading.RLock()
        # 设置持久化: 由 SleepSettingsStore 承担（agent_id 白名单净化 +
        # 固定目录, 文件 IO 不在本模块）—— 此前设置仅存内存, agent 重启即丢
        self._settings_store = settings_store
        # RSI 反馈统计
        self._consolidation_count: int = 0
        self._total_memories_processed: int = 0
        self._total_merged: int = 0
        self._temperature_sum: float = 0.0

        # API 能力状态（此前 /api/v1/sleep 端点因缺少这些能力而全部降级为 mock）
        self._is_sleeping: bool = False
        self._sleep_phase: str = "awake"
        self._last_sleep_time: Optional[float] = None
        self._last_wake_time: Optional[float] = None
        self._sleep_started_at: Optional[float] = None
        self._total_sleep_duration: float = 0.0
        self._sleep_cycles: int = 0
        # 资源修复: _dream_logs/_merge_history 曾只增不减/全量 id 内嵌,
        # 静态期睡眠整理每轮把整库 id 列表永久留存 → 现在有界+截断内嵌
        self._MAX_DREAM_LOGS = 200
        self._MAX_MERGE_HISTORY = 500
        self._MAX_INVOLVED_IDS = 100
        self._dream_logs: List[Dict[str, Any]] = []
        self._merge_history: List[Dict[str, Any]] = []
        # 冲突解决审计记录（多成员簇合并时产生, /conflicts 端点数据源）
        self._conflict_resolutions: List[Dict[str, Any]] = []
        self._settings: Dict[str, Any] = {
            "auto_sleep_enabled": True,
            "sleep_threshold_minutes": 30,
            "sleep_duration_minutes": 60,
            "dream_replay_enabled": True,
            "memory_consolidation_enabled": True,
            "conflict_resolution_enabled": True,
            # ── 阶段推进参数（默认值 = 原 idle_tracker 硬编码, 行为零漂移）──
            "sleep_mode": "temperature",  # temperature | time | either
            "temp_threshold_light_sleep": 30.0,
            "temp_threshold_deep_sleep": 25.0,
            "temp_threshold_rem": 20.0,
            "temp_threshold_hibernate": 15.0,
            "idle_threshold_light_sleep": 30,  # 分钟
            "idle_threshold_deep_sleep": 60,
            "idle_threshold_rem": 90,
            "idle_threshold_hibernate": 120,
            "monitor_interval_seconds": 60,
        }
        if self._settings_store is not None:
            self._load_settings()

        logger.debug(
            f"SleepConsolidation 初始化: " f"similarity={similarity_threshold}, " f"archive={archive_threshold}"
        )

    def set_state_value(self, key: str, value: Any) -> None:
        """设置状态值（供 IdleTimeTracker 调用）"""
        self._state[key] = value

    def get_state_value(self, key: str, default: Any = None) -> Any:
        """获取状态值"""
        return self._state.get(key, default)

    def cluster_by_similarity(self, memories: List[MemoryRecord]) -> List[List[MemoryRecord]]:
        """基于语义相似度聚类

        使用简单的贪心聚类算法：
        1. 遍历所有记忆
        2. 找到与当前记忆最相似的簇
        3. 如果相似度超过阈值，加入该簇
        4. 否则创建新簇

        Args:
            memories: 记忆列表

        Returns:
            List[List[MemoryRecord]]: 聚类结果
        """
        if not memories:
            return []

        clusters: List[List[MemoryRecord]] = []

        for memory in memories:
            best_cluster = None
            best_similarity = 0.0

            # 找到最相似的簇
            for cluster in clusters:
                # 使用簇中心（第一个元素）计算相似度
                if cluster[0].embedding and memory.embedding:
                    sim = cosine_similarity(cluster[0].embedding, memory.embedding)
                    if sim > best_similarity:
                        best_similarity = sim
                        best_cluster = cluster

            # 如果相似度超过阈值，加入簇
            if best_cluster is not None and best_similarity >= self.similarity_threshold:
                best_cluster.append(memory)
            else:
                # 创建新簇
                clusters.append([memory])

        logger.debug("聚类结果: %s 条记忆 → %s 个簇", len(memories), len(clusters))
        return clusters

    def merge_cluster(self, cluster: List[MemoryRecord]) -> MergeResult:
        """合并一个簇中的记忆

        合并策略：
        - 内容：取最长的内容（包含最多信息）
        - 温度：取平均值
        - 重要性：取最高值
        - 分类：合并所有分类（去重）

        Args:
            cluster: 同一簇中的记忆

        Returns:
            MergeResult: 合并结果
        """
        if not cluster:
            raise ValueError("空簇无法合并")

        if len(cluster) == 1:
            mem = cluster[0]
            return MergeResult(
                merged_id=mem.id,
                merged_content=mem.content,
                source_ids=[mem.id],
                avg_temperature=mem.temperature,
                avg_importance=mem.importance,
                combined_categories=mem.categories.copy(),
            )

        # 取最长的内容
        longest = max(cluster, key=lambda m: len(m.content))

        # 计算平均值
        avg_temp = sum(m.temperature for m in cluster) / len(cluster)
        avg_importance = sum(m.importance for m in cluster) / len(cluster)

        # 合并分类（去重）
        all_categories = list(set(cat for m in cluster for cat in m.categories))

        # 生成合并ID
        merged_id = f"merged_{cluster[0].id}_{len(cluster)}"

        # 记录来源
        source_ids = [m.id for m in cluster]

        result = MergeResult(
            merged_id=merged_id,
            merged_content=longest.content,
            source_ids=source_ids,
            avg_temperature=avg_temp,
            avg_importance=avg_importance,
            combined_categories=all_categories,
        )

        # 冲突解决审计: 多成员簇且内容有差异时记录"保留了什么、合并了什么"。
        # 相同内容的重复记忆是普通去重, 不算冲突。conflict_resolution_enabled
        # 关闭时不记录。此前该设置键无消费方, /conflicts 端点恒为空。
        contents = [m.content for m in cluster]
        if (
            self._settings.get("conflict_resolution_enabled", True)
            and len(set(contents)) > 1
        ):
            kept = longest.content
            dropped = [c for c in contents if c != kept]
            self._conflict_resolutions.insert(
                0,
                {
                    "id": f"cr_{int(time.time() * 1000)}_{cluster[0].id}",
                    "agent_id": cluster[0].agent_id,
                    "field": "content",
                    "local_value": kept[:200],
                    "remote_value": " | ".join(c[:200] for c in dropped),
                    "resolved": True,
                    "resolution": "keep_longest",
                    "resolution_strategy": "keep_longest",
                    "conflict_type": "memory_merge",
                    "source_memories": source_ids,
                    "success": True,
                    "created_at": datetime.now().isoformat(),
                },
            )

        logger.debug("合并簇: %s 条记忆 → %s", len(cluster), merged_id)
        return result

    def apply_sleep_decay(self, memories: List[MemoryRecord]) -> List[MemoryRecord]:
        """应用睡眠期间的温度衰减（补课 5.3 收敛：委托 TemperatureEngine.on_decay）

        遗忘曲线唯一实现在 temperature.py（消费方 5:1）——本方法收敛为
        批量包装，不再自持第二套衰减公式。TemperatureEngine 不可用时
        回退原内联公式（保留归档阈值语义）。

        Args:
            memories: 记忆列表

        Returns:
            List[MemoryRecord]: 更新后的记忆列表
        """
        engine = None
        try:
            from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine

            engine = getattr(self, "_temperature_engine", None)
            if engine is None:
                engine = TemperatureEngine()
                self._temperature_engine = engine
        except Exception as e:
            logger.debug("TemperatureEngine 不可用，回退内联衰减: %s", e)

        if engine is not None:
            # on_decay(current_temp: float, ...) → {"new_temp": ...}
            for memory in memories:
                try:
                    outcome = engine.on_decay(
                        memory.temperature,
                        last_accessed=memory.created_at.isoformat() if hasattr(memory.created_at, "isoformat") else str(memory.created_at),
                        importance=memory.importance,
                        emotion_score=memory.emotion_score,
                        recall_count=memory.recall_count,
                    )
                    new_temp = outcome.get("new_temp") if isinstance(outcome, dict) else outcome
                    if isinstance(new_temp, (int, float)):
                        memory.temperature = max(0.0, min(float(memory.temperature), float(new_temp)))
                except Exception as e:
                    logger.debug("on_decay 单条失败（保留原温度）: %s", e)
            if engine is not None:
                # 归档阈值语义保留（TemperatureEngine 不管归档）
                for memory in memories:
                    if memory.temperature < self.archive_threshold and not memory.is_archived:
                        memory.is_archived = True
                        logger.debug("记忆 %s 已归档 (温度: %.1f)", memory.id, memory.temperature)
                return memories
            # 引擎签名不兼容 → 走回退

        # 回退：原内联公式
        for memory in memories:
            decay = self.decay_rate * memory.temperature
            importance_protection = 1.0 - 0.5 * memory.importance
            actual_decay = decay * importance_protection
            memory.temperature = max(0.0, memory.temperature - actual_decay)
            if memory.temperature < self.archive_threshold:
                memory.is_archived = True
                logger.debug("记忆 %s 已归档 (温度: %.1f)", memory.id, memory.temperature)
        return memories

    def consolidate(
        self, memories: List[MemoryRecord], isolation_context: Optional["IsolationContext"] = None
    ) -> Tuple[List[MemoryRecord], List[MergeResult]]:
        """执行完整的睡眠整合流程

        步骤：
        1. 聚类相似记忆
        2. 合并每个簇
        3. 应用温度衰减
        4. 返回整合后的记忆和合并记录

        Args:
            memories: 记忆列表
            isolation_context: 隔离上下文（可选）

        Returns:
            Tuple[List[MemoryRecord], List[MergeResult]]:
                整合后的记忆列表, 合并记录列表
        """
        logger.info("开始睡眠整合: %s 条记忆", len(memories))

        # 1. 聚类
        clusters = self.cluster_by_similarity(memories)

        # 2. 合并
        merged_memories = []
        merge_results = []

        for cluster in clusters:
            merge_result = self.merge_cluster(cluster)
            merge_results.append(merge_result)

            # 单例簇（未发生真实合并）：原样保留原记录，只走后续温度衰减。
            # 禁止伪造 merged_from=[自身id] —— 下游写回以 merged_from 非空判定
            # "合并产物"，伪造会把未合并记忆当新记忆重新插入 → 每轮巩固全库翻倍。
            if len(cluster) == 1:
                mem = cluster[0]
                if isolation_context is not None:
                    mem.agent_id = isolation_context.agent_id
                    mem.neuser_id = isolation_context.neuser_id
                    mem.user_id = isolation_context.user_id
                merged_memories.append(mem)
                continue

            # 创建合并后的记忆记录
            merged_memory = MemoryRecord(
                id=merge_result.merged_id,
                content=merge_result.merged_content,
                temperature=merge_result.avg_temperature,
                importance=merge_result.avg_importance,
                categories=merge_result.combined_categories,
                merged_from=merge_result.source_ids,
                created_at=datetime.now(),
                # 继承隔离上下文
                agent_id=isolation_context.agent_id if isolation_context else "default",
                neuser_id=isolation_context.neuser_id if isolation_context else "default",
                user_id=isolation_context.user_id if isolation_context else "default",
            )

            # 保留嵌入（使用第一个记忆的嵌入）
            if cluster[0].embedding:
                merged_memory.embedding = cluster[0].embedding

            merged_memories.append(merged_memory)

        # 3. 温度衰减
        merged_memories = self.apply_sleep_decay(merged_memories)

        # 4. 统计
        active_count = sum(1 for m in merged_memories if not m.is_archived)
        archived_count = sum(1 for m in merged_memories if m.is_archived)

        logger.info(
            f"睡眠整合完成: "
            f"合并 {len(memories)} → {len(merged_memories)} 条记忆, "
            f"活跃 {active_count}, 归档 {archived_count}"
        )

        # 更新 RSI 反馈统计
        self._consolidation_count += 1
        self._total_memories_processed += len(memories)
        self._total_merged += len(merge_results)
        self._temperature_sum += sum(m.temperature for m in merged_memories)

        return merged_memories, merge_results

    def get_feedback(self) -> Dict[str, Any]:
        """
        获取睡眠整合模块的反馈信号，供 RSI 系统使用。

        Returns:
            Dict[str, Any]: 包含 consolidation_count, merge_rate, avg_temperature
        """
        total_memories = self._total_memories_processed
        merge_rate = self._total_merged / total_memories if total_memories > 0 else 0.0
        total_merged_memories = self._consolidation_count  # 每次整合产出的记忆数
        avg_temperature = self._temperature_sum / total_merged_memories if total_merged_memories > 0 else 50.0

        return {
            "consolidation_count": self._consolidation_count,
            "merge_rate": merge_rate,
            "avg_temperature": avg_temperature,
        }

    def run_sleep_cycle(self, memories: List[MemoryRecord], phase: str = "sleep") -> Dict[str, Any]:
        """执行睡眠周期（向后兼容包装）

        Args:
            memories: 记忆列表
            phase: 睡眠阶段（默认 "sleep"）

        Returns:
            Dict[str, Any]: 包含整合结果的字典
        """
        merged_memories, merge_results = self.consolidate(memories)

        # 计算统计信息
        active_count = sum(1 for m in merged_memories if not m.is_archived)
        archived_count = sum(1 for m in merged_memories if m.is_archived)

        # 构建结果字典（向后兼容）
        result = {
            "phase": phase,
            "total_processed": len(memories),
            "merged_count": len(merge_results),
            "archived_count": archived_count,
            "active_count": active_count,
            "merged_memories": merged_memories,
            "merge_results": merge_results,
        }

        logger.info("睡眠周期完成: 阶段=%s, 处理=%s 条记忆", phase, len(memories))
        return result

    # ────── API 能力层（/api/v1/sleep 端点契约）──────

    def is_sleeping(self) -> bool:
        """当前是否处于睡眠状态"""
        return self._is_sleeping

    def get_sleep_phase(self) -> str:
        """当前睡眠阶段"""
        return self._sleep_phase

    def get_last_sleep_time(self) -> Optional[float]:
        """最近一次入睡时间戳"""
        return self._last_sleep_time

    def get_last_wake_time(self) -> Optional[float]:
        """最近一次唤醒时间戳"""
        return self._last_wake_time

    def get_total_sleep_duration(self) -> float:
        """累计睡眠时长（秒）"""
        return self._total_sleep_duration

    def get_sleep_cycles(self) -> int:
        """累计睡眠周期数"""
        return self._sleep_cycles

    def start_sleep(self, duration_minutes: Optional[int] = None) -> Dict[str, Any]:
        """主动进入睡眠：立即执行一轮真实的记忆整理并写回

        Args:
            duration_minutes: 名义睡眠时长（分钟），整理本身同步完成；
                不传时回退设置 sleep_duration_minutes（设置通路修复：此前该
                设置键无消费方）

        Returns:
            整理统计 dict
        """
        if self._is_sleeping:
            return {"message": "already_sleeping", "sleep_cycles": self._sleep_cycles}

        if duration_minutes is None:
            duration_minutes = int(self._settings.get("sleep_duration_minutes", 60))

        now = time.time()
        self._is_sleeping = True
        self._sleep_phase = "deep_sleep"
        self._last_sleep_time = now
        self._sleep_started_at = now
        self._sleep_cycles += 1

        result: Dict[str, Any] = {
            "duration_minutes": duration_minutes,
            "total_processed": 0,
            "merged_count": 0,
            "archived_count": 0,
            "write_back": {},
        }

        if self._settings.get("memory_consolidation_enabled", True) and self.memory_manager:
            try:
                all_memories = self.memory_manager.get_all_memories()
                if all_memories:
                    records = [MemoryRecord.from_dict(m) for m in all_memories]
                    cycle = self.run_sleep_cycle(records, phase="deep_sleep")

                    from neurova.cognitive_layers.memory_layer.sleep_writeback import (
                        write_back_consolidation_result,
                    )

                    write_stats = write_back_consolidation_result(self.memory_manager, cycle)

                    result = {
                        "total_processed": cycle["total_processed"],
                        "merged_count": cycle["merged_count"],
                        "archived_count": cycle["archived_count"],
                        "write_back": write_stats,
                    }

                    agent_id = records[0].agent_id if records else "default"
                    involved = [m.id for m in records]
                    # 梦境回放开关: dream_replay_enabled=False 时不记录梦境,
                    # 但整合与合并历史照常（此前该设置键无消费方）
                    if self._settings.get("dream_replay_enabled", True):
                        self._dream_logs.insert(
                            0,
                            {
                                "dream_id": f"dream_{int(now * 1000)}_{self._sleep_cycles}",
                                "agent_id": agent_id,
                                "timestamp": now,
                                "dream_type": "replay",
                                "content": (
                                    f"整理 {cycle['total_processed']} 条记忆，"
                                    f"合并 {cycle['merged_count']} 组，归档 {cycle['archived_count']} 条"
                                ),
                                # 资源修复: 原样嵌入整库 id 列表 → 截断到前 100
                                "memories_involved": involved[: self._MAX_INVOLVED_IDS],
                                "involved_total": len(involved),
                                "insights_generated": cycle["merged_count"],
                                "duration": time.time() - now,
                            },
                        )
                        if len(self._dream_logs) > self._MAX_DREAM_LOGS:
                            self._dream_logs = self._dream_logs[: self._MAX_DREAM_LOGS]
                    for merge_result in cycle["merge_results"]:
                        if len(merge_result.source_ids) < 2:
                            continue  # 单例簇不是真实合并
                        self._merge_history.append(
                            {
                                "merge_id": merge_result.merged_id,
                                "agent_id": agent_id,
                                "timestamp": now,
                                # 资源修复: source_ids 原样嵌入可到整库规模 → 截断
                                "source_memories": merge_result.source_ids[: self._MAX_INVOLVED_IDS],
                                "source_total": len(merge_result.source_ids),
                                "target_memory": merge_result.merged_id,
                                "merge_type": "consolidation",
                                "success": True,
                                "conflicts_resolved": 0,
                            }
                        )
                        if len(self._merge_history) > self._MAX_MERGE_HISTORY:
                            self._merge_history = self._merge_history[-self._MAX_MERGE_HISTORY:]
            except Exception as e:
                logger.warning("主动睡眠整理失败: %s", e)

        logger.info("主动睡眠开始: 时长=%s 分钟, 处理=%s 条", duration_minutes, result["total_processed"])
        return result

    def wake(self) -> Dict[str, Any]:
        """唤醒：结束睡眠状态并累计时长"""
        now = time.time()
        if self._sleep_started_at:
            self._total_sleep_duration += max(0.0, now - self._sleep_started_at)
        self._is_sleeping = False
        self._sleep_phase = "awake"
        self._last_wake_time = now
        self._sleep_started_at = None
        return {
            "total_sleep_duration": self._total_sleep_duration,
            "sleep_cycles": self._sleep_cycles,
        }

    def get_dream_logs(self, limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
        """获取梦境（整理回放）记录，最新在前"""
        return self._dream_logs[offset : offset + limit]

    def get_dream_insights(self, limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
        """获取梦境洞察（当前由合并记录派生，无独立洞察时返回空）"""
        return []

    def get_memory_merges(self, limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
        """获取记忆合并历史，最新在前"""
        return self._merge_history[offset : offset + limit]

    def get_conflict_resolutions(self, limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
        """获取冲突解决审计记录，最新在前（此前恒返回空列表）"""
        return self._conflict_resolutions[offset : offset + limit]

    def resolve_conflict(
        self,
        resolution_id: str,
        resolution: str,
        apply_to_store: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """更新一条冲突记录的解决方式（前端 /conflicts/{id}/resolve 的后端）。

        补课 5.1：apply_to_store=True 时按 resolution 真写回记忆库——
        keep_longest/keep_newest 保留胜者、软删落选者；merge 重写胜者
        内容为"落选者要点 + 胜者原文"。memory_manager 缺失或操作失败
        时仅更新审计记录（诚实边界：不假装已改库）。

        Returns:
            更新后的记录 dict；未知 id 或非法 resolution 返回 None
        """
        if resolution not in ("keep_longest", "keep_newest", "merge"):
            return None
        for rec in self._conflict_resolutions:
            if rec.get("id") == resolution_id:
                rec["resolution"] = resolution
                rec["resolution_strategy"] = resolution
                rec["resolved"] = True
                if apply_to_store and self.memory_manager is not None:
                    applied = self._apply_conflict_resolution_to_store(rec, resolution)
                    rec["applied_to_store"] = applied
                    rec["applied_at"] = datetime.now().isoformat()
                return rec
        return None

    def _apply_conflict_resolution_to_store(self, rec: Dict[str, Any], resolution: str) -> bool:
        """把冲突解决写回记忆库（keep_* 软删落选者；merge 重写胜者）。

        Returns:
            True=至少执行了一次写操作；False=无法执行（缺 API/无来源）
        """
        source_ids: List[str] = rec.get("source_memories") or []
        if not source_ids or self.memory_manager is None:
            return False
        try:
            records = []
            for mid in source_ids:
                m = self.memory_manager.get_memory(mid) if hasattr(self.memory_manager, "get_memory") else None
                if m is not None:
                    records.append(m)
            if len(records) < 2:
                return False

            if resolution == "keep_newest":
                records.sort(key=lambda m: m.created_at, reverse=True)
            else:
                # keep_longest / merge 均以最长内容为胜者
                records.sort(key=lambda m: len(m.content), reverse=True)
            winner, losers = records[0], records[1:]

            ok = True
            if resolution == "merge":
                merged_content = "\n\n".join(m.content for m in reversed(records))
                ok = self.memory_manager.update_memory(winner.id, content=merged_content)
            for l in losers:
                # 软删优先（保留审计痕迹）；无 soft-delete 时跳过删除
                if hasattr(self.memory_manager, "delete_memory_soft"):
                    ok = self.memory_manager.delete_memory_soft(l.id) and ok
            return bool(ok)
        except Exception as e:
            from neurova.core.logger import get_logger as _gl

            _gl(__name__).warning("冲突解决写回失败（保留审计记录）: %s", e)
            return False

    def get_settings(self) -> Dict[str, Any]:
        """获取睡眠设置"""
        with self._settings_lock:
            return dict(self._settings)

    def update_settings(self, updates: Dict[str, Any]) -> None:
        """更新睡眠设置（未知键忽略），提供 settings_store 时持久化"""
        if not isinstance(updates, dict):
            return
        with self._settings_lock:
            for key, value in updates.items():
                if key in self._settings:
                    self._settings[key] = value
            if self._settings_store is not None:
                self._settings_store.save(dict(self._settings))

    def _load_settings(self) -> None:
        """从持久化存储加载设置（未知键忽略, 缺失/损坏降级为默认）"""
        if self._settings_store is None:
            return
        data = self._settings_store.load()
        if isinstance(data, dict):
            for key, value in data.items():
                if key in self._settings:
                    self._settings[key] = value
        logger.debug("睡眠设置已从持久化存储加载")
