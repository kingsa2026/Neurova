"""
工作流引擎

Neurova CogArch 1.0.0 的执行组件之一
负责：工作流定义、流程调度、状态管理
"""

from __future__ import annotations

import asyncio
import datetime
from neurova.core.logger import get_logger
import typing
import uuid
from dataclasses import dataclass, field
from enum import Enum

logger = get_logger(__name__)


class WorkflowStatus(Enum):
    """工作流状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class NodeType(Enum):
    """节点类型"""

    TASK = "task"
    CONDITION = "condition"
    PARALLEL = "parallel"
    LOOP = "loop"
    START = "start"
    END = "end"


@dataclass
class WorkflowNode:
    """工作流节点"""

    node_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    node_type: NodeType = NodeType.TASK
    action: str = ""
    parameters: typing.Dict[str, typing.Any] = field(default_factory=dict)
    next_nodes: typing.List[str] = field(default_factory=list)
    condition: typing.Optional[str] = None
    timeout: float = 30

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "node_type": self.node_type.value,
            "action": self.action,
            "parameters": self.parameters,
            "next_nodes": self.next_nodes,
            "condition": self.condition,
            "timeout": self.timeout,
        }


@dataclass
class WorkflowDefinition:
    """工作流定义"""

    workflow_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    nodes: typing.Dict[str, WorkflowNode] = field(default_factory=dict)
    start_node: str = ""
    variables: typing.Dict[str, typing.Any] = field(default_factory=dict)
    version: str = "1.0.0"
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "start_node": self.start_node,
            "variables": self.variables,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> "WorkflowDefinition":
        wf = cls()
        wf.workflow_id = data.get("workflow_id", wf.workflow_id)
        wf.name = data.get("name", "")
        wf.description = data.get("description", "")
        wf.start_node = data.get("start_node", "")
        wf.variables = data.get("variables", {})
        wf.version = data.get("version", "1.0.0")

        for node_id, node_data in data.get("nodes", {}).items():
            node = WorkflowNode(
                node_id=node_data.get("node_id", node_id),
                name=node_data.get("name", ""),
                node_type=NodeType(node_data.get("node_type", "task")),
                action=node_data.get("action", ""),
                parameters=node_data.get("parameters", {}),
                next_nodes=node_data.get("next_nodes", []),
                condition=node_data.get("condition"),
                timeout=node_data.get("timeout", 30),
            )
            wf.nodes[node_id] = node

        return wf


@dataclass
class WorkflowInstance:
    """工作流实例"""

    instance_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str = ""
    status: WorkflowStatus = WorkflowStatus.PENDING
    current_node: str = ""
    variables: typing.Dict[str, typing.Any] = field(default_factory=dict)
    start_time: typing.Optional[datetime.datetime] = None
    end_time: typing.Optional[datetime.datetime] = None
    duration: typing.Optional[float] = None
    node_results: typing.Dict[str, typing.Any] = field(default_factory=dict)
    errors: typing.List[str] = field(default_factory=list)

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        return {
            "instance_id": self.instance_id,
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "current_node": self.current_node,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration": self.duration,
            "node_results": self.node_results,
            "errors": self.errors,
        }


class WorkflowEngine:
    """
    工作流引擎

    管理工作流定义、执行和状态。
    """

    def __init__(self, config: typing.Dict[str, typing.Any] = None):
        self._config = config or {}
        self._lock = __import__("threading").RLock()

        # 工作流定义
        self._workflows: typing.Dict[str, WorkflowDefinition] = {}

        # 运行实例
        self._instances: typing.Dict[str, WorkflowInstance] = {}

        # 动作处理器
        self._action_handlers: typing.Dict[str, typing.Callable] = {}

        logger.info("WorkflowEngine 初始化完成")

    def register_workflow(self, definition: WorkflowDefinition) -> None:
        """注册工作流"""
        with self._lock:
            self._workflows[definition.workflow_id] = definition
            logger.debug("工作流已注册: %s", definition.name)

    def unregister_workflow(self, workflow_id: str) -> bool:
        """取消注册"""
        with self._lock:
            if workflow_id in self._workflows:
                del self._workflows[workflow_id]
                return True
            return False

    def list_workflows(self) -> typing.List[typing.Dict[str, typing.Any]]:
        """列出工作流"""
        return [
            {"workflow_id": wf.workflow_id, "name": wf.name, "nodes": len(wf.nodes)} for wf in self._workflows.values()
        ]

    def get_workflow(self, workflow_id: str) -> typing.Optional[WorkflowDefinition]:
        """获取工作流定义"""
        return self._workflows.get(workflow_id)

    def register_action(self, action_name: str, handler: typing.Callable) -> None:
        """注册动作处理器"""
        self._action_handlers[action_name] = handler
        logger.debug("动作已注册: %s", action_name)

    async def execute(self, workflow_id: str, parameters: typing.Dict[str, typing.Any] = None) -> typing.Any:
        """执行工作流"""
        definition = self._workflows.get(workflow_id)
        if not definition:
            raise ValueError(f"工作流未注册: {workflow_id}")

        # 创建实例
        instance = WorkflowInstance(
            workflow_id=workflow_id,
            variables={**definition.variables, **(parameters or {})},
            start_time=datetime.datetime.now(),
        )

        with self._lock:
            self._instances[instance.instance_id] = instance

        try:
            instance.status = WorkflowStatus.RUNNING
            result = await self._execute_workflow(definition, instance)
            instance.status = WorkflowStatus.COMPLETED
            instance.end_time = datetime.datetime.now()
            instance.duration = (instance.end_time - instance.start_time).total_seconds()
            return result
        except Exception as e:
            instance.status = WorkflowStatus.FAILED
            instance.errors.append(str(e))
            instance.end_time = datetime.datetime.now()
            instance.duration = (instance.end_time - instance.start_time).total_seconds()
            logger.error("工作流执行失败: %s, 错误: %s", workflow_id, e)
            raise

    async def _execute_workflow(self, definition: WorkflowDefinition, instance: WorkflowInstance) -> typing.Any:
        """执行工作流内部逻辑"""
        if not definition.start_node:
            raise ValueError("工作流无起始节点")

        current_node_id = definition.start_node
        result = None

        while current_node_id:
            node = definition.nodes.get(current_node_id)
            if not node:
                raise ValueError(f"节点未找到: {current_node_id}")

            instance.current_node = current_node_id

            # 执行节点
            result = await self._execute_node(node, instance)
            instance.node_results[current_node_id] = result

            # 获取下一个节点
            if node.next_nodes:
                current_node_id = node.next_nodes[0]
            else:
                current_node_id = None

        return result

    async def _execute_node(self, node: WorkflowNode, instance: WorkflowInstance) -> typing.Any:
        """执行单个节点"""
        logger.debug("执行节点: %s (%s)", node.name, node.node_type.value)

        if node.node_type == NodeType.CONDITION:
            return await self._execute_condition(node, instance)
        elif node.node_type == NodeType.PARALLEL:
            return await self._execute_parallel(node, instance)
        else:
            return await self._execute_task(node, instance)

    async def _execute_task(self, node: WorkflowNode, instance: WorkflowInstance) -> typing.Any:
        """执行任务节点"""
        action = node.action

        if action in self._action_handlers:
            handler = self._action_handlers[action]
            params = {**node.parameters, **instance.variables}

            if asyncio.iscoroutinefunction(handler):
                return await handler(**params)
            else:
                return handler(**params)

        # 默认：返回参数
        logger.warning("未找到动作处理器: %s", action)
        return {"action": action, "parameters": node.parameters}

    async def _execute_condition(self, node: WorkflowNode, instance: WorkflowInstance) -> typing.Any:
        """执行条件节点"""
        condition = node.condition or ""

        # 简单条件评估
        try:
            result = eval(condition, {"__builtins__": {}}, instance.variables)
            return result
        except Exception:
            return False

    async def _execute_parallel(self, node: WorkflowNode, instance: WorkflowInstance) -> typing.Any:
        """执行并行节点"""
        tasks = []
        for next_id in node.next_nodes:
            next_node = instance.variables.get("_definition", {}).get("nodes", {}).get(next_id)
            if next_node:
                tasks.append(self._execute_node(next_node, instance))

        if tasks:
            return await asyncio.gather(*tasks)
        return None

    def get_instance(self, instance_id: str) -> typing.Optional[WorkflowInstance]:
        """获取实例"""
        return self._instances.get(instance_id)

    def list_instances(self, workflow_id: str = None, status: WorkflowStatus = None) -> typing.List[WorkflowInstance]:
        """列出实例"""
        instances = list(self._instances.values())
        if workflow_id:
            instances = [i for i in instances if i.workflow_id == workflow_id]
        if status:
            instances = [i for i in instances if i.status == status]
        return instances

    async def cancel_instance(self, instance_id: str) -> bool:
        """取消实例"""
        instance = self._instances.get(instance_id)
        if instance and instance.status == WorkflowStatus.RUNNING:
            instance.status = WorkflowStatus.CANCELLED
            instance.end_time = datetime.datetime.now()
            instance.duration = (instance.end_time - instance.start_time).total_seconds()
            return True
        return False

    def get_statistics(self) -> typing.Dict[str, typing.Any]:
        """获取统计"""
        instances = list(self._instances.values())
        total = len(instances)
        completed = sum(1 for i in instances if i.status == WorkflowStatus.COMPLETED)
        failed = sum(1 for i in instances if i.status == WorkflowStatus.FAILED)

        return {
            "workflows": len(self._workflows),
            "instances": total,
            "completed": completed,
            "failed": failed,
            "success_rate": completed / total if total > 0 else 0,
        }
