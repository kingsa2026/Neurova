# -*- coding: utf-8 -*-
"""
工作流数据模型

定义工作流执行过程中的数据结构。
"""

import time
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class FlowPhase(str, Enum):
    """工作流执行阶段"""
    IDLE = "idle"                      # 空闲
    INITIALIZATION = "initialization"  # 初始化
    PLANNING = "planning"              # 规划
    EXECUTION = "execution"            # 执行
    CONVERSATION = "conversation"      # 对话
    REVIEW = "review"                  # 评审
    COMPLETION = "completion"          # 完成
    FAILED = "failed"                  # 失败
    CANCELLED = "cancelled"            # 取消


class FlowEvent(str, Enum):
    """工作流事件类型"""
    PHASE_CHANGED = "phase_changed"              # 阶段变更
    STEP_STARTED = "step_started"                # 步骤开始
    STEP_COMPLETED = "step_completed"            # 步骤完成
    STEP_FAILED = "step_failed"                  # 步骤失败
    TASK_ASSIGNED = "task_assigned"              # 任务分配
    TASK_REASSIGNED = "task_reassigned"          # 任务重新分配
    APPROVAL_REQUESTED = "approval_requested"    # 请求批准
    APPROVAL_GRANTED = "approval_granted"        # 批准
    APPROVAL_REJECTED = "approval_rejected"      # 拒绝
    WORKFLOW_COMPLETED = "workflow_completed"    # 工作流完成
    WORKFLOW_FAILED = "workflow_failed"          # 工作流失败
    WORKFLOW_CANCELLED = "workflow_cancelled"    # 工作流取消


@dataclass
class FlowContext:
    """工作流执行上下文"""
    flow_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    template_id: str = ""                                    # 关联的模板ID
    current_phase: FlowPhase = FlowPhase.INITIALIZATION      # 当前阶段
    current_step_id: Optional[str] = None                   # 当前步骤ID
    
    # 执行状态
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    failed_at: Optional[float] = None
    
    # 参与者
    participants: Dict[str, str] = field(default_factory=dict)  # agent_id -> role
    active_agents: List[str] = field(default_factory=list)      # 当前活跃的agent
    
    # 步骤状态
    completed_steps: List[str] = field(default_factory=list)    # 已完成的步骤ID
    failed_steps: List[str] = field(default_factory=list)       # 失败的步骤ID
    skipped_steps: List[str] = field(default_factory=list)      # 跳过的步骤ID
    
    # 数据存储
    step_outputs: Dict[str, Any] = field(default_factory=dict)  # step_id -> output
    shared_data: Dict[str, Any] = field(default_factory=dict)   # 共享数据
    
    # 事件历史
    event_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # 错误信息
    error_message: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None
    
    def add_event(self, event_type: FlowEvent, data: Dict[str, Any] = None) -> None:
        """添加事件到历史"""
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type.value if isinstance(event_type, FlowEvent) else event_type,
            "timestamp": time.time(),
            "phase": self.current_phase.value if isinstance(self.current_phase, FlowPhase) else self.current_phase,
            "step_id": self.current_step_id,
            "data": data or {},
        }
        self.event_history.append(event)
        self.updated_at = time.time()
    
    def set_phase(self, phase: FlowPhase) -> None:
        """设置当前阶段"""
        old_phase = self.current_phase
        self.current_phase = phase
        self.updated_at = time.time()
        self.add_event(FlowEvent.PHASE_CHANGED, {
            "old_phase": old_phase.value if isinstance(old_phase, FlowPhase) else old_phase,
            "new_phase": phase.value if isinstance(phase, FlowPhase) else phase,
        })
    
    def complete_step(self, step_id: str, output: Any = None) -> None:
        """标记步骤完成"""
        if step_id not in self.completed_steps:
            self.completed_steps.append(step_id)
        if output is not None:
            self.step_outputs[step_id] = output
        self.updated_at = time.time()
        self.add_event(FlowEvent.STEP_COMPLETED, {"step_id": step_id})
    
    def fail_step(self, step_id: str, error: str = None) -> None:
        """标记步骤失败"""
        if step_id not in self.failed_steps:
            self.failed_steps.append(step_id)
        self.updated_at = time.time()
        self.add_event(FlowEvent.STEP_FAILED, {"step_id": step_id, "error": error})
    
    def skip_step(self, step_id: str) -> None:
        """跳过步骤"""
        if step_id not in self.skipped_steps:
            self.skipped_steps.append(step_id)
        self.updated_at = time.time()
    
    def is_step_completed(self, step_id: str) -> bool:
        """检查步骤是否已完成"""
        return step_id in self.completed_steps
    
    def is_step_failed(self, step_id: str) -> bool:
        """检查步骤是否失败"""
        return step_id in self.failed_steps
    
    def get_step_output(self, step_id: str) -> Any:
        """获取步骤输出"""
        return self.step_outputs.get(step_id)
    
    def set_shared_data(self, key: str, value: Any) -> None:
        """设置共享数据"""
        self.shared_data[key] = value
        self.updated_at = time.time()
    
    def get_shared_data(self, key: str, default: Any = None) -> Any:
        """获取共享数据"""
        return self.shared_data.get(key, default)
    
    def complete(self) -> None:
        """标记工作流完成"""
        self.current_phase = FlowPhase.COMPLETION
        self.completed_at = time.time()
        self.updated_at = time.time()
        self.add_event(FlowEvent.WORKFLOW_COMPLETED)
    
    def fail(self, error: str = None, details: Dict[str, Any] = None) -> None:
        """标记工作流失败"""
        self.current_phase = FlowPhase.FAILED
        self.failed_at = time.time()
        self.updated_at = time.time()
        self.error_message = error
        self.error_details = details
        self.add_event(FlowEvent.WORKFLOW_FAILED, {"error": error})
    
    def cancel(self) -> None:
        """取消工作流"""
        self.current_phase = FlowPhase.CANCELLED
        self.completed_at = time.time()
        self.updated_at = time.time()
        self.add_event(FlowEvent.WORKFLOW_CANCELLED)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "flow_id": self.flow_id,
            "template_id": self.template_id,
            "current_phase": self.current_phase.value if isinstance(self.current_phase, FlowPhase) else self.current_phase,
            "current_step_id": self.current_step_id,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "failed_at": self.failed_at,
            "participants": self.participants,
            "active_agents": self.active_agents,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "skipped_steps": self.skipped_steps,
            "step_outputs": self.step_outputs,
            "shared_data": self.shared_data,
            "event_count": len(self.event_history),
            "error_message": self.error_message,
        }


@dataclass
class ScheduledTask:
    """计划任务"""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""                                          # 任务名称
    description: str = ""                                   # 任务描述
    
    # 调度配置
    scheduled_at: Optional[float] = None                   # 计划执行时间
    interval_seconds: Optional[int] = None                 # 重复间隔（秒）
    cron_expression: Optional[str] = None                  # Cron 表达式
    
    # 执行配置
    agent_id: str = ""                                      # 执行的 Agent ID
    action: str = ""                                        # 执行的动作
    parameters: Dict[str, Any] = field(default_factory=dict)  # 动作参数
    
    # 状态
    status: str = "pending"                                 # pending, running, completed, failed, cancelled
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_run_at: Optional[float] = None
    next_run_at: Optional[float] = None
    run_count: int = 0
    max_runs: Optional[int] = None                         # 最大执行次数
    
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
            self.next_run_at = time.time() + self.interval_seconds
            self.status = "pending"
        elif self.cron_expression:
            # TODO: 实现 cron 表达式解析
            pass
    
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