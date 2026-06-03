# -*- coding: utf-8 -*-
"""
协作系统数据模型

定义协作模板、角色、任务步骤和工作流的数据结构。
"""

import time
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class TemplateType(str, Enum):
    """协作模板类型"""
    CODE_REVIEW = "code_review"           # 代码评审
    PAIR_PROGRAMMING = "pair_programming"  # 结对编程
    DIAGNOSTIC = "diagnostic"              # 问题诊断
    KNOWLEDGE_SHARING = "knowledge_sharing"  # 知识共享
    CUSTOM = "custom"                      # 自定义模板


class AgentRole(str, Enum):
    """Agent 角色"""
    COORDINATOR = "coordinator"           # 协调者
    REVIEWER = "reviewer"                 # 评审者
    AUTHOR = "author"                     # 作者/执行者
    TEACHER = "teacher"                   # 教师
    LEARNER = "learner"                   # 学习者
    DIAGNOSTIC = "diagnostic"             # 诊断者
    SOLVER = "solver"                     # 解决者
    OBSERVER = "observer"                 # 观察者
    PARTICIPANT = "participant"           # 参与者


@dataclass
class TaskStep:
    """协作任务步骤"""
    step_id: str = ""                                    # 步骤ID
    name: str = ""                                       # 步骤名称
    description: str = ""                                # 步骤描述
    assigned_role: AgentRole = AgentRole.PARTICIPANT     # 负责角色
    required_capabilities: List[str] = field(default_factory=list)  # 所需能力
    input_requirements: Dict[str, Any] = field(default_factory=dict)  # 输入要求
    output_produces: List[str] = field(default_factory=list)  # 输出产物
    depends_on: List[str] = field(default_factory=list)   # 依赖步骤
    timeout_seconds: int = 300                            # 超时时间
    optional: bool = False                               # 是否可选
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "step_id": self.step_id,
            "name": self.name,
            "description": self.description,
            "assigned_role": self.assigned_role.value if isinstance(self.assigned_role, AgentRole) else self.assigned_role,
            "required_capabilities": self.required_capabilities,
            "input_requirements": self.input_requirements,
            "output_produces": self.output_produces,
            "depends_on": self.depends_on,
            "timeout_seconds": self.timeout_seconds,
            "optional": self.optional,
        }


@dataclass
class WorkflowDefinition:
    """工作流定义"""
    workflow_id: str = ""                              # 工作流ID
    name: str = ""                                      # 工作流名称
    description: str = ""                               # 工作流描述
    steps: List[TaskStep] = field(default_factory=list) # 任务步骤
    parallel_allowed: bool = False                      # 是否允许并行
    max_concurrent_steps: int = 2                       # 最大并行步骤数
    rollback_on_failure: bool = True                    # 失败时是否回滚
    
    def get_step(self, step_id: str) -> Optional[TaskStep]:
        """获取指定步骤"""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None
    
    def get_step_order(self) -> List[str]:
        """获取拓扑排序后的步骤顺序"""
        # 简单的拓扑排序
        step_ids = {s.step_id for s in self.steps}
        order = []
        remaining = set(step_ids)
        completed = set()
        
        while remaining:
            # 找一个没有未完成依赖的步骤
            for step_id in list(remaining):
                step = self.get_step(step_id)
                if step and all(d in completed for d in step.depends_on):
                    order.append(step_id)
                    completed.add(step_id)
                    remaining.remove(step_id)
                    break
            else:
                # 有循环依赖，选择第一个
                order.append(next(iter(remaining)))
                remaining.remove(next(iter(remaining)))
        
        return order
    
    def validate(self) -> tuple[bool, List[str]]:
        """验证工作流定义
        
        Returns:
            (是否有效, 错误列表)
        """
        errors = []
        
        # 检查步骤ID唯一性
        step_ids = [s.step_id for s in self.steps]
        if len(step_ids) != len(set(step_ids)):
            errors.append("步骤ID必须唯一")
        
        # 检查依赖的有效性
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    errors.append(f"步骤 {step.step_id} 引用了不存在的依赖 {dep}")
        
        # 检查循环依赖
        try:
            self.get_step_order()
        except Exception as e:
            errors.append(f"工作流存在循环依赖: {e}")
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "parallel_allowed": self.parallel_allowed,
            "max_concurrent_steps": self.max_concurrent_steps,
            "rollback_on_failure": self.rollback_on_failure,
        }