from __future__ import annotations

"""
Execution Engine - 执行引擎（脑干）

所有 Agent 共用的执行引擎，负责：
- 工具执行（Tool Engine）
- 工作流执行（Workflow Engine）
- MCP 协议支持
- 执行监控

采用单例模式，确保多个 Agent 共用同一个执行引擎实例。
"""

import datetime
from neurova.core.logger import get_logger
import threading
import typing
import uuid
from dataclasses import dataclass, field
from enum import Enum

logger = get_logger(__name__)


@dataclass
class ExecutionStatus(Enum):
    """执行状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class ExecutionResult:
    """执行结果"""

    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: ExecutionStatus = field(default_factory=lambda: ExecutionStatus.PENDING)
    result: typing.Any = None
    error: typing.Optional[str] = None
    start_time: typing.Optional[datetime.datetime] = None
    end_time: typing.Optional[datetime.datetime] = None
    duration: typing.Optional[float] = None
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "execution_id": self.execution_id,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration": self.duration,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> "ExecutionResult":
        """从字典创建"""
        result = cls()
        if "execution_id" in data:
            result.execution_id = data["execution_id"]
        if "status" in data:
            result.status = ExecutionStatus(data["status"])
        if "result" in data:
            result.result = data["result"]
        if "error" in data:
            result.error = data["error"]
        if "start_time" in data:
            result.start_time = datetime.datetime.fromisoformat(data["start_time"])
        if "end_time" in data:
            result.end_time = datetime.datetime.fromisoformat(data["end_time"])
        if "duration" in data:
            result.duration = data["duration"]
        if "metadata" in data:
            result.metadata = data["metadata"]
        return result


class ExecutionEngine:
    """
    执行引擎

    单例模式，管理工具执行、工作流执行和执行监控。
    """

    _instance: typing.Optional["ExecutionEngine"] = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._executions: typing.Dict[str, ExecutionResult] = {}
        self._lock = threading.RLock()
        self._event_bus = None
        self._tool_engine = None
        self._workflow_engine = None
        self._execution_monitor = None
        self._running = False

        # 初始化执行引擎组件
        self._init_components()

        self._initialized = True
        logger.info("ExecutionEngine 初始化完成")

    def _init_components(self) -> None:
        """初始化执行引擎组件"""
        try:
            # 导入执行引擎组件（延迟导入避免循环依赖）
            from neurova.execution_engine.execution_monitor import ExecutionMonitor
            from neurova.execution_engine.tool_engine import ToolEngine
            from neurova.execution_engine.workflow_engine import WorkflowEngine

            self._tool_engine = ToolEngine()
            self._workflow_engine = WorkflowEngine()
            self._execution_monitor = ExecutionMonitor()

            logger.debug("ExecutionEngine 组件初始化完成")

        except ImportError as e:
            logger.warning("ExecutionEngine 组件导入失败: %s", e)
            # 创建占位组件
            self._tool_engine = None
            self._workflow_engine = None
            self._execution_monitor = None

    async def execute_plan(self, plan: typing.Dict[str, typing.Any]) -> ExecutionResult:
        """执行计划"""
        execution_id = str(uuid.uuid4())
        result = ExecutionResult(
            execution_id=execution_id, status=ExecutionStatus.RUNNING, start_time=datetime.datetime.now()
        )

        with self._lock:
            self._executions[execution_id] = result

        try:
            # 执行计划节点
            await self._execute_plan_nodes(plan)

            result.status = ExecutionStatus.COMPLETED
            result.end_time = datetime.datetime.now()
            result.duration = (result.end_time - result.start_time).total_seconds()

            logger.info("计划执行完成: %s", execution_id)

        except Exception as e:
            result.status = ExecutionStatus.FAILED
            result.error = str(e)
            result.end_time = datetime.datetime.now()
            result.duration = (result.end_time - result.start_time).total_seconds()

            logger.error("计划执行失败: %s, 错误: %s", execution_id, e)
            raise

        return result

    async def _execute_plan_nodes(self, plan: typing.Dict[str, typing.Any]) -> None:
        """执行计划节点"""
        nodes = plan.get("nodes", [])
        execution_order = plan.get("execution_order", [])

        if not execution_order:
            # 简单顺序执行
            await self._execute_simple_plan(nodes)
        else:
            # 按指定顺序执行
            for node_id in execution_order:
                node = next((n for n in nodes if n.get("id") == node_id), None)
                if node:
                    await self._execute_node(node)

    async def _execute_simple_plan(self, nodes: typing.List[typing.Dict[str, typing.Any]]) -> None:
        """执行简单计划（顺序执行）"""
        for node in nodes:
            await self._execute_node(node)

    async def _execute_node(self, node: typing.Dict[str, typing.Any]) -> typing.Any:
        """执行单个节点"""
        node_type = node.get("type", "tool")

        if node_type == "tool":
            return await self.execute_tool(
                tool_name=node.get("tool_name", ""), parameters=node.get("parameters", {}), timeout=node.get("timeout")
            )
        elif node_type == "workflow":
            return await self.execute_workflow(
                workflow_id=node.get("workflow_id", ""), parameters=node.get("parameters", {})
            )
        elif node_type == "condition":
            # 条件节点
            condition = node.get("condition", {})
            if self._evaluate_condition(condition):
                next_node = node.get("true_node")
                if next_node:
                    return await self._execute_node(next_node)
            else:
                next_node = node.get("false_node")
                if next_node:
                    return await self._execute_node(next_node)

        return None

    def _get_next_node(
        self, nodes: typing.List[typing.Dict[str, typing.Any]], current_id: str
    ) -> typing.Optional[typing.Dict[str, typing.Any]]:
        """获取下一个节点"""
        # 简单实现：返回列表中的下一个节点
        for i, node in enumerate(nodes):
            if node.get("id") == current_id and i + 1 < len(nodes):
                return nodes[i + 1]
        return None

    def _evaluate_condition(self, condition: typing.Dict[str, typing.Any]) -> bool:
        """评估条件"""
        # 简单条件评估
        condition_type = condition.get("type", "always_true")

        if condition_type == "always_true":
            return True
        elif condition_type == "always_false":
            return False
        elif condition_type == "variable_check":
            # 变量检查条件
            condition.get("variable")
            operator = condition.get("operator", "==")
            condition.get("value")

            # 这里需要从上下文中获取变量值
            # 暂时返回 True
            return True

        return True

    async def execute_tool(
        self, tool_name: str, parameters: typing.Dict[str, typing.Any] = None, timeout: float = None
    ) -> typing.Any:
        """执行工具"""
        if not self._tool_engine:
            raise RuntimeError("ToolEngine 未初始化")

        execution_id = str(uuid.uuid4())
        result = ExecutionResult(
            execution_id=execution_id, status=ExecutionStatus.RUNNING, start_time=datetime.datetime.now()
        )

        with self._lock:
            self._executions[execution_id] = result

        try:
            # 调用工具引擎执行工具
            tool_result = await self._tool_engine.execute(
                tool_name=tool_name, parameters=parameters or {}, timeout=timeout
            )

            result.status = ExecutionStatus.COMPLETED
            result.result = tool_result
            result.end_time = datetime.datetime.now()
            result.duration = (result.end_time - result.start_time).total_seconds()

            logger.info("工具执行完成: %s, 执行ID: %s", tool_name, execution_id)
            return tool_result

        except Exception as e:
            result.status = ExecutionStatus.FAILED
            result.error = str(e)
            result.end_time = datetime.datetime.now()
            result.duration = (result.end_time - result.start_time).total_seconds()

            logger.error("工具执行失败: %s, 错误: %s", tool_name, e)
            raise

    async def _call_llm(self, prompt: str, model: str = None, **kwargs) -> str:
        """调用 LLM"""
        # 这里需要集成 LLM 客户端
        # 暂时返回占位符
        logger.warning("_call_llm 方法未实现")
        return "LLM 调用未实现"

    async def execute_workflow(self, workflow_id: str, parameters: typing.Dict[str, typing.Any] = None) -> typing.Any:
        """执行工作流"""
        if not self._workflow_engine:
            raise RuntimeError("WorkflowEngine 未初始化")

        execution_id = str(uuid.uuid4())
        result = ExecutionResult(
            execution_id=execution_id, status=ExecutionStatus.RUNNING, start_time=datetime.datetime.now()
        )

        with self._lock:
            self._executions[execution_id] = result

        try:
            # 调用工作流引擎执行工作流
            workflow_result = await self._workflow_engine.execute(workflow_id=workflow_id, parameters=parameters or {})

            result.status = ExecutionStatus.COMPLETED
            result.result = workflow_result
            result.end_time = datetime.datetime.now()
            result.duration = (result.end_time - result.start_time).total_seconds()

            logger.info("工作流执行完成: %s, 执行ID: %s", workflow_id, execution_id)
            return workflow_result

        except Exception as e:
            result.status = ExecutionStatus.FAILED
            result.error = str(e)
            result.end_time = datetime.datetime.now()
            result.duration = (result.end_time - result.start_time).total_seconds()

            logger.error("工作流执行失败: %s, 错误: %s", workflow_id, e)
            raise

    def get_execution_result(self, execution_id: str) -> typing.Optional[ExecutionResult]:
        """获取执行结果"""
        return self._executions.get(execution_id)

    def list_executions(self, status: ExecutionStatus = None, limit: int = 100) -> typing.List[ExecutionResult]:
        """列出执行记录"""
        executions = list(self._executions.values())

        if status:
            executions = [e for e in executions if e.status == status]

        # 按开始时间倒序排序
        executions.sort(key=lambda x: x.start_time or datetime.datetime.min, reverse=True)

        return executions[:limit]

    async def cancel_execution(self, execution_id: str) -> bool:
        """取消执行"""
        with self._lock:
            result = self._executions.get(execution_id)
            if not result:
                return False

            if result.status in [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED]:
                return False

            result.status = ExecutionStatus.CANCELLED
            result.end_time = datetime.datetime.now()
            result.duration = (result.end_time - result.start_time).total_seconds()

            logger.info("执行已取消: %s", execution_id)
            return True

    def register_tool(self, tool_name: str, tool_func: typing.Callable, description: str = "") -> None:
        """注册工具"""
        if self._tool_engine:
            self._tool_engine.register_tool(tool_name, tool_func, description)
            logger.debug("工具已注册: %s", tool_name)
        else:
            logger.warning("ToolEngine 未初始化，无法注册工具")

    def set_event_bus(self, event_bus) -> None:
        """设置事件总线"""
        self._event_bus = event_bus
        if self._execution_monitor:
            self._execution_monitor.set_event_bus(event_bus)


# 工厂函数
_execution_engine: typing.Optional[ExecutionEngine] = None


def get_execution_engine() -> ExecutionEngine:
    """获取执行引擎单例"""
    global _execution_engine
    if _execution_engine is None:
        _execution_engine = ExecutionEngine()
    return _execution_engine


def reset_execution_engine() -> None:
    """重置执行引擎（用于测试）"""
    global _execution_engine
    _execution_engine = None
