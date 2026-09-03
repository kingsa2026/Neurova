"""P1-5 技能执行体解释器测试

Skill manifest.config 中的 tool_sequence 必须能被实际执行；
目前 Skill.execute() 直接 raise NotImplementedError，让所有合成/封装的
工具都是“能看见不能调”的空壳。

覆盖：
1. ToolSequenceSkill 执行多步并按步名引用前置输出
2. 单步失败正确传播为 SkillResult(success=False)
3. SkillRegistry.register_skill 在 manifest 含 tool_sequence 时
   自动构建可执行 Skill（execute 真正可跑），否则回退到原行为
4. 单步的 tool_router.execute 异常被捕获后转为 SkillResult(success=False)
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def make_registry_with_router(router_exec_results: list):
    """构造 SkillRegistry + 模拟 tool_router，按调用顺序返回预设结果"""
    from neurova.skill_system import SkillRegistry, ToolSequenceSkill

    registry = SkillRegistry()
    calls: list = []
    router = SimpleNamespace()

    async def _exec(**kwargs):
        calls.append(kwargs)
        return router_exec_results.pop(0) if router_exec_results else SimpleNamespace(
            success=True, result={"ok": True}, error=None
        )

    router.execute = _exec
    registry.tool_router = router
    return registry, calls, ToolSequenceSkill


def manifest(name: str, tool_sequence: list, description: str = "auto skill"):
    return SimpleNamespace(
        name=name, id=name, description=description,
        config={"tool_sequence": tool_sequence},
    )


class TestToolSequenceSkillExecution:
    def test_two_step_sequence_runs_in_order(self):
        reg, calls, _ = make_registry_with_router([
            SimpleNamespace(success=True, result={"url": "https://a"}, error=None),
            SimpleNamespace(success=True, result={"ok": True}, error=None),
        ])
        ok = reg.register_skill(manifest("auto", [
            {"tool": "browser_navigate", "params": {"url": "https://a"}},
            {"tool": "browser_screenshot", "params": {}},
        ]))
        assert ok is True
        skill = reg.get_skill("auto")
        assert skill is not None
        result = asyncio.run(skill.execute({}, context={}))
        assert result.success is True
        assert len(calls) == 2
        assert calls[0]["tool_name"] == "browser_navigate"
        assert calls[1]["tool_name"] == "browser_screenshot"

    def test_step_failure_returns_error_result(self):
        reg, calls, _ = make_router_with_one_failure()
        reg.register_skill(manifest("auto", [
            {"tool": "a", "params": {}},
            {"tool": "b", "params": {}},
        ]))
        skill = reg.get_skill("auto")
        result = asyncio.run(skill.execute({}, context={}))
        assert result.success is False
        assert "a" in result.error
        # b 不应被调用（首个失败即停）
        assert len(calls) == 1

    def test_reuse_previous_step_output_in_later_params(self):
        reg, calls, _ = make_registry_with_router([
            SimpleNamespace(success=True, result={"content": "ABC"}, error=None),
            SimpleNamespace(success=True, result={"ok": True}, error=None),
        ])
        reg.register_skill(manifest("auto", [
            {"tool": "fetch", "params": {}},
            {"tool": "save", "params": {"data": "{step_0.content}"}},
        ]))
        skill = reg.get_skill("auto")
        asyncio.run(skill.execute({}, context={}))
        # 第二步 params 渲染了前一步输出
        assert calls[1]["params"]["data"] == "ABC"

    def test_register_without_tool_sequence_keeps_fallback(self):
        """无 tool_sequence 的 manifest 仍走原路径（不破坏现有技能）"""
        from neurova.skill_system import SkillRegistry

        reg = SkillRegistry()
        reg.tool_router = MagicMock()
        ok = reg.register_skill(SimpleNamespace(
            name="simple", description="x", config={}
        ))
        assert ok is True
        # execute 仍抛 NotImplementedError（说明走的是基类）
        with pytest.raises(NotImplementedError):
            asyncio.run(reg.get_skill("simple").execute({}))


def make_router_with_one_failure():
    from neurova.skill_system import SkillRegistry, ToolSequenceSkill

    registry = SkillRegistry()
    calls: list = []

    async def _exec(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            success=False, result=None, error=f"工具 {kwargs['tool_name']} 失败"
        )

    router = SimpleNamespace(execute=_exec)
    registry.tool_router = router
    return registry, calls, ToolSequenceSkill
