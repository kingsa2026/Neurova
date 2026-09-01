"""
计划编排器 - 小脑

Neurova CogArch 1.0.0 的核心执行组件
负责：任务分解与规划、执行计划生成、多步骤任务编排、与 CognitionOrchestrator 对接
"""

import asyncio
from neurova.core.logger import get_logger
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = get_logger(__name__)


class StepStatus(str, Enum):
    """步骤状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    WAITING = "waiting"


class PlanStatus(str, Enum):
    """计划状态"""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


@dataclass
class ExecutionStep:
    """执行步骤"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    step_type: str = "task"  # task, condition, parallel, loop
    status: StepStatus = StepStatus.PENDING
    dependencies: List[str] = field(default_factory=list)  # 依赖的步骤ID
    parameters: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_ms: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    timeout_seconds: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "step_type": self.step_type,
            "status": self.status.value,
            "dependencies": self.dependencies,
            "parameters": self.parameters,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionStep":
        """从字典创建"""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            description=data.get("description", ""),
            step_type=data.get("step_type", "task"),
            status=StepStatus(data.get("status", "pending")),
            dependencies=data.get("dependencies", []),
            parameters=data.get("parameters", {}),
            result=data.get("result"),
            error=data.get("error"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            duration_ms=data.get("duration_ms"),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            timeout_seconds=data.get("timeout_seconds"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ExecutionPlan:
    """执行计划"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    status: PlanStatus = PlanStatus.CREATED
    steps: List[ExecutionStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_ms: Optional[float] = None
    priority: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "steps": [step.to_dict() for step in self.steps],
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "priority": self.priority,
            "metadata": self.metadata,
            "results": self.results,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionPlan":
        """从字典创建"""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            description=data.get("description", ""),
            status=PlanStatus(data.get("status", "created")),
            steps=[ExecutionStep.from_dict(step) for step in data.get("steps", [])],
            created_at=data.get("created_at", time.time()),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            duration_ms=data.get("duration_ms"),
            priority=data.get("priority", 0),
            metadata=data.get("metadata", {}),
            results=data.get("results", {}),
        )

    def get_step(self, step_id: str) -> Optional[ExecutionStep]:
        """获取步骤"""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def get_step_by_name(self, name: str) -> Optional[ExecutionStep]:
        """按名称获取步骤"""
        for step in self.steps:
            if step.name == name:
                return step
        return None

    def get_pending_steps(self) -> List[ExecutionStep]:
        """获取待执行的步骤"""
        return [step for step in self.steps if step.status == StepStatus.PENDING]

    def get_running_steps(self) -> List[ExecutionStep]:
        """获取正在运行的步骤"""
        return [step for step in self.steps if step.status == StepStatus.RUNNING]

    def get_completed_steps(self) -> List[ExecutionStep]:
        """获取已完成的步骤"""
        return [step for step in self.steps if step.status == StepStatus.COMPLETED]

    def get_failed_steps(self) -> List[ExecutionStep]:
        """获取失败的步骤"""
        return [step for step in self.steps if step.status == StepStatus.FAILED]

    def is_complete(self) -> bool:
        """检查计划是否完成"""
        return all(step.status in [StepStatus.COMPLETED, StepStatus.SKIPPED] for step in self.steps)

    def has_failed(self) -> bool:
        """检查计划是否有失败步骤"""
        return any(step.status == StepStatus.FAILED for step in self.steps)


@dataclass
class TaskComplexity:
    """任务复杂度分析"""

    level: str = "medium"  # low, medium, high, very_high
    estimated_steps: int = 1
    estimated_duration_ms: float = 0.0
    dependencies: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


class PlanOrchestrator:
    """
    计划编排器

    功能：
    1. 任务分解与规划
    2. 执行计划生成
    3. 多步骤任务编排
    4. 与 CognitionOrchestrator 对接
    """

    def __init__(self, max_concurrent_steps: int = 5):
        """
        初始化编排器

        Args:
            max_concurrent_steps: 最大并发步骤数
        """
        self.max_concurrent_steps = max_concurrent_steps

        # 存储执行计划
        self._plans: Dict[str, ExecutionPlan] = {}

        # 步骤执行器注册表
        self._step_executors: Dict[str, Callable] = {}

        # 执行历史
        self._execution_history: List[Dict[str, Any]] = []

        # 统计信息
        self._stats = {
            "plans_created": 0,
            "plans_completed": 0,
            "plans_failed": 0,
            "steps_executed": 0,
            "steps_failed": 0,
        }

        logger.info("PlanOrchestrator initialized")

    def register_step_executor(self, step_type: str, executor: Callable) -> None:
        """
        注册步骤执行器

        Args:
            step_type: 步骤类型
            executor: 执行器函数
        """
        self._step_executors[step_type] = executor
        logger.info("Registered step executor for type: %s", step_type)

    def create_plan(
        self,
        name: str,
        description: str = "",
        steps: Optional[List[Dict[str, Any]]] = None,
        priority: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExecutionPlan:
        """
        创建执行计划

        Args:
            name: 计划名称
            description: 计划描述
            steps: 步骤定义列表
            priority: 优先级
            metadata: 元数据

        Returns:
            创建的执行计划
        """
        plan = ExecutionPlan(name=name, description=description, priority=priority, metadata=metadata or {})

        # 添加步骤
        if steps:
            for step_data in steps:
                step = ExecutionStep.from_dict(step_data)
                plan.steps.append(step)

        # 存储计划
        self._plans[plan.id] = plan
        self._stats["plans_created"] += 1

        logger.info("Created plan: %s (ID: %s)", plan.name, plan.id)
        return plan

    async def execute_plan(self, plan_id: str, context: Optional[Dict[str, Any]] = None) -> ExecutionPlan:
        """
        执行计划

        Args:
            plan_id: 计划ID
            context: 执行上下文

        Returns:
            执行后的计划
        """
        plan = self._plans.get(plan_id)
        if not plan:
            raise ValueError(f"Plan not found: {plan_id}")

        if plan.status == PlanStatus.RUNNING:
            raise ValueError(f"Plan is already running: {plan_id}")

        # 更新状态
        plan.status = PlanStatus.RUNNING
        plan.started_at = time.time()

        logger.info("Executing plan: %s (ID: %s)", plan.name, plan.id)

        try:
            # 按依赖关系执行步骤
            await self._execute_steps(plan, context or {})

            # 检查是否完成
            if plan.is_complete():
                plan.status = PlanStatus.COMPLETED
                self._stats["plans_completed"] += 1
                logger.info("Plan completed: %s", plan.name)
            else:
                plan.status = PlanStatus.FAILED
                self._stats["plans_failed"] += 1
                logger.warning("Plan failed: %s", plan.name)

        except Exception as e:
            plan.status = PlanStatus.FAILED
            self._stats["plans_failed"] += 1
            logger.error("Plan execution failed: %s", e)
            raise

        finally:
            plan.completed_at = time.time()
            if plan.started_at:
                plan.duration_ms = (plan.completed_at - plan.started_at) * 1000

        return plan

    async def _execute_steps(self, plan: ExecutionPlan, context: Dict[str, Any]) -> None:
        """执行计划步骤"""
        # 构建依赖图
        dependency_graph = self._build_dependency_graph(plan)

        # 找出可以并行执行的步骤
        executable_steps = self._get_executable_steps(plan, dependency_graph)

        while executable_steps:
            # 并行执行可执行的步骤
            tasks = []
            for step in executable_steps[: self.max_concurrent_steps]:
                task = asyncio.create_task(self._execute_step_with_retry(step, context))
                tasks.append(task)

            # 等待所有任务完成
            await asyncio.gather(*tasks, return_exceptions=True)

            # 更新可执行步骤
            executable_steps = self._get_executable_steps(plan, dependency_graph)

    def _build_dependency_graph(self, plan: ExecutionPlan) -> Dict[str, List[str]]:
        """构建依赖图"""
        graph = {}
        for step in plan.steps:
            graph[step.id] = step.dependencies.copy()
        return graph

    def _get_executable_steps(self, plan: ExecutionPlan, dependency_graph: Dict[str, List[str]]) -> List[ExecutionStep]:
        """获取可执行的步骤"""
        executable = []

        for step in plan.steps:
            # 跳过已完成或失败的步骤
            if step.status in [StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.CANCELLED, StepStatus.SKIPPED]:
                continue

            # 检查依赖是否满足
            dependencies = dependency_graph.get(step.id, [])
            dependencies_met = all(
                plan.get_step(dep_id) and plan.get_step(dep_id).status in [StepStatus.COMPLETED, StepStatus.SKIPPED]
                for dep_id in dependencies
            )

            if dependencies_met and step.status == StepStatus.PENDING:
                executable.append(step)

        return executable

    async def _execute_step_with_retry(self, step: ExecutionStep, context: Dict[str, Any]) -> None:
        """带重试的步骤执行"""
        step.status = StepStatus.RUNNING
        step.started_at = time.time()

        for attempt in range(step.max_retries + 1):
            try:
                # 执行步骤
                result = await self._execute_step(step, context)

                # 成功
                step.status = StepStatus.COMPLETED
                step.result = result
                step.completed_at = time.time()
                step.duration_ms = (step.completed_at - step.started_at) * 1000

                self._stats["steps_executed"] += 1
                logger.info("Step completed: %s (attempt %s)", step.name, attempt + 1)
                return

            except Exception as e:
                step.retry_count = attempt + 1
                step.error = str(e)

                if attempt < step.max_retries:
                    logger.warning("Step failed, retrying: %s (attempt %s)", step.name, attempt + 1)
                    await asyncio.sleep(1 * (attempt + 1))  # 指数退避
                else:
                    step.status = StepStatus.FAILED
                    step.completed_at = time.time()
                    step.duration_ms = (step.completed_at - step.started_at) * 1000

                    self._stats["steps_failed"] += 1
                    logger.error("Step failed after %s attempts: %s", step.max_retries + 1, step.name)
                    raise

    async def _execute_step(self, step: ExecutionStep, context: Dict[str, Any]) -> Any:
        """执行单个步骤"""
        step_type = step.step_type

        # 查找执行器
        executor = self._step_executors.get(step_type)
        if not executor:
            raise ValueError(f"No executor registered for step type: {step_type}")

        # 准备执行参数
        exec_params = {"step": step, "context": context, "parameters": step.parameters}

        # 执行
        if asyncio.iscoroutinefunction(executor):
            return await executor(**exec_params)
        else:
            return executor(**exec_params)

    def _analyze_complexity(self, task_description: str, context: Optional[Dict[str, Any]] = None) -> TaskComplexity:
        """
        分析任务复杂度

        Args:
            task_description: 任务描述
            context: 上下文

        Returns:
            任务复杂度分析
        """
        # 简单启发式分析
        complexity = TaskComplexity()

        # 基于描述长度估算
        word_count = len(task_description.split())
        if word_count < 10:
            complexity.level = "low"
            complexity.estimated_steps = 1
        elif word_count < 30:
            complexity.level = "medium"
            complexity.estimated_steps = 3
        elif word_count < 100:
            complexity.level = "high"
            complexity.estimated_steps = 5
        else:
            complexity.level = "very_high"
            complexity.estimated_steps = 10

        # 估算耗时（每步骤平均5秒）
        complexity.estimated_duration_ms = complexity.estimated_steps * 5000

        # 检查关键词
        keywords = task_description.lower()
        if any(word in keywords for word in ["复杂", "困难", "挑战", "complex", "difficult"]):
            complexity.risks.append("任务描述包含复杂度关键词")

        if any(word in keywords for word in ["并行", "同时", "parallel", "simultaneous"]):
            complexity.recommendations.append("考虑并行执行")

        return complexity

    def _decompose_task(self, task_description: str, context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        分解任务

        Args:
            task_description: 任务描述
            context: 上下文

        Returns:
            步骤定义列表
        """
        # 简单分解策略
        steps = []

        # 分析任务描述
        sentences = task_description.split("。")
        for i, sentence in enumerate(sentences):
            if sentence.strip():
                step = {"name": f"Step {i + 1}", "description": sentence.strip(), "step_type": "task", "parameters": {}}
                steps.append(step)

        # 如果没有分解出步骤，创建单个步骤
        if not steps:
            steps = [{"name": "Main Task", "description": task_description, "step_type": "task", "parameters": {}}]

        return steps

    def _optimize_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        """
        优化计划

        Args:
            plan: 执行计划

        Returns:
            优化后的计划
        """
        # 分析依赖关系
        dependency_graph = self._build_dependency_graph(plan)

        # 识别可以并行执行的步骤
        parallel_groups = self._identify_parallel_groups(plan, dependency_graph)

        # 更新步骤元数据
        for group_idx, group in enumerate(parallel_groups):
            for step_id in group:
                step = plan.get_step(step_id)
                if step:
                    step.metadata["parallel_group"] = group_idx

        logger.info("Optimized plan: %s parallel groups identified", len(parallel_groups))
        return plan

    def _identify_parallel_groups(self, plan: ExecutionPlan, dependency_graph: Dict[str, List[str]]) -> List[List[str]]:
        """识别可并行执行的步骤组"""
        groups = []
        processed = set()

        # 拓扑排序
        while len(processed) < len(plan.steps):
            # 找出没有未处理依赖的步骤
            current_group = []
            for step in plan.steps:
                if step.id in processed:
                    continue

                dependencies = dependency_graph.get(step.id, [])
                if all(dep_id in processed for dep_id in dependencies):
                    current_group.append(step.id)

            if not current_group:
                # 避免无限循环
                break

            groups.append(current_group)
            processed.update(current_group)

        return groups

    def get_plan(self, plan_id: str) -> Optional[ExecutionPlan]:
        """获取计划"""
        return self._plans.get(plan_id)

    def get_all_plans(self) -> List[ExecutionPlan]:
        """获取所有计划"""
        return list(self._plans.values())

    def delete_plan(self, plan_id: str) -> bool:
        """删除计划"""
        if plan_id in self._plans:
            del self._plans[plan_id]
            logger.info("Deleted plan: %s", plan_id)
            return True
        return False

    def cancel_plan(self, plan_id: str) -> bool:
        """取消计划"""
        plan = self._plans.get(plan_id)
        if not plan:
            return False

        plan.status = PlanStatus.CANCELLED
        plan.completed_at = time.time()

        # 取消所有待执行的步骤
        for step in plan.steps:
            if step.status in [StepStatus.PENDING, StepStatus.RUNNING]:
                step.status = StepStatus.CANCELLED

        logger.info("Cancelled plan: %s", plan_id)
        return True

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "active_plans": len([p for p in self._plans.values() if p.status == PlanStatus.RUNNING]),
            "total_plans": len(self._plans),
            "registered_executors": list(self._step_executors.keys()),
        }


# 全局实例
_plan_orchestrator: Optional[PlanOrchestrator] = None
_plan_orchestrator_lock = __import__('threading').Lock()


def get_plan_orchestrator() -> PlanOrchestrator:
    """获取 PlanOrchestrator 全局唯一实例"""
    global _plan_orchestrator
    if _plan_orchestrator is None:
        with _plan_orchestrator_lock:
            if _plan_orchestrator is None:
                _plan_orchestrator = PlanOrchestrator()
    return _plan_orchestrator


def reset_plan_orchestrator() -> None:
    """重置 PlanOrchestrator 全局实例（用于测试）"""
    global _plan_orchestrator
    _plan_orchestrator = None
