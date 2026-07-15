"""
工具层共享类型定义（ADR 0009 / 0010 规范位置）。

本模块是工具层跨模块共享类型的单一规范定义来源：
- ExecutionStatus: 工具执行状态枚举（ADR 0009）
- TimeoutStrategy: 超时策略枚举
- ToolExecutionContext: 工具执行上下文 dataclass（ADR 0010）

其他模块应从本模块 import 这些类型，禁止本地重复定义。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class ExecutionStatus(str, Enum):
    """工具执行状态 — 单一规范定义（ADR 0009）。

    继承 (str, Enum) 使 `ExecutionStatus.COMPLETED == "completed"` 成立，
    与既有字符串比较代码兼容。
    """

    PENDING = "pending"          # 等待执行
    RUNNING = "running"          # 执行中
    COMPLETED = "completed"      # 执行完成（兼容 orchestrator 旧 SUCCESS 语义）
    FAILED = "failed"            # 执行失败
    CANCELLED = "cancelled"      # 已取消
    TIMEOUT = "timeout"         # 执行超时
    SKIPPED = "skipped"          # 跳过（orchestrator 独有，保留）


class TimeoutStrategy(Enum):
    """超时策略枚举。"""

    STRICT = "strict"        # 严格超时
    ELASTIC = "elastic"      # 弹性超时（自动续时）
    INFINITE = "infinite"    # 无限等待


@dataclass
class ToolExecutionContext:
    """工具执行上下文 — 单一规范定义（ADR 0010）。

    14 字段版本，支持完整的执行状态承载（含 result/error/status/retries）。
    """

    context_id: str
    tool_name: str
    params: Dict[str, Any]
    user_input: str
    timeout: float = 30.0
    strategy: TimeoutStrategy = TimeoutStrategy.STRICT
    status: ExecutionStatus = ExecutionStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    retries: int = 0
    max_retries: int = 3
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "context_id": self.context_id,
            "tool_name": self.tool_name,
            "params": self.params,
            "user_input": self.user_input,
            "timeout": self.timeout,
            "strategy": self.strategy.value,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "retries": self.retries,
            "max_retries": self.max_retries,
            "metadata": self.metadata,
        }
