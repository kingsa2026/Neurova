# -*- coding: utf-8 -*-
"""
工作流数据模型

定义工作流执行过程中的数据结构。
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class FlowContext:
    """工作流执行上下文"""

    flow_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    template_id: str = ""  # 关联的模板ID
    current_step_id: Optional[str] = None  # 当前步骤ID

    # 执行状态
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    failed_at: Optional[float] = None

    # 参与者
    participants: Dict[str, str] = field(default_factory=dict)  # agent_id -> role
    active_agents: List[str] = field(default_factory=list)  # 当前活跃的agent

    # 步骤状态
    completed_steps: List[str] = field(default_factory=list)  # 已完成的步骤ID
    failed_steps: List[str] = field(default_factory=list)  # 失败的步骤ID
    skipped_steps: List[str] = field(default_factory=list)  # 跳过的步骤ID

    # 数据存储
    step_outputs: Dict[str, Any] = field(default_factory=dict)  # step_id -> output
    shared_data: Dict[str, Any] = field(default_factory=dict)  # 共享数据

    # 错误信息
    error_message: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None

def compute_next_run(
    cron_expression: Optional[str] = None,
    interval_seconds: Optional[int] = None,
    after: Optional[float] = None,
) -> Optional[float]:
    """计算下一次触发时间戳。

    - interval: after + interval_seconds;
    - cron(5 段 分 时 日 月 周): APScheduler CronTrigger 语义
      (day_of_week 数字 0=周一..6=周日, 与前端可视化构建器一致), 忽略 after 的秒数;
    - 两者皆无 → None(单次任务, 不排程)。

    返回 None 时任务不循环(单次触发或表达式不可解析)。
    """
    import time
    from datetime import datetime

    try:
        if interval_seconds and interval_seconds > 0:
            base = after if after is not None else time.time()
            return base + interval_seconds
        if cron_expression:
            from apscheduler.triggers.cron import CronTrigger
            import zoneinfo

            parts = cron_expression.split()
            if len(parts) < 5:
                return None
            tz = zoneinfo.ZoneInfo("Asia/Shanghai")
            base = after if after is not None else time.time()
            trigger = CronTrigger(
                minute=parts[0], hour=parts[1], day=parts[2],
                month=parts[3], day_of_week=parts[4], timezone=tz,
            )
            nxt = trigger.get_next_fire_time(None, datetime.fromtimestamp(base, tz=tz))
            return nxt.timestamp() if nxt is not None else None
    except Exception:
        return None
    return None

@dataclass
class ScheduledTask:
    """计划任务"""

    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""  # 任务名称
    description: str = ""  # 任务描述

    # 调度配置
    scheduled_at: Optional[float] = None  # 计划执行时间
    interval_seconds: Optional[int] = None  # 重复间隔（秒）
    cron_expression: Optional[str] = None  # Cron 表达式

    # 执行配置
    agent_id: str = ""  # 执行的 Agent ID
    action: str = ""  # 执行的动作
    parameters: Dict[str, Any] = field(default_factory=dict)  # 动作参数

    # 状态
    status: str = "pending"  # pending, running, completed, failed, cancelled
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_run_at: Optional[float] = None
    next_run_at: Optional[float] = None
    run_count: int = 0
    max_runs: Optional[int] = None  # 最大执行次数

    # 结果
    last_result: Optional[Any] = None
    last_error: Optional[str] = None

    def is_due(self) -> bool:
        """检查任务是否到期"""
        if self.status != "pending":
            return False

        if self.scheduled_at and time.time() >= self.scheduled_at:
            return True

        if self.next_run_at and time.time() >= self.next_run_at:
            return True

        return False

    def mark_running(self) -> None:
        """标记为运行中"""
        self.status = "running"
        self.updated_at = time.time()

    def mark_completed(self, result: Any = None) -> None:
        """标记为完成"""
        self.status = "completed"
        self.last_result = result
        self.last_run_at = time.time()
        self.run_count += 1
        self.updated_at = time.time()

        # 计算下次运行时间
        if self.interval_seconds:
            self.next_run_at = compute_next_run(interval_seconds=self.interval_seconds)
            self.status = "pending"
        elif self.cron_expression:
            # cron 循环: 计算下一次触发; 表达式不可解析时保持 completed(不再触发)
            self.next_run_at = compute_next_run(cron_expression=self.cron_expression)
            if self.next_run_at is not None:
                self.status = "pending"

    def mark_failed(self, error: str = None) -> None:
        """标记为失败"""
        self.status = "failed"
        self.last_error = error
        self.last_run_at = time.time()
        self.run_count += 1
        self.updated_at = time.time()

    def cancel(self) -> None:
        """取消任务"""
        self.status = "cancelled"
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "description": self.description,
            "scheduled_at": self.scheduled_at,
            "interval_seconds": self.interval_seconds,
            "cron_expression": self.cron_expression,
            "agent_id": self.agent_id,
            "action": self.action,
            "parameters": self.parameters,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_run_at": self.last_run_at,
            "next_run_at": self.next_run_at,
            "run_count": self.run_count,
            "max_runs": self.max_runs,
        }
