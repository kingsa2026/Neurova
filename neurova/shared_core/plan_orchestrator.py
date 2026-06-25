from __future__ import annotations

"""
Shared Plan Orchestrator - 共用任务编排器（小脑）

所有 Agent 共用的任务编排器，负责：
- 意图分析
- 复杂度识别
- 任务图生成
- 拓扑排序
- 执行计划生成

采用单例模式，确保多个 Agent 共用同一个编排器实例。
"""

import asyncio
import datetime
from neurova.core.logger import get_logger
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = get_logger(__name__)


class NodeType(Enum):
    """任务节点类型"""

    ACTION = "action"  # 执行动作
    CONDITION = "condition"  # 条件判断
    PARALLEL = "parallel"  # 并行执行
    SEQUENTIAL = "sequential"  # 顺序执行
    LOOP = "loop"  # 循环
    SUBPLAN = "subplan"  # 子计划
    LLM_CALL = "llm_call"  # LLM 调用
    TOOL_CALL = "tool_call"  # 工具调用


class PlanStatus(Enum):
    """计划状态"""

    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


@dataclass
class TaskNode:
    """任务节点"""

    node_id: str
    name: str
    node_type: NodeType
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)  # 依赖的节点 ID
    status: str = "pending"
    result: Optional[Any] = None
    error: Optional[str] = None
    timeout_seconds: int = 300
    retry_count: int = 0
    max_retries: int = 3
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "node_type": self.node_type.value,
            "description": self.description,
            "parameters": self.parameters,
            "dependencies": self.dependencies,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "timeout_seconds": self.timeout_seconds,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskNode:
        return cls(
            node_id=data.get("node_id", ""),
            name=data.get("name", ""),
            node_type=NodeType(data.get("node_type", "action")),
            description=data.get("description", ""),
            parameters=data.get("parameters", {}),
            dependencies=data.get("dependencies", []),
            status=data.get("status", "pending"),
            result=data.get("result"),
            error=data.get("error"),
            timeout_seconds=data.get("timeout_seconds", 300),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TaskPlan:
    """任务计划"""

    plan_id: str
    name: str
    description: str = ""
    status: PlanStatus = PlanStatus.DRAFT
    nodes: List[TaskNode] = field(default_factory=list)
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    complexity: str = "simple"  # simple, medium, complex
    intent: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "nodes": [n.to_dict() for n in self.nodes],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "complexity": self.complexity,
            "intent": self.intent,
            "metadata": self.metadata,
            "node_count": len(self.nodes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskPlan:
        plan = cls(
            plan_id=data.get("plan_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            status=PlanStatus(data.get("status", "draft")),
            complexity=data.get("complexity", "simple"),
            intent=data.get("intent", ""),
            metadata=data.get("metadata", {}),
        )
        for node_data in data.get("nodes", []):
            plan.nodes.append(TaskNode.from_dict(node_data))
        if "created_at" in data:
            try:
                plan.created_at = datetime.datetime.fromisoformat(data["created_at"])
            except (ValueError, TypeError):
                pass
        if "updated_at" in data:
            try:
                plan.updated_at = datetime.datetime.fromisoformat(data["updated_at"])
            except (ValueError, TypeError):
                pass
        return plan

    def get_node(self, node_id: str) -> Optional[TaskNode]:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None

    def get_execution_order(self) -> List[List[str]]:
        """拓扑排序，返回分层执行顺序"""
        in_degree: Dict[str, int] = {n.node_id: 0 for n in self.nodes}
        adj: Dict[str, List[str]] = {n.node_id: [] for n in self.nodes}
        for node in self.nodes:
            for dep in node.dependencies:
                if dep in adj:
                    adj[dep].append(node.node_id)
                    in_degree[node.node_id] += 1

        layers: List[List[str]] = []
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        while queue:
            layers.append(queue[:])
            next_queue = []
            for nid in queue:
                for child in adj.get(nid, []):
                    in_degree[child] -= 1
                    if in_degree[child] == 0:
                        next_queue.append(child)
            queue = next_queue
        return layers


class SharedPlanOrchestrator:
    """共用任务编排器（单例）"""

    _instance: Optional[SharedPlanOrchestrator] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        if self._initialized:
            return
        self._initialized = True
        self.config = config or {}
        self.plans: Dict[str, TaskPlan] = {}
        self.node_handlers: Dict[str, Callable] = {}
        self._event_bus: Optional[Any] = None
        self._register_builtin_nodes()
        logger.info("SharedPlanOrchestrator 初始化完成")

    def _register_builtin_nodes(self):
        """注册内置节点类型"""
        self.node_handlers[NodeType.ACTION.value] = self._handle_action
        self.node_handlers[NodeType.LLM_CALL.value] = self._handle_llm_call
        self.node_handlers[NodeType.TOOL_CALL.value] = self._handle_tool_call
        self.node_handlers[NodeType.CONDITION.value] = self._handle_condition

    def analyze_intent(self, user_input: str) -> Dict[str, Any]:
        """分析用户意图"""
        intent_keywords = {
            "search": ["搜索", "查找", "search", "find", "look"],
            "create": ["创建", "新建", "生成", "create", "new", "generate"],
            "modify": ["修改", "更新", "编辑", "modify", "update", "edit"],
            "delete": ["删除", "移除", "delete", "remove"],
            "analyze": ["分析", "检查", "诊断", "analyze", "check", "diagnose"],
            "execute": ["执行", "运行", "运行", "execute", "run"],
        }
        detected_intents = []
        lower_input = user_input.lower()
        for intent, keywords in intent_keywords.items():
            if any(kw in lower_input for kw in keywords):
                detected_intents.append(intent)
        complexity = self._assess_complexity(user_input)
        return {
            "intents": detected_intents or ["general"],
            "complexity": complexity,
            "input_length": len(user_input),
            "has_tools": any(w in lower_input for w in ["工具", "tool", "api", "http"]),
        }

    def _assess_complexity(self, text: str) -> str:
        """评估任务复杂度"""
        word_count = len(text.split())
        if word_count < 20:
            return "simple"
        elif word_count < 100:
            return "medium"
        return "complex"

    def _decompose_task(self, intent_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """分解任务为子任务"""
        subtasks = []
        for intent in intent_result.get("intents", ["general"]):
            subtasks.append({"type": intent, "complexity": intent_result.get("complexity", "simple")})
        return subtasks

    def _analyze_tool_requirements(self, subtasks: List[Dict[str, Any]]) -> List[str]:
        """分析工具需求"""
        tools = set()
        for task in subtasks:
            task_type = task.get("type", "")
            if task_type == "search":
                tools.add("memory_search")
            elif task_type == "create":
                tools.add("file_write")
            elif task_type == "analyze":
                tools.add("file_read")
        return list(tools)

    def generate_plan(self, user_input: str, plan_name: Optional[str] = None) -> TaskPlan:
        """生成执行计划"""
        intent_result = self.analyze_intent(user_input)
        complexity = intent_result["complexity"]
        plan_id = str(uuid.uuid4())
        plan = TaskPlan(
            plan_id=plan_id,
            name=plan_name or f"plan-{plan_id[:8]}",
            description=user_input[:200],
            complexity=complexity,
            intent=str(intent_result["intents"]),
        )
        if complexity == "simple":
            plan.nodes = self._generate_simple_plan_nodes(intent_result)
        elif complexity == "medium":
            plan.nodes = self._generate_medium_plan_nodes(intent_result)
        else:
            plan.nodes = self._generate_complex_plan_nodes(intent_result)
        plan.status = PlanStatus.READY
        plan.updated_at = datetime.datetime.now(datetime.timezone.utc)
        self.plans[plan_id] = plan
        logger.info("生成计划: %s (复杂度: %s, 节点数: %s)", plan.name, complexity, len(plan.nodes))
        return plan

    def _generate_simple_plan_nodes(self, intent_result: Dict[str, Any]) -> List[TaskNode]:
        """生成简单计划节点"""
        return [
            TaskNode(
                node_id=str(uuid.uuid4()),
                name="execute",
                node_type=NodeType.ACTION,
                description="执行简单任务",
                parameters={"intent": intent_result.get("intents", ["general"])[0]},
            )
        ]

    def _generate_medium_plan_nodes(self, intent_result: Dict[str, Any]) -> List[TaskNode]:
        """生成中等复杂度计划节点"""
        analyze_node = TaskNode(
            node_id=str(uuid.uuid4()),
            name="analyze",
            node_type=NodeType.LLM_CALL,
            description="分析任务需求",
        )
        execute_node = TaskNode(
            node_id=str(uuid.uuid4()),
            name="execute",
            node_type=NodeType.ACTION,
            description="执行任务",
            dependencies=[analyze_node.node_id],
        )
        verify_node = TaskNode(
            node_id=str(uuid.uuid4()),
            name="verify",
            node_type=NodeType.CONDITION,
            description="验证结果",
            dependencies=[execute_node.node_id],
        )
        return [analyze_node, execute_node, verify_node]

    def _generate_complex_plan_nodes(self, intent_result: Dict[str, Any]) -> List[TaskNode]:
        """生成复杂计划节点"""
        decompose_node = TaskNode(
            node_id=str(uuid.uuid4()),
            name="decompose",
            node_type=NodeType.LLM_CALL,
            description="分解复杂任务",
        )
        plan_node = TaskNode(
            node_id=str(uuid.uuid4()),
            name="plan",
            node_type=NodeType.LLM_CALL,
            description="生成子计划",
            dependencies=[decompose_node.node_id],
        )
        execute_node = TaskNode(
            node_id=str(uuid.uuid4()),
            name="execute_parallel",
            node_type=NodeType.PARALLEL,
            description="并行执行子任务",
            dependencies=[plan_node.node_id],
        )
        synthesize_node = TaskNode(
            node_id=str(uuid.uuid4()),
            name="synthesize",
            node_type=NodeType.LLM_CALL,
            description="综合结果",
            dependencies=[execute_node.node_id],
        )
        return [decompose_node, plan_node, execute_node, synthesize_node]

    def get_plan(self, plan_id: str) -> Optional[TaskPlan]:
        return self.plans.get(plan_id)

    def list_plans(self, status: Optional[PlanStatus] = None) -> List[TaskPlan]:
        plans = list(self.plans.values())
        if status:
            plans = [p for p in plans if p.status == status]
        return plans

    def delete_plan(self, plan_id: str) -> bool:
        if plan_id in self.plans:
            del self.plans[plan_id]
            return True
        return False

    def update_plan_status(self, plan_id: str, status: PlanStatus) -> bool:
        plan = self.plans.get(plan_id)
        if plan:
            plan.status = status
            plan.updated_at = datetime.datetime.now(datetime.timezone.utc)
            return True
        return False

    async def orchestrate(self, plan_id: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """执行计划"""
        plan = self.get_plan(plan_id)
        if not plan:
            return {"error": "计划不存在"}
        plan.status = PlanStatus.RUNNING
        execution_layers = plan.get_execution_order()
        results: Dict[str, Any] = {}
        for layer in execution_layers:
            tasks = []
            for node_id in layer:
                node = plan.get_node(node_id)
                if node:
                    tasks.append(self._execute_node(node, context or {}, results))
            layer_results = await asyncio.gather(*tasks, return_exceptions=True)
            for nid, res in zip(layer, layer_results):
                if isinstance(res, Exception):
                    results[nid] = {"error": str(res)}
                else:
                    results[nid] = res
        failed = any(isinstance(r, dict) and "error" in r for r in results.values())
        plan.status = PlanStatus.FAILED if failed else PlanStatus.SUCCESS
        return {"plan_id": plan_id, "status": plan.status.value, "results": results}

    async def _execute_node(self, node: TaskNode, context: Dict[str, Any], results: Dict[str, Any]) -> Any:
        """执行单个节点"""
        node.status = "running"
        handler = self.node_handlers.get(node.node_type.value)
        if handler:
            try:
                result = await handler(node, context, results)
                node.status = "success"
                node.result = result
                return result
            except Exception as e:
                node.status = "failed"
                node.error = str(e)
                raise
        else:
            node.status = "skipped"
            return {"skipped": True, "reason": f"no handler for {node.node_type.value}"}

    async def _handle_action(self, node: TaskNode, context: Dict, results: Dict) -> Any:
        return {"action": node.name, "parameters": node.parameters}

    async def _handle_llm_call(self, node: TaskNode, context: Dict, results: Dict) -> Any:
        return {"llm_call": node.name, "description": node.description}

    async def _handle_tool_call(self, node: TaskNode, context: Dict, results: Dict) -> Any:
        return {"tool_call": node.name, "parameters": node.parameters}

    async def _handle_condition(self, node: TaskNode, context: Dict, results: Dict) -> Any:
        return {"condition": node.name, "result": True}

    def set_event_bus(self, event_bus: Any):
        self._event_bus = event_bus


def get_shared_plan_orchestrator(config: Optional[Dict[str, Any]] = None) -> SharedPlanOrchestrator:
    return SharedPlanOrchestrator(config)


def reset_shared_plan_orchestrator():
    with SharedPlanOrchestrator._lock:
        SharedPlanOrchestrator._instance = None
