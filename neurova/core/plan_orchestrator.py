"""
计划与任务编排器 - 小脑

Neurova CogArch 1.0.0 的核心组件之一
负责：意图分析、复杂度识别、任务图生成、拓扑排序、执行协调
"""

import asyncio
import datetime
import logging
import typing
import uuid
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# ────── 数据模型 ──────


class TaskComplexity(Enum):
    """任务复杂度"""

    SIMPLE = "simple"  # 简单任务
    COMPOUND = "compound"  # 复合任务
    PARALLEL = "parallel"  # 并行任务
    DAG = "dag"  # 有向无环图任务


class RetryPolicy(Enum):
    """重试策略"""

    NONE = "none"  # 不重试
    LINEAR = "linear"  # 线性重试
    EXPONENTIAL = "exponential"  # 指数退避
    FIXED = "fixed"  # 固定间隔


@dataclass
class TaskNode:
    """任务节点"""

    task_id: str = ""
    name: str = ""
    description: str = ""
    tool_name: str = ""
    parameters: typing.Dict[str, typing.Any] = field(default_factory=dict)
    dependencies: typing.List[str] = field(default_factory=list)
    timeout: float = 30.0  # 超时（秒）
    retry_policy: RetryPolicy = RetryPolicy.NONE
    max_retries: int = 0
    priority: int = 0
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.task_id:
            self.task_id = str(uuid.uuid4())[:8]

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "description": self.description,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "dependencies": self.dependencies,
            "timeout": self.timeout,
            "retry_policy": self.retry_policy.value,
            "max_retries": self.max_retries,
            "priority": self.priority,
            "metadata": self.metadata,
        }


@dataclass
class Plan:
    """执行计划"""

    plan_id: str = ""
    name: str = ""
    description: str = ""
    complexity: TaskComplexity = TaskComplexity.SIMPLE
    tasks: typing.List[TaskNode] = field(default_factory=list)
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.plan_id:
            self.plan_id = str(uuid.uuid4())[:8]

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "plan_id": self.plan_id,
            "name": self.name,
            "description": self.description,
            "complexity": self.complexity.value,
            "tasks": [task.to_dict() for task in self.tasks],
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class PlanResult:
    """计划执行结果"""

    plan_id: str = ""
    success: bool = False
    task_results: typing.Dict[str, typing.Any] = field(default_factory=dict)
    total_duration_ms: float = 0.0
    error: typing.Optional[str] = None
    timestamp: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "plan_id": self.plan_id,
            "success": self.success,
            "task_results": self.task_results,
            "total_duration_ms": self.total_duration_ms,
            "error": self.error,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ExecutionFeedback:
    """执行反馈"""

    task_id: str = ""
    success: bool = False
    output: typing.Optional[typing.Dict[str, typing.Any]] = None
    duration_ms: float = 0.0
    error: typing.Optional[str] = None
    retry_count: int = 0
    timestamp: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "success": self.success,
            "output": self.output,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "retry_count": self.retry_count,
            "timestamp": self.timestamp.isoformat(),
        }


# ────── 主类 ──────


class PlanOrchestrator:
    """
    计划编排器

    负责意图分析、复杂度识别、任务图生成、拓扑排序、执行协调。
    """

    def __init__(self, config: typing.Optional[typing.Dict[str, typing.Any]] = None):
        """
        初始化计划编排器

        参数:
            config: 配置字典
        """
        self._config = config or {}
        self._plans: typing.Dict[str, Plan] = {}
        self._executor = None

        logger.info("PlanOrchestrator initialized")

    def set_executor(self, executor: typing.Any) -> None:
        """设置执行器"""
        self._executor = executor

    def decompose_intent(self, intent: str, context: typing.Optional[typing.Dict[str, typing.Any]] = None) -> Plan:
        """
        分解意图为执行计划

        参数:
            intent: 意图描述
            context: 上下文

        返回:
            Plan: 执行计划
        """
        # 分析复杂度
        complexity = self._analyze_complexity(intent, context)

        # 根据复杂度创建计划
        if complexity == TaskComplexity.SIMPLE:
            plan = self._create_simple_plan(intent, context)
        elif complexity == TaskComplexity.COMPOUND:
            plan = self._create_compound_plan(intent, context)
        elif complexity == TaskComplexity.PARALLEL:
            plan = self._create_parallel_plan(intent, context)
        else:  # DAG
            plan = self._create_dag_plan(intent, context)

        # 存储计划
        self._plans[plan.plan_id] = plan

        logger.info("Created plan %s for intent: %s...", plan.plan_id, intent[:50])
        return plan

    async def execute_plan(
        self, plan_id: str, context: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> PlanResult:
        """
        执行计划

        参数:
            plan_id: 计划 ID
            context: 上下文

        返回:
            PlanResult: 执行结果
        """
        plan = self._plans.get(plan_id)
        if not plan:
            return PlanResult(plan_id=plan_id, success=False, error=f"Plan not found: {plan_id}")

        start_time = time.time()

        try:
            # 根据复杂度执行
            if plan.complexity in (TaskComplexity.SIMPLE, TaskComplexity.COMPOUND):
                results = await self._execute_sequential(plan, context)
            else:
                results = await self._execute_parallel(plan, context)

            duration_ms = (time.time() - start_time) * 1000

            # 检查所有任务是否成功
            all_success = all(r.get("success", False) for r in results.values())

            return PlanResult(
                plan_id=plan_id,
                success=all_success,
                task_results=results,
                total_duration_ms=duration_ms,
                error=None if all_success else "Some tasks failed",
            )

        except Exception as e:
            logger.error("Plan execution failed: %s", e)
            return PlanResult(
                plan_id=plan_id, success=False, total_duration_ms=(time.time() - start_time) * 1000, error=str(e)
            )

    def adjust_plan(self, plan_id: str, feedback: ExecutionFeedback) -> typing.Optional[Plan]:
        """
        调整计划

        参数:
            plan_id: 计划 ID
            feedback: 执行反馈

        返回:
            Optional[Plan]: 调整后的计划
        """
        plan = self._plans.get(plan_id)
        if not plan:
            return None

        # 根据反馈调整计划
        if not feedback.success:
            # 找到失败的任务
            for task in plan.tasks:
                if task.task_id == feedback.task_id:
                    # 调整重试策略
                    if task.retry_policy == RetryPolicy.NONE:
                        task.retry_policy = RetryPolicy.LINEAR
                        task.max_retries = 3

                    logger.info("Adjusted task %s retry policy", task.task_id)
                    break

        return plan

    def _analyze_complexity(
        self, intent: str, context: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> TaskComplexity:
        """
        分析复杂度

        参数:
            intent: 意图
            context: 上下文

        返回:
            TaskComplexity: 复杂度
        """
        intent_lower = intent.lower()

        # 简单关键词匹配
        if any(word in intent_lower for word in ["并且", "同时", "and", "also", "parallel"]):
            return TaskComplexity.PARALLEL

        if any(word in intent_lower for word in ["然后", "接着", "then", "after", "sequence"]):
            return TaskComplexity.COMPOUND

        if any(word in intent_lower for word in ["依赖", "依赖于", "depend", "require"]):
            return TaskComplexity.DAG

        return TaskComplexity.SIMPLE

    def _create_simple_plan(self, intent: str, context: typing.Optional[typing.Dict[str, typing.Any]] = None) -> Plan:
        """创建简单计划"""
        task = TaskNode(
            name="simple_task",
            description=intent,
            tool_name="general_tool",
        )

        return Plan(
            name="Simple Plan",
            description=intent,
            complexity=TaskComplexity.SIMPLE,
            tasks=[task],
        )

    def _create_compound_plan(self, intent: str, context: typing.Optional[typing.Dict[str, typing.Any]] = None) -> Plan:
        """创建复合计划"""
        # 分解为多个步骤
        steps = intent.split("然后")
        if len(steps) == 1:
            steps = intent.split("then")

        tasks = []
        for i, step in enumerate(steps):
            task = TaskNode(
                name=f"step_{i}",
                description=step.strip(),
                tool_name="general_tool",
                dependencies=[f"step_{i-1}"] if i > 0 else [],
            )
            tasks.append(task)

        return Plan(
            name="Compound Plan",
            description=intent,
            complexity=TaskComplexity.COMPOUND,
            tasks=tasks,
        )

    def _create_parallel_plan(self, intent: str, context: typing.Optional[typing.Dict[str, typing.Any]] = None) -> Plan:
        """创建并行计划"""
        # 分解为并行任务
        parts = intent.split("并且")
        if len(parts) == 1:
            parts = intent.split("同时")
        if len(parts) == 1:
            parts = intent.split("and")

        tasks = []
        for i, part in enumerate(parts):
            task = TaskNode(
                name=f"parallel_{i}",
                description=part.strip(),
                tool_name="general_tool",
            )
            tasks.append(task)

        return Plan(
            name="Parallel Plan",
            description=intent,
            complexity=TaskComplexity.PARALLEL,
            tasks=tasks,
        )

    def _create_dag_plan(self, intent: str, context: typing.Optional[typing.Dict[str, typing.Any]] = None) -> Plan:
        """创建 DAG 计划"""
        # 简单的 DAG 创建
        task1 = TaskNode(
            name="task_a",
            description="Task A",
            tool_name="tool_a",
        )

        task2 = TaskNode(
            name="task_b",
            description="Task B",
            tool_name="tool_b",
            dependencies=["task_a"],
        )

        task3 = TaskNode(
            name="task_c",
            description="Task C",
            tool_name="tool_c",
            dependencies=["task_a"],
        )

        return Plan(
            name="DAG Plan",
            description=intent,
            complexity=TaskComplexity.DAG,
            tasks=[task1, task2, task3],
        )

    def _topological_sort(self, tasks: typing.List[TaskNode]) -> typing.List[TaskNode]:
        """
        拓扑排序

        参数:
            tasks: 任务列表

        返回:
            List[TaskNode]: 排序后的任务列表
        """
        # 构建邻接表
        graph: typing.Dict[str, typing.List[str]] = {}
        in_degree: typing.Dict[str, int] = {}

        for task in tasks:
            graph[task.task_id] = []
            in_degree[task.task_id] = 0

        for task in tasks:
            for dep in task.dependencies:
                if dep in graph:
                    graph[dep].append(task.task_id)
                    in_degree[task.task_id] += 1

        # 拓扑排序
        queue = [task_id for task_id, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            task_id = queue.pop(0)
            result.append(task_id)

            for neighbor in graph[task_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # 返回排序后的任务
        task_map = {task.task_id: task for task in tasks}
        return [task_map[task_id] for task_id in result if task_id in task_map]

    async def _execute_sequential(
        self, plan: Plan, context: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> typing.Dict[str, typing.Any]:
        """
        顺序执行

        参数:
            plan: 计划
            context: 上下文

        返回:
            Dict: 任务结果
        """
        results = {}

        # 拓扑排序
        sorted_tasks = self._topological_sort(plan.tasks)

        for task in sorted_tasks:
            result = await self._execute_single_task(task, context)
            results[task.task_id] = result

            # 如果任务失败，停止执行
            if not result.get("success", False):
                logger.warning("Task %s failed, stopping sequential execution", task.task_id)
                break

        return results

    async def _execute_parallel(
        self, plan: Plan, context: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> typing.Dict[str, typing.Any]:
        """
        并行执行

        参数:
            plan: 计划
            context: 上下文

        返回:
            Dict: 任务结果
        """
        results = {}

        # 按依赖分组
        levels = self._group_by_dependency_level(plan.tasks)

        for level_tasks in levels:
            # 并行执行同一层级的任务
            tasks_coroutines = [self._execute_single_task(task, context) for task in level_tasks]

            level_results = await asyncio.gather(*tasks_coroutines, return_exceptions=True)

            for task, result in zip(level_tasks, level_results):
                if isinstance(result, Exception):
                    results[task.task_id] = {"success": False, "error": str(result)}
                else:
                    results[task.task_id] = result

        return results

    def _group_by_dependency_level(self, tasks: typing.List[TaskNode]) -> typing.List[typing.List[TaskNode]]:
        """
        按依赖层级分组

        参数:
            tasks: 任务列表

        返回:
            List[List[TaskNode]]: 分组后的任务
        """
        task_map = {task.task_id: task for task in tasks}
        levels: typing.List[typing.List[TaskNode]] = []
        assigned = set()

        while len(assigned) < len(tasks):
            current_level = []

            for task in tasks:
                if task.task_id in assigned:
                    continue

                # 检查所有依赖是否已分配
                deps_met = all(dep in assigned for dep in task.dependencies if dep in task_map)

                if deps_met:
                    current_level.append(task)

            if not current_level:
                # 避免无限循环
                break

            for task in current_level:
                assigned.add(task.task_id)

            levels.append(current_level)

        return levels

    async def _execute_single_task(
        self, task: TaskNode, context: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> typing.Dict[str, typing.Any]:
        """
        执行单个任务

        参数:
            task: 任务节点
            context: 上下文

        返回:
            Dict: 任务结果
        """
        start_time = time.time()

        try:
            # 模拟任务执行
            result = await self._simulate_task_execution(task, context)

            duration_ms = (time.time() - start_time) * 1000

            return {
                "success": True,
                "task_id": task.task_id,
                "output": result,
                "duration_ms": duration_ms,
            }

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error("Task %s failed: %s", task.task_id, e)

            return {
                "success": False,
                "task_id": task.task_id,
                "error": str(e),
                "duration_ms": duration_ms,
            }

    async def _simulate_task_execution(
        self, task: TaskNode, context: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> typing.Dict[str, typing.Any]:
        """
        模拟任务执行

        参数:
            task: 任务节点
            context: 上下文

        返回:
            Dict: 执行结果
        """
        # 模拟执行延迟
        await asyncio.sleep(0.1)

        return {
            "task_name": task.name,
            "tool_name": task.tool_name,
            "parameters": task.parameters,
            "simulated": True,
        }

    def get_plan(self, plan_id: str) -> typing.Optional[Plan]:
        """
        获取计划

        参数:
            plan_id: 计划 ID

        返回:
            Optional[Plan]: 计划
        """
        return self._plans.get(plan_id)

    def list_plans(self) -> typing.List[Plan]:
        """
        列出所有计划

        返回:
            List[Plan]: 计划列表
        """
        return list(self._plans.values())


# ────── 单例管理 ──────

_orchestrator_instance: typing.Optional[PlanOrchestrator] = None
_instance_lock = __import__("threading").Lock()


def get_plan_orchestrator(**kwargs) -> PlanOrchestrator:
    """获取全局计划编排器实例"""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        with _instance_lock:
            if _orchestrator_instance is None:
                _orchestrator_instance = PlanOrchestrator(**kwargs)
    return _orchestrator_instance


def reset_plan_orchestrator():
    """重置全局计划编排器实例"""
    global _orchestrator_instance
    with _instance_lock:
        _orchestrator_instance = None
