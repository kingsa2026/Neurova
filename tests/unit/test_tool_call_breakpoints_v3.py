"""
TDD 测试:工具调用断点 V2-7 和 V2-8 修复

V2-7 (MID): tool_router.py _resolve_skill_tool 对类 B 的
  Dict[str, Tuple[Skill, Path]] 元组未解包,导致 proxy.description/parameters
  为空。LLM 幻觉调用未在 tools 列表的 skill 名时触发。

V2-8 (LOW): base.py _build_tools_from_skills 是死代码(无调用点),
  与 V2-1 同根 .skills bug,但已通过 V2-1 修复(property 已加)。
  此方法应删除以保持代码整洁。

TDD 垂直切片: 一次一个测试 → 一次一个实现。
"""
import importlib.util
from unittest.mock import MagicMock

import pytest


# 加载被 neurova.skill_system 包遮蔽的 neurova/skill_system.py 单文件
_SPEC = importlib.util.spec_from_file_location(
    "neurova_skill_system_standalone_for_test_v3",
    "e:/项目/Neurova/neurova/skill_system.py",
)
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
Skill = _MOD.Skill


# ──────────────────────────────────────────────────────────────────
# 切片 1 — V2-7: _resolve_skill_tool 必须解包类 B 的元组
# ──────────────────────────────────────────────────────────────────

class TestResolveSkillToolUnpacksTuple:
    """V2-7: _resolve_skill_tool 在 skills 字典值是元组时必须解包取 Skill。

    类 B(neurova.skills.registry.SkillRegistry)的 .skills 返回
    Dict[str, Tuple[Skill, Path]]。原代码 `skill = skills[tool_name]`
    直接拿到元组,后续 getattr(元组, "description", "") 返回空字符串。

    修复:_resolve_skill_tool 在取到 skill 后,若是元组则解包取 [0]。
    """

    def test_resolve_skill_tool_unpacks_tuple_from_class_b(self):
        """类 B 的 skills 字典值是 (Skill, Path) 元组时,proxy.description 非空。"""
        from neurova.tool_layers.tool_router import ToolRouter

        # 构造类 B 风格的 skill_manager:has_skill 返回 True,
        # skills 返回 Dict[str, Tuple[Skill, Path]]
        test_skill = Skill(name="weather", description="查询天气工具")
        test_path = "/fake/path/to/skill.py"

        sm = MagicMock()
        sm.has_skill = MagicMock(return_value=True)
        # 类 B 的 skills 是 Dict[str, Tuple[Skill, Path]]
        sm.skills = {"weather": (test_skill, test_path)}

        tr = ToolRouter.__new__(ToolRouter)
        tr._skill_manager = sm

        import asyncio
        proxy = asyncio.run(tr._resolve_skill_tool("weather"))

        assert proxy is not None, "应返回 proxy,而非 None"
        assert proxy.description == "查询天气工具", (
            f"类 B 元组未解包,description 应为 '查询天气工具',实际:'{proxy.description}'"
        )

    def test_resolve_skill_tool_handles_class_a_dict(self):
        """类 A 的 skills 字典值是 Skill 对象(非元组),应正常工作。"""
        from neurova.tool_layers.tool_router import ToolRouter

        test_skill = Skill(name="search", description="搜索工具")
        sm = MagicMock()
        sm.has_skill = MagicMock(return_value=True)
        # 类 A 的 skills 是 Dict[str, Skill]
        sm.skills = {"search": test_skill}

        tr = ToolRouter.__new__(ToolRouter)
        tr._skill_manager = sm

        import asyncio
        proxy = asyncio.run(tr._resolve_skill_tool("search"))

        assert proxy is not None
        assert proxy.description == "搜索工具"


# ──────────────────────────────────────────────────────────────────
# 切片 2 — V2-8: _build_tools_from_skills 死代码应删除
# ──────────────────────────────────────────────────────────────────

class TestBuildToolsFromSkillsDeadCodeRemoved:
    """V2-8: base.py _build_tools_from_skills 是死代码(无调用点)。

    grep 确认全代码库无任何调用此方法的地方。它包含与 V2-1 同根的
    `.skills` bug(V2-1 已通过加 property 修复),但作为死代码仍是不洁。

    修复:删除此方法以保持代码整洁(AGENTS.md 规则:surgical changes,
    every changed line should trace back to the request)。

    删除验证:删除后 BaseAgentLoop 不应再有此方法。
    """

    def test_build_tools_from_skills_method_removed(self):
        """base.py 的 _build_tools_from_skills 方法应已删除。"""
        from neurova.agent.loops.base import BaseAgentLoop

        # 死代码应已删除,不再作为类方法存在
        assert not hasattr(BaseAgentLoop, "_build_tools_from_skills"), (
            "BaseAgentLoop._build_tools_from_skills 是死代码(无调用点),应删除。"
            "此方法包含与 V2-1 同根的 .skills bug,虽然 V2-1 已通过加 property 修复,"
            "但保留死代码会增加维护负担和未来误用风险。"
        )

    def test_no_callers_of_build_tools_from_skills(self):
        """全代码库不应有任何代码调用 _build_tools_from_skills。"""
        import subprocess
        # 用 ripgrep 搜索调用点(排除方法定义本身和测试文件)
        result = subprocess.run(
            ["rg", "_build_tools_from_skills", "e:/项目/Neurova/neurova"],
            capture_output=True, text=True, shell=False,
        )
        # 修复后,neurova 目录下不应有任何匹配(包括方法定义)
        assert result.returncode != 0 or not result.stdout.strip(), (
            f"仍存在 _build_tools_from_skills 引用:\n{result.stdout}"
            "死代码应完全删除,包括定义。"
        )
