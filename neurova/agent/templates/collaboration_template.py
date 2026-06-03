# -*- coding: utf-8 -*-
"""
Agent 协作模板定义

提供协作模板的数据结构和默认实现。
"""

import json
import logging
import time
import uuid
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)

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

@dataclass
class CollaborationTemplate:
    """Agent 协作模板"""
    template_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""                                        # 模板名称
    description: str = ""                                 # 模板描述
    template_type: TemplateType = TemplateType.CUSTOM     # 模板类型
    version: str = "1.0"                                 # 模板版本

    # Agent 配置
    roles: Dict[str, AgentRole] = field(default_factory=dict)  # agent_id -> role
    role_requirements: Dict[str, List[str]] = field(default_factory=dict)  # role -> required capabilities

    # 工作流定义
    workflow: WorkflowDefinition = None                   # 工作流定义

    # 模板配置
    max_participants: int = 5                             # 最大参与者数
    min_participants: int = 2                             # 最小参与者数
    timeout_seconds: int = 3600                           # 默认超时时间
    allow_observer: bool = True                          # 是否允许观察者

    # 元数据
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    created_by: str = "system"                            # 创建者
    tags: List[str] = field(default_factory=list)        # 标签
    is_preset: bool = False                              # 是否为预设模板

    def __post_init__(self):
        """初始化后处理"""
        if self.workflow is None:
            self.workflow = WorkflowDefinition()

    def get_role_agents(self, role: AgentRole) -> List[str]:
        """获取指定角色的所有 Agent"""
        return [
            agent_id for agent_id, r in self.roles.items()
            if r == role
        ]

    def assign_role(self, agent_id: str, role: AgentRole) -> None:
        """分配角色"""
        self.roles[agent_id] = role
        self.updated_at = time.time()

    def unassign_role(self, agent_id: str) -> Optional[AgentRole]:
        """取消角色分配"""
        role = self.roles.pop(agent_id, None)
        if role:
            self.updated_at = time.time()
        return role

    def get_required_capabilities(self) -> List[str]:
        """获取所需能力列表"""
        capabilities = set()
        for role, caps in self.role_requirements.items():
            capabilities.update(caps)
        return list(capabilities)

    def validate(self) -> tuple[bool, List[str]]:
        """验证模板

        Returns:
            (是否有效, 错误列表)
        """
        errors = []

        # 检查基本字段
        if not self.name:
            errors.append("模板名称不能为空")

        if not self.workflow.steps:
            errors.append("工作流必须包含至少一个步骤")

        # 检查参与者数量
        if len(self.roles) > self.max_participants:
            errors.append(f"参与者数量 ({len(self.roles)}) 超过最大限制 ({self.max_participants})")

        if len(self.roles) < self.min_participants:
            errors.append(f"参与者数量 ({len(self.roles)}) 少于最小要求 ({self.min_participants})")

        # 验证工作流
        workflow_valid, workflow_errors = self.workflow.validate()
        if not workflow_valid:
            errors.extend(workflow_errors)

        return len(errors) == 0, errors

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "template_type": self.template_type.value if isinstance(self.template_type, TemplateType) else self.template_type,
            "version": self.version,
            "roles": {k: v.value for k, v in self.roles.items()},
            "role_requirements": self.role_requirements,
            "workflow": self.workflow.to_dict() if self.workflow else {},
            "max_participants": self.max_participants,
            "min_participants": self.min_participants,
            "timeout_seconds": self.timeout_seconds,
            "allow_observer": self.allow_observer,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "tags": self.tags,
            "is_preset": self.is_preset,
        }

    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CollaborationTemplate":
        """从字典创建"""
        # 转换角色
        roles = {}
        for agent_id, role in data.get("roles", {}).items():
            roles[agent_id] = AgentRole(role) if isinstance(role, str) else role

        # 转换工作流
        workflow_data = data.get("workflow", {})
        if workflow_data:
            steps = []
            for step_data in workflow_data.get("steps", []):
                step = TaskStep(
                    step_id=step_data.get("step_id", ""),
                    name=step_data.get("name", ""),
                    description=step_data.get("description", ""),
                    assigned_role=AgentRole(step_data.get("assigned_role", "participant")),
                    required_capabilities=step_data.get("required_capabilities", []),
                    input_requirements=step_data.get("input_requirements", {}),
                    output_produces=step_data.get("output_produces", []),
                    depends_on=step_data.get("depends_on", []),
                    timeout_seconds=step_data.get("timeout_seconds", 300),
                    optional=step_data.get("optional", False),
                )
                steps.append(step)

            workflow = WorkflowDefinition(
                workflow_id=workflow_data.get("workflow_id", ""),
                name=workflow_data.get("name", ""),
                description=workflow_data.get("description", ""),
                steps=steps,
                parallel_allowed=workflow_data.get("parallel_allowed", False),
                max_concurrent_steps=workflow_data.get("max_concurrent_steps", 2),
                rollback_on_failure=workflow_data.get("rollback_on_failure", True),
            )
        else:
            workflow = WorkflowDefinition()

        return cls(
            template_id=data.get("template_id", str(uuid.uuid4())),
            name=data.get("name", ""),
            description=data.get("description", ""),
            template_type=TemplateType(data.get("template_type", "custom")),
            version=data.get("version", "1.0"),
            roles=roles,
            role_requirements=data.get("role_requirements", {}),
            workflow=workflow,
            max_participants=data.get("max_participants", 5),
            min_participants=data.get("min_participants", 2),
            timeout_seconds=data.get("timeout_seconds", 3600),
            allow_observer=data.get("allow_observer", True),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            created_by=data.get("created_by", "system"),
            tags=data.get("tags", []),
            is_preset=data.get("is_preset", False),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "CollaborationTemplate":
        """从 JSON 字符串创建"""
        return cls.from_dict(json.loads(json_str))

class TemplateManager:
    """协作模板管理器"""

    def __init__(self):
        self._templates: Dict[str, CollaborationTemplate] = {}
        self._type_index: Dict[TemplateType, List[str]] = {}  # type -> list of template_ids
        self._tag_index: Dict[str, List[str]] = {}  # tag -> list of template_ids

    def register_template(self, template: CollaborationTemplate) -> bool:
        """
        注册协作模板

        Args:
            template: 协作模板

        Returns:
            是否注册成功
        """
        # 验证模板
        valid, errors = template.validate()
        if not valid:
            logger.error(f"模板验证失败: {errors}")
            return False

        self._templates[template.template_id] = template

        # 更新索引
        self._update_type_index(template)
        self._update_tag_index(template)

        logger.info(f"模板已注册: {template.name} ({template.template_id})")
        return True

    def unregister_template(self, template_id: str) -> bool:
        """取消注册模板"""
        if template_id not in self._templates:
            return False

        template = self._templates.pop(template_id)

        # 从索引中移除
        self._remove_from_type_index(template)
        self._remove_from_tag_index(template)

        logger.info(f"模板已取消注册: {template.name}")
        return True

    def get_template(self, template_id: str) -> Optional[CollaborationTemplate]:
        """获取指定模板"""
        return self._templates.get(template_id)

    def list_templates(self, template_type: TemplateType = None,
                      tags: List[str] = None) -> List[CollaborationTemplate]:
        """
        列出模板

        Args:
            template_type: 按类型过滤
            tags: 按标签过滤

        Returns:
            模板列表
        """
        templates = list(self._templates.values())

        if template_type:
            templates = [t for t in templates if t.template_type == template_type]

        if tags:
            templates = [t for t in templates if any(tag in t.tags for tag in tags)]

        return templates

    def search_templates(self, query: str) -> List[CollaborationTemplate]:
        """搜索模板"""
        query_lower = query.lower()
        results = []

        for template in self._templates.values():
            # 搜索名称
            if query_lower in template.name.lower():
                results.append(template)
                continue

            # 搜索描述
            if query_lower in template.description.lower():
                results.append(template)
                continue

            # 搜索标签
            for tag in template.tags:
                if query_lower in tag.lower():
                    results.append(template)
                    break

        return results

    def clone_template(self, template_id: str, new_name: str = None) -> Optional[CollaborationTemplate]:
        """
        克隆模板

        Args:
            template_id: 原模板ID
            new_name: 新模板名称

        Returns:
            克隆的新模板
        """
        original = self.get_template(template_id)
        if original is None:
            return None

        cloned = CollaborationTemplate.from_dict(original.to_dict())
        cloned.template_id = str(uuid.uuid4())
        cloned.name = new_name or f"{original.name} (副本)"
        cloned.created_at = time.time()
        cloned.updated_at = time.time()
        cloned.created_by = "cloned"
        cloned.is_preset = False

        return cloned

    def _update_type_index(self, template: CollaborationTemplate) -> None:
        """更新类型索引"""
        template_type = template.template_type
        if isinstance(template_type, str):
            template_type = TemplateType(template_type)

        if template_type not in self._type_index:
            self._type_index[template_type] = []
        if template.template_id not in self._type_index[template_type]:
            self._type_index[template_type].append(template.template_id)

    def _update_tag_index(self, template: CollaborationTemplate) -> None:
        """更新标签索引"""
        for tag in template.tags:
            if tag not in self._tag_index:
                self._tag_index[tag] = []
            if template.template_id not in self._tag_index[tag]:
                self._tag_index[tag].append(template.template_id)

    def _remove_from_type_index(self, template: CollaborationTemplate) -> None:
        """从类型索引移除"""
        template_type = template.template_type
        if isinstance(template_type, str):
            template_type = TemplateType(template_type)

        if template_type in self._type_index:
            self._type_index[template_type].remove(template.template_id)

    def _remove_from_tag_index(self, template: CollaborationTemplate) -> None:
        """从标签索引移除"""
        for tag in template.tags:
            if tag in self._tag_index:
                self._tag_index[tag].remove(template.template_id)

# 全局模板管理器实例
_global_template_manager: Optional[TemplateManager] = None

def get_template_manager() -> TemplateManager:
    """获取全局模板管理器"""
    global _global_template_manager
    if _global_template_manager is None:
        _global_template_manager = TemplateManager()
        # 注册预设模板
        from .preset_templates import PRESET_TEMPLATES
        for template in PRESET_TEMPLATES:
            _global_template_manager.register_template(template)
    return _global_template_manager
