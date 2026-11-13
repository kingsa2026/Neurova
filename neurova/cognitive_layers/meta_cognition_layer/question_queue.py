from __future__ import annotations

"""
问题队列系统

问题生成、冷却管理、状态跟踪

功能:
- 生成问题并存储到 question_queue
- 冷却时间管理（避免重复问）
- 问题状态更新
- 主动提问时读取 question_queue
"""

import json
from neurova.core.logger import get_logger
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class QuestionStatus(Enum):
    """问题状态枚举"""

    PENDING = "pending"  # 待处理（已生成，等待提问）
    ASKED = "asked"  # 已提问
    ANSWERED = "answered"  # 已回答
    ARCHIVED = "archived"  # 已归档
    COOLDOWN = "cooldown"  # 冷却中


class QuestionPriority(Enum):
    """问题优先级枚举"""

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass
class QuestionEntry:
    """问题条目数据模型"""

    id: str
    content: str
    status: QuestionStatus = QuestionStatus.PENDING
    priority: QuestionPriority = QuestionPriority.NORMAL
    cooldown_until: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    asked_at: Optional[float] = None
    answered_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "content": self.content,
            "status": self.status.value,
            "priority": self.priority.value,
            "cooldown_until": self.cooldown_until,
            "created_at": self.created_at,
            "asked_at": self.asked_at,
            "answered_at": self.answered_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuestionEntry":
        """从字典创建"""
        return cls(
            id=data["id"],
            content=data["content"],
            status=QuestionStatus(data.get("status", "pending")),
            priority=QuestionPriority(data.get("priority", "normal")),
            cooldown_until=data.get("cooldown_until"),
            created_at=data.get("created_at", time.time()),
            asked_at=data.get("asked_at"),
            answered_at=data.get("answered_at"),
            metadata=data.get("metadata", {}),
        )


# 优先级排序权重
_PRIORITY_ORDER = {
    QuestionPriority.HIGH: 0,
    QuestionPriority.NORMAL: 1,
    QuestionPriority.LOW: 2,
}


class CuriosityType(Enum):
    """好奇心类型（D4 自 proactive_question.py 取长补短并入，2026-11-14 退役裁定）"""

    KNOWLEDGE_GAP = "knowledge_gap"  # 知识缺口
    NOVELTY_SEEKING = "novelty_seeking"  # 新奇探索
    PATTERN_DISCOVERY = "pattern_discovery"  # 模式发现
    CAUSAL_REASONING = "causal_reasoning"  # 因果推理
    COUNTERFACTUAL = "counterfactual"  # 反事实思考


@dataclass
class ExplorationRecord:
    """探索记录（好奇心驱动的问题探索台账）"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    question_id: str = ""
    topic: str = ""
    curiosity_type: CuriosityType = CuriosityType.KNOWLEDGE_GAP
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    status: str = "in_progress"  # in_progress / completed / abandoned
    findings: List[str] = field(default_factory=list)
    knowledge_gained: float = 0.0


class CuriosityDrive:
    """好奇心驱动器（D4 并入；评估函数已做实，不再恒返占位值）。

    强度 = 基线 0.5 + 知识缺口×0.3 + 新颖性×0.2 − 探索疲劳×0.4，夹到 [0,1]。
    - 新颖性**做实**：按主题首见/复见次数衰减（复见一次 -0.3，下限 0）；
    - 知识缺口：显式信号（unknown_terms/unresolved/open_questions）或缺口账本
      均值；两者皆无时回落 0.5（中性未知，不伪造确定值）；
    - 探索疲劳**做实**：近 24h 探索越多越克制（原版三项只会加分、强度恒 ≥0.5，
      其 <0.3 的生成闸永不可达——本次改为疲劳负项，闸门真实可达）。
    """

    def __init__(self) -> None:
        self._explorations: Dict[str, ExplorationRecord] = {}
        self._knowledge_gaps: Dict[str, float] = {}
        self._seen_topics: Dict[str, int] = {}

    def calculate_intensity(self, context: Dict[str, Any]) -> float:
        """计算好奇心强度（0.0-1.0）"""
        topic = str(context.get("current_topic", "") or "")
        adjustments = [
            self._assess_knowledge_gap(context) * 0.3,
            self._assess_context_novelty(topic) * 0.2,
        ]
        fatigue = min(1.0, len(self._get_recent_explorations(hours=24)) / 10.0)
        adjustments.append(-fatigue * 0.4)
        return max(0.0, min(1.0, 0.5 + sum(adjustments)))

    def _get_recent_explorations(self, hours: int = 24) -> List[ExplorationRecord]:
        """获取最近的探索记录"""
        cutoff = time.time() - hours * 3600
        return [e for e in self._explorations.values() if e.started_at >= cutoff]

    def _assess_context_novelty(self, topic: str) -> float:
        """评估上下文新颖性：主题首见满分，每复见一次衰减 0.3"""
        if not topic:
            return 0.5
        return max(0.0, 1.0 - self._seen_topics.get(topic, 0) * 0.3)

    def _assess_knowledge_gap(self, context: Dict[str, Any]) -> float:
        """评估知识缺口：缺口账本均值；无账本时看显式信号，皆无回落中性 0.5"""
        if self._knowledge_gaps:
            return sum(self._knowledge_gaps.values()) / len(self._knowledge_gaps)
        if self._identify_knowledge_gaps(context):
            return 0.8
        return 0.5

    def _identify_knowledge_gaps(self, context: Dict[str, Any]) -> List[str]:
        """识别知识缺口：显式信号优先，其次缺口账本按缺口从大到小"""
        for key in ("unknown_terms", "unresolved", "open_questions"):
            values = context.get(key)
            if values:
                return [str(v) for v in values]
        if self._knowledge_gaps:
            return [t for t, _ in sorted(self._knowledge_gaps.items(), key=lambda x: x[1], reverse=True)]
        return []

    def record_exploration(
        self, question_id: str, topic: str, curiosity_type: CuriosityType
    ) -> ExplorationRecord:
        """记录探索开始（同主题计入新颖性衰减账本）"""
        exploration = ExplorationRecord(
            question_id=question_id,
            topic=topic,
            curiosity_type=curiosity_type,
        )
        self._explorations[exploration.id] = exploration
        if topic:
            self._seen_topics[topic] = self._seen_topics.get(topic, 0) + 1
        logger.debug("记录探索: %s", exploration.id)
        return exploration

    def complete_exploration(
        self, exploration_id: str, findings: List[str], knowledge_gained: float = 0.0
    ) -> Optional[ExplorationRecord]:
        """完成探索（ findings 与获得知识量入账，冲抵同主题知识缺口）"""
        exploration = self._explorations.get(exploration_id)
        if not exploration:
            return None
        exploration.ended_at = time.time()
        exploration.status = "completed"
        exploration.findings = findings
        exploration.knowledge_gained = knowledge_gained
        if exploration.topic in self._knowledge_gaps:
            self._knowledge_gaps[exploration.topic] = max(
                0.0, self._knowledge_gaps[exploration.topic] - knowledge_gained
            )
        logger.debug("完成探索: %s", exploration_id)
        return exploration

    def generate_curiosity_question(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """生成好奇心驱动的问题草案（强度 <0.3 不生成）。

        Returns:
            {content, priority, curiosity_type, topic, intensity} 或 None。
            priority/curiosity_type 为枚举值字符串，供队列元数据直接使用。
        """
        intensity = self.calculate_intensity(context)
        if intensity < 0.3:
            return None

        gaps = self._identify_knowledge_gaps(context)
        if gaps:
            curiosity_type = CuriosityType.KNOWLEDGE_GAP
            topic = gaps[0]
        else:
            curiosity_type = CuriosityType.NOVELTY_SEEKING
            topic = str(context.get("current_topic", "") or "未知主题")

        templates = {
            CuriosityType.KNOWLEDGE_GAP: f"关于 {topic}，我还不了解什么？",
            CuriosityType.NOVELTY_SEEKING: f"关于 {topic}，有什么新发现吗？",
            CuriosityType.PATTERN_DISCOVERY: f"在 {topic} 中，有什么模式可以发现？",
            CuriosityType.CAUSAL_REASONING: f"在 {topic} 中，因果关系是什么？",
            CuriosityType.COUNTERFACTUAL: f"如果 {topic} 的情况不同，会怎样？",
        }
        return {
            "content": templates.get(curiosity_type, f"关于 {topic}，有什么有趣的问题？"),
            "priority": QuestionPriority.HIGH.value if intensity > 0.7 else QuestionPriority.NORMAL.value,
            "curiosity_type": curiosity_type.value,
            "topic": topic,
            "intensity": intensity,
        }

    def get_exploration_stats(self) -> Dict[str, Any]:
        """获取探索统计信息"""
        explorations = list(self._explorations.values())
        if not explorations:
            return {
                "total_explorations": 0,
                "completed_explorations": 0,
                "average_knowledge_gained": 0,
                "curiosity_type_distribution": {},
            }
        completed = [e for e in explorations if e.status == "completed"]
        total_knowledge = sum(e.knowledge_gained for e in completed)
        type_dist: Dict[str, int] = {}
        for exploration in explorations:
            ct = exploration.curiosity_type.value
            type_dist[ct] = type_dist.get(ct, 0) + 1
        return {
            "total_explorations": len(explorations),
            "completed_explorations": len(completed),
            "average_knowledge_gained": total_knowledge / len(completed) if completed else 0,
            "curiosity_type_distribution": type_dist,
        }


class QuestionQueueManager:
    """
    问题队列管理器

    管理 Agent 主动提问的问题队列，支持冷却时间、状态跟踪和持久化。
    """

    def __init__(
        self,
        memory_manager=None,
        default_cooldown: float = 300.0,
        max_questions: int = 100,
    ):
        """
        初始化问题队列管理器

        Args:
            memory_manager: 记忆管理器实例，用于持久化问题
            default_cooldown: 默认冷却时间（秒）
            max_questions: 队列最大问题数
        """
        self._memory_manager = memory_manager
        self._default_cooldown = default_cooldown
        self._max_questions = max_questions
        self._lock = threading.RLock()

        # 内存中的问题队列
        self._questions: Dict[str, QuestionEntry] = {}

        # P0-B 根因修复: question_id -> 记忆 id 映射。此前每次状态流转都 remember
        # 一条新记忆 → 同一问题在库中随状态变化不断复制。
        self._memory_ids: Dict[str, str] = {}

        # 状态索引
        self._status_index: Dict[QuestionStatus, List[str]] = {status: [] for status in QuestionStatus}

        # D4 并入：好奇心驱动器（探索台账/强度模型），生成的问题走本队列持久化通道
        self.curiosity_drive = CuriosityDrive()
        self._base_cooldown = default_cooldown

        # 2026-09-07 根因修复（audit SUB-P2-15）：on_initialize 全仓无人调用，
        # 持久化问题跨重启静默丢失且 _memory_ids 为空导致每次状态流转复制新记忆；
        # 构造时直接加载（对齐 GrowthLogManager 的根因修复）
        self.on_initialize()

    def on_initialize(self) -> None:
        """初始化回调：从记忆系统加载问题"""
        self._load_questions_from_memory()
        logger.info("QuestionQueueManager initialized with %s questions", len(self._questions))

    def on_start(self) -> None:
        """启动回调"""
        logger.info("QuestionQueueManager started")

    def on_stop(self) -> None:
        """停止回调：保存所有问题到记忆"""
        self._save_questions_to_memory()
        logger.info("QuestionQueueManager stopped")

    def generate_question(
        self,
        content: str,
        priority: QuestionPriority = QuestionPriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> QuestionEntry:
        """
        生成新问题并添加到队列

        Args:
            content: 问题内容
            priority: 问题优先级
            metadata: 额外元数据

        Returns:
            新创建的 QuestionEntry
        """
        with self._lock:
            normalized = " ".join((content or "").split()).lower()
            if normalized:
                for existing in self._questions.values():
                    if existing.status is not QuestionStatus.ANSWERED:
                        continue
                    if (" ".join(existing.content.split()).lower() == normalized
                            and all(existing.metadata.get(k) == (metadata or {}).get(k)
                                    for k in ("agent_id", "user_id"))):
                        logger.info("Duplicate of answered question %s... not regenerated", existing.id[:8])
                        return existing

            # 检查队列容量
            if len(self._questions) >= self._max_questions:
                self._archive_oldest_pending_unlocked()

            question_id = str(uuid.uuid4())
            entry = QuestionEntry(
                id=question_id,
                content=content,
                status=QuestionStatus.PENDING,
                priority=priority,
                metadata=metadata or {},
            )

            self._questions[question_id] = entry
            self._status_index[QuestionStatus.PENDING].append(question_id)

            # 持久化
            self._save_single_question(entry)
            self._on_question_generate(entry)

            logger.info("Generated question: %s... (%s)", question_id[:8], priority.value)
            return entry

    def get_pending_questions(self) -> List[QuestionEntry]:
        """
        获取所有待处理的问题（冷却已过期）

        Returns:
            可提问的 QuestionEntry 列表
        """
        now = time.time()
        with self._lock:
            pending = []
            for qid in self._status_index.get(QuestionStatus.PENDING, []):
                entry = self._questions.get(qid)
                if entry is None:
                    continue
                # 检查冷却时间
                if entry.cooldown_until and now < entry.cooldown_until:
                    continue
                pending.append(entry)

            # 也包含冷却结束的 COOLDOWN 状态问题
            for qid in list(self._status_index.get(QuestionStatus.COOLDOWN, [])):
                entry = self._questions.get(qid)
                if entry is None:
                    continue
                if entry.cooldown_until and now >= entry.cooldown_until:
                    # 冷却结束，移回 PENDING
                    entry.status = QuestionStatus.PENDING
                    entry.cooldown_until = None
                    self._status_index[QuestionStatus.COOLDOWN].remove(qid)
                    self._status_index[QuestionStatus.PENDING].append(qid)
                    pending.append(entry)

            # 按优先级排序
            pending.sort(key=lambda q: _PRIORITY_ORDER.get(q.priority, 1))
            return pending

    def get_next_question(self) -> Optional[QuestionEntry]:
        """
        获取下一个最适合提问的问题

        Returns:
            最高优先级的待处理问题，没有则返回 None
        """
        pending = self.get_pending_questions()
        return pending[0] if pending else None

    def mark_asked(self, question_id: str) -> bool:
        """
        标记问题已被提问

        Args:
            question_id: 问题 ID

        Returns:
            是否成功标记
        """
        with self._lock:
            entry = self._questions.get(question_id)
            if entry is None:
                return False

            old_status = entry.status
            entry.status = QuestionStatus.ASKED
            entry.asked_at = time.time()

            # 计算冷却时间
            entry.cooldown_until = self._calculate_next_cooldown(entry)

            # 更新状态索引
            if question_id in self._status_index.get(old_status, []):
                self._status_index[old_status].remove(question_id)
            self._status_index[QuestionStatus.ASKED].append(question_id)

            self._save_single_question(entry)
            self._on_question_ask(entry)
            logger.info("Question %s... marked as asked", question_id[:8])
            return True

    def mark_answered(
        self,
        question_id: str,
        answer: str = "",
        lesson: Optional[Dict[str, Any]] = None,
        require_durable: bool = False,
        allow_correction: bool = True,
    ) -> bool:
        """
        标记问题已被回答

        Args:
            question_id: 问题 ID
            answer: 用户给出的答案（存入 metadata）
            lesson: 回答沉淀的教学内容（metadata["lesson"]，含 answerer_id/
                publication 等），与答案同一条记录持久化
            require_durable: True 时无 memory_manager 直接失败（HTTP 路径必须
                持久；standalone 内存队列不受影响）

        Returns:
            是否成功标记
        """
        with self._lock:
            entry = self._questions.get(question_id)
            if entry is None:
                return False

            if not answer.strip() or (require_durable and self._memory_manager is None):
                return False
            unchanged = entry.status is QuestionStatus.ANSWERED and entry.metadata.get("answer") == answer
            if unchanged and (lesson is None or entry.metadata.get("lesson") == lesson):
                return True
            if entry.status is QuestionStatus.ANSWERED and not allow_correction:
                return False

            # Persist a candidate before mutating the live record or its indexes.
            candidate = QuestionEntry.from_dict(json.loads(json.dumps(entry.to_dict())))
            candidate.status = QuestionStatus.ANSWERED
            candidate.answered_at = time.time()
            candidate.metadata["answer"] = answer
            candidate.metadata.pop("lesson", None)
            if lesson is not None:
                candidate.metadata["lesson"] = lesson
            if not self._save_single_question(candidate):
                return False
            self._status_index[entry.status].remove(question_id)
            entry.status = candidate.status
            entry.answered_at = candidate.answered_at
            entry.metadata = candidate.metadata
            self._status_index[QuestionStatus.ANSWERED].append(question_id)
            return True

    @staticmethod
    def visible_to(entry: QuestionEntry, agent_id: str, user_id: str) -> bool:
        metadata = entry.metadata
        lesson = metadata.get("lesson") or {}
        return (metadata.get("agent_id", agent_id) == agent_id
                and metadata.get("user_id", user_id) == user_id
                and lesson.get("agent_id", agent_id) == agent_id
                and lesson.get("answerer_id", user_id) == user_id)

    def retrieve_lessons(self, kb, query: str, agent_id: str, user_id: str) -> List[Dict[str, Any]]:
        """Replay the durable outbox before reading; never serve stale corrections."""
        if not user_id or self._memory_manager is None:
            return []
        with self._lock:
            current = {}
            for entry in self._questions.values():
                lesson = entry.metadata.get("lesson")
                if entry.status is QuestionStatus.ANSWERED and lesson and self.visible_to(entry, agent_id, user_id):
                    kb.publish_growth_lesson(lesson)
                    current[entry.id] = lesson["revision"]
            return [lesson for lesson in kb.find_growth_lessons(query, agent_id, user_id)
                    if current.get(lesson["question_id"]) == lesson["revision"]]

    def archive_question(self, question_id: str) -> bool:
        """
        归档问题

        Args:
            question_id: 问题 ID

        Returns:
            是否成功归档
        """
        with self._lock:
            entry = self._questions.get(question_id)
            if entry is None:
                return False

            old_status = entry.status
            entry.status = QuestionStatus.ARCHIVED

            if question_id in self._status_index.get(old_status, []):
                self._status_index[old_status].remove(question_id)
            self._status_index[QuestionStatus.ARCHIVED].append(question_id)

            self._on_question_archive(entry)
            logger.info("Question %s... archived", question_id[:8])
            return True

    def update_question(self, question_id: str, **kwargs: Any) -> bool:
        """
        更新问题属性

        Args:
            question_id: 问题 ID
            **kwargs: 要更新的属性（content, priority, metadata）

        Returns:
            是否成功更新
        """
        with self._lock:
            entry = self._questions.get(question_id)
            if entry is None:
                return False

            if "content" in kwargs:
                entry.content = kwargs["content"]
            if "priority" in kwargs:
                entry.priority = kwargs["priority"]
            if "metadata" in kwargs:
                entry.metadata.update(kwargs["metadata"])

            self._save_single_question(entry)
            return True

    def get_question(self, question_id: str) -> Optional[QuestionEntry]:
        """根据 ID 获取单个问题"""
        return self._questions.get(question_id)

    def get_questions_by_status(self, status: QuestionStatus) -> List[QuestionEntry]:
        """按状态过滤问题列表（线程安全版本）"""
        with self._lock:
            return self.get_questions_by_status_unlocked(status)

    def clear_cooldown(self, question_id: str) -> bool:
        """清除问题的冷却状态"""
        with self._lock:
            entry = self._questions.get(question_id)
            if entry is None:
                return False

            if entry.status == QuestionStatus.COOLDOWN:
                entry.status = QuestionStatus.PENDING
                entry.cooldown_until = None
                if question_id in self._status_index[QuestionStatus.COOLDOWN]:
                    self._status_index[QuestionStatus.COOLDOWN].remove(question_id)
                self._status_index[QuestionStatus.PENDING].append(question_id)
            else:
                entry.cooldown_until = None

            return True

    def get_queue_stats(self) -> Dict[str, Any]:
        """获取队列统计信息"""
        with self._lock:
            return {
                "total": len(self._questions),
                "by_status": {status.value: len(self._status_index.get(status, [])) for status in QuestionStatus},
                "by_priority": {
                    p.value: sum(1 for q in self._questions.values() if q.priority == p) for p in QuestionPriority
                },
                "curiosity": self.curiosity_drive.get_exploration_stats(),
            }

    # ============================================================
    # 好奇心驱动提问（D4 自 proactive_question.py 取长补短并入）
    # ============================================================

    def generate_curiosity_question(self, context: Dict[str, Any]) -> Optional[QuestionEntry]:
        """按好奇心强度生成问题并走现役持久化队列（强度 <0.3 返回 None）。

        与旧版差别：生成结果进 generate_question 单源通道——去重、容量治理、
        记忆持久化全部继承现役队列语义；好奇心类型/主题/强度存 metadata。
        """
        draft = self.curiosity_drive.generate_curiosity_question(context)
        if draft is None:
            return None
        return self.generate_question(
            content=draft["content"],
            priority=QuestionPriority(draft["priority"]),
            metadata={
                "curiosity_type": draft["curiosity_type"],
                "topic": draft["topic"],
                "intensity": draft["intensity"],
            },
        )

    def evaluate_question_quality(
        self,
        content: str,
        priority: QuestionPriority = QuestionPriority.NORMAL,
        curiosity_type: Optional[CuriosityType] = None,
    ) -> float:
        """评估问题质量（0.0-1.0）：基线 0.4 + 优先级加分 + 好奇心类型加分。

        自 proactive_question.py 取长补短并入（做实为按传入特征计算，非恒 0.5）。
        """
        score = 0.4
        score += {QuestionPriority.HIGH: 0.2, QuestionPriority.NORMAL: 0.1, QuestionPriority.LOW: 0.0}.get(
            priority, 0.0
        )
        score += {
            CuriosityType.KNOWLEDGE_GAP: 0.2,
            CuriosityType.NOVELTY_SEEKING: 0.15,
            CuriosityType.PATTERN_DISCOVERY: 0.2,
            CuriosityType.CAUSAL_REASONING: 0.25,
            CuriosityType.COUNTERFACTUAL: 0.2,
        }.get(curiosity_type, 0.0)
        _ = content  # 保留入参：未来可按内容特征（具体性/可答性）加细
        return max(0.0, min(1.0, score))

    def on_user_busy(self) -> None:
        """用户忙碌：冷却翻倍（不低于 600s 口径），降低打扰频率"""
        self._default_cooldown = max(self._default_cooldown, self._base_cooldown * 2)

    def on_user_idle(self) -> None:
        """用户空闲：恢复基准冷却"""
        self._default_cooldown = self._base_cooldown

    def _load_questions_from_memory(self) -> None:
        """从记忆系统加载问题

        根因修复: 原实现调用 memory_manager.search(query=..., category=...)，
        该方法不存在（真实 API 是 get_memories(category=...)）→ 每次加载都抛
        异常被吞，问题队列跨重启永不恢复。
        """
        if self._memory_manager is None:
            return

        try:
            stored = self._memory_manager.get_memories(category="system", limit=self._max_questions)
            for mem in stored:
                try:
                    content = mem.get("content") if isinstance(mem, dict) else getattr(mem, "content", None)
                    data = json.loads(content) if isinstance(content, str) else content
                    if isinstance(data, dict) and "id" in data:
                        entry = QuestionEntry.from_dict(data)
                        if entry.id not in self._questions:
                            self._questions[entry.id] = entry
                            self._status_index[entry.status].append(entry.id)
                            mem_id = mem.get("id") if isinstance(mem, dict) else getattr(mem, "id", None)
                            if mem_id:
                                self._memory_ids[entry.id] = mem_id
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
        except Exception as e:
            logger.warning("Failed to load questions from memory: %s", e)

    def _save_questions_to_memory(self) -> None:
        """将所有问题保存到记忆系统"""
        if self._memory_manager is None:
            return

        try:
            for entry in self._questions.values():
                self._save_single_question(entry)
        except Exception as e:
            logger.warning("Failed to save questions to memory: %s", e)

    def _save_single_question(self, entry: QuestionEntry) -> bool:
        """保存单个问题到记忆

        P0-B 根因修复: 已有对应记忆时用 update_memory 原位更新 content（content
        即问题的完整 JSON），不再重复 remember。
        2026-09-17: 如实向调用方返回落盘成败——此前异常吞成 debug 日志恒 True，
        mark_answered 拿不到失败信号，用户答案可能静默丢失还报成功。
        """
        if self._memory_manager is None:
            return True

        try:
            content_json = json.dumps(entry.to_dict(), ensure_ascii=False)
            memory_id = self._memory_ids.get(entry.id)
            if memory_id:
                if self._memory_manager.update_memory(memory_id, content=content_json):
                    return True
                # 记忆已被删除等场景 → 落空后重建
                self._memory_ids.pop(entry.id, None)

            new_id = self._memory_manager.remember(
                content=content_json,
                category="system",
                importance=30.0,
                metadata={"type": "question_queue", "question_id": entry.id},
            )
            if not new_id:
                return False
            self._memory_ids[entry.id] = new_id
            return True
        except Exception as e:
            logger.warning("Failed to save question %s...: %s", entry.id[:8], e)
            return False

    def _archive_oldest_pending(self) -> None:
        """归档最旧的待处理问题（带锁）"""
        with self._lock:
            self._archive_oldest_pending_unlocked()

    def _archive_oldest_pending_unlocked(self) -> None:
        """归档最旧的待处理问题（无锁）"""
        pending_ids = self._status_index.get(QuestionStatus.PENDING, [])
        if not pending_ids:
            return

        # 找到最旧的
        oldest_id = None
        oldest_time = float("inf")
        for qid in pending_ids:
            entry = self._questions.get(qid)
            if entry and entry.created_at < oldest_time:
                oldest_time = entry.created_at
                oldest_id = qid

        if oldest_id:
            entry = self._questions[oldest_id]
            entry.status = QuestionStatus.ARCHIVED
            pending_ids.remove(oldest_id)
            self._status_index[QuestionStatus.ARCHIVED].append(oldest_id)
            logger.info("Auto-archived oldest question: %s...", oldest_id[:8])

    def get_questions_by_status_unlocked(self, status: QuestionStatus) -> List[QuestionEntry]:
        """按状态获取问题（无锁版本）"""
        result = []
        for qid in self._status_index.get(status, []):
            entry = self._questions.get(qid)
            if entry:
                result.append(entry)
        return result

    def _calculate_next_cooldown(self, entry: QuestionEntry) -> float:
        """计算下一次冷却时间"""
        # 根据优先级调整冷却时间
        multiplier = {
            QuestionPriority.HIGH: 0.5,
            QuestionPriority.NORMAL: 1.0,
            QuestionPriority.LOW: 2.0,
        }
        return time.time() + self._default_cooldown * multiplier.get(entry.priority, 1.0)

    def _on_question_generate(self, entry: QuestionEntry) -> None:
        """问题生成事件回调"""
        logger.debug("Question generated: %s... - %s...", entry.id[:8], entry.content[:50])

    def _on_question_ask(self, entry: QuestionEntry) -> None:
        """问题提问事件回调"""
        logger.debug("Question asked: %s...", entry.id[:8])

    def _on_question_archive(self, entry: QuestionEntry) -> None:
        """问题归档事件回调"""
        logger.debug("Question archived: %s...", entry.id[:8])
