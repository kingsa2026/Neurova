"""003 残留 · `ToolRouter` 必须复判工具结果的内容成败（假成功票的第二个生产点）。

票据 003 点名「`tool_router.py` 的 `ToolResult(success=True, result={...})` 必须复判」，
前一轮只把**咽喉内层**（`tool_executor._execute_tool_core`）改对了：`ToolRouter.execute`
仍对任何不抛异常的结果无条件 `success=True`，于是同一失败工具在两条消费链上分叉：

- 走到咽喉的调用（文本链/原生链）→ 失败票，正确；
- 走到 `SkillRegistry` 里自动技能（`ToolSequenceSkill.execute` 读 `result.success`）的
  调用 → 恒真 ⇒ 自动技能产出假成功票（审计 L-02）。

判据单源：咽喉的 `ToolExecutor._result_is_success`，本文件不复写第二份内容判据。
"""

from __future__ import annotations

import pytest

from neurova.skill_system import ToolSequenceSkill
from neurova.tool_layers.tool_router import ToolRouter


class _ErrorTool:
    """工具边界替身：真实生产工具失败时返回 `{"error": …}` 而不抛异常。

    与 `agent/loops/base.py` 的脚本化模型替身同理——替身只放工具边界，
    路由器的路由、成败判据、自动技能的步进消费全走真代码。
    """

    name = "flaky_tool"

    async def execute(self, params):
        return {"error": "上游超时", "success": False}


class _OkTool:
    name = "steady_tool"

    async def execute(self, params):
        return {"result": "ok"}


def _router_with(tool) -> ToolRouter:
    router = ToolRouter()
    router.register_builtin(tool.name, tool)
    return router


class TestRouterVerdict:
    @pytest.mark.asyncio
    async def test_error_payload_is_reported_as_failure(self):
        result = await _router_with(_ErrorTool()).execute("flaky_tool", {})
        assert result.success is False, (
            f"工具返回 error 却被路由器包成成功票：{result}"
        )
        assert result.error, "失败必须带上原因，不许静默成功"

    @pytest.mark.asyncio
    async def test_success_payload_is_still_success(self):
        result = await _router_with(_OkTool()).execute("steady_tool", {})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_route_raises_for_error_payload(self):
        """`route()` 的契约是失败即抛——它读的就是 `execute` 的成败位。"""
        with pytest.raises(ValueError):
            await _router_with(_ErrorTool()).route("flaky_tool", {})


class TestAutoSkillConsumesTheSameVerdict:
    """同契约的第二个消费方：自动技能不得再产假成功票。"""

    @pytest.mark.asyncio
    async def test_tool_sequence_skill_reports_failure_for_error_step(self):
        skill = ToolSequenceSkill(
            name="auto_flaky",
            description="单步自动技能",
            tool_sequence=[{"tool": "flaky_tool", "params": {}}],
            tool_router=_router_with(_ErrorTool()),
        )

        result = await skill.execute({})

        assert result.success is False, (
            f"单步工具真失败，自动技能仍产成功票：success={result.success} data={result.data}"
        )
        assert result.error, "失败必须点名原因"

    @pytest.mark.asyncio
    async def test_tool_sequence_skill_success_shape_unchanged(self):
        """反向锁：成功的步进照旧成功，判据收紧不是把整条臂关掉。"""
        skill = ToolSequenceSkill(
            name="auto_steady",
            description="单步自动技能",
            tool_sequence=[{"tool": "steady_tool", "params": {}}],
            tool_router=_router_with(_OkTool()),
        )

        result = await skill.execute({})
        assert result.success is True
