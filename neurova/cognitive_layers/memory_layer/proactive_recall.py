"""
主动回忆机制 - 基于上下文的智能记忆唤醒
"""

import datetime
from neurova.core.logger import get_logger
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = get_logger(__name__)


class TriggerType(str, Enum):
    """触发器类型"""

    KEYWORD = "keyword"  # 关键词触发
    EMOTION = "emotion"  # 情感触发
    TIME = "time"  # 时间触发
    FREQUENCY = "frequency"  # 频率触发
    CONTEXT = "context"  # 上下文触发
    CUSTOM = "custom"  # 自定义触发


@dataclass
class RecallTrigger:
    """回忆触发器"""

    trigger_type: TriggerType
    name: str
    description: str = ""
    enabled: bool = True
    priority: int = 0
    config: Dict[str, Any] = field(default_factory=dict)
    last_triggered: Optional[datetime.datetime] = None
    trigger_count: int = 0


@dataclass
class RecallSuggestion:
    """回忆建议"""

    memory_id: str
    content: str
    relevance_score: float
    trigger_type: TriggerType
    trigger_name: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))


class ProactiveRecall:
    """
    主动回忆系统

    基于上下文的智能记忆唤醒，支持：
    1. 关键词触发 - 检测特定关键词
    2. 情感触发 - 基于情感状态
    3. 时间触发 - 基于时间模式
    4. 频率触发 - 基于访问频率
    5. 上下文触发 - 基于对话上下文
    6. 自定义触发 - 用户自定义规则
    """

    def __init__(
        self,
        storage: Any = None,
        emotion_analyzer: Any = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化主动回忆系统

        Args:
            storage: 存储后端
            emotion_analyzer: 情感分析器
            config: 配置字典
        """
        self._storage = storage
        self._emotion_analyzer = emotion_analyzer
        self._config = config or {}
        self._lock = threading.RLock()

        # 触发器注册表
        self._triggers: Dict[str, RecallTrigger] = {}

        # 触发器处理函数
        self._trigger_handlers: Dict[TriggerType, Callable] = {
            TriggerType.KEYWORD: self._keyword_trigger,
            TriggerType.EMOTION: self._emotion_trigger,
            TriggerType.TIME: self._time_trigger,
            TriggerType.FREQUENCY: self._frequency_trigger,
            TriggerType.CONTEXT: self._context_trigger,
        }

        # 缓存
        self._suggestion_cache: Dict[str, List[RecallSuggestion]] = {}
        self._cache_ttl = self._config.get("cache_ttl", 300)  # 5分钟
        self._cache_timestamps: Dict[str, float] = {}

        # 统计
        self._total_suggestions = 0
        self._total_triggers = 0

        # 初始化默认触发器
        self._init_default_triggers()

        logger.info("ProactiveRecall initialized")

    def _init_default_triggers(self) -> None:
        """初始化默认触发器"""
        # 关键词触发器
        self.add_trigger(
            RecallTrigger(
                trigger_type=TriggerType.KEYWORD,
                name="important_keywords",
                description="检测重要关键词",
                priority=10,
                config={
                    "keywords": ["重要", "关键", "注意", "记住", "必须", "urgent", "important"],
                    "case_sensitive": False,
                },
            )
        )

        # 情感触发器
        self.add_trigger(
            RecallTrigger(
                trigger_type=TriggerType.EMOTION,
                name="strong_emotion",
                description="检测强烈情感",
                priority=8,
                config={
                    "emotions": ["anger", "fear", "joy", "surprise"],
                    "threshold": 0.7,
                },
            )
        )

        # 时间触发器
        self.add_trigger(
            RecallTrigger(
                trigger_type=TriggerType.TIME,
                name="recent_memories",
                description="最近记忆",
                priority=5,
                config={
                    "hours": 24,
                    "min_count": 3,
                },
            )
        )

        # 频率触发器
        self.add_trigger(
            RecallTrigger(
                trigger_type=TriggerType.FREQUENCY,
                name="frequently_accessed",
                description="频繁访问的记忆",
                priority=6,
                config={
                    "min_access_count": 5,
                    "time_window_hours": 168,  # 一周
                },
            )
        )

        logger.info("Initialized %s default triggers", len(self._triggers))

    def add_trigger(self, trigger: RecallTrigger) -> None:
        """
        添加触发器

        Args:
            trigger: 触发器对象
        """
        with self._lock:
            self._triggers[trigger.name] = trigger
            logger.debug("Trigger added: %s (%s)", trigger.name, trigger.trigger_type.value)

    def remove_trigger(self, name: str) -> bool:
        """
        移除触发器

        Args:
            name: 触发器名称

        Returns:
            是否移除成功
        """
        with self._lock:
            if name in self._triggers:
                del self._triggers[name]
                logger.debug("Trigger removed: %s", name)
                return True
            return False

    def get_trigger(self, name: str) -> Optional[RecallTrigger]:
        """
        获取触发器

        Args:
            name: 触发器名称

        Returns:
            触发器对象，如果不存在返回None
        """
        return self._triggers.get(name)

    def list_triggers(self) -> List[RecallTrigger]:
        """
        列出所有触发器

        Returns:
            触发器列表
        """
        return list(self._triggers.values())

    def generate_suggestions(
        self,
        context: str,
        agent_id: str = "default",
        user_id: str = "default",
        limit: int = 10,
    ) -> List[RecallSuggestion]:
        """
        生成回忆建议

        Args:
            context: 当前上下文
            agent_id: Agent ID
            user_id: 用户ID
            limit: 返回建议数量限制

        Returns:
            回忆建议列表
        """
        with self._lock:
            self._total_triggers += 1

            # 检查缓存
            cache_key = f"{context}:{agent_id}:{user_id}"
            if cache_key in self._suggestion_cache:
                cache_time = self._cache_timestamps.get(cache_key, 0)
                if time.time() - cache_time < self._cache_ttl:
                    return self._suggestion_cache[cache_key][:limit]

            # 收集所有触发器的建议
            all_suggestions: List[RecallSuggestion] = []

            # 按优先级排序触发器
            sorted_triggers = sorted(
                self._triggers.values(),
                key=lambda t: t.priority,
                reverse=True,
            )

            for trigger in sorted_triggers:
                if not trigger.enabled:
                    continue

                try:
                    # 获取触发器处理函数
                    handler = self._trigger_handlers.get(trigger.trigger_type)
                    if handler:
                        suggestions = handler(context, trigger, agent_id, user_id)
                        all_suggestions.extend(suggestions)

                        # 更新触发器统计
                        trigger.trigger_count += 1
                        trigger.last_triggered = datetime.datetime.now(datetime.timezone.utc)

                except Exception as e:
                    logger.warning("Trigger %s failed: %s", trigger.name, e)

            # 去重和排序
            unique_suggestions = self._deduplicate_suggestions(all_suggestions)
            sorted_suggestions = sorted(
                unique_suggestions,
                key=lambda s: s.relevance_score,
                reverse=True,
            )

            # 限制数量
            result = sorted_suggestions[:limit]

            # 更新缓存
            self._suggestion_cache[cache_key] = result
            self._cache_timestamps[cache_key] = time.time()

            self._total_suggestions += len(result)

            return result

    def _keyword_trigger(
        self,
        context: str,
        trigger: RecallTrigger,
        agent_id: str,
        user_id: str,
    ) -> List[RecallSuggestion]:
        """
        关键词触发器

        Args:
            context: 当前上下文
            trigger: 触发器配置
            agent_id: Agent ID
            user_id: 用户ID

        Returns:
            回忆建议列表
        """
        suggestions = []

        if not self._storage:
            return suggestions

        config = trigger.config
        keywords = config.get("keywords", [])
        case_sensitive = config.get("case_sensitive", False)

        # 提取上下文中的关键词
        if not case_sensitive:
            context_lower = context.lower()
        else:
            context_lower = context

        # 检查是否包含关键词
        matched_keywords = []
        for keyword in keywords:
            if not case_sensitive:
                keyword_lower = keyword.lower()
            else:
                keyword_lower = keyword

            if keyword_lower in context_lower:
                matched_keywords.append(keyword)

        if not matched_keywords:
            return suggestions

        # 搜索包含关键词的记忆
        try:
            for keyword in matched_keywords:
                memories = self._storage.search_memories(
                    query=keyword,
                    limit=5,
                    agent_id=agent_id,
                    user_id=user_id,
                )

                for memory in memories:
                    # 计算相关性分数
                    score = self._calculate_keyword_score(memory, matched_keywords)

                    suggestions.append(
                        RecallSuggestion(
                            memory_id=memory.get("id", ""),
                            content=memory.get("content", ""),
                            relevance_score=score,
                            trigger_type=TriggerType.KEYWORD,
                            trigger_name=trigger.name,
                            metadata={
                                "matched_keywords": matched_keywords,
                                "keyword": keyword,
                            },
                        )
                    )
        except Exception as e:
            logger.warning("Keyword trigger search failed: %s", e)

        return suggestions

    def _emotion_trigger(
        self,
        context: str,
        trigger: RecallTrigger,
        agent_id: str,
        user_id: str,
    ) -> List[RecallSuggestion]:
        """
        情感触发器

        Args:
            context: 当前上下文
            trigger: 触发器配置
            agent_id: Agent ID
            user_id: 用户ID

        Returns:
            回忆建议列表
        """
        suggestions = []

        if not self._storage or not self._emotion_analyzer:
            return suggestions

        config = trigger.config
        config.get("emotions", [])
        threshold = config.get("threshold", 0.7)

        try:
            # 分析当前情感
            emotion_result = self._emotion_analyzer.analyze(context)
            current_emotion = emotion_result.get("dominant_emotion", "")
            emotion_score = emotion_result.get("score", 0.0)

            # 检查是否匹配目标情感
            if current_emotion in target_emotion and emotion_score >= threshold:
                # 搜索相似情感的记忆
                memories = self._storage.search_by_emotion(
                    emotion=current_emotion,
                    min_score=threshold,
                    limit=5,
                    agent_id=agent_id,
                    user_id=user_id,
                )

                for memory in memories:
                    memory_emotion = memory.get("emotion", {})
                    memory_score = memory_emotion.get("score", 0.0)

                    # 计算情感相似度
                    similarity = 1.0 - abs(emotion_score - memory_score)

                    suggestions.append(
                        RecallSuggestion(
                            memory_id=memory.get("id", ""),
                            content=memory.get("content", ""),
                            relevance_score=similarity * 0.8,  # 情感触发权重较低
                            trigger_type=TriggerType.EMOTION,
                            trigger_name=trigger.name,
                            metadata={
                                "current_emotion": current_emotion,
                                "current_score": emotion_score,
                                "memory_emotion": memory_emotion,
                            },
                        )
                    )
        except Exception as e:
            logger.warning("Emotion trigger failed: %s", e)

        return suggestions

    def _time_trigger(
        self,
        context: str,
        trigger: RecallTrigger,
        agent_id: str,
        user_id: str,
    ) -> List[RecallSuggestion]:
        """
        时间触发器

        Args:
            context: 当前上下文
            trigger: 触发器配置
            agent_id: Agent ID
            user_id: 用户ID

        Returns:
            回忆建议列表
        """
        suggestions = []

        if not self._storage:
            return suggestions

        config = trigger.config
        hours = config.get("hours", 24)
        min_count = config.get("min_count", 3)

        try:
            # 获取最近记忆
            recent_memories = self._storage.get_recent_memories(
                hours=hours,
                limit=20,
                agent_id=agent_id,
                user_id=user_id,
            )

            # 检查数量是否达到阈值
            if len(recent_memories) >= min_count:
                # 按时间分组
                time_groups = self._group_by_time(recent_memories, hours=hours)

                for time_key, group in time_groups.items():
                    if len(group) >= min_count:
                        # 计算时间相关性
                        for memory in group:
                            # 最近的记忆分数更高
                            created_at = memory.get("created_at", "")
                            if created_at:
                                try:
                                    if isinstance(created_at, str):
                                        dt = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                                    else:
                                        dt = created_at

                                    hours_ago = (
                                        datetime.datetime.now(datetime.timezone.utc) - dt
                                    ).total_seconds() / 3600
                                    time_score = max(0, 1.0 - (hours_ago / hours))

                                    suggestions.append(
                                        RecallSuggestion(
                                            memory_id=memory.get("id", ""),
                                            content=memory.get("content", ""),
                                            relevance_score=time_score * 0.6,  # 时间触发权重较低
                                            trigger_type=TriggerType.TIME,
                                            trigger_name=trigger.name,
                                            metadata={
                                                "hours_ago": hours_ago,
                                                "time_group": time_key,
                                            },
                                        )
                                    )
                                except Exception:
                                    pass
        except Exception as e:
            logger.warning("Time trigger failed: %s", e)

        return suggestions

    def _frequency_trigger(
        self,
        context: str,
        trigger: RecallTrigger,
        agent_id: str,
        user_id: str,
    ) -> List[RecallSuggestion]:
        """
        频率触发器

        Args:
            context: 当前上下文
            trigger: 触发器配置
            agent_id: Agent ID
            user_id: 用户ID

        Returns:
            回忆建议列表
        """
        suggestions = []

        if not self._storage:
            return suggestions

        config = trigger.config
        min_access_count = config.get("min_access_count", 5)
        time_window_hours = config.get("time_window_hours", 168)

        try:
            # 获取频繁访问的记忆
            frequent_memories = self._storage.get_frequent_memories(
                min_access_count=min_access_count,
                time_window_hours=time_window_hours,
                limit=10,
                agent_id=agent_id,
                user_id=user_id,
            )

            for memory in frequent_memories:
                access_count = memory.get("access_count", 0)

                # 计算频率分数
                frequency_score = min(1.0, access_count / (min_access_count * 2))

                suggestions.append(
                    RecallSuggestion(
                        memory_id=memory.get("id", ""),
                        content=memory.get("content", ""),
                        relevance_score=frequency_score * 0.7,  # 频率触发权重中等
                        trigger_type=TriggerType.FREQUENCY,
                        trigger_name=trigger.name,
                        metadata={
                            "access_count": access_count,
                            "time_window_hours": time_window_hours,
                        },
                    )
                )
        except Exception as e:
            logger.warning("Frequency trigger failed: %s", e)

        return suggestions

    def _context_trigger(
        self,
        context: str,
        trigger: RecallTrigger,
        agent_id: str,
        user_id: str,
    ) -> List[RecallSuggestion]:
        """
        上下文触发器

        Args:
            context: 当前上下文
            trigger: 触发器配置
            agent_id: Agent ID
            user_id: 用户ID

        Returns:
            回忆建议列表
        """
        suggestions = []

        if not self._storage:
            return suggestions

        config = trigger.config
        min_similarity = config.get("min_similarity", 0.5)

        try:
            # 使用语义搜索
            similar_memories = self._storage.search_memories(
                query=context,
                limit=10,
                agent_id=agent_id,
                user_id=user_id,
            )

            for memory in similar_memories:
                # 计算相似度分数
                similarity = memory.get("similarity", 0.0)

                if similarity >= min_similarity:
                    suggestions.append(
                        RecallSuggestion(
                            memory_id=memory.get("id", ""),
                            content=memory.get("content", ""),
                            relevance_score=similarity,
                            trigger_type=TriggerType.CONTEXT,
                            trigger_name=trigger.name,
                            metadata={
                                "similarity": similarity,
                                "query_length": len(context),
                            },
                        )
                    )
        except Exception as e:
            logger.warning("Context trigger failed: %s", e)

        return suggestions

    def _calculate_keyword_score(
        self,
        memory: Dict[str, Any],
        keywords: List[str],
    ) -> float:
        """
        计算关键词分数

        Args:
            memory: 记忆数据
            keywords: 匹配的关键词

        Returns:
            分数 (0-1)
        """
        content = memory.get("content", "")
        if not content:
            return 0.0

        # 统计关键词出现次数
        content_lower = content.lower()
        keyword_count = sum(1 for keyword in keywords if keyword.lower() in content_lower)

        # 计算分数
        score = min(1.0, keyword_count / len(keywords))

        # 考虑内容长度
        length_factor = min(1.0, len(content) / 100)

        return score * 0.9 + length_factor * 0.1

    def _group_by_time(
        self,
        memories: List[Dict[str, Any]],
        hours: int = 24,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        按时间分组

        Args:
            memories: 记忆列表
            hours: 时间窗口（小时）

        Returns:
            时间分组字典
        """
        groups = defaultdict(list)

        for memory in memories:
            created_at = memory.get("created_at", "")
            if created_at:
                try:
                    if isinstance(created_at, str):
                        dt = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    else:
                        dt = created_at

                    # 计算时间窗口
                    window = dt.replace(
                        hour=(dt.hour // hours) * hours,
                        minute=0,
                        second=0,
                        microsecond=0,
                    )
                    window_key = window.isoformat()
                    groups[window_key].append(memory)
                except Exception:
                    groups["unknown"].append(memory)
            else:
                groups["unknown"].append(memory)

        return dict(groups)

    def _deduplicate_suggestions(
        self,
        suggestions: List[RecallSuggestion],
    ) -> List[RecallSuggestion]:
        """
        去重建议

        Args:
            suggestions: 建议列表

        Returns:
            去重后的建议列表
        """
        seen_ids: Set[str] = set()
        unique_suggestions = []

        for suggestion in suggestions:
            if suggestion.memory_id not in seen_ids:
                seen_ids.add(suggestion.memory_id)
                unique_suggestions.append(suggestion)

        return unique_suggestions

    def add_custom_trigger(
        self,
        name: str,
        handler: Callable[[str, RecallTrigger, str, str], List[RecallSuggestion]],
        description: str = "",
        priority: int = 0,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        添加自定义触发器

        Args:
            name: 触发器名称
            handler: 处理函数
            description: 描述
            priority: 优先级
            config: 配置
        """
        # 注册处理函数
        self._trigger_handlers[TriggerType.CUSTOM] = handler

        # 创建触发器
        trigger = RecallTrigger(
            trigger_type=TriggerType.CUSTOM,
            name=name,
            description=description,
            priority=priority,
            config=config or {},
        )

        self.add_trigger(trigger)

    def clear_cache(self) -> None:
        """清空缓存"""
        with self._lock:
            self._suggestion_cache.clear()
            self._cache_timestamps.clear()
            logger.debug("ProactiveRecall cache cleared")

    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息

        Returns:
            统计信息字典
        """
        with self._lock:
            return {
                "total_triggers": len(self._triggers),
                "total_suggestions": self._total_suggestions,
                "total_trigger_calls": self._total_triggers,
                "cache_size": len(self._suggestion_cache),
                "trigger_stats": {
                    name: {
                        "type": trigger.trigger_type.value,
                        "enabled": trigger.enabled,
                        "priority": trigger.priority,
                        "trigger_count": trigger.trigger_count,
                        "last_triggered": trigger.last_triggered.isoformat() if trigger.last_triggered else None,
                    }
                    for name, trigger in self._triggers.items()
                },
            }


# 全局单例
_proactive_recall: Optional[ProactiveRecall] = None
_recall_lock = threading.Lock()


def get_proactive_recall(
    storage: Any = None,
    emotion_analyzer: Any = None,
    config: Optional[Dict[str, Any]] = None,
) -> ProactiveRecall:
    """
    获取全局主动回忆系统单例

    Args:
        storage: 存储后端
        emotion_analyzer: 情感分析器
        config: 配置字典

    Returns:
        ProactiveRecall实例
    """
    global _proactive_recall
    if _proactive_recall is None:
        with _recall_lock:
            if _proactive_recall is None:
                _proactive_recall = ProactiveRecall(
                    storage=storage,
                    emotion_analyzer=emotion_analyzer,
                    config=config,
                )
    return _proactive_recall


def reset_proactive_recall() -> None:
    """重置全局主动回忆系统（用于测试）"""
    global _proactive_recall
    with _recall_lock:
        _proactive_recall = None
