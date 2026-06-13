"""
自我反思模块

分析记忆模式、检测异常、生成洞察
"""

from __future__ import annotations

import datetime
import logging
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PatternType(str, Enum):
    """模式类型"""

    TEMPORAL = "temporal"  # 时间模式
    EMOTIONAL = "emotional"  # 情感模式
    TOPIC = "topic"  # 主题模式
    BEHAVIORAL = "behavioral"  # 行为模式
    COGNITIVE = "cognitive"  # 认知模式


@dataclass
class MemoryPattern:
    """记忆模式"""

    pattern_id: str
    pattern_type: PatternType
    description: str
    frequency: int = 0
    confidence: float = 0.0
    first_seen: Optional[datetime.datetime] = None
    last_seen: Optional[datetime.datetime] = None
    examples: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type.value,
            "description": self.description,
            "frequency": self.frequency,
            "confidence": self.confidence,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "examples": self.examples[:5],  # 限制示例数量
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryPattern":
        """从字典创建"""
        return cls(
            pattern_id=data["pattern_id"],
            pattern_type=PatternType(data["pattern_type"]),
            description=data["description"],
            frequency=data.get("frequency", 0),
            confidence=data.get("confidence", 0.0),
            first_seen=datetime.datetime.fromisoformat(data["first_seen"]) if data.get("first_seen") else None,
            last_seen=datetime.datetime.fromisoformat(data["last_seen"]) if data.get("last_seen") else None,
            examples=data.get("examples", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Anomaly:
    """异常"""

    anomaly_id: str
    description: str
    severity: str  # low, medium, high, critical
    timestamp: datetime.datetime
    related_memories: List[str] = field(default_factory=list)
    suggested_action: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "anomaly_id": self.anomaly_id,
            "description": self.description,
            "severity": self.severity,
            "timestamp": self.timestamp.isoformat(),
            "related_memories": self.related_memories,
            "suggested_action": self.suggested_action,
            "metadata": self.metadata,
        }


@dataclass
class Insight:
    """洞察"""

    insight_id: str
    title: str
    description: str
    insight_type: str  # pattern, anomaly, recommendation, observation
    confidence: float = 0.0
    impact_score: float = 0.0
    related_patterns: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "insight_id": self.insight_id,
            "title": self.title,
            "description": self.description,
            "insight_type": self.insight_type,
            "confidence": self.confidence,
            "impact_score": self.impact_score,
            "related_patterns": self.related_patterns,
            "action_items": self.action_items,
            "metadata": self.metadata,
        }


class SelfReflection:
    """自我反思模块

    分析记忆模式、检测异常、生成洞察。
    """

    def __init__(
        self,
        memory_manager: Any = None,
        max_patterns: int = 100,
        max_anomalies: int = 50,
        max_insights: int = 50,
    ):
        """初始化自我反思模块

        Args:
            memory_manager: 记忆管理器
            max_patterns: 最大模式数
            max_anomalies: 最大异常数
            max_insights: 最大洞察数
        """
        self._memory_manager = memory_manager
        self._max_patterns = max_patterns
        self._max_anomalies = max_anomalies
        self._max_insights = max_insights

        # 存储
        self._patterns: Dict[str, MemoryPattern] = {}
        self._anomalies: List[Anomaly] = []
        self._insights: List[Insight] = []

        # 统计信息
        self._stats = {
            "total_analyses": 0,
            "patterns_detected": 0,
            "anomalies_detected": 0,
            "insights_generated": 0,
        }

        # 线程安全
        self._lock = threading.RLock()

        logger.info("SelfReflection 初始化完成")

    def analyze_memory_patterns(
        self,
        memories: List[Any],
        time_window_days: int = 30,
    ) -> List[MemoryPattern]:
        """分析记忆模式

        Args:
            memories: 记忆列表
            time_window_days: 时间窗口（天）

        Returns:
            检测到的模式列表
        """
        with self._lock:
            try:
                patterns = []

                # 分析情感分布
                emotion_patterns = self._analyze_emotion_distribution(memories)
                patterns.extend(emotion_patterns)

                # 分析时间分布
                time_patterns = self._analyze_time_distribution(memories, time_window_days)
                patterns.extend(time_patterns)

                # 分析类别分布
                category_patterns = self._analyze_category_distribution(memories)
                patterns.extend(category_patterns)

                # 更新模式索引
                for pattern in patterns:
                    self._patterns[pattern.pattern_id] = pattern

                # 更新统计
                self._stats["total_analyses"] += 1
                self._stats["patterns_detected"] += len(patterns)

                logger.info("检测到 %s 个模式", len(patterns))
                return patterns
            except Exception as e:
                logger.error("分析记忆模式失败: %s", e)
                return []

    def _analyze_emotion_distribution(self, memories: List[Any]) -> List[MemoryPattern]:
        """分析情感分布

        Args:
            memories: 记忆列表

        Returns:
            情感模式列表
        """
        patterns = []

        try:
            # 统计情感分布
            emotion_counts: Counter[str] = Counter()

            for memory in memories:
                emotion = getattr(memory, "emotion", None)
                if emotion:
                    emotion_counts[emotion] += 1

            if not emotion_counts:
                return patterns

            # 分析主导情感
            total_memories = len(memories)
            for emotion, count in emotion_counts.most_common(3):
                ratio = count / total_memories

                if ratio > 0.1:  # 超过10%的记忆有相同情感
                    pattern = MemoryPattern(
                        pattern_id=f"emotion_{emotion}_{int(time.time())}",
                        pattern_type=PatternType.EMOTIONAL,
                        description=f"情感 '{emotion}' 频繁出现，占比 {ratio * 100:.1f}%%",
                        frequency=count,
                        confidence=min(1.0, ratio * 2),
                        metadata={
                            "emotion": emotion,
                            "ratio": ratio,
                            "count": count,
                        },
                    )
                    patterns.append(pattern)

            return patterns
        except Exception as e:
            logger.warning("分析情感分布失败: %s", e)
            return []

    def _analyze_time_distribution(
        self,
        memories: List[Any],
        time_window_days: int,
    ) -> List[MemoryPattern]:
        """分析时间分布

        Args:
            memories: 记忆列表
            time_window_days: 时间窗口（天）

        Returns:
            时间模式列表
        """
        patterns = []

        try:
            # 按小时统计记忆数量
            hour_counts: Counter[int] = Counter()
            day_counts: Counter[str] = Counter()

            for memory in memories:
                timestamp = getattr(memory, "timestamp", None)
                if not timestamp:
                    continue

                hour_counts[timestamp.hour] += 1
                day_counts[timestamp.strftime("%A")] += 1

            # 分析活跃时段
            if hour_counts:
                peak_hour = hour_counts.most_common(1)[0]
                total_memories = sum(hour_counts.values())
                peak_ratio = peak_hour[1] / total_memories

                if peak_ratio > 0.15:  # 超过15%的记忆在同一小时
                    pattern = MemoryPattern(
                        pattern_id=f"time_hour_{peak_hour[0]}_{int(time.time())}",
                        pattern_type=PatternType.TEMPORAL,
                        description=f"在 {peak_hour[0]}:00 时段记忆最活跃，占比 {peak_ratio * 100:.1f}%%",
                        frequency=peak_hour[1],
                        confidence=min(1.0, peak_ratio * 3),
                        metadata={
                            "hour": peak_hour[0],
                            "ratio": peak_ratio,
                        },
                    )
                    patterns.append(pattern)

            # 分析活跃日期
            if day_counts:
                peak_day = day_counts.most_common(1)[0]
                total_days = sum(day_counts.values())
                day_ratio = peak_day[1] / total_days

                if day_ratio > 0.2:  # 超过20%的记忆在同一天
                    pattern = MemoryPattern(
                        pattern_id=f"time_day_{peak_day[0]}_{int(time.time())}",
                        pattern_type=PatternType.TEMPORAL,
                        description=f"在 {peak_day[0]} 记忆最活跃，占比 {day_ratio * 100:.1f}%%",
                        frequency=peak_day[1],
                        confidence=min(1.0, day_ratio * 2),
                        metadata={
                            "day": peak_day[0],
                            "ratio": day_ratio,
                        },
                    )
                    patterns.append(pattern)

            return patterns
        except Exception as e:
            logger.warning("分析时间分布失败: %s", e)
            return []

    def _analyze_category_distribution(self, memories: List[Any]) -> List[MemoryPattern]:
        """分析类别分布

        Args:
            memories: 记忆列表

        Returns:
            类别模式列表
        """
        patterns = []

        try:
            # 统计类别分布
            category_counts: Counter[str] = Counter()

            for memory in memories:
                # 尝试从不同属性获取类别
                category = None
                if hasattr(memory, "category"):
                    category = memory.category
                elif hasattr(memory, "type"):
                    category = memory.type
                elif hasattr(memory, "tags"):
                    tags = getattr(memory, "tags", [])
                    if tags:
                        category = tags[0]

                if category:
                    category_counts[str(category)] += 1

            if not category_counts:
                return patterns

            # 分析主要类别
            total_memories = len(memories)
            for category, count in category_counts.most_common(3):
                ratio = count / total_memories

                if ratio > 0.2:  # 超过20%的记忆属于同一类别
                    pattern = MemoryPattern(
                        pattern_id=f"category_{category}_{int(time.time())}",
                        pattern_type=PatternType.TOPIC,
                        description=f"类别 '{category}' 占主导地位，占比 {ratio * 100:.1f}%%",
                        frequency=count,
                        confidence=min(1.0, ratio * 2),
                        metadata={
                            "category": category,
                            "ratio": ratio,
                            "count": count,
                        },
                    )
                    patterns.append(pattern)

            return patterns
        except Exception as e:
            logger.warning("分析类别分布失败: %s", e)
            return []

    def detect_anomalies(
        self,
        memories: List[Any],
        baseline_days: int = 30,
    ) -> List[Anomaly]:
        """检测异常

        Args:
            memories: 记忆列表
            baseline_days: 基线时间（天）

        Returns:
            检测到的异常列表
        """
        with self._lock:
            try:
                anomalies = []

                # 检测情感异常
                emotion_anomalies = self._detect_emotion_anomalies(memories)
                anomalies.extend(emotion_anomalies)

                # 检测时间异常
                time_anomalies = self._detect_time_anomalies(memories, baseline_days)
                anomalies.extend(time_anomalies)

                # 检测内容异常
                content_anomalies = self._detect_content_anomalies(memories)
                anomalies.extend(content_anomalies)

                # 更新存储
                self._anomalies.extend(anomalies)
                if len(self._anomalies) > self._max_anomalies:
                    self._anomalies = self._anomalies[-self._max_anomalies :]

                # 更新统计
                self._stats["anomalies_detected"] += len(anomalies)

                logger.info("检测到 %s 个异常", len(anomalies))
                return anomalies
            except Exception as e:
                logger.error("检测异常失败: %s", e)
                return []

    def _detect_emotion_anomalies(self, memories: List[Any]) -> List[Anomaly]:
        """检测情感异常

        Args:
            memories: 记忆列表

        Returns:
            情感异常列表
        """
        anomalies = []

        try:
            # 统计情感分布
            emotion_counts: Counter[str] = Counter()
            negative_emotions = {"sadness", "anger", "fear", "disgust", "contempt"}

            for memory in memories:
                emotion = getattr(memory, "emotion", None)
                if emotion:
                    emotion_counts[emotion] += 1

            if not emotion_counts:
                return anomalies

            total_memories = len(memories)

            # 检测负面情感过多
            negative_count = sum(emotion_counts.get(e, 0) for e in negative_emotions)
            negative_ratio = negative_count / total_memories

            if negative_ratio > 0.5:  # 超过50%的负面情感
                anomaly = Anomaly(
                    anomaly_id=f"emotion_negative_{int(time.time())}",
                    description=f"负面情感比例过高: {negative_ratio * 100:.1f}%%",
                    severity="high",
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                    suggested_action="建议分析负面情感来源，提供情感支持",
                    metadata={
                        "negative_ratio": negative_ratio,
                        "negative_count": negative_count,
                        "total_memories": total_memories,
                    },
                )
                anomalies.append(anomaly)

            # 检测情感突然变化
            if len(memories) >= 10:
                recent_memories = memories[-10:]
                recent_emotions = [getattr(m, "emotion", None) for m in recent_memories]
                recent_emotions = [e for e in recent_emotions if e]

                if recent_emotions:
                    # 计算情感多样性
                    unique_emotions = len(set(recent_emotions))
                    if unique_emotions > 5:  # 情感变化过于频繁
                        anomaly = Anomaly(
                            anomaly_id=f"emotion_volatility_{int(time.time())}",
                            description=f"情感变化过于频繁: 最近10条记忆中出现 {unique_emotions} 种不同情感",
                            severity="medium",
                            timestamp=datetime.datetime.now(datetime.timezone.utc),
                            suggested_action="建议检查情感稳定性",
                            metadata={
                                "unique_emotions": unique_emotions,
                                "recent_emotions": recent_emotions,
                            },
                        )
                        anomalies.append(anomaly)

            return anomalies
        except Exception as e:
            logger.warning("检测情感异常失败: %s", e)
            return []

    def _detect_time_anomalies(
        self,
        memories: List[Any],
        baseline_days: int,
    ) -> List[Anomaly]:
        """检测时间异常

        Args:
            memories: 记忆列表
            baseline_days: 基线时间（天）

        Returns:
            时间异常列表
        """
        anomalies = []

        try:
            if len(memories) < 10:
                return anomalies

            # 计算记忆频率
            current_time = datetime.datetime.now(datetime.timezone.utc)
            baseline_start = current_time - datetime.timedelta(days=baseline_days)

            # 统计每天的记忆数量
            daily_counts: Counter[str] = Counter()
            for memory in memories:
                timestamp = getattr(memory, "timestamp", None)
                if timestamp and timestamp >= baseline_start:
                    day_key = timestamp.strftime("%Y-%m-%d")
                    daily_counts[day_key] += 1

            if not daily_counts:
                return anomalies

            # 计算平均值和标准差
            counts = list(daily_counts.values())
            avg_count = sum(counts) / len(counts)

            if len(counts) > 1:
                variance = sum((x - avg_count) ** 2 for x in counts) / (len(counts) - 1)
                std_dev = variance**0.5

                # 检测异常高或低的频率
                for day, count in daily_counts.items():
                    if std_dev > 0:
                        z_score = (count - avg_count) / std_dev

                        if z_score > 2:  # 异常高
                            anomaly = Anomaly(
                                anomaly_id=f"time_high_{day}_{int(time.time())}",
                                description=f"记忆频率异常高: {day} 有 {count} 条记忆",
                                severity="medium",
                                timestamp=datetime.datetime.now(datetime.timezone.utc),
                                suggested_action="建议检查是否有特殊事件",
                                metadata={
                                    "date": day,
                                    "count": count,
                                    "average": avg_count,
                                    "z_score": z_score,
                                },
                            )
                            anomalies.append(anomaly)
                        elif z_score < -2:  # 异常低
                            anomaly = Anomaly(
                                anomaly_id=f"time_low_{day}_{int(time.time())}",
                                description=f"记忆频率异常低: {day} 只有 {count} 条记忆",
                                severity="low",
                                timestamp=datetime.datetime.now(datetime.timezone.utc),
                                suggested_action="建议检查系统是否正常运行",
                                metadata={
                                    "date": day,
                                    "count": count,
                                    "average": avg_count,
                                    "z_score": z_score,
                                },
                            )
                            anomalies.append(anomaly)

            return anomalies
        except Exception as e:
            logger.warning("检测时间异常失败: %s", e)
            return []

    def _detect_content_anomalies(self, memories: List[Any]) -> List[Anomaly]:
        """检测内容异常

        Args:
            memories: 记忆列表

        Returns:
            内容异常列表
        """
        anomalies = []

        try:
            # 检测重复内容
            content_hashes: Counter[str] = Counter()

            for memory in memories:
                content = getattr(memory, "content", None)
                if content:
                    # 简单的内容哈希
                    content_hash = hash(content[:100])  # 只取前100字符
                    content_hashes[content_hash] += 1

            # 检测重复
            for content_hash, count in content_hashes.items():
                if count > 5:  # 超过5次重复
                    anomaly = Anomaly(
                        anomaly_id=f"content_duplicate_{content_hash}_{int(time.time())}",
                        description=f"检测到重复内容: 出现 {count} 次",
                        severity="low",
                        timestamp=datetime.datetime.now(datetime.timezone.utc),
                        suggested_action="建议检查是否有重复记忆需要清理",
                        metadata={
                            "content_hash": content_hash,
                            "count": count,
                        },
                    )
                    anomalies.append(anomaly)

            return anomalies
        except Exception as e:
            logger.warning("检测内容异常失败: %s", e)
            return []

    def generate_insights(
        self,
        patterns: List[MemoryPattern],
        anomalies: List[Anomaly],
    ) -> List[Insight]:
        """生成洞察

        Args:
            patterns: 模式列表
            anomalies: 异常列表

        Returns:
            洞察列表
        """
        with self._lock:
            try:
                insights = []

                # 从模式生成洞察
                pattern_insights = self._generate_pattern_insights(patterns)
                insights.extend(pattern_insights)

                # 从异常生成洞察
                anomaly_insights = self._generate_anomaly_insights(anomalies)
                insights.extend(anomaly_insights)

                # 更新存储
                self._insights.extend(insights)
                if len(self._insights) > self._max_insights:
                    self._insights = self._insights[-self._max_insights :]

                # 更新统计
                self._stats["insights_generated"] += len(insights)

                logger.info("生成 %s 个洞察", len(insights))
                return insights
            except Exception as e:
                logger.error("生成洞察失败: %s", e)
                return []

    def _generate_pattern_insights(self, patterns: List[MemoryPattern]) -> List[Insight]:
        """从模式生成洞察

        Args:
            patterns: 模式列表

        Returns:
            洞察列表
        """
        insights = []

        try:
            for pattern in patterns:
                if pattern.confidence > 0.7:  # 高置信度模式
                    insight = Insight(
                        insight_id=f"pattern_{pattern.pattern_id}",
                        title=f"发现模式: {pattern.description}",
                        description=f"检测到 {pattern.pattern_type.value} 类型的模式，置信度 {pattern.confidence * 100:.1f}%%",
                        insight_type="pattern",
                        confidence=pattern.confidence,
                        impact_score=0.5,
                        related_patterns=[pattern.pattern_id],
                        action_items=[f"关注 {pattern.pattern_type.value} 模式的变化"],
                    )
                    insights.append(insight)

            return insights
        except Exception as e:
            logger.warning("从模式生成洞察失败: %s", e)
            return []

    def _generate_anomaly_insights(self, anomalies: List[Anomaly]) -> List[Insight]:
        """从异常生成洞察

        Args:
            anomalies: 异常列表

        Returns:
            洞察列表
        """
        insights = []

        try:
            for anomaly in anomalies:
                severity_score = {
                    "low": 0.3,
                    "medium": 0.5,
                    "high": 0.7,
                    "critical": 0.9,
                }.get(anomaly.severity, 0.5)

                insight = Insight(
                    insight_id=f"anomaly_{anomaly.anomaly_id}",
                    title=f"发现异常: {anomaly.description[:50]}",
                    description=anomaly.description,
                    insight_type="anomaly",
                    confidence=0.8,
                    impact_score=severity_score,
                    action_items=[anomaly.suggested_action] if anomaly.suggested_action else [],
                )
                insights.append(insight)

            return insights
        except Exception as e:
            logger.warning("从异常生成洞察失败: %s", e)
            return []

    def get_patterns(self, pattern_type: Optional[PatternType] = None) -> List[MemoryPattern]:
        """获取模式

        Args:
            pattern_type: 模式类型过滤

        Returns:
            模式列表
        """
        with self._lock:
            patterns = list(self._patterns.values())

            if pattern_type:
                patterns = [p for p in patterns if p.pattern_type == pattern_type]

            return patterns

    def get_anomalies(self, severity: Optional[str] = None) -> List[Anomaly]:
        """获取异常

        Args:
            severity: 严重程度过滤

        Returns:
            异常列表
        """
        with self._lock:
            anomalies = self._anomalies.copy()

            if severity:
                anomalies = [a for a in anomalies if a.severity == severity]

            return anomalies

    def get_insights(self, insight_type: Optional[str] = None) -> List[Insight]:
        """获取洞察

        Args:
            insight_type: 洞察类型过滤

        Returns:
            洞察列表
        """
        with self._lock:
            insights = self._insights.copy()

            if insight_type:
                insights = [i for i in insights if i.insight_type == insight_type]

            return insights

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息

        Returns:
            统计信息字典
        """
        with self._lock:
            return {
                **self._stats,
                "patterns_count": len(self._patterns),
                "anomalies_count": len(self._anomalies),
                "insights_count": len(self._insights),
            }

    def clear(self) -> None:
        """清空所有数据"""
        with self._lock:
            self._patterns.clear()
            self._anomalies.clear()
            self._insights.clear()

            self._stats = {
                "total_analyses": 0,
                "patterns_detected": 0,
                "anomalies_detected": 0,
                "insights_generated": 0,
            }

            logger.info("SelfReflection 数据已清空")


# 全局实例管理
_self_reflection_instances: Dict[str, SelfReflection] = {}
_self_reflection_lock = threading.Lock()


def get_self_reflection(
    memory_manager: Any = None,
    instance_id: str = "default",
) -> SelfReflection:
    """获取自我反思模块单例

    Args:
        memory_manager: 记忆管理器
        instance_id: 实例ID

    Returns:
        自我反思模块实例
    """
    global _self_reflection_instances

    with _self_reflection_lock:
        if instance_id not in _self_reflection_instances:
            _self_reflection_instances[instance_id] = SelfReflection(memory_manager=memory_manager)
        return _self_reflection_instances[instance_id]


def reset_self_reflection(instance_id: Optional[str] = None) -> None:
    """重置自我反思模块单例

    Args:
        instance_id: 实例ID，为None时重置所有
    """
    global _self_reflection_instances

    with _self_reflection_lock:
        if instance_id is None:
            _self_reflection_instances.clear()
        elif instance_id in _self_reflection_instances:
            _self_reflection_instances[instance_id].clear()
            del _self_reflection_instances[instance_id]


def reset_all_self_reflection() -> None:
    """重置所有自我反思模块单例"""
    reset_self_reflection(None)
