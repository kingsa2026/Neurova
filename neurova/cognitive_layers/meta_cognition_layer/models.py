"""
Meta-cognition Layer Models - 元认知层数据模型

定义元认知层所需的数据模型
"""

from dataclasses import dataclass
import datetime
import enum
import typing
import uuid

from enum import Enum
from neurova.mem_core import Memory

# cognitive_layers imports
import neurova.cognitive_layers.memory_layer.models

class SkillCategory(str, Enum):
    """技能分类"""
    COGNITIVE = "cognitive"       # 认知技能
    MEMORY = "memory"             # 记忆技能
    REASONING = "reasoning"       # 推理技能
    LEARNING = "learning"         # 学习技能
    COMMUNICATION = "communication"  # 沟通技能
    EXECUTION = "execution"       # 执行技能
    MONITORING = "monitoring"     # 监控技能
    INTEGRATION = "integration"   # 集成技能


class SkillStatus(str, Enum):
    """技能状态"""
    INACTIVE = "inactive"         # 未激活
    ACTIVE = "active"             # 激活
    LEARNING = "learning"         # 学习中
    MASTERED = "mastered"         # 已掌握
    DEPRECATED = "deprecated"     # 已废弃
    BROKEN = "broken"             # 已损坏


@dataclass
class Skill:
    """技能"""
    skill_id: str
    name: str
    description: str
    category: SkillCategory
    version: str = "1.0.0"
    status: SkillStatus = SkillStatus.INACTIVE
    parameters: Dict[str, Any] = None
    dependencies: List[str] = None
    examples: List[Dict[str, Any]] = None
    success_rate: float = 0.0
    execution_count: int = 0
    last_used: Optional[float] = None
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {}
        if self.dependencies is None:
            self.dependencies = []
        if self.examples is None:
            self.examples = []
        if self.metadata is None:
            self.metadata = {}
        if self.created_at == 0.0:
            self.created_at = time.time()
        if self.updated_at == 0.0:
            self.updated_at = self.created_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "version": self.version,
            "status": self.status.value,
            "parameters": self.parameters,
            "dependencies": self.dependencies,
            "examples": self.examples,
            "success_rate": self.success_rate,
            "execution_count": self.execution_count,
            "last_used": self.last_used,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Skill":
        return cls(
            skill_id=data["skill_id"],
            name=data["name"],
            description=data["description"],
            category=SkillCategory(data["category"]),
            version=data.get("version", "1.0.0"),
            status=SkillStatus(data.get("status", "inactive")),
            parameters=data.get("parameters", {}),
            dependencies=data.get("dependencies", []),
            examples=data.get("examples", []),
            success_rate=data.get("success_rate", 0.0),
            execution_count=data.get("execution_count", 0),
            last_used=data.get("last_used"),
            created_at=data.get("created_at", 0.0),
            updated_at=data.get("updated_at", 0.0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class SkillExecutionRecord:
    """技能执行记录"""
    record_id: str
    skill_id: str
    task_id: str
    start_time: float
    end_time: float = 0.0
    success: bool = False
    input_data: Dict[str, Any] = None
    output_data: Dict[str, Any] = None
    error_message: str = ""
    execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.input_data is None:
            self.input_data = {}
        if self.output_data is None:
            self.output_data = {}
        if self.metadata is None:
            self.metadata = {}
        if self.end_time == 0.0:
            self.end_time = self.start_time
        if self.execution_time_ms == 0.0:
            self.execution_time_ms = (self.end_time - self.start_time) * 1000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "skill_id": self.skill_id,
            "task_id": self.task_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "success": self.success,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "error_message": self.error_message,
            "execution_time_ms": self.execution_time_ms,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillExecutionRecord":
        return cls(
            record_id=data["record_id"],
            skill_id=data["skill_id"],
            task_id=data["task_id"],
            start_time=data["start_time"],
            end_time=data.get("end_time", 0.0),
            success=data.get("success", False),
            input_data=data.get("input_data", {}),
            output_data=data.get("output_data", {}),
            error_message=data.get("error_message", ""),
            execution_time_ms=data.get("execution_time_ms", 0.0),
            metadata=data.get("metadata", {}),
        )


class MemoryCategory(str, Enum):
    """记忆分类"""
    EPISODIC = "episodic"         # 情景记忆
    SEMANTIC = "semantic"         # 语义记忆
    PROCEDURAL = "procedural"     # 程序记忆
    SHORT_TERM = "short_term"     # 短期记忆
    LONG_TERM = "long_term"       # 长期记忆
    WORKING = "working"           # 工作记忆
    EMOTIONAL = "emotional"       # 情感记忆
    SENSORY = "sensory"           # 感官记忆
