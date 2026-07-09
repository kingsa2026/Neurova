"""
Memory Core - Neurova的记忆系统核心模块
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from neurova.cognitive_layers.memory_layer.isolation import IsolationContext

# ────── Enums ──────


class MemoryType(Enum):
    """记忆类型"""

    SEMANTIC = "semantic"  # 语义记忆（事实知识）
    EPISODIC = "episodic"  # 情景记忆（事件经历）
    PROCEDURAL = "procedural"  # 程序记忆（技能操作）
    PATTERN = "pattern"  # 模式记忆（行为模式）
    EMOTIONAL = "emotional"  # 情感记忆
    WORKING = "working"  # 工作记忆


class MemoryCategory(Enum):
    """记忆分类"""

    GENERAL = "general"
    CONVERSATION = "conversation"
    KNOWLEDGE = "knowledge"
    EXPERIENCE = "experience"
    TOOL_USAGE = "tool_usage"
    REFLECTION = "reflection"
    USER_PREFERENCE = "user_preference"


class LifecycleStage(Enum):
    """记忆生命周期阶段"""

    ACTIVE = "active"  # 活跃
    CONSOLIDATED = "consolidated"  # 已巩固
    ARCHIVED = "archived"  # 已归档
    FORGOTTEN = "forgotten"  # 已遗忘
    CRYSTALLIZED = "crystallized"  # 已结晶（永久）


class MemoryPerspective(Enum):
    """记忆视角"""

    FIRST_PERSON = "first_person"  # 第一人称
    SECOND_PERSON = "second_person"  # 第二人称
    THIRD_PERSON = "third_person"  # 第三人称
    SYSTEM = "system"  # 系统视角


class EmotionType(Enum):
    """情感类型"""

    NEUTRAL = "neutral"
    JOY = "joy"
    SADNESS = "sadness"
    ANGER = "anger"
    FEAR = "fear"
    SURPRISE = "surprise"
    DISGUST = "disgust"
    TRUST = "trust"
    ANTICIPATION = "anticipation"


# ────── Data Models ──────


@dataclass
class UserProfile:
    """用户档案"""

    user_id: str = ""
    name: str = ""
    preferences: Dict[str, Any] = field(default_factory=dict)
    traits: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "preferences": self.preferences,
            "traits": self.traits,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserProfile":
        return cls(
            user_id=data.get("user_id", ""),
            name=data.get("name", ""),
            preferences=data.get("preferences", {}),
            traits=data.get("traits", []),
        )


@dataclass
class Skill:
    """技能模型"""

    skill_id: str = ""
    name: str = ""
    description: str = ""
    category: str = "general"
    parameters: Dict[str, Any] = field(default_factory=dict)
    usage_count: int = 0
    success_rate: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "parameters": self.parameters,
            "usage_count": self.usage_count,
            "success_rate": self.success_rate,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Skill":
        return cls(
            skill_id=data.get("skill_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            category=data.get("category", "general"),
            parameters=data.get("parameters", {}),
            usage_count=data.get("usage_count", 0),
            success_rate=data.get("success_rate", 0.0),
        )


@dataclass
class SelfModel:
    """自我模型"""

    agent_id: str = ""
    name: str = ""
    personality_traits: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    beliefs: Dict[str, Any] = field(default_factory=dict)
    goals: List[str] = field(default_factory=list)
    version: int = 1
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "personality_traits": self.personality_traits,
            "capabilities": self.capabilities,
            "beliefs": self.beliefs,
            "goals": self.goals,
            "version": self.version,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SelfModel":
        return cls(
            agent_id=data.get("agent_id", ""),
            name=data.get("name", ""),
            personality_traits=data.get("personality_traits", []),
            capabilities=data.get("capabilities", []),
            beliefs=data.get("beliefs", {}),
            goals=data.get("goals", []),
            version=data.get("version", 1),
        )


@dataclass
class Attachment:
    """附件"""

    id: str = ""
    filename: str = ""
    content_type: str = ""
    size: int = 0
    path: str = ""
    memory_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "filename": self.filename,
            "content_type": self.content_type,
            "size": self.size,
            "path": self.path,
            "memory_id": self.memory_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class MemoryRelation:
    """记忆关联"""

    id: str = ""
    source_memory_id: str = ""
    target_memory_id: str = ""
    relation_type: str = "related"  # related, causes, part_of, contradicts
    strength: float = 1.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_memory_id": self.source_memory_id,
            "target_memory_id": self.target_memory_id,
            "relation_type": self.relation_type,
            "strength": self.strength,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class MetaTrace:
    """推理轨迹元数据"""

    trace_id: str = ""
    memory_id: str = ""
    reasoning_steps: List[str] = field(default_factory=list)
    confidence: float = 0.0
    sources: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "memory_id": self.memory_id,
            "reasoning_steps": self.reasoning_steps,
            "confidence": self.confidence,
            "sources": self.sources,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class Memory:
    """核心记忆模型"""

    id: str = ""
    content: str = ""
    memory_type: MemoryType = MemoryType.SEMANTIC
    category: MemoryCategory = MemoryCategory.GENERAL
    lifecycle_stage: LifecycleStage = LifecycleStage.ACTIVE
    perspective: MemoryPerspective = MemoryPerspective.FIRST_PERSON
    emotion: EmotionType = EmotionType.NEUTRAL
    temperature: float = 100.0
    importance: float = 50.0
    access_count: int = 0
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    agent_id: str = ""
    neuser_id: str = ""
    user_id: str = ""
    shared: bool = False  # 跨 agent 共享开关
    share_group_ids: List[str] = field(default_factory=list)  # 共享组ID列表
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed_at: Optional[datetime] = None
    isolation_context: Optional[IsolationContext] = None

    def __post_init__(self):
        """处理隔离上下文：从上下文设置三层隔离字段"""
        if self.isolation_context is not None:
            self.agent_id = self.isolation_context.agent_id
            self.neuser_id = self.isolation_context.neuser_id
            self.user_id = self.isolation_context.user_id
            self.shared = self.isolation_context.shared
            if self.isolation_context.share_group_ids:
                self.share_group_ids = list(self.isolation_context.share_group_ids)

    def touch(self):
        """访问一次，温度升高"""
        self.access_count += 1
        self.temperature = min(100.0, self.temperature + 10.0)
        self.last_accessed_at = datetime.now(timezone.utc)
        self.updated_at = self.last_accessed_at

    def decay(self, hours: float = 1.0, rate: float = 1.0):
        """温度衰减 — 委托 TemperatureEngine.on_decay 贝叶斯遗忘曲线

        Bug M-5 修复：原实现 temp -= rate * hours 是线性衰减，完全绕过
        TemperatureEngine.on_decay 的贝叶斯曲线（curve_factor/emotion_protect/
        saturation/importance_weight/important_protection）。现委托引擎计算，
        与 MemoryManager.run_decay_cycle 保持一致的语义。

        贝叶斯特性：
          - 固化记忆（CRYSTALLIZED）不衰减
          - 高温记忆（>=80）不衰减
          - 今天访问过的记忆（days_idle < 1.0）不衰减

        Args:
            hours: 保留参数（贝叶斯曲线用 days_idle，不直接使用 hours）
            rate:  保留参数（贝叶斯曲线通过 curve_factor 等因子调整，不直接使用 rate）
        """
        # 延迟导入避免循环依赖（与 manager.run_decay_cycle 一致）
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine

        now = datetime.now(timezone.utc)

        # 计算 days_idle（贝叶斯曲线的核心输入）
        last_accessed = self.last_accessed_at or self.created_at
        if last_accessed.tzinfo is None:
            last_accessed = last_accessed.replace(tzinfo=timezone.utc)
        days_idle = max(0.0, (now - last_accessed).total_seconds() / 86400.0)

        # 情感分数（EmotionType → 0.0-1.0，与 manager 一致）
        emotion_score = 0.0 if self.emotion == EmotionType.NEUTRAL else 0.5

        # 归一化 importance（0-100 → 0.0-1.0）
        importance_norm = max(0.0, min(1.0, float(self.importance) / 100.0))

        # 固化 / 重要检测（与 manager 一致）
        is_crystallized = self.lifecycle_stage == LifecycleStage.CRYSTALLIZED
        # BUG-4 修复: 原表达式 `A or B if C else D` 在空 metadata 时高重要性记忆保护失效
        is_important = importance_norm >= 0.8 or bool(
            (self.metadata or {}).get("is_important", False)
        )

        # 委托贝叶斯曲线
        # BUG-3 修复: on_decay 现为实例方法, 显式通过 _get_default() 获取默认实例
        result = TemperatureEngine._get_default().on_decay(
            current_temp=self.temperature,
            days_idle=days_idle,
            importance=importance_norm,
            emotion_score=emotion_score,
            recall_count=self.access_count,
            relation_count=0,
            is_important=is_important,
            is_crystallized=is_crystallized,
        )
        self.temperature = result["new_temp"]
        self.updated_at = now

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "memory_type": self.memory_type.value,
            "category": self.category.value,
            "lifecycle_stage": self.lifecycle_stage.value,
            "perspective": self.perspective.value,
            "emotion": self.emotion.value,
            "temperature": self.temperature,
            "importance": self.importance,
            "access_count": self.access_count,
            "metadata": self.metadata,
            "agent_id": self.agent_id,
            "neuser_id": self.neuser_id,
            "user_id": self.user_id,
            "shared": self.shared,
            "share_group_ids": self.share_group_ids,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_accessed_at": self.last_accessed_at.isoformat() if self.last_accessed_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], isolation_context: Optional["IsolationContext"] = None) -> "Memory":
        def _parse_enum(enum_cls, val, default):
            if isinstance(val, enum_cls):
                return val
            try:
                return enum_cls(val)
            except (ValueError, KeyError):
                return default

        def _parse_dt(val):
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                try:
                    return datetime.fromisoformat(val)
                except ValueError:
                    return datetime.now(timezone.utc)
            return datetime.now(timezone.utc)

        # Bug 2 修复: 若未传 isolation_context, 则从 agent_id/neuser_id/user_id 字段重建
        if isolation_context is None:
            agent_id = data.get("agent_id", "")
            neuser_id = data.get("neuser_id", "")
            user_id = data.get("user_id", "")
            # 任一字段非空即视为有效, 构造 IsolationContext (延迟导入避免循环依赖)
            if agent_id or neuser_id or user_id:
                from neurova.cognitive_layers.memory_layer.isolation import IsolationContext
                isolation_context = IsolationContext(
                    agent_id=agent_id or "default",
                    neuser_id=neuser_id or "default",
                    user_id=user_id or "default",
                )

        return cls(
            id=data.get("id", ""),
            content=data.get("content", ""),
            memory_type=_parse_enum(MemoryType, data.get("memory_type"), MemoryType.SEMANTIC),
            category=_parse_enum(MemoryCategory, data.get("category"), MemoryCategory.GENERAL),
            lifecycle_stage=_parse_enum(LifecycleStage, data.get("lifecycle_stage"), LifecycleStage.ACTIVE),
            perspective=_parse_enum(MemoryPerspective, data.get("perspective"), MemoryPerspective.FIRST_PERSON),
            emotion=_parse_enum(EmotionType, data.get("emotion"), EmotionType.NEUTRAL),
            temperature=data.get("temperature", 100.0),
            importance=data.get("importance", 50.0),
            access_count=data.get("access_count", 0),
            metadata=data.get("metadata", {}),
            agent_id=data.get("agent_id", ""),
            neuser_id=data.get("neuser_id", ""),
            user_id=data.get("user_id", ""),
            shared=data.get("shared", False),
            share_group_ids=data.get("share_group_ids", []),
            created_at=_parse_dt(data.get("created_at")),
            updated_at=_parse_dt(data.get("updated_at")),
            isolation_context=isolation_context,
        )
