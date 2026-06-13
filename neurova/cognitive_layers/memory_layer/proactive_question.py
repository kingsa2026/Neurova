from __future__ import annotations

"""
主动提问与好奇心驱动系统

功能:
- 主动提问时机判断
- 好奇心驱动机制
- 问题质量评估
- 探索历史追踪

依赖:
- BaseModule: 统一模块基类
"""

import datetime
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ────── Enums ──────


class QuestionPriority(Enum):
    """问题优先级"""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class QuestionStatus(Enum):
    """问题状态"""

    PENDING = "pending"  # 待提问
    ASKED = "asked"  # 已提问
    ANSWERED = "answered"  # 已回答
    DISMISSED = "dismissed"  # 已忽略
    EXPIRED = "expired"  # 已过期


class CuriosityType(Enum):
    """好奇心类型"""

    KNOWLEDGE_GAP = "knowledge_gap"  # 知识缺口
    NOVELTY_SEEKING = "novelty_seeking"  # 新奇探索
    PATTERN_DISCOVERY = "pattern_discovery"  # 模式发现
    CAUSAL_REASONING = "causal_reasoning"  # 因果推理
    COUNTERFACTUAL = "counterfactual"  # 反事实思考


# ────── Data Models ──────


@dataclass
class Question:
    """问题模型"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    priority: QuestionPriority = QuestionPriority.NORMAL
    status: QuestionStatus = QuestionStatus.PENDING
    curiosity_type: Optional[CuriosityType] = None
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    asked_at: Optional[datetime.datetime] = None
    answered_at: Optional[datetime.datetime] = None
    answer: Optional[str] = None
    usefulness_score: float = 0.0
    expires_at: Optional[datetime.datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "priority": self.priority.value,
            "status": self.status.value,
            "curiosity_type": self.curiosity_type.value if self.curiosity_type else None,
            "context": self.context,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "asked_at": self.asked_at.isoformat() if self.asked_at else None,
            "answered_at": self.answered_at.isoformat() if self.answered_at else None,
            "answer": self.answer,
            "usefulness_score": self.usefulness_score,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Question":
        def _parse_dt(val: Any) -> Optional[datetime.datetime]:
            if isinstance(val, datetime.datetime):
                return val
            if isinstance(val, str):
                try:
                    return datetime.datetime.fromisoformat(val)
                except ValueError:
                    return None
            return None

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            content=data.get("content", ""),
            priority=QuestionPriority(data.get("priority", "normal")),
            status=QuestionStatus(data.get("status", "pending")),
            curiosity_type=CuriosityType(data["curiosity_type"]) if data.get("curiosity_type") else None,
            context=data.get("context", {}),
            metadata=data.get("metadata", {}),
            created_at=_parse_dt(data.get("created_at")) or datetime.datetime.now(datetime.timezone.utc),
            asked_at=_parse_dt(data.get("asked_at")),
            answered_at=_parse_dt(data.get("answered_at")),
            answer=data.get("answer"),
            usefulness_score=data.get("usefulness_score", 0.0),
            expires_at=_parse_dt(data.get("expires_at")),
        )


@dataclass
class ExplorationRecord:
    """探索记录"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    question_id: str = ""
    topic: str = ""
    curiosity_type: CuriosityType = CuriosityType.KNOWLEDGE_GAP
    start_time: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    end_time: Optional[datetime.datetime] = None
    status: str = "in_progress"  # in_progress, completed, abandoned
    findings: List[str] = field(default_factory=list)
    knowledge_gained: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "question_id": self.question_id,
            "topic": self.topic,
            "curiosity_type": self.curiosity_type.value,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status,
            "findings": self.findings,
            "knowledge_gained": self.knowledge_gained,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExplorationRecord":
        def _parse_dt(val: Any) -> Optional[datetime.datetime]:
            if isinstance(val, datetime.datetime):
                return val
            if isinstance(val, str):
                try:
                    return datetime.datetime.fromisoformat(val)
                except ValueError:
                    return None
            return None

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            question_id=data.get("question_id", ""),
            topic=data.get("topic", ""),
            curiosity_type=CuriosityType(data.get("curiosity_type", "knowledge_gap")),
            start_time=_parse_dt(data.get("start_time")) or datetime.datetime.now(datetime.timezone.utc),
            end_time=_parse_dt(data.get("end_time")),
            status=data.get("status", "in_progress"),
            findings=data.get("findings", []),
            knowledge_gained=data.get("knowledge_gained", 0.0),
            metadata=data.get("metadata", {}),
        )


# ────── Question Queue Manager ──────


class QuestionQueueManager:
    """
    问题队列管理器

    管理待提问的问题队列。
    """

    def __init__(self, max_questions: int = 100):
        """
        初始化问题队列管理器

        Args:
            max_questions: 最大问题数量
        """
        self.max_questions = max_questions
        self._questions: Dict[str, Question] = {}
        self._status_index: Dict[QuestionStatus, List[str]] = {s: [] for s in QuestionStatus}

        logger.info("QuestionQueueManager 初始化完成")

    def add_question(self, question: Question) -> Question:
        """
        添加问题

        Args:
            question: 问题

        Returns:
            添加的问题
        """
        # 检查是否超过最大数量
        if len(self._questions) >= self.max_questions:
            # 移除最旧的已回答或已忽略的问题
            self._cleanup_old_questions()

        self._questions[question.id] = question
        self._status_index[question.status].append(question.id)

        logger.debug("添加问题: %s", question.id)
        return question

    def get_pending_questions(self, limit: int = 10) -> List[Question]:
        """
        获取待提问的问题

        Args:
            limit: 返回数量限制

        Returns:
            待提问的问题列表
        """
        pending_ids = self._status_index.get(QuestionStatus.PENDING, [])
        questions = [self._questions[qid] for qid in pending_ids if qid in self._questions]

        # 按优先级排序
        priority_order = {
            QuestionPriority.URGENT: 0,
            QuestionPriority.HIGH: 1,
            QuestionPriority.NORMAL: 2,
            QuestionPriority.LOW: 3,
        }
        questions.sort(key=lambda q: priority_order.get(q.priority, 2))

        return questions[:limit]

    def mark_asked(self, question_id: str) -> Optional[Question]:
        """
        标记问题为已提问

        Args:
            question_id: 问题ID

        Returns:
            更新后的问题
        """
        question = self._questions.get(question_id)
        if not question:
            return None

        # 更新状态索引
        self._status_index[question.status].remove(question_id)
        question.status = QuestionStatus.ASKED
        question.asked_at = datetime.datetime.now(datetime.timezone.utc)
        self._status_index[question.status].append(question_id)

        logger.debug("标记问题为已提问: %s", question_id)
        return question

    def mark_answered(self, question_id: str, answer: str) -> Optional[Question]:
        """
        标记问题为已回答

        Args:
            question_id: 问题ID
            answer: 回答

        Returns:
            更新后的问题
        """
        question = self._questions.get(question_id)
        if not question:
            return None

        # 更新状态索引
        self._status_index[question.status].remove(question_id)
        question.status = QuestionStatus.ANSWERED
        question.answered_at = datetime.datetime.now(datetime.timezone.utc)
        question.answer = answer
        self._status_index[question.status].append(question_id)

        logger.debug("标记问题为已回答: %s", question_id)
        return question

    def mark_dismissed(self, question_id: str) -> Optional[Question]:
        """
        标记问题为已忽略

        Args:
            question_id: 问题ID

        Returns:
            更新后的问题
        """
        question = self._questions.get(question_id)
        if not question:
            return None

        # 更新状态索引
        self._status_index[question.status].remove(question_id)
        question.status = QuestionStatus.DISMISSED
        self._status_index[question.status].append(question_id)

        logger.debug("标记问题为已忽略: %s", question_id)
        return question

    def remove_question(self, question_id: str) -> bool:
        """
        移除问题

        Args:
            question_id: 问题ID

        Returns:
            是否移除成功
        """
        question = self._questions.get(question_id)
        if not question:
            return False

        # 从索引中移除
        self._status_index[question.status].remove(question_id)
        del self._questions[question_id]

        logger.debug("移除问题: %s", question_id)
        return True

    def get_question(self, question_id: str) -> Optional[Question]:
        """
        获取问题

        Args:
            question_id: 问题ID

        Returns:
            问题
        """
        return self._questions.get(question_id)

    def clear_expired(self) -> int:
        """
        清理过期问题

        Returns:
            清理的问题数量
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        expired_ids = []

        for question_id, question in self._questions.items():
            if question.expires_at and question.expires_at <= now:
                expired_ids.append(question_id)

        for question_id in expired_ids:
            question = self._questions[question_id]
            self._status_index[question.status].remove(question_id)
            question.status = QuestionStatus.EXPIRED
            self._status_index[question.status].append(question_id)

        if expired_ids:
            logger.debug("清理过期问题: %s 个", len(expired_ids))

        return len(expired_ids)

    def _cleanup_old_questions(self) -> None:
        """清理旧的问题"""
        # 移除最旧的已回答或已忽略的问题
        to_remove = []

        for status in [QuestionStatus.ANSWERED, QuestionStatus.DISMISSED, QuestionStatus.EXPIRED]:
            question_ids = self._status_index.get(status, [])
            if question_ids:
                # 按创建时间排序，移除最旧的
                questions = [(qid, self._questions[qid]) for qid in question_ids if qid in self._questions]
                questions.sort(key=lambda x: x[1].created_at)

                # 移除最旧的
                if questions:
                    to_remove.append(questions[0][0])

        for question_id in to_remove:
            self.remove_question(question_id)


# ────── Curiosity Drive ──────


class CuriosityDrive:
    """
    好奇心驱动器

    计算好奇心强度，生成好奇心驱动的问题。
    """

    def __init__(self):
        """初始化好奇心驱动器"""
        self._explorations: Dict[str, ExplorationRecord] = {}
        self._knowledge_gaps: Dict[str, float] = {}

        logger.info("CuriosityDrive 初始化完成")

    def calculate_intensity(self, context: Dict[str, Any]) -> float:
        """
        计算好奇心强度

        Args:
            context: 上下文信息

        Returns:
            好奇心强度 (0.0 - 1.0)
        """
        # 基础强度
        base_intensity = 0.5

        # 根据上下文调整
        adjustments = []

        # 1. 知识缺口
        knowledge_gap = self._assess_knowledge_gap(context)
        adjustments.append(knowledge_gap * 0.3)

        # 2. 上下文新颖性
        novelty = self._assess_context_novelty(context)
        adjustments.append(novelty * 0.2)

        # 3. 最近探索频率（探索越多，好奇心越低）
        recent_explorations = self._get_recent_explorations(hours=24)
        exploration_factor = max(0, 1.0 - len(recent_explorations) * 0.1)
        adjustments.append(exploration_factor * 0.2)

        # 计算最终强度
        intensity = base_intensity + sum(adjustments)

        # 限制在 0.0 - 1.0 范围
        return max(0.0, min(1.0, intensity))

    def _get_recent_explorations(self, hours: int = 24) -> List[ExplorationRecord]:
        """获取最近的探索记录"""
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)

        recent = []
        for exploration in self._explorations.values():
            if exploration.start_time >= cutoff:
                recent.append(exploration)

        return recent

    def _assess_context_novelty(self, context: Dict[str, Any]) -> float:
        """评估上下文新颖性"""
        # 简化实现：检查是否有新的关键词
        # 实际实现应该使用向量相似度或关键词匹配
        return 0.5

    def _assess_knowledge_gap(self, context: Dict[str, Any]) -> float:
        """评估知识缺口"""
        # 简化实现：检查已知知识缺口
        if not self._knowledge_gaps:
            return 0.5

        # 返回平均知识缺口
        return sum(self._knowledge_gaps.values()) / len(self._knowledge_gaps)

    def _identify_knowledge_gaps(self, context: Dict[str, Any]) -> List[str]:
        """识别知识缺口"""
        # 简化实现
        return []

    def record_exploration(self, question_id: str, topic: str, curiosity_type: CuriosityType) -> ExplorationRecord:
        """
        记录探索

        Args:
            question_id: 问题ID
            topic: 主题
            curiosity_type: 好奇心类型

        Returns:
            探索记录
        """
        exploration = ExplorationRecord(
            question_id=question_id,
            topic=topic,
            curiosity_type=curiosity_type,
        )

        self._explorations[exploration.id] = exploration

        logger.debug("记录探索: %s", exploration.id)
        return exploration

    def complete_exploration(
        self, exploration_id: str, findings: List[str], knowledge_gained: float = 0.0
    ) -> Optional[ExplorationRecord]:
        """
        完成探索

        Args:
            exploration_id: 探索ID
            findings: 发现
            knowledge_gained: 获得的知识量

        Returns:
            更新后的探索记录
        """
        exploration = self._explorations.get(exploration_id)
        if not exploration:
            return None

        exploration.end_time = datetime.datetime.now(datetime.timezone.utc)
        exploration.status = "completed"
        exploration.findings = findings
        exploration.knowledge_gained = knowledge_gained

        # 更新知识缺口
        if exploration.topic in self._knowledge_gaps:
            self._knowledge_gaps[exploration.topic] = max(0, self._knowledge_gaps[exploration.topic] - knowledge_gained)

        logger.debug("完成探索: %s", exploration_id)
        return exploration

    def generate_curiosity_question(self, context: Dict[str, Any]) -> Optional[Question]:
        """
        生成好奇心驱动的问题

        Args:
            context: 上下文信息

        Returns:
            生成的问题
        """
        # 计算好奇心强度
        intensity = self.calculate_intensity(context)

        # 如果好奇心强度太低，不生成问题
        if intensity < 0.3:
            return None

        # 识别知识缺口
        knowledge_gaps = self._identify_knowledge_gaps(context)

        # 选择好奇心类型
        if knowledge_gaps:
            curiosity_type = CuriosityType.KNOWLEDGE_GAP
            topic = knowledge_gaps[0]
        else:
            curiosity_type = CuriosityType.NOVELTY_SEEKING
            topic = context.get("current_topic", "未知主题")

        # 生成问题内容
        question_templates = {
            CuriosityType.KNOWLEDGE_GAP: f"关于 {topic}，我还不了解什么？",
            CuriosityType.NOVELTY_SEEKING: f"关于 {topic}，有什么新发现吗？",
            CuriosityType.PATTERN_DISCOVERY: f"在 {topic} 中，有什么模式可以发现？",
            CuriosityType.CAUSAL_REASONING: f"在 {topic} 中，因果关系是什么？",
            CuriosityType.COUNTERFACTUAL: f"如果 {topic} 的情况不同，会怎样？",
        }

        content = question_templates.get(curiosity_type, f"关于 {topic}，有什么有趣的问题？")

        # 创建问题
        question = Question(
            content=content,
            priority=QuestionPriority.HIGH if intensity > 0.7 else QuestionPriority.NORMAL,
            curiosity_type=curiosity_type,
            context=context,
        )

        logger.debug("生成好奇心问题: %s", question.id)
        return question

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

        # 好奇心类型分布
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


# ────── Proactive Question Manager ──────


class ProactiveQuestionManager:
    """
    主动提问管理器

    管理主动提问的时机、质量评估和探索历史。
    """

    def __init__(self, agent_id: str):
        """
        初始化主动提问管理器

        Args:
            agent_id: Agent ID
        """
        self.agent_id = agent_id

        # 子组件
        self.question_queue = QuestionQueueManager()
        self.curiosity_drive = CuriosityDrive()

        # 状态
        self._session_active = False
        self._last_question_time: Optional[datetime.datetime] = None
        self._question_cooldown = 300  # 5分钟冷却时间

        # 统计
        self._stats = {
            "questions_generated": 0,
            "questions_asked": 0,
            "questions_answered": 0,
            "questions_dismissed": 0,
            "explorations_started": 0,
            "explorations_completed": 0,
        }

        logger.info("ProactiveQuestionManager 初始化: %s", agent_id)

    def on_initialize(self) -> None:
        """初始化回调"""
        logger.debug("ProactiveQuestionManager 初始化完成: %s", self.agent_id)

    def on_start(self) -> None:
        """启动回调"""
        self._session_active = True
        logger.debug("ProactiveQuestionManager 启动: %s", self.agent_id)

    def on_stop(self) -> None:
        """停止回调"""
        self._session_active = False
        logger.debug("ProactiveQuestionManager 停止: %s", self.agent_id)

    def should_ask_question(self, context: Dict[str, Any]) -> bool:
        """
        判断是否应该提问

        Args:
            context: 上下文信息

        Returns:
            是否应该提问
        """
        if not self._session_active:
            return False

        # 检查冷却时间
        if self._last_question_time:
            elapsed = (datetime.datetime.now(datetime.timezone.utc) - self._last_question_time).total_seconds()
            if elapsed < self._question_cooldown:
                return False

        # 检查是否有待提问的问题
        pending_questions = self.question_queue.get_pending_questions(limit=1)
        if not pending_questions:
            return False

        # 计算好奇心强度
        intensity = self.curiosity_drive.calculate_intensity(context)

        # 根据强度决定是否提问
        return intensity > 0.5

    def evaluate_question_quality(self, question: Question) -> float:
        """
        评估问题质量

        Args:
            question: 问题

        Returns:
            质量分数 (0.0 - 1.0)
        """
        # 简化实现
        quality_score = 0.5

        # 根据优先级调整
        priority_scores = {
            QuestionPriority.URGENT: 0.3,
            QuestionPriority.HIGH: 0.2,
            QuestionPriority.NORMAL: 0.1,
            QuestionPriority.LOW: 0.0,
        }
        quality_score += priority_scores.get(question.priority, 0)

        # 根据好奇心类型调整
        if question.curiosity_type:
            type_scores = {
                CuriosityType.KNOWLEDGE_GAP: 0.2,
                CuriosityType.NOVELTY_SEEKING: 0.15,
                CuriosityType.PATTERN_DISCOVERY: 0.2,
                CuriosityType.CAUSAL_REASONING: 0.25,
                CuriosityType.COUNTERFACTUAL: 0.2,
            }
            quality_score += type_scores.get(question.curiosity_type, 0)

        return min(1.0, quality_score)

    def get_next_question(self, context: Dict[str, Any]) -> Optional[Question]:
        """
        获取下一个问题

        Args:
            context: 上下文信息

        Returns:
            下一个问题
        """
        # 检查是否应该提问
        if not self.should_ask_question(context):
            return None

        # 获取待提问的问题
        pending_questions = self.question_queue.get_pending_questions(limit=1)

        if pending_questions:
            return pending_questions[0]

        return None

    def create_question(
        self,
        content: str,
        priority: QuestionPriority = QuestionPriority.NORMAL,
        curiosity_type: Optional[CuriosityType] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Question:
        """
        创建问题

        Args:
            content: 问题内容
            priority: 优先级
            curiosity_type: 好奇心类型
            context: 上下文

        Returns:
            创建的问题
        """
        question = Question(
            content=content,
            priority=priority,
            curiosity_type=curiosity_type,
            context=context or {},
        )

        self.question_queue.add_question(question)
        self._stats["questions_generated"] += 1

        logger.debug("创建问题: %s", question.id)
        return question

    def generate_curiosity_questions(self, context: Dict[str, Any], count: int = 3) -> List[Question]:
        """
        生成好奇心驱动的问题

        Args:
            context: 上下文信息
            count: 生成数量

        Returns:
            生成的问题列表
        """
        questions = []

        for _ in range(count):
            question = self.curiosity_drive.generate_curiosity_question(context)
            if question:
                self.question_queue.add_question(question)
                questions.append(question)
                self._stats["questions_generated"] += 1

        return questions

    def mark_question_asked(self, question_id: str) -> Optional[Question]:
        """
        标记问题为已提问

        Args:
            question_id: 问题ID

        Returns:
            更新后的问题
        """
        question = self.question_queue.mark_asked(question_id)
        if question:
            self._last_question_time = datetime.datetime.now(datetime.timezone.utc)
            self._stats["questions_asked"] += 1

        return question

    def mark_question_answered(self, question_id: str, answer: str) -> Optional[Question]:
        """
        标记问题为已回答

        Args:
            question_id: 问题ID
            answer: 回答

        Returns:
            更新后的问题
        """
        question = self.question_queue.mark_answered(question_id, answer)
        if question:
            self._stats["questions_answered"] += 1
            self._update_question_usefulness(question)

        return question

    def mark_question_dismissed(self, question_id: str) -> Optional[Question]:
        """
        标记问题为已忽略

        Args:
            question_id: 问题ID

        Returns:
            更新后的问题
        """
        question = self.question_queue.mark_dismissed(question_id)
        if question:
            self._stats["questions_dismissed"] += 1

        return question

    def _update_question_usefulness(self, question: Question) -> None:
        """更新问题有用性分数"""
        # 简化实现
        if question.answer:
            # 有回答的问题有用性较高
            question.usefulness_score = 0.7
        else:
            question.usefulness_score = 0.3

    def start_exploration(self, question_id: str, topic: str, curiosity_type: CuriosityType) -> ExplorationRecord:
        """
        开始探索

        Args:
            question_id: 问题ID
            topic: 主题
            curiosity_type: 好奇心类型

        Returns:
            探索记录
        """
        exploration = self.curiosity_drive.record_exploration(question_id, topic, curiosity_type)
        self._stats["explorations_started"] += 1

        return exploration

    def complete_exploration(
        self, exploration_id: str, findings: List[str], knowledge_gained: float = 0.0
    ) -> Optional[ExplorationRecord]:
        """
        完成探索

        Args:
            exploration_id: 探索ID
            findings: 发现
            knowledge_gained: 获得的知识量

        Returns:
            更新后的探索记录
        """
        exploration = self.curiosity_drive.complete_exploration(exploration_id, findings, knowledge_gained)
        if exploration:
            self._stats["explorations_completed"] += 1

        return exploration

    def _on_user_busy(self) -> None:
        """用户忙碌回调"""
        # 降低提问频率
        self._question_cooldown = 600  # 10分钟

    def _on_user_idle(self) -> None:
        """用户空闲回调"""
        # 恢复正常提问频率
        self._question_cooldown = 300  # 5分钟

    def _on_conversation_end(self) -> None:
        """对话结束回调"""
        # 清理过期问题
        self.question_queue.clear_expired()

    def _on_memory_created(self, memory_id: str) -> None:
        """记忆创建回调"""
        # 可以根据新记忆生成好奇心问题

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "queue_stats": {
                "pending": len(self.question_queue._status_index.get(QuestionStatus.PENDING, [])),
                "asked": len(self.question_queue._status_index.get(QuestionStatus.ASKED, [])),
                "answered": len(self.question_queue._status_index.get(QuestionStatus.ANSWERED, [])),
            },
            "curiosity_stats": self.curiosity_drive.get_exploration_stats(),
        }

    def reset_session(self) -> None:
        """重置会话"""
        self._session_active = False
        self._last_question_time = None
        self._question_cooldown = 300

        logger.debug("重置会话: %s", self.agent_id)
