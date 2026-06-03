from __future__ import annotations

"""
上下文系统数据模型

包含:
- ContextPriority: 上下文优先级枚举
- TokenBudget: Token 预算配置
- ContextEntry: 上下文条目
- ContextBuildResult: 上下文构建结果
"""

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

class ContextPriority(Enum):
    """上下文优先级"""
    CRITICAL = 100   # 系统提示、固化记忆
    HIGH = 80        # 高温记忆、反思日志
    NORMAL = 50      # 普通记忆
    LOW = 20         # 低温记忆、归档内容

@dataclass
class TokenBudget:
    """Token 预算配置 - 增强版"""
    max_total: int = 16000
    system_prompt: int = 1500
    reflection_log: int = 1000
    memories: int = 4000
    conversation_history: int = 6000
    experience_knowledge: int = 1500
    emotion_context: int = 500

    @property
    def chinese_ratio(self) -> float:
        return 1.5

    @property
    def english_ratio(self) -> float:
        return 0.25

@dataclass
class ContextEntry:
    """上下文条目"""
    id: str
    content: str
    priority: ContextPriority
    category: str
    temperature: float = 50.0
    is_crystallized: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: dt.datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'content': self.content,
            'priority': self.priority.value,
            'category': self.category,
            'temperature': self.temperature,
            'is_crystallized': self.is_crystallized,
            'metadata': self.metadata,
            'created_at': self.created_at,
        }

@dataclass
class ContextBuildResult:
    """上下文构建结果"""
    context: List[Dict[str, str]]
    total_tokens: int
    compression_ratio: float
    reflection_count: int
    memory_count: int
    history_count: int
    stats: Dict[str, Any]
