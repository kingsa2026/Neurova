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
    # 产物件：落产物目录并注册 artifact（重放登记出第二份产物与下载口）
    "write_pdf",
    "canvas_add_node", "canvas_connect", "canvas_create", "canvas_remove_node",
    "canvas_move_node", "canvas_set_config", "canvas_layout", "canvas_run",
    "computer_click", "computer_click_element", "computer_click_mark",
    "computer_type", "computer_scroll", "computer_set_value",
    "computer_shell", "computer_ssh_exec", "computer_screenshot",
    "browser_click", "browser_click_role", "browser_fill_role",
    "browser_type", "browser_navigate", "browser_screenshot",
    "computer_som_snapshot", "computer_dom_snapshot",
    # P0-3 会话式 shell：进程输出不可重放（重跑时系统状态已变）
    "exec_command", "write_stdin",
    # 多步编排：内层步进可能含任意写操作，重放制造新变更
    "orchestrate_tools",
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
    同 P0-4 permissions 能力面先例），并被消费链 resolve 读取。

    Issue #62：本组用例原以裸 MagicMock agent 直调 create_skill，自动落盘臂
    的证据闸（creation_governance，自动技能需 ≥3 次独立成功证据）落地后，
    MagicMock 的 `config.agent_id` 被当成真值写进 sqlite → `ProgrammingError:
    type 'MagicMock' is not supported`。断言意图（reproducible 推导）没变，
    契约变了——fixture 补齐"真实 SkillService + 已留存证据"（与
    tests/unit/evolution/test_skill_creation_canonical.py 同法）。
    """

    @staticmethod
    def _executor(tmp_path, monkeypatch, agent_id, steps, description):
        """构造已满足证据闸的 create_skill 执行器，返回 (exe, registry)。"""
        from unittest.mock import MagicMock

        from neurova.skills.skill_service import SkillService
        from neurova.tool_executor import ToolExecutor

        monkeypatch.setenv("NEUROVA_SKILL_REVIEW_GATE", "0")
        service = SkillService(agent_id=agent_id, skills_dir=str(tmp_path))
        monkeypatch.setattr("neurova.skills.skill_service.SkillService", lambda **kw: service)
        # 证据按**结构身份**计量：序列必须与 proposal 归一后一致（tool/params）
        sequence = [{"tool": s["name"], "params": s["params"]} for s in steps]
        for index in range(3):
            service.creation_evidence.record(f"proven-{index}", sequence, description, True)

        registry = MagicMock()
        registry.register_skill = MagicMock(return_value=True)
        agent = MagicMock()
        agent.config.agent_id = agent_id
        agent._skill_registry = registry
        return ToolExecutor(agent), registry

    @pytest.mark.asyncio
    async def test_all_reproducible_steps_declare_true(self, tmp_path, monkeypatch):
        steps = [{"name": "weather", "params": {"city": "北京"}},
                 {"name": "web_search", "params": {"query": "AI"}}]
        exe, registry = self._executor(
            tmp_path, monkeypatch, "repro-all", steps, "查天气并搜索资讯")
        await exe._execute_builtin_tool("create_skill", {
            "name": "lookup", "description": "查天气并搜索资讯", "steps": steps,
        })
        manifest = registry.register_skill.call_args[0][0]
        assert manifest.config["reproducible"] is True

    @pytest.mark.asyncio
    async def test_any_mutation_step_declares_false(self, tmp_path, monkeypatch):
        steps = [{"name": "run_code", "params": {"code": "1"}},
                 {"name": "file_write", "params": {"file_path": "a", "content": "b"}}]
        exe, registry = self._executor(
            tmp_path, monkeypatch, "repro-mutation", steps, "跑代码再存文件")
        await exe._execute_builtin_tool("create_skill", {
            "name": "danger", "description": "跑代码再存文件", "steps": steps,
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

# ── 跨轴一致性：写作用域声明 ⇒ 不可重现（与 Issue #286 的 planning 同根因）──


class TestWriteScopedToolsAreNeverReproducible:
    """有写作用域的工具不得被判为可重现 —— 两条轴不同，但这条**单向蕴含**必须成立。

    两条轴各答一个事实：`capability.readOnly` 问"两个调用同时跑会不会互踩"
    （并行轴）；`_NON_REPRODUCIBLE_TOOLS` 问"重放会不会制造新副作用"（重放轴）。
    两轴**不合并** —— `computer_screenshot` 是反例：语义只读、却因瞬时快照而不可重放，
    它留在名单里是正确处置（见下面的反向控制）。

    但一个方向必须成立：声明了写作用域（`readOnly=False`）的工具，结果不可能
    "重放不制造新变更" —— 那正是 `readOnly=False` 的定义。反过来不成立
    （只读也可能不可重放），故本判据**只钉单向蕴含**，不把两轴并成一个字段。

    命中点：`write_pdf`（工单 001）落产物目录并注册 artifact，声明面写着
    `readOnly=False`，重放轴上却算可重现 ⇒ 它进了遗传引擎的"可安全组合的只读原语"
    池（`genetic_engine._available_tools` 由本名单派生），溢出元数据也把它标成可重放。
    与 `planning` 在治理放行轴上被误算同类：**同一份事实在两条轴上被读成两件事**。
    """

    def test_offendersAreNamed(self):
        from neurova.builtin_tools import (
            _BUILTIN_SCHEMAS,
            _NON_REPRODUCIBLE_TOOLS,
            get_builtin_tool_capability,
        )

        offenders = sorted(
            name
            for name in _BUILTIN_SCHEMAS
            if (cap := get_builtin_tool_capability(name)) is not None
            and not cap.readOnly
            and name not in _NON_REPRODUCIBLE_TOOLS
        )
        assert not offenders, (
            "这些工具声明了写作用域（readOnly=False），重放轴上却被判为可重现："
            f"{offenders} —— 重放会制造新变更（落盘/注册 artifact）"
        )

    def test_reverseDirectionIsNotClaimed(self):
        """反向不成立，判据不得被读成"两轴合并"。

        只读工具**可以**不可重放：截图/DOM 快照重放不回当时画面。若有人把两轴
        并成一个字段，这条会红 —— 它钉住"不合并"这件事本身。
        """
        from neurova.builtin_tools import _NON_REPRODUCIBLE_TOOLS, get_builtin_tool_capability

        for name in ("computer_screenshot", "computer_dom_snapshot", "computer_som_snapshot"):
            cap = get_builtin_tool_capability(name)
            assert cap is not None and cap.readOnly, f"{name} 应声明为只读"
            assert name in _NON_REPRODUCIBLE_TOOLS, (
                f"{name} 是瞬时快照：只读但不可重放，必须留在重放名单里"
            )

    def test_writePdfIsNotInTheReproduciblePool(self):
        """消费面自证：遗传引擎的"只读原语"池里不得出现写作用域工具。"""
        from neurova.evolution.genetic_engine import ToolGeneticEngine

        pool = ToolGeneticEngine(seed=11)._available_tools
        from neurova.builtin_tools import get_builtin_tool_capability

        leaked = [
            name
            for name in pool
            if (cap := get_builtin_tool_capability(name)) is not None and not cap.readOnly
        ]
        assert not leaked, f"写作用域工具进了只读原语池：{leaked}"

