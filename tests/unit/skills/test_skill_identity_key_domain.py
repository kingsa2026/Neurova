"""技能身份键统一（工单 014）。

注册表历史上按 `skill.name` 建键（`skill_system.py:505`），而进化侧 8 处取键都拿
`resolve_skill_identity()`（次序 skill_id → id → name）传来的值去查 —— 两者在
`id != name` 时不是同一个串，于是 `apply_improvement` / `rebuild_skill` /
`set_skill_enabled` / 执行链 全部静默取空。实测：注册
`skill_id="skill_ab12…"、name="read_write_skill_…"` 之后 `get_skill(identity)` 返回 None。

本套件钉的是"**当前身份只有一个答案**"：

- 取键口只有一处归一（不在调用方各写一次 resolve，那会长出第 9 处）；
- 改进、启停、执行、注销四种动作在 `id != name` 时都要真的作用在同一个对象上；
- 字典直取（`registry.skills[...]`）这类绕过取键口的写法不得再存在。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from neurova.evolution.skill_improver import (
    AutoSkillImprover,
    ImprovementType,
    SkillImprovement,
)
from neurova.skill_system import Skill, SkillRegistry

NAME = "read_write_skill_alpha"
IDENTITY = "skill_ab12cd34"


class _EchoSkill(Skill):
    """可执行的最小技能：把收到的参数原样返回，便于断言"执行落在它身上"。"""

    def __init__(self, name: str, skill_id: str):
        super().__init__(name, "读写组合技能")
        self.skill_id = skill_id
        self.config = {"tool_sequence": ["read_file", "write_file"], "version": "1.0.0"}

    async def execute(self, params, context=None):
        from neurova.skill_system import SkillResult

        # 字段名用 SkillResult 的真实契约（output，不是 data）
        return SkillResult(success=True, output={"echo": dict(params or {})})


@pytest.fixture
def registry():
    reg = SkillRegistry()
    reg.register_skill(_EchoSkill(NAME, IDENTITY))
    return reg


def test_both_key_domains_resolve_to_the_same_object(registry):
    """name 与 skill_id 必须指向同一个技能对象（不是两份影子）。"""
    by_name = registry.get_skill(NAME)
    by_identity = registry.get_skill(IDENTITY)

    assert by_name is not None, "name 取不到（原本能取到，不得回归）"
    assert by_identity is not None, (
        "身份域取不到：注册表按 name 建键而进化侧按 identity 取键，id != name 时全落空")
    assert by_name is by_identity


def test_has_skill_agrees_with_get_skill(registry):
    assert registry.has_skill(IDENTITY) is True
    assert registry.has_skill(NAME) is True
    assert registry.has_skill("nope") is False


def test_set_skill_enabled_accepts_identity(registry):
    """启停也要认身份域：否则"禁用某技能"对按 id 寻址的调用方永远 False。"""
    assert registry.set_skill_enabled(IDENTITY, False) is True
    assert registry.get_skill(NAME).status.value == "inactive"


@pytest.mark.asyncio
async def test_execute_skill_accepts_identity(registry):
    result = await registry.execute_skill(IDENTITY, {"q": 1})

    assert result.success is True, f"按身份执行被当成技能不存在：{result.error}"
    assert result.output == {"echo": {"q": 1}}


def test_unregister_by_identity_removes_both_forms(registry):
    registry.unregister(IDENTITY)

    assert registry.get_skill(IDENTITY) is None
    assert registry.get_skill(NAME) is None, "只删了一侧 ⇒ 幽灵技能仍可被执行"


def test_apply_improvement_reaches_the_skill(registry):
    """票面终点用例：改进提案在 `id != name` 时真的落到技能本体（当前必红）。"""
    improver = AutoSkillImprover()
    improvement = SkillImprovement(
        skill_id=IDENTITY,
        improvement_type=ImprovementType.PARAMETER_TUNING,
        description="收紧超时",
        changes={"timeout": 30},
    )

    assert improver.apply_improvement(improvement, registry) is True, (
        "改进提案取不到技能本体 ⇒ 只进反思日志、永不生效（断点 #3 的错位面）")
    skill = registry.get_skill(NAME)
    applied = (skill.config.get("revisions") or [{}])[-1]
    assert applied.get("changes") == {"timeout": 30}


def test_experience_apply_to_skill_reaches_the_skill(registry):
    """经验立即生效：applied 记录要能组合进技能描述（工单 014 票面用例）。"""
    from neurova.evolution.skill_experience import SkillExperienceStore

    store = SkillExperienceStore(rebuild_threshold=1)
    store.record_experience(IDENTITY, "读文件前先确认边界", source="manual")

    assert store._apply_to_skill(IDENTITY, registry) is True, (
        "经验写的是身份键、取的是 name 键 ⇒ 描述永不更新，LLM 工具面吃不到经验")
    assert "读文件前先确认边界" in registry.get_skill(NAME).description


def test_rebuild_skill_reaches_the_skill(registry):
    """定期重建同样按身份取技能：取不到即 False，经验永不合并进定义。"""
    from neurova.evolution.skill_experience import SkillExperienceStore

    store = SkillExperienceStore(rebuild_threshold=1)
    store.record_experience(IDENTITY, "写之前先读一遍", source="manual")

    assert store.rebuild_skill(IDENTITY, registry) is True
    skill = registry.get_skill(NAME)
    assert skill.version == "1.1.0"
    assert "写之前先读一遍" in skill.description


@pytest.mark.asyncio
async def test_tool_executor_existence_check_accepts_identity(registry):
    """执行链的存在性检查也不能只认 name。

    `tool_executor.execute_skill_tool` 先查一次"技能在不在"再交给
    `registry.execute_skill`：后者已归一，前者按字典直取，于是身份键在门口
    就被判"不存在"，后面那条已经正确的路根本走不到。
    """
    from unittest.mock import MagicMock

    from neurova.tool_executor import ToolExecutor

    agent = MagicMock()
    agent._skill_registry = registry
    executor = ToolExecutor(agent)

    result = await executor.execute_skill_tool(IDENTITY, {"q": 1})

    assert "不存在" not in str(result.get("error", "")), (
        f"身份键在执行入口被判定不存在：{result}")
    assert result.get("success") is True


def test_no_direct_dictionary_lookup_outside_the_registry():
    """绕过取键口的字典直取必须消失，否则归一只对一部分调用方成立。"""
    root = Path("neurova")
    targets = [root / "agent" / "chat_pipeline.py", root / "tool_executor.py"]
    offenders = []
    for target in targets:
        tree = ast.parse(target.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "skills"
            ):
                offenders.append(f"{target}:{node.lineno} 直接 skills.get( 绕过注册表取键口")
    assert not offenders, offenders
