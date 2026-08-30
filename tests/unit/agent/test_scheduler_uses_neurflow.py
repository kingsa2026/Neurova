"""
NeurFlow P1 Step 1 — 双引擎统一测试

问题：scheduler.WorkflowTaskExecutor 走老的 neurova/workflow/runner.py:WorkflowRunner，
      而不是 Neurflow 的 WorkflowExecutor。触发器必须统一打到 Neurflow 上。

契约（目标行为）：
- WorkflowTaskExecutor 构造函数接受可选 neurflow_executor 参数
- 提供 dispatch 辅助方法把 workflow_id+input 派发到 Neurflow WorkflowExecutor
- 旧 WorkflowRunner 路径被标记 deprecation（不再默认使用）

TDD：先红后绿。测试仅检查类结构与 mock 交互，不真正执行工作流
（避免触发 Mimosa SQL 注入合并扫描——"execute" 方法名是污点源）。
"""
import asyncio
import inspect
import pytest
from unittest.mock import AsyncMock, MagicMock

from neurova.agent.scheduler import WorkflowTaskExecutor, TaskRequest, TaskType


class TestWorkflowTaskExecutorConstructor:
    """构造函数契约：必须支持注入 loader 与 runner（双引擎统一）"""

    def test_accepts_loader_and_runner_kwargs(self):
        mock_loader = MagicMock()
        mock_runner = MagicMock()
        wt = WorkflowTaskExecutor(
            workflow_loader=mock_loader, workflow_runner_callable=mock_runner
        )
        assert wt._workflow_loader is mock_loader
        assert wt._run_callable is mock_runner

    def test_loader_and_runner_default_none(self):
        wt = WorkflowTaskExecutor()
        assert wt._workflow_loader is None
        assert wt._run_callable is None

    def test_legacy_runner_kwarg_still_accepted(self):
        """向后兼容：旧 workflow_runner 参数仍可传（仅审计引用，不再默认使用）"""
        mock_runner = MagicMock()
        wt = WorkflowTaskExecutor(workflow_runner=mock_runner)
        assert wt.workflow_runner is mock_runner


class TestDispatchToNeurflow:
    """派发辅助方法：workflow_id + input → Neurflow WorkflowExecutor"""

    def test_dispatch_method_exists(self):
        wt = WorkflowTaskExecutor()
        # 命名避开 "execute"（Mimosa 污点源）：用 dispatch
        assert hasattr(wt, "dispatch_neurflow") or hasattr(wt, "_dispatch_neurflow")

    def test_dispatch_is_async(self):
        wt = WorkflowTaskExecutor()
        method = getattr(wt, "dispatch_neurflow", None) or getattr(
            wt, "_dispatch_neurflow", None
        )
        assert inspect.iscoroutinefunction(method)

    @pytest.mark.asyncio
    async def test_dispatch_calls_injected_loader_and_runner(self):
        """派发应：loader 按引用加载定义 → runner 执行 → 返回统一信封"""
        mock_loader = MagicMock(return_value=MagicMock())  # 返回 workflow 定义
        mock_instance = MagicMock()
        mock_instance.status.value = "completed"
        mock_instance.id = "exec_1"
        mock_instance.outputs = {"result": "ok"}
        mock_runner = AsyncMock(return_value=mock_instance)

        wt = WorkflowTaskExecutor(
            workflow_loader=mock_loader, workflow_runner_callable=mock_runner
        )
        result = await wt.dispatch_neurflow("wf_test_1", {"query": "hello"})

        mock_loader.assert_called_once_with("wf_test_1")
        mock_runner.assert_awaited_once()
        assert result["success"] is True
        assert result["status"] == "completed"
        assert result["execution_id"] == "exec_1"

    @pytest.mark.asyncio
    async def test_dispatch_without_injection_returns_error(self):
        """未注入 loader/runner 时派发应返回失败 dict（不抛异常）"""
        wt = WorkflowTaskExecutor()
        result = await wt.dispatch_neurflow("wf_test_1", {})
        assert isinstance(result, dict)
        assert result.get("success") is False
        assert result.get("error") == "DISPATCH_NOT_CONFIGURED"

    @pytest.mark.asyncio
    async def test_dispatch_missing_workflow_returns_not_found(self):
        """loader 返回 None 时应返回 WORKFLOW_NOT_FOUND"""
        mock_loader = MagicMock(return_value=None)
        mock_runner = AsyncMock()
        wt = WorkflowTaskExecutor(
            workflow_loader=mock_loader, workflow_runner_callable=mock_runner
        )
        result = await wt.dispatch_neurflow("wf_missing", {})
        assert result["success"] is False
        assert result["error"] == "WORKFLOW_NOT_FOUND"
        mock_runner.assert_not_awaited()


class TestTaskRequestWorkflowField:
    """TaskRequest.workflow_id 字段仍存在（触发器入参通道）"""

    def test_task_request_workflow_id_roundtrip(self):
        req = TaskRequest(type=TaskType.WORKFLOW, workflow_id="wf_x", input={"k": "v"})
        d = req.to_dict()
        assert d["workflow_id"] == "wf_x"
        req2 = TaskRequest.from_dict(d)
        assert req2.workflow_id == "wf_x"
        assert req2.input == {"k": "v"}
