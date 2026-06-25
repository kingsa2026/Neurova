"""
Neurflow 执行引擎 — 垂直切片 6
工作流执行、节点调度、变量传递、事件通知
"""

from neurova.core.logger import get_logger
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

from .dag import get_dag_validator
from .models import (
    ExecutionInstance,
    NodeExecutionResult,
    WorkflowDefinition,
    WorkflowNode,
    WorkflowStatus,
)
from .node_registry import get_node_registry
from .variable_resolver import ResolutionContext, get_variable_resolver

logger = get_logger(__name__)


class ExecutionStatus(Enum):
    """执行状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class ExecutionEventType(Enum):
    """执行事件类型枚举"""

    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    VARIABLE_SET = "variable_set"
    PAUSED = "paused"
    RESUMED = "resumed"


@dataclass
class ExecutionEvent:
    """执行事件

    使用 ExecutionEventType 枚举或字符串（向后兼容）
    """

    type: Union[ExecutionEventType, str]
    workflow_id: str
    execution_id: str
    node_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class WorkflowExecutor:
    """
    工作流执行器

    职责：
    1. 创建执行实例
    2. 拓扑排序节点
    3. 按顺序执行节点
    4. 传递变量和上下文
    5. 事件通知
    """

    def __init__(self):
        """初始化执行器"""
        self._dag_validator = get_dag_validator()
        self._variable_resolver = get_variable_resolver()
        self._node_registry = get_node_registry()
        # 确保内置节点已注册
        self._node_registry.ensure_builtin()
        self._event_handlers: List[Callable] = []
        self._instances: Dict[str, ExecutionInstance] = {}
        self._statuses: Dict[str, ExecutionStatus] = {}

    def on_event(self, handler: Callable[[ExecutionEvent], None]) -> None:
        """注册事件处理器"""
        self._event_handlers.append(handler)

    def _emit(self, event: ExecutionEvent) -> None:
        """发送事件"""
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error("事件处理器错误: %s", e)

    def create_instance(
        self,
        workflow: WorkflowDefinition,
        inputs: Dict[str, Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> ExecutionInstance:
        """
        创建执行实例

        Args:
            workflow: 工作流定义
            inputs: 输入变量
            user_id: 用户 ID
            agent_id: Agent ID

        Returns:
            ExecutionInstance
        """
        instance_id = f"exec_{uuid.uuid4().hex[:12]}"

        # 初始化变量
        variables = {}
        for var in workflow.variables:
            variables[var.name] = var.default_value

        instance = ExecutionInstance(
            id=instance_id,
            workflow_id=workflow.id,
            status=WorkflowStatus.DRAFT,
            inputs=inputs,
            variables=variables,
            started_at=time.time(),
            agent_id=agent_id,
            user_id=user_id,
        )

        self._instances[instance_id] = instance
        self._statuses[instance_id] = ExecutionStatus.PENDING

        return instance

    def get_status(self, execution_id: str) -> ExecutionStatus:
        """获取执行状态"""
        return self._statuses.get(execution_id, ExecutionStatus.PENDING)

    def validate_workflow(self, workflow: WorkflowDefinition):
        """验证工作流"""
        return self._dag_validator.validate(workflow.nodes, workflow.edges)

    async def execute(
        self,
        workflow: WorkflowDefinition,
        inputs: Dict[str, Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        memory_manager: Optional[Any] = None,
        context_pool: Optional[Any] = None,
        emotion_module: Optional[Any] = None,
        crystallizer: Optional[Any] = None,
    ) -> ExecutionInstance:
        """
        执行工作流

        Args:
            workflow: 工作流定义
            inputs: 输入变量
            user_id: 用户 ID
            agent_id: Agent ID
            memory_manager: 记忆管理器（可选）
            context_pool: 上下文池（可选）
            emotion_module: 情感模块（可选）
            crystallizer: 结晶器（可选）

        Returns:
            ExecutionInstance 执行实例
        """
        # 创建执行实例
        instance = self.create_instance(workflow, inputs, user_id, agent_id)
        execution_id = instance.id

        # 验证工作流
        validation = self.validate_workflow(workflow)
        if not validation.is_valid:
            instance.status = WorkflowStatus.FAILED
            instance.error = f"工作流验证失败: {'; '.join(validation.errors)}"
            instance.finished_at = time.time()
            instance.duration = instance.finished_at - instance.started_at
            self._statuses[execution_id] = ExecutionStatus.FAILED
            return instance

        # 获取执行路径（使用公共 API）
        execution_order = self._dag_validator.get_execution_path(workflow.nodes, workflow.edges)
        if not execution_order:
            instance.status = WorkflowStatus.FAILED
            instance.error = "拓扑排序失败：无法确定执行顺序（可能存在环）"
            instance.finished_at = time.time()
            instance.duration = instance.finished_at - instance.started_at
            self._statuses[execution_id] = ExecutionStatus.FAILED
            return instance

        # 构建节点映射
        node_map = {n.id: n for n in workflow.nodes}

        # 构建解析上下文
        resolution_context = ResolutionContext(
            workflow_id=workflow.id,
            execution_id=execution_id,
            inputs=inputs,
            variables=dict(instance.variables),
            agent_id=agent_id,
            user_id=user_id,
            memory_manager=memory_manager,
            context_pool=context_pool,
            emotion_module=emotion_module,
            crystallizer=crystallizer,
        )

        # 发送工作流开始事件
        self._statuses[execution_id] = ExecutionStatus.RUNNING
        instance.status = WorkflowStatus.RUNNING

        self._emit(
            ExecutionEvent(
                type=ExecutionEventType.WORKFLOW_STARTED,
                workflow_id=workflow.id,
                execution_id=execution_id,
                data={"inputs": inputs},
            )
        )

        # 按拓扑顺序执行节点
        try:
            for node_id in execution_order:
                node = node_map[node_id]

                # 发送节点开始事件
                self._emit(
                    ExecutionEvent(
                        type=ExecutionEventType.NODE_STARTED,
                        workflow_id=workflow.id,
                        execution_id=execution_id,
                        node_id=node_id,
                    )
                )

                # 解析节点配置
                resolved_config = self._variable_resolver.resolve_config(node.config, resolution_context)

                # 执行节点
                started_at = time.time()
                try:
                    result = await self._execute_node(
                        node,
                        resolved_config,
                        {
                            "inputs": inputs,
                            "variables": resolution_context.variables,
                            "node_results": resolution_context.node_results,
                            "memory_manager": resolution_context.memory_manager,
                            "context_pool": resolution_context.context_pool,
                            "emotion_module": resolution_context.emotion_module,
                            "crystallizer": resolution_context.crystallizer,
                            "variable_resolver": self._variable_resolver,
                            "resolution_context": resolution_context,
                        },
                    )

                    finished_at = time.time()

                    # 记录节点结果
                    node_result = NodeExecutionResult(
                        node_id=node_id,
                        status="success",
                        output=result.get("output"),
                        started_at=started_at,
                        finished_at=finished_at,
                        duration=finished_at - started_at,
                    )
                    instance.node_results[node_id] = node_result

                    # 更新上下文
                    resolution_context.node_results[node_id] = result

                    # 变量节点特殊处理
                    if node.type == "builtin:variable" and isinstance(result.get("output"), dict):
                        var_output = result["output"]
                        if "name" in var_output and "value" in var_output:
                            var_name = var_output["name"]
                            var_value = var_output["value"]
                            instance.variables[var_name] = var_value
                            resolution_context.variables[var_name] = var_value

                    # 发送节点完成事件
                    self._emit(
                        ExecutionEvent(
                            type=ExecutionEventType.NODE_COMPLETED,
                            workflow_id=workflow.id,
                            execution_id=execution_id,
                            node_id=node_id,
                            data={"result": result},
                        )
                    )

                except Exception as e:
                    finished_at = time.time()

                    # 记录失败
                    node_result = NodeExecutionResult(
                        node_id=node_id,
                        status="failed",
                        output=None,
                        error=str(e),
                        started_at=started_at,
                        finished_at=finished_at,
                        duration=finished_at - started_at,
                    )
                    instance.node_results[node_id] = node_result

                    # 发送节点失败事件
                    self._emit(
                        ExecutionEvent(
                            type=ExecutionEventType.NODE_FAILED,
                            workflow_id=workflow.id,
                            execution_id=execution_id,
                            node_id=node_id,
                            data={"error": str(e)},
                        )
                    )

                    # 工作流失败
                    instance.status = WorkflowStatus.FAILED
                    instance.error = f"节点 '{node_id}' 执行失败: {str(e)}"
                    instance.finished_at = time.time()
                    instance.duration = instance.finished_at - instance.started_at
                    self._statuses[execution_id] = ExecutionStatus.FAILED

                    self._emit(
                        ExecutionEvent(
                            type=ExecutionEventType.WORKFLOW_FAILED,
                            workflow_id=workflow.id,
                            execution_id=execution_id,
                            data={"error": instance.error},
                        )
                    )

                    return instance

            # 工作流完成
            instance.status = WorkflowStatus.COMPLETED
            instance.finished_at = time.time()
            instance.duration = instance.finished_at - instance.started_at
            self._statuses[execution_id] = ExecutionStatus.COMPLETED

            # 收集最终输出（最后一个节点的输出）
            if instance.node_results:
                last_node_id = execution_order[-1]
                if last_node_id in instance.node_results:
                    instance.outputs = {"result": instance.node_results[last_node_id].output}

            self._emit(
                ExecutionEvent(
                    type=ExecutionEventType.WORKFLOW_COMPLETED,
                    workflow_id=workflow.id,
                    execution_id=execution_id,
                    data={"outputs": instance.outputs},
                )
            )

        except Exception as e:
            instance.status = WorkflowStatus.FAILED
            instance.error = f"执行异常: {str(e)}"
            instance.finished_at = time.time()
            instance.duration = instance.finished_at - instance.started_at
            self._statuses[execution_id] = ExecutionStatus.FAILED

            self._emit(
                ExecutionEvent(
                    type=ExecutionEventType.WORKFLOW_FAILED,
                    workflow_id=workflow.id,
                    execution_id=execution_id,
                    data={"error": str(e)},
                )
            )

        return instance

    async def _execute_node(
        self, node: WorkflowNode, config: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行单个节点

        Args:
            node: 工作流节点
            config: 已解析的配置
            context: 执行上下文

        Returns:
            执行结果
        """
        # 内置节点处理
        if node.type == "builtin:start":
            return {"output": context.get("inputs", {})}

        elif node.type == "builtin:end":
            # 收集所有节点输出
            node_results = context.get("node_results", {})
            if node_results:
                last_output = None
                for node_id, result in node_results.items():
                    if result.get("output") is not None:
                        last_output = result["output"]
                return {"output": last_output}
            return {"output": None}

        elif node.type == "builtin:variable":
            return {"output": {"name": config.get("name", ""), "value": config.get("value")}}

        elif node.type == "builtin:transform":
            # 简单变换（实际应支持代码执行）
            expression = config.get("expression", "")
            return {"output": f"transform: {expression}"}

        # 注册表中的节点
        node_type = node.type
        executor = self._node_registry.get_executor(node_type)
        if executor:
            return await executor(config, context)

        # 默认返回
        return {"output": None}

    def cancel(self, execution_id: str) -> bool:
        """
        取消执行

        Args:
            execution_id: 执行 ID

        Returns:
            是否成功取消
        """
        if execution_id not in self._instances:
            return False

        instance = self._instances[execution_id]
        status = self._statuses.get(execution_id)

        # 只能取消运行中的执行
        if status not in [ExecutionStatus.RUNNING, ExecutionStatus.PAUSED]:
            return False

        instance.status = WorkflowStatus.CANCELLED
        instance.finished_at = time.time()
        instance.duration = instance.finished_at - instance.started_at
        instance.error = "执行已取消"
        self._statuses[execution_id] = ExecutionStatus.CANCELLED

        self._emit(
            ExecutionEvent(
                type=ExecutionEventType.WORKFLOW_FAILED,
                workflow_id=instance.workflow_id,
                execution_id=execution_id,
                data={"error": "执行已取消"},
            )
        )

        return True

    def resume(self, execution_id: str) -> bool:
        """
        恢复执行（人工审批后）

        Args:
            execution_id: 执行 ID

        Returns:
            是否成功恢复
        """
        if execution_id not in self._instances:
            return False

        instance = self._instances[execution_id]
        status = self._statuses.get(execution_id)

        # 只能恢复暂停的执行
        if status != ExecutionStatus.PAUSED:
            return False

        instance.status = WorkflowStatus.RUNNING
        self._statuses[execution_id] = ExecutionStatus.RUNNING

        self._emit(
            ExecutionEvent(type=ExecutionEventType.RESUMED, workflow_id=instance.workflow_id, execution_id=execution_id)
        )

        return True

    def get_recent_executions(
        self,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 10,
        since_timestamp: Optional[float] = None,
    ) -> List[ExecutionInstance]:
        """
        获取最近的执行实例

        Args:
            agent_id: 可选，按 Agent ID 过滤
            user_id: 可选，按用户 ID 过滤
            limit: 最大返回数量
            since_timestamp: 可选，只返回此时间戳之后的执行

        Returns:
            按开始时间降序排列的执行实例列表
        """
        now = time.time()
        if since_timestamp is None:
            # 默认返回最近 5 分钟内的执行
            since_timestamp = now - 300

        # 收集符合条件的实例
        recent = []
        for instance_id, instance in self._instances.items():
            # 时间过滤
            if instance.started_at < since_timestamp:
                continue

            # Agent ID 过滤
            if agent_id and instance.agent_id != agent_id:
                continue

            # User ID 过滤
            if user_id and instance.user_id != user_id:
                continue

            # 只包含已完成的执行
            status = self._statuses.get(instance_id)
            if status in [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED]:
                recent.append(instance)

        # 按开始时间降序排序
        recent.sort(key=lambda x: x.started_at, reverse=True)

        # 限制返回数量
        return recent[:limit]


# 单例
_workflow_executor: Optional[WorkflowExecutor] = None


def get_workflow_executor() -> WorkflowExecutor:
    """获取工作流执行器单例"""
    global _workflow_executor
    if _workflow_executor is None:
        _workflow_executor = WorkflowExecutor()
    return _workflow_executor


__all__ = ["ExecutionStatus", "ExecutionEventType", "ExecutionEvent", "WorkflowExecutor", "get_workflow_executor"]
