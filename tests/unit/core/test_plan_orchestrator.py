"""
测试计划编排器
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
        assert TaskComplexity.ITERATIVE.value == "iterative"


class TestRetryPolicy:
    """测试RetryPolicy数据类"""
    
    def test_create_retry_policy(self):
        """测试创建重试策略"""
        policy = RetryPolicy()
        
        assert policy.max_retries == 3
        assert policy.retry_delay == 1.0
        assert policy.exponential_backoff is True
    
    def test_create_custom_retry_policy(self):
        """测试创建自定义重试策略"""
        policy = RetryPolicy(
            max_retries=5,
            retry_delay=2.0,
            exponential_backoff=False,
        )
        
        assert policy.max_retries == 5
        assert policy.retry_delay == 2.0
        assert policy.exponential_backoff is False


class TestTaskNode:
    """测试TaskNode数据类"""
    
    def test_create_task_node(self):
        """测试创建任务节点"""
        node = TaskNode(
            id="task_1",
            description="测试任务",
            tool="test_tool",
            agent="test_agent",
        )
        
        assert node.id == "task_1"
        assert node.description == "测试任务"
        assert node.tool == "test_tool"
        assert node.agent == "test_agent"
        assert node.depends_on == []
        assert node.status == "pending"
        assert node.result is None
        assert node.error is None
    
    def test_task_node_with_dependencies(self):
        """测试带依赖的任务节点"""
        node = TaskNode(
            id="task_2",
            description="依赖任务",
            depends_on=["task_1"],
        )
        
        assert node.depends_on == ["task_1"]
    
    def test_task_node_with_retry_policy(self):
        """测试带重试策略的任务节点"""
        policy = RetryPolicy(max_retries=5)
        node = TaskNode(
            id="task_1",
            description="测试任务",
            retry_policy=policy,
        )
        
        assert node.retry_policy.max_retries == 5


class TestPlan:
    """测试Plan数据类"""
    
    def test_create_plan(self):
        """测试创建计划"""
        tasks = [
            TaskNode(id="task_1", description="任务1"),
            TaskNode(id="task_2", description="任务2"),
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


class TestPlanResult:
    """测试PlanResult数据类"""
    
    def test_create_plan_result(self):
        """测试创建计划结果"""
        now = datetime.now()
        
        result = PlanResult(
            plan_id="plan_1",
            success=True,
            task_results={"task_1": "result1"},
            errors=[],
            started_at=now,
            completed_at=now,
            duration_seconds=1.5,
        )
        
        assert result.plan_id == "plan_1"
        assert result.success is True
        assert result.duration_seconds == 1.5


class TestExecutionFeedback:
    """测试ExecutionFeedback数据类"""
    
    def test_create_execution_feedback(self):
        """测试创建执行反馈"""
        feedback = ExecutionFeedback(
            task_id="task_1",
            success=True,
            result="result",
            error=None,
            execution_time=1.0,
        )
        
        assert feedback.task_id == "task_1"
        assert feedback.success is True
        assert feedback.result == "result"
        assert feedback.error is None
        assert feedback.execution_time == 1.0


class TestPlanOrchestrator:
    """测试PlanOrchestrator类"""
    
    def test_init(self):
        """测试初始化"""
        orchestrator = PlanOrchestrator()
        
        assert orchestrator.event_bus is None
        assert orchestrator.service_manager is None
        assert orchestrator.active_plans == {}
        assert orchestrator.task_results == {}
    
    @pytest.mark.asyncio
    async def test_decompose_intent_simple(self):
        """测试分解简单意图"""
        orchestrator = PlanOrchestrator()
        
        plan = await orchestrator.decompose_intent(
            intent="执行简单任务",
            context={},
        )
        
        assert plan is not None
        assert plan.complexity == TaskComplexity.SIMPLE
        assert len(plan.tasks) >= 1
    
    @pytest.mark.asyncio
    async def test_decompose_intent_compound(self):
        """测试分解复合意图"""
        orchestrator = PlanOrchestrator()
        
        plan = await orchestrator.decompose_intent(
            intent="执行任务A和任务B",
            context={},
        )
        
        assert plan.complexity == TaskComplexity.COMPOUND
    
    @pytest.mark.asyncio
    async def test_decompose_intent_parallel(self):
        """测试分解并行意图"""
        orchestrator = PlanOrchestrator()
        
        plan = await orchestrator.decompose_intent(
            intent="同时执行多个任务",
            context={},
        )
        
        assert plan.complexity == TaskComplexity.PARALLEL
    
    @pytest.mark.asyncio
    async def test_decompose_intent_iterative(self):
        """测试分解迭代意图"""
        orchestrator = PlanOrchestrator()
        
        plan = await orchestrator.decompose_intent(
            intent="重复执行任务",
            context={},
        )
        
        assert plan.complexity == TaskComplexity.ITERATIVE
    
    @pytest.mark.asyncio
    async def test_execute_plan(self):
        """测试执行计划"""
        orchestrator = PlanOrchestrator()
        
        plan = await orchestrator.decompose_intent(
            intent="执行任务",
            context={},
        )
        
        result = await orchestrator.execute_plan(plan)
        
        assert result is not None
        assert result.plan_id == plan.plan_id
        assert "completed" in [t.status for t in plan.tasks]
    
    @pytest.mark.asyncio
    async def test_execute_plan_with_event_bus(self):
        """测试带事件总线的计划执行"""
        mock_event_bus = MagicMock()
        orchestrator = PlanOrchestrator(event_bus=mock_event_bus)
        
        plan = await orchestrator.decompose_intent(
            intent="执行任务",
            context={},
        )
        
        result = await orchestrator.execute_plan(plan)
        
        assert mock_event_bus.emit.called
    
    @pytest.mark.asyncio
    async def test_adjust_plan(self):
        """测试调整计划"""
        orchestrator = PlanOrchestrator()
        
        plan = await orchestrator.decompose_intent(
            intent="执行任务",
            context={},
        )
        
        feedback = [
            ExecutionFeedback(
                task_id="task_1",
                success=False,
                result=None,
                error="执行失败",
                execution_time=1.0,
                suggestions=["重试建议"],
            )
        ]
        
        adjusted_plan = await orchestrator.adjust_plan(plan, feedback)
        
        assert adjusted_plan is not None
        assert adjusted_plan.plan_id != plan.plan_id
        assert len(adjusted_plan.tasks) == len(plan.tasks)
    
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
    
    @pytest.mark.asyncio
    async def test_topological_sort_simple(self):
        """测试简单拓扑排序"""
        orchestrator = PlanOrchestrator()
        
        tasks = [
            TaskNode(id="task_1", description="任务1"),
            TaskNode(id="task_2", description="任务2", depends_on=["task_1"]),
        ]
        
        sorted_tasks = orchestrator._topological_sort(tasks)
        
        assert sorted_tasks[0].id == "task_1"
        assert sorted_tasks[1].id == "task_2"
    
    @pytest.mark.asyncio
    async def test_topological_sort_complex(self):
        """测试复杂拓扑排序"""
        orchestrator = PlanOrchestrator()
        
        tasks = [
            TaskNode(id="task_1", description="任务1"),
            TaskNode(id="task_2", description="任务2", depends_on=["task_1"]),
            TaskNode(id="task_3", description="任务3", depends_on=["task_1"]),
            TaskNode(id="task_4", description="任务4", depends_on=["task_2", "task_3"]),
        ]
        
        sorted_tasks = orchestrator._topological_sort(tasks)
        
        assert sorted_tasks[0].id == "task_1"
        assert sorted_tasks[3].id == "task_4"


class TestComplexityAnalysis:
    """测试复杂度分析"""
    
    @pytest.mark.asyncio
    async def test_analyze_simple_intent(self):
        """测试简单意图分析"""
        orchestrator = PlanOrchestrator()
        
        complexity = await orchestrator._analyze_complexity("简单任务", {})
        
        assert complexity == TaskComplexity.SIMPLE
    
    @pytest.mark.asyncio
    async def test_analyze_compound_intent(self):
        """测试复合意图分析"""
        orchestrator = PlanOrchestrator()
        
        complexity = await orchestrator._analyze_complexity("执行A和B", {})
        
        assert complexity == TaskComplexity.COMPOUND
    
    @pytest.mark.asyncio
    async def test_analyze_parallel_intent(self):
        """测试并行意图分析"""
        orchestrator = PlanOrchestrator()
        
        complexity = await orchestrator._analyze_complexity("同时执行", {})
        
        assert complexity == TaskComplexity.PARALLEL
    
    @pytest.mark.asyncio
    async def test_analyze_iterative_intent(self):
        """测试迭代意图分析"""
        orchestrator = PlanOrchestrator()
        
        complexity = await orchestrator._analyze_complexity("重复执行", {})
        
        assert complexity == TaskComplexity.ITERATIVE
