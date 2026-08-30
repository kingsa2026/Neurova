"""
NeurFlow P0 Step 2 — 流式调试 API 测试

测试 DebugSession 与 execute_debug：
- DebugSession 是 dataclass，含 asyncio.Event 字段（resume_event）
- WorkflowExecutor.execute_debug() 存在且为 async generator
- DebugSession.wait_resume() 是 async 方法
- DebugSession.resume() 触发事件，让 wait_resume 解除阻塞

TDD：先红后绿。仅测数据契约，不调 WorkflowExecutor.execute。
"""
import asyncio
import inspect
import pytest

from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor


class TestDebugSession:
    """DebugSession 数据契约"""

    def test_debug_session_is_importable(self):
        from neurova.collaboration.neurflow.execution_engine import DebugSession

        assert DebugSession is not None

    def test_debug_session_has_resume_event_field(self):
        from neurova.collaboration.neurflow.execution_engine import DebugSession

        session = DebugSession()
        assert hasattr(session, "resume_event")
        assert isinstance(session.resume_event, asyncio.Event)

    def test_debug_session_has_breakpoints_field(self):
        from neurova.collaboration.neurflow.execution_engine import DebugSession

        session = DebugSession(breakpoints={"n1", "n2"})
        assert session.breakpoints == {"n1", "n2"}

    def test_debug_session_default_breakpoints_empty(self):
        from neurova.collaboration.neurflow.execution_engine import DebugSession

        session = DebugSession()
        assert session.breakpoints == set() or session.breakpoints is None

    def test_debug_session_has_step_mode_field(self):
        from neurova.collaboration.neurflow.execution_engine import DebugSession

        session = DebugSession()
        assert hasattr(session, "step_mode")
        # step_mode: None | "in" | "over" | "out"
        assert session.step_mode in (None, "in", "over", "out")


class TestDebugSessionAsync:
    """DebugSession 异步行为契约"""

    @pytest.mark.asyncio
    async def test_wait_resume_blocks_until_resume_called(self):
        from neurova.collaboration.neurflow.execution_engine import DebugSession

        session = DebugSession()
        # wait_resume 应在未 resume 时阻塞；resume 后立即返回
        task = asyncio.create_task(session.wait_resume())
        await asyncio.sleep(0.02)
        assert not task.done(), "未 resume 时 wait_resume 应阻塞"

        session.resume()
        await asyncio.wait_for(task, timeout=1.0)
        assert task.done()

    @pytest.mark.asyncio
    async def test_resume_is_synchronous_method(self):
        from neurova.collaboration.neurflow.execution_engine import DebugSession

        session = DebugSession()
        # resume() 自身必须是同步触发；不可 await
        assert not inspect.iscoroutinefunction(session.resume)

        # 行为：resume 后 wait_resume 解锁
        task = asyncio.create_task(session.wait_resume())
        session.resume()
        await asyncio.wait_for(task, timeout=1.0)


class TestExecuteDebugMethod:
    """WorkflowExecutor.execute_debug 契约"""

    def test_execute_debug_method_exists(self):
        assert hasattr(WorkflowExecutor, "execute_debug")

    def test_execute_debug_is_async_generator(self):
        method = WorkflowExecutor.execute_debug
        assert inspect.isasyncgenfunction(method), "execute_debug 应为 async generator"

    def test_execute_debug_signature_accepts_breakpoints(self):
        sig = inspect.signature(WorkflowExecutor.execute_debug)
        assert "breakpoints" in sig.parameters or "debug_session" in sig.parameters


class TestDebugSessionPauseResume:
    """DebugSession 暂停/恢复模式：step_mode 决定下一步行为"""

    @pytest.mark.asyncio
    async def test_step_mode_can_be_set_to_in(self):
        from neurova.collaboration.neurflow.execution_engine import DebugSession

        session = DebugSession()
        session.step_mode = "in"
        assert session.step_mode == "in"

    @pytest.mark.asyncio
    async def test_step_mode_can_be_set_to_over(self):
        from neurova.collaboration.neurflow.execution_engine import DebugSession

        session = DebugSession()
        session.step_mode = "over"
        assert session.step_mode == "over"

    @pytest.mark.asyncio
    async def test_step_mode_can_be_set_to_out(self):
        from neurova.collaboration.neurflow.execution_engine import DebugSession

        session = DebugSession()
        session.step_mode = "out"
        assert session.step_mode == "out"


class TestExecuteDebugBackwardCompat:
    """原有 execute() 仍然存在（向后兼容）"""

    def test_execute_method_still_exists(self):
        assert hasattr(WorkflowExecutor, "execute")
        # execute 是普通 async 方法（非 generator）
        assert inspect.iscoroutinefunction(WorkflowExecutor.execute)