from __future__ import annotations

"""
上下文池数据模型 - Context Pool Models

ContextSource 和 ContextInput 是 context_pool 模块的核心数据类型，
提取到独立模块以避免循环导入。
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List


class ContextSource(Enum):
    """上下文来源枚举"""

    SYSTEM_INSTRUCTION = "system_instruction"  # 系统指令
    DEVELOPER_INSTRUCTION = "developer_instruction"  # 开发者指令
    MEMORY = "memory"  # 记忆
    CONVERSATION = "conversation"  # 对话历史
    EXPERIENCE = "experience"  # 经验知识
    EMOTION = "emotion"  # 情感状态
    REFLECTION = "reflection"  # 反思日志
    TOOL_CALL = "tool_call"  # 工具调用
    MULTIMODAL = "multimodal"  # 多模态内容
    USER_INPUT = "user_input"  # 用户输入
    SUMMARY = "summary"  # 溢出折叠摘要（P1-1③：压缩视图而非丢内容）


@dataclass
class ContextInput:
    """上下文输入数据类 - 活水上下文池的基础单元"""

    source: ContextSource
    content: str
    priority: int = 50
    metadata: Dict[str, Any] = field(default_factory=dict)
    tokens: int = 0
    tags: List[str] = field(default_factory=list)  # 标签列表
    hash: str = None  # 内容哈希（用于精确去重）
    created_at: datetime = None  # 创建时间
    updated_at: datetime = None  # 更新时间

    def __post_init__(self):
        """初始化后处理"""
        # 自动生成哈希
        if self.hash is None:
            self.hash = self.compute_hash(self.source, self.content)

        # 自动设置时间
        now = datetime.now()
        if self.created_at is None:
            self.created_at = now
        if self.updated_at is None:
            self.updated_at = now

    @classmethod
    def compute_hash(cls, source: "ContextSource", content: str) -> str:
        """统一的内容指纹入口（source 域限定去重指纹，非安全用途）。

        任何需要在池外判断"内容是否已归档"的场景（如对话窗口排除重复调取）
        都必须经由本方法计算，保证与 __post_init__ 的去重哈希同源。
        """
        raw = f"{source.value}:{content}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "source": self.source.value,
            "content": self.content,
            "priority": self.priority,
            "metadata": self.metadata,
            "tokens": self.tokens,
            "tags": self.tags,
            "hash": self.hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
