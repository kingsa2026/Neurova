"""
测试计划编排器（对齐 neurova/core/plan_orchestrator.py 真实契约）
"""
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from neurova.core.plan_orchestrator import (
    TaskComplexity,
    RetryPolicy,
    TaskNode,
    Plan,
    PlanResult,
    ExecutionFeedback,
    PlanOrchestrator,
)


class TestTaskComplexity:
    """测试TaskComplexity枚举"""

    def test_task_complexity_members(self):
        """测试复杂度枚举成员"""
        assert TaskComplexity.SIMPLE.value == "simple"
        assert TaskComplexity.COMPOUND.value == "compound"
        assert TaskComplexity.PARALLEL.value == "parallel"
        assert TaskComplexity.DAG.value == "dag"


class TestRetryPolicy:
    """测试RetryPolicy枚举"""

    def test_retry_policy_members(self):
        """测试重试策略枚举成员"""
        assert RetryPolicy.NONE.value == "none"
        assert RetryPolicy.LINEAR.value == "linear"
        assert RetryPolicy.EXPONENTIAL.value == "exponential"
        assert RetryPolicy.FIXED.value == "fixed"


class TestTaskNode:
    """测试TaskNode数据类"""

    def test_create_task_node(self):
        """测试创建任务节点"""
        node = TaskNode(
            task_id="task_1",
            description="测试任务",
            tool_name="test_tool",
        )

        assert node.task_id == "task_1"
        assert node.description == "测试任务"
        assert node.tool_name == "test_tool"
        assert node.dependencies == []
        assert node.retry_policy == RetryPolicy.NONE
        assert node.metadata == {}

    def test_task_node_auto_id(self):
        """未指定 task_id 时自动生成"""
        node = TaskNode(description="自动ID任务")

        assert node.task_id != ""

    def test_task_node_with_dependencies(self):
        """测试带依赖的任务节点"""
        node = TaskNode(
            task_id="task_2",
            description="依赖任务",
            dependencies=["task_1"],
        )

        assert node.dependencies == ["task_1"]

    def test_task_node_with_retry_policy(self):
        """测试带重试策略的任务节点"""
        node = TaskNode(
            task_id="task_1",
            description="测试任务",
            retry_policy=RetryPolicy.LINEAR,
            max_retries=5,
        )

        assert node.retry_policy == RetryPolicy.LINEAR
        assert node.max_retries == 5

    def test_task_node_to_dict(self):
        """测试任务节点字典化"""
        node = TaskNode(task_id="task_1", description="任务", tool_name="tool")
        data = node.to_dict()

        assert data["task_id"] == "task_1"
        assert data["tool_name"] == "tool"
        assert data["retry_policy"] == "none"


class TestPlan:
    """测试Plan数据类"""

    def test_create_plan(self):
        """测试创建计划"""
        tasks = [
            TaskNode(task_id="task_1", description="任务1"),
            TaskNode(task_id="task_2", description="任务2"),
        ]

        plan = Plan(
            plan_id="plan_1",
            description="测试计划",
            complexity=TaskComplexity.SIMPLE,
            tasks=tasks,
        )

        assert plan.plan_id == "plan_1"
        assert plan.description == "测试计划"
        assert plan.complexity == TaskComplexity.SIMPLE
        assert len(plan.tasks) == 2

    def test_plan_to_dict(self):
        """测试计划字典化"""
        plan = Plan(plan_id="plan_1", name="计划", complexity=TaskComplexity.DAG)
        data = plan.to_dict()

        assert data["plan_id"] == "plan_1"
        assert data["complexity"] == "dag"


class TestPlanResult:
    """测试PlanResult数据类"""

    def test_create_plan_result(self):
        """测试创建计划结果"""
        result = PlanResult(
            plan_id="plan_1",
            success=True,
            task_results={"task_1": "result1"},
            total_duration_ms=1500.0,
        )

        assert result.plan_id == "plan_1"
        assert result.success is True
        assert result.total_duration_ms == 1500.0
        assert result.error is None

    def test_plan_result_to_dict(self):
        """测试计划结果字典化"""
        result = PlanResult(plan_id="plan_1", success=False, error="boom")
        data = result.to_dict()

        assert data["success"] is False
        assert data["error"] == "boom"


class TestExecutionFeedback:
    """测试ExecutionFeedback数据类"""

    def test_create_execution_feedback(self):
        """测试创建执行反馈"""
        feedback = ExecutionFeedback(
            task_id="task_1",
            success=True,
            output={"result": "result"},
            error=None,
            duration_ms=1.0,
        )

        assert feedback.task_id == "task_1"
        assert feedback.success is True
        assert feedback.output == {"result": "result"}
        assert feedback.error is None
        assert feedback.duration_ms == 1.0


class TestPlanOrchestrator:
    """测试PlanOrchestrator类"""

    def test_init(self):
        """测试初始化"""
        orchestrator = PlanOrchestrator()

        assert orchestrator._plans == {}
        assert orchestrator._executor is None

    def test_decompose_intent_simple(self):
        """测试分解简单意图（同步方法）"""
        orchestrator = PlanOrchestrator()

        plan = orchestrator.decompose_intent(
            intent="执行简单任务",
            context={},
        )

        assert plan is not None
        assert plan.complexity == TaskComplexity.SIMPLE
        assert len(plan.tasks) >= 1

    def test_decompose_intent_compound(self):
        """测试分解复合意图"""
        orchestrator = PlanOrchestrator()

        plan = orchestrator.decompose_intent(
            intent="执行任务A然后执行任务B",
            context={},
        )

        assert plan.complexity == TaskComplexity.COMPOUND

    def test_decompose_intent_parallel(self):
        """测试分解并行意图"""
        orchestrator = PlanOrchestrator()

        plan = orchestrator.decompose_intent(
            intent="同时执行多个任务",
            context={},
        )

        assert plan.complexity == TaskComplexity.PARALLEL

    def test_decompose_intent_dag(self):
        """测试分解 DAG 意图"""
        orchestrator = PlanOrchestrator()

        plan = orchestrator.decompose_intent(
            intent="执行依赖任务",
            context={},
        )

        assert plan.complexity == TaskComplexity.DAG

    def test_decompose_intent_stores_plan(self):
        """分解后的计划被登记，可通过 get_plan/list_plans 取回"""
        orchestrator = PlanOrchestrator()

        plan = orchestrator.decompose_intent("执行任务")

        assert orchestrator.get_plan(plan.plan_id) is plan
        assert plan in orchestrator.list_plans()

    @pytest.mark.asyncio
    async def test_execute_plan(self):
        """测试执行计划（契约：execute_plan(plan_id)）"""
        orchestrator = PlanOrchestrator()

        plan = orchestrator.decompose_intent(
            intent="执行任务",
            context={},
        )

        result = await orchestrator.execute_plan(plan.plan_id)

        assert result is not None
        assert result.plan_id == plan.plan_id
        assert result.success is True
        assert set(result.task_results.keys()) == {t.task_id for t in plan.tasks}

    @pytest.mark.asyncio
    async def test_execute_plan_not_found(self):
        """执行不存在的计划返回失败结果"""
        orchestrator = PlanOrchestrator()

        result = await orchestrator.execute_plan("nonexistent")

        assert result.success is False
        assert "not found" in (result.error or "")

    def test_adjust_plan(self):
        """测试调整计划（契约：adjust_plan(plan_id, feedback)，失败反馈就地升级重试策略）"""
        orchestrator = PlanOrchestrator()

        plan = orchestrator.decompose_intent(
            intent="执行任务",
            context={},
        )
        task = plan.tasks[0]

        feedback = ExecutionFeedback(
            task_id=task.task_id,
            success=False,
            error="执行失败",
            duration_ms=1.0,
        )

        adjusted_plan = orchestrator.adjust_plan(plan.plan_id, feedback)

        assert adjusted_plan is plan
        assert task.retry_policy == RetryPolicy.LINEAR
        assert task.max_retries == 3

    def test_adjust_plan_not_found(self):
        """调整不存在的计划返回 None"""
        orchestrator = PlanOrchestrator()

        feedback = ExecutionFeedback(task_id="task_1", success=False)
        assert orchestrator.adjust_plan("nonexistent", feedback) is None

    def test_get_plan(self):
        """测试获取计划"""
        orchestrator = PlanOrchestrator()

        plan = orchestrator.get_plan("nonexistent")

        assert plan is None

    def test_list_plans(self):
        """测试列出计划"""
        orchestrator = PlanOrchestrator()

        plans = orchestrator.list_plans()

        assert plans == []


class TestTopologicalSort:
    """测试拓扑排序"""

    def test_topological_sort_simple(self):
        """测试简单拓扑排序"""
        orchestrator = PlanOrchestrator()

        tasks = [
            TaskNode(task_id="task_1", description="任务1"),
            TaskNode(task_id="task_2", description="任务2", dependencies=["task_1"]),
        ]

        sorted_tasks = orchestrator._topological_sort(tasks)

        assert sorted_tasks[0].task_id == "task_1"
        assert sorted_tasks[1].task_id == "task_2"

    def test_topological_sort_complex(self):
        """测试复杂拓扑排序"""
        orchestrator = PlanOrchestrator()

        tasks = [
            TaskNode(task_id="task_1", description="任务1"),
            TaskNode(task_id="task_2", description="任务2", dependencies=["task_1"]),
            TaskNode(task_id="task_3", description="任务3", dependencies=["task_1"]),
            TaskNode(task_id="task_4", description="任务4", dependencies=["task_2", "task_3"]),
        ]

        sorted_tasks = orchestrator._topological_sort(tasks)

        assert sorted_tasks[0].task_id == "task_1"
        assert sorted_tasks[3].task_id == "task_4"

    def test_topological_sort_missing_dependency(self):
        """依赖缺失的任务仍出现在结果中（不崩）"""
        orchestrator = PlanOrchestrator()

        tasks = [
            TaskNode(task_id="task_1", description="任务1", dependencies=["ghost"]),
        ]

        sorted_tasks = orchestrator._topological_sort(tasks)

        assert [t.task_id for t in sorted_tasks] == ["task_1"]


class TestComplexityAnalysis:
    """测试复杂度分析"""

    def test_analyze_simple_intent(self):
        """测试简单意图分析"""
        orchestrator = PlanOrchestrator()

        complexity = orchestrator._analyze_complexity("简单任务", {})

        assert complexity == TaskComplexity.SIMPLE

    def test_analyze_compound_intent(self):
        """测试复合意图分析"""
        orchestrator = PlanOrchestrator()

        complexity = orchestrator._analyze_complexity("先执行A然后执行B", {})

        assert complexity == TaskComplexity.COMPOUND

    def test_analyze_parallel_intent(self):
        """测试并行意图分析"""
        orchestrator = PlanOrchestrator()

        complexity = orchestrator._analyze_complexity("同时执行", {})

        assert complexity == TaskComplexity.PARALLEL

    def test_analyze_dag_intent(self):
        """测试 DAG 意图分析"""
        orchestrator = PlanOrchestrator()

        complexity = orchestrator._analyze_complexity("依赖模块A", {})

        assert complexity == TaskComplexity.DAG
