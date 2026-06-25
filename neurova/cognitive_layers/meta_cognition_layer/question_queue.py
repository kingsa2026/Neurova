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

        # 状态索引
        self._status_index: Dict[QuestionStatus, List[str]] = {status: [] for status in QuestionStatus}

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

            self._on_question_ask(entry)
            logger.info("Question %s... marked as asked", question_id[:8])
            return True

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
            }

    def _load_questions_from_memory(self) -> None:
        """从记忆系统加载问题"""
        if self._memory_manager is None:
            return

        try:
            # 尝试从记忆管理器加载问题数据
            stored = self._memory_manager.search(
                query="question_queue",
                category="system",
                limit=self._max_questions,
            )
            if stored:
                for mem in stored:
                    try:
                        data = json.loads(mem.content) if isinstance(mem.content, str) else mem.content
                        if isinstance(data, dict) and "id" in data:
                            entry = QuestionEntry.from_dict(data)
                            self._questions[entry.id] = entry
                            self._status_index[entry.status].append(entry.id)
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

    def _save_single_question(self, entry: QuestionEntry) -> None:
        """保存单个问题到记忆"""
        if self._memory_manager is None:
            return

        try:
            self._memory_manager.remember(
                content=json.dumps(entry.to_dict(), ensure_ascii=False),
                category="system",
                importance=0.3,
                metadata={"type": "question_queue", "question_id": entry.id},
            )
        except Exception as e:
            logger.debug("Failed to save question %s...: %s", entry.id[:8], e)

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
