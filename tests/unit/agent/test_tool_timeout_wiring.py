"""
P1-2 切片 2 — _execute_single_tool 超时转后台接线测试

单一咽喉点：治理预检之后的执行链经 ToolCoordinator.run_with_timeout——
- 快工具正常返回结果
- 慢工具超时 → background 信封（success=False，tool_source=background）
- 转后台的任务继续跑完，结果落 pending hints（经 executor.tool_coordinator 取回）
- 协调器不可用时降级直接执行（不因协调器故障瘫痪工具）
"""

import asyncio

import pytest
from types import SimpleNamespace

from neurova.agent.tool_coordinator import ToolCoordinator
from neurova.tool_executor import ToolExecutor


def _make_executor(core_impl):
    agent = SimpleNamespace(
        _current_user_id="u1",
        config=SimpleNamespace(user_id="u1", agent_id="a1", name="t"),
        context_orchestrator=None,
        skill_registry=None,
    )
    executor = ToolExecutor(agent)
    executor.tool_coordinator = ToolCoordinator()
    executor._execute_tool_core = core_impl  # monkeypatch 核心链
    return executor


class TestTimeoutOffloadWiring:
    @pytest.mark.asyncio
    async def test_fast_core_returns_result(self):
        async def core(name, params):
            return {"ok": True}, True, "builtin"

        executor = _make_executor(core)
        result = await executor._execute_single_tool("memory_search", {}, skip_governance=True)
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_slow_core_offloads_background_envelope(self, monkeypatch):
        # 注册表给 web_search 30s——monkeypatch 成 0.05s 触发转后台
        # 懒加载：超时函数在使用点从真源模块导入，patch 真源
        monkeypatch.setattr(
            "neurova.agent.tool_coordinator.get_tool_timeout",
            lambda name, default=None: 0.05,
        )

        async def slow_core(name, params):
            await asyncio.sleep(0.3)
            return {"late": True}, True, "builtin"

        executor = _make_executor(slow_core)
        result = await executor._execute_single_tool("web_search", {}, skip_governance=True)

        assert result["status"] == "background"
        assert result["tool_name"] == "web_search"

        # 后台任务继续跑完 → hint 落地
        hints = []
        for _ in range(50):
            hints = executor.tool_coordinator.pop_pending_hints()
            if hints:
                break
            await asyncio.sleep(0.05)
        assert hints and hints[0]["success"] is True
        # 后台观察的是核心链三元组：(result, success, tool_source)
        core_result = hints[0]["result"][0]
        assert core_result == {"late": True}

    @pytest.mark.asyncio
    async def test_per_tool_timeout_from_registry(self):
        """memory_search 注册表超时 10s——用 0.3s 慢核心不会触发后台（注册表生效）"""
        async def medium_core(name, params):
            await asyncio.sleep(0.3)
            return {"fine": True}, True, "builtin"

        executor = _make_executor(medium_core)
        result = await executor._execute_single_tool("memory_search", {}, skip_governance=True)
        assert result == {"fine": True}  # 10s 注册表超时未触发

    @pytest.mark.asyncio
    async def test_core_exception_propagates(self):
        async def broken_core(name, params):
            raise RuntimeError("core boom")

        executor = _make_executor(broken_core)
        with pytest.raises(RuntimeError, match="core boom"):
            await executor._execute_single_tool("memory_search", {}, skip_governance=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
