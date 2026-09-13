# -*- coding: utf-8 -*-
"""工具 reproducible 元数据与注册标准（P1 #6 触点1）。

定稿（对比报告 §5.6）：全量工具强制显式判定可重现性；内置工具从
_NON_REPRODUCIBLE_TOOLS 单源推导；外部（MCP/agent 自创未声明）一律
保守判 False（数据保真优先——不可重放的原文不允许进溢出文件被清理）。
"""
import pytest

import neurova.builtin_tools as bt
from neurova.builtin_tools import (
    BuiltinTool,
    BuiltinToolRegistry,
    _BUILTIN_SCHEMAS,
)

# 快照/突变/副作用类——重放不可能或重放制造新副作用
EXPECTED_NON_REPRODUCIBLE = {
    "run_code", "git", "file_write", "file_create", "file_edit", "file_delete",
    "create_skill", "spawn_subagent", "planning",
    "canvas_add_node", "canvas_connect", "canvas_create", "canvas_remove_node",
    "canvas_move_node", "canvas_set_config", "canvas_layout", "canvas_run",
    "computer_click", "computer_click_element", "computer_click_mark",
    "computer_type", "computer_scroll", "computer_set_value",
    "computer_shell", "computer_ssh_exec", "computer_screenshot",
    "browser_click", "browser_click_role", "browser_fill_role",
    "browser_type", "browser_navigate", "browser_screenshot",
    "computer_som_snapshot", "computer_dom_snapshot",
}


def test_non_reproducible_set_is_subset_of_registered_schemas():
    assert EXPECTED_NON_REPRODUCIBLE <= set(_BUILTIN_SCHEMAS), (
        f"打标名单含未注册工具: {EXPECTED_NON_REPRODUCIBLE - set(_BUILTIN_SCHEMAS)}"
    )


def test_registry_is_reproducible_covers_all_builtins():
    """全量 63 内置工具都有确定的 bool 判定（用户拍板：全部都打）。"""
    reg = BuiltinToolRegistry()
    for name in _BUILTIN_SCHEMAS:
        val = reg.is_tool_reproducible(name)
        assert isinstance(val, bool), f"{name} 缺 reproducible 判定"
        assert val is (name not in EXPECTED_NON_REPRODUCIBLE), name


def test_unknown_external_tools_default_false():
    """外部/MCP/自创未声明 → 保守 False（fail-closed 数据保真方向）。"""
    reg = BuiltinToolRegistry()
    assert reg.is_tool_reproducible("mcp__server__whatever") is False
    assert reg.is_tool_reproducible("not_a_tool") is False


def test_register_tool_records_reproducible_and_forces_bool():
    """动态注册路径：reproducible 缺省(None)按外部保守 False 落定；显式值保留。"""
    reg = BuiltinToolRegistry()
    t1 = BuiltinTool(name="dyn_a", description="d", parameters={})
    reg.register_tool(t1)
    assert reg.is_tool_reproducible("dyn_a") is False
    t2 = BuiltinTool(name="dyn_b", description="d", parameters={}, reproducible=True)
    reg.register_tool(t2)
    assert reg.is_tool_reproducible("dyn_b") is True


def test_builtin_tool_dataclass_field_declared():
    """BuiltinTool 数据类必须有该声明位（同 sandbox_required 模式，不进模型 schema）。"""
    t = BuiltinTool(name="x", description="", parameters={})
    assert hasattr(t, "reproducible")
    assert "reproducible" not in t.to_openai_format()["function"]  # 模型可见面零变化


# ── 自创工具继承标准（§5.6 触点1 拍板）────────────────────────────


class TestSynthesizedSkillInheritsStandard:
    """create_skill 序列技能的可重现性=步骤推导（声明与实际行为一致，
    同 P0-4 permissions 能力面先例），并被消费链 resolve 读取。"""

    @pytest.mark.asyncio
    async def test_all_reproducible_steps_declare_true(self):
        from unittest.mock import MagicMock

        from neurova.tool_executor import ToolExecutor

        registry = MagicMock()
        registry.register_skill = MagicMock(return_value=True)
        agent = MagicMock()
        agent._skill_registry = registry
        exe = ToolExecutor(agent)
        await exe._execute_builtin_tool("create_skill", {
            "name": "lookup", "description": "查天气并搜索资讯",
            "steps": [{"name": "weather", "params": {"city": "北京"}},
                      {"name": "web_search", "params": {"query": "AI"}}],
        })
        manifest = registry.register_skill.call_args[0][0]
        assert manifest.config["reproducible"] is True

    @pytest.mark.asyncio
    async def test_any_mutation_step_declares_false(self):
        from unittest.mock import MagicMock

        from neurova.tool_executor import ToolExecutor

        registry = MagicMock()
        registry.register_skill = MagicMock(return_value=True)
        agent = MagicMock()
        agent._skill_registry = registry
        exe = ToolExecutor(agent)
        await exe._execute_builtin_tool("create_skill", {
            "name": "danger", "description": "跑代码再存文件",
            "steps": [{"name": "run_code", "params": {"code": "1"}},
                      {"name": "file_write", "params": {"file_path": "a", "content": "b"}}],
        })
        manifest = registry.register_skill.call_args[0][0]
        assert manifest.config["reproducible"] is False

    def test_resolve_reads_skill_declaration(self):
        """消费面 resolve_tool_reproducible：builtin 优先，其次 skill 声明，缺省 False。"""
        from types import SimpleNamespace

        from neurova.core.tool_offload import resolve_tool_reproducible

        # builtin 命中
        assert resolve_tool_reproducible(SimpleNamespace(), "file_read") is True
        assert resolve_tool_reproducible(SimpleNamespace(), "run_code") is False

        # skill 声明命中（registry.skills 带 manifest config）
        class _Reg:
            skills = {
                "lookup": SimpleNamespace(config={"reproducible": True}),
                "danger": SimpleNamespace(config={"reproducible": False}),
            }

        agent = SimpleNamespace(_skill_registry=_Reg())
        assert resolve_tool_reproducible(agent, "lookup") is True
        assert resolve_tool_reproducible(agent, "danger") is False
        # 未知（MCP/无声明）保守 False
        assert resolve_tool_reproducible(agent, "mcp__x__y") is False
        assert resolve_tool_reproducible(None, "whatever") is False
