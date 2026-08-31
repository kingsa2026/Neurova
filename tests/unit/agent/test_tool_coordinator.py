"""
P1-2 工具执行协调器红测（对标 QP ToolCoordinator offload 语义）

- 超时注册表：per-tool 超时元数据（未知工具回落默认）
- 超时转后台：执行超时不取消——任务转入后台继续跑，立即返回 background
  信封；后台完成后经 pop_pending_hints 取回结果提示（注入下一轮上下文）
- 并行安全声明制：is_concurrency_safe 只对声明清单内的只读工具为 True
"""

import asyncio

import pytest

from neurova.agent.tool_coordinator import (
    TOOL_DEFAULT_TIMEOUT_S,
    get_tool_timeout,
    is_concurrency_safe,
    ToolCoordinator,
)


class TestTimeoutRegistry:
    def test_known_tool_uses_registered_timeout(self):
        assert get_tool_timeout("web_search") == 30
        assert get_tool_timeout("browser_navigate") == 90
        assert get_tool_timeout("memory_search") == 10

    def test_unknown_tool_falls_back_to_default(self):
        assert get_tool_timeout("totally_unknown_tool") == TOOL_DEFAULT_TIMEOUT_S

    def test_case_insensitive(self):
        assert get_tool_timeout("WEB_SEARCH") == 30


class TestConcurrencySafeDeclaration:
    def test_readonly_tools_declared_safe(self):
        for name in ("memory_search", "recall_history", "web_search", "calculator"):
            assert is_concurrency_safe(name) is True, name

    def test_side_effect_tools_not_safe(self):
        for name in ("file_write", "file_delete", "browser_click", "shell_execute"):
            assert is_concurrency_safe(name) is False, name

    def test_unknown_tool_conservative_false(self):
        assert is_concurrency_safe("totally_unknown_tool") is False


class TestCoordinatorOffload:
    @pytest.mark.asyncio
    async def test_completes_within_timeout_returns_result(self):
        coordinator = ToolCoordinator()

        async def fast():
            return {"ok": True}

        result = await coordinator.run_with_timeout("memory_search", fast, timeout=2.0)
        assert result == {"ok": True}
        assert coordinator.pop_pending_hints() == []

    @pytest.mark.asyncio
    async def test_timeout_offloads_to_background(self):
        """超时：任务不取消，转入后台继续；立即返回 background 信封"""
        coordinator = ToolCoordinator()
        finished = asyncio.Event()

        async def slow():
            await asyncio.sleep(0.3)
            finished.set()
            return {"data": "late result"}

        result = await coordinator.run_with_timeout("web_search", slow, timeout=0.05)
        assert result["status"] == "background"
        assert result["tool_name"] == "web_search"
        assert result.get("task_id")

        # 后台任务仍在跑并完成（未被取消）
        await asyncio.wait_for(finished.wait(), timeout=2.0)

    @pytest.mark.asyncio
    async def test_background_result_lands_in_pending_hints(self):
        coordinator = ToolCoordinator()

        async def slow():
            await asyncio.sleep(0.1)
            return {"data": "late result"}

        envelope = await coordinator.run_with_timeout("web_search", slow, timeout=0.02)
        task_id = envelope["task_id"]

        hints = []
        for _ in range(50):
            hints = coordinator.pop_pending_hints()
            if hints:
                break
            await asyncio.sleep(0.05)

        assert len(hints) == 1
        assert hints[0]["task_id"] == task_id
        assert hints[0]["tool_name"] == "web_search"
        assert "late result" in str(hints[0]["result"])
        assert coordinator.pop_pending_hints() == []  # 取走即清空

    @pytest.mark.asyncio
    async def test_background_error_recorded_as_failed_hint(self):
        coordinator = ToolCoordinator()

        async def boom():
            await asyncio.sleep(0.05)
            raise RuntimeError("后台炸了")

        envelope = await coordinator.run_with_timeout("web_search", boom, timeout=0.01)
        assert envelope["status"] == "background"

        hints = []
        for _ in range(50):
            hints = coordinator.pop_pending_hints()
            if hints:
                break
            await asyncio.sleep(0.05)

        assert hints and hints[0]["success"] is False
        assert "后台炸了" in str(hints[0]["error"])

    @pytest.mark.asyncio
    async def test_same_task_continues_no_double_execution(self):
        """核心语义：转后台的是同一个任务——副作用不双执行"""
        coordinator = ToolCoordinator()
        attempts = []

        async def work():
            attempts.append(1)
            await asyncio.sleep(0.08)
            return "survived"

        envelope = await coordinator.run_with_timeout("web_search", work(), timeout=0.01)
        assert envelope["status"] == "background"

        hints = []
        for _ in range(50):
            hints = coordinator.pop_pending_hints()
            if hints:
                break
            await asyncio.sleep(0.05)
        assert attempts == [1]  # 单次执行（同一任务），无重建
        assert hints and hints[0]["result"] == "survived"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
