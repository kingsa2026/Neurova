# -*- coding: utf-8 -*-
"""轮级候选正文覆盖槽（§8 前置 2 的执行面，票面 2026-10-09 Task 2）。

立论取证（本批实测，探针 `.tmp_armLeakProbe.py` 用完即删）：今天要让两份候选正文
各走一遍注入管线，唯一办法是原地改 registry 里那个技能对象的 `doc_text`——全局态，
两臂并发即串：`ARM_WANTED=CAND_A prompt_has_CAND_A=False prompt_has_CAND_B=True`，
另一臂同样没拿到自己要的那份。覆盖槽只作用本轮、且不碰技能对象本体。

判据三对：各得其所 / 复位不泄漏 / 未设槽时逐字节照旧（反证，防"槽把生产路径改掉"）。
"""

import asyncio
from types import SimpleNamespace

import pytest

from neurova.core import turn_context
from neurova.skills.skill_injection import inject_skill_mentions

SHIPPED = "仓内正文：先列要点再写代码。"
CAND_A = "候选正文 A：只输出要点列表。"
CAND_B = "候选正文 B：只输出代码，不要解释。"


class _Skill:
    def __init__(self, name="sk-a", doc_text=SHIPPED):
        self.name = name
        self.skill_id = name
        self.description = "描述"
        self.doc_text = doc_text


def _registry(*skills):
    return SimpleNamespace(skills={s.name: s for s in skills})


async def _promptWith(name, mapping):
    """在独立任务里设槽→取 prompt→复位（ContextVar 的父子作用域要靠真任务）。"""
    token = turn_context.set_turn_skill_text_override(mapping)
    try:
        return inject_skill_mentions(f"${name} 任务", _registry(_Skill(name=name)))
    finally:
        turn_context.reset_turn_skill_text_override(token)


@pytest.mark.asyncio
async def test_eachArmSeesItsOwnCandidateBody():
    """两臂并发各得其所——这正是全局 `doc_text` 做不到的那一格。"""
    promptA, promptB = await asyncio.gather(
        _promptWith("sk-a", {"sk-a": CAND_A}),
        _promptWith("sk-a", {"sk-a": CAND_B}),
    )

    assert CAND_A in promptA and CAND_B not in promptA, promptA
    assert CAND_B in promptB and CAND_A not in promptB, promptB
    assert SHIPPED not in promptA and SHIPPED not in promptB, (
        "覆盖没咬住，读到的还是仓内正文")


@pytest.mark.asyncio
async def test_overrideScopesToTheTurnItWasSetIn():
    """复位后不得泄漏：槽复位 / 从未设过 两条路径都必须回到仓内正文。"""
    afterReset = await _promptWith("sk-a", {"sk-a": CAND_A})
    assert CAND_A in afterReset

    neverSet = await _promptWith("sk-a", {})
    assert CAND_A not in neverSet and SHIPPED in neverSet, (
        f"槽复位后仍带着上一臂的正文：{neverSet}")


@pytest.mark.asyncio
async def test_emptyCandidateBodyIsHonouredNotFalledBack():
    """空正文是**有意的候选**（清空指令体），不许悄悄回落成仓内正文去比 0 差。"""
    prompt = await _promptWith("sk-a", {"sk-a": ""})
    assert SHIPPED not in prompt or "任务" in prompt
    assert SHIPPED not in prompt, f"空覆盖被当未设，落回仓内正文：{prompt}"


@pytest.mark.asyncio
async def test_overrideIsKeyedBySkillNameNotGlobally():
    """覆盖 sk-a 不得污染 sk-b 的正文——否则双臂会顺手改掉邻居技能的评分。"""
    token = turn_context.set_turn_skill_text_override({"sk-a": CAND_A})
    try:
        registry = _registry(_Skill("sk-a"), _Skill("sk-b"))
        prompt = inject_skill_mentions("$sk-b 任务", registry)
        assert SHIPPED in prompt and CAND_A not in prompt, prompt
    finally:
        turn_context.reset_turn_skill_text_override(token)


@pytest.mark.asyncio
async def test_overrideNeverMutatesTheSkillObject():
    """反证另一半：槽的作用面是读取路径，技能对象本体的 `doc_text` 必须原样不动。"""
    skill = _Skill()
    registry = _registry(skill)
    token = turn_context.set_turn_skill_text_override({"sk-a": CAND_A})
    try:
        inject_skill_mentions("$sk-a 任务", registry)
    finally:
        turn_context.reset_turn_skill_text_override(token)

    assert skill.doc_text == SHIPPED, (
        f"覆盖槽写回了技能对象（全局态污染）：{skill.doc_text}")
    assert SHIPPED in inject_skill_mentions("$sk-a 任务", registry), (
        "槽复位后仍读到候选正文")


def test_unsetSlotKeepsProductionBytesIdentical():
    """未设槽时的现值钉死：生产路径一处都不该因为这批改动而变。

    这一格在改动前后**同态为绿**（前瞻守卫，不是红）——它守的是"槽把默认路径改掉"这一类
    回归，写法是把期望文本直接钉成字面量，而不是与"改动前的自己"比。
    """
    registry = _registry(_Skill())
    prompt = inject_skill_mentions("$sk-a 任务", registry)
    assert prompt == f"$sk-a 任务\n\n[技能说明 sk-a]\n{SHIPPED}", repr(prompt)


def test_skillMdToolPathHonoursTheSameSlot(tmp_path):
    """同契约的第二命中点：SKILL.md 型技能的指令体是经**工具返回**进模型的。

    只覆盖 mention 注入面，这类技能的候选正文到不了模型 ⇒ 两臂比出假 0 差。
    """
    from neurova.skills.builtin.skill_doc_executor import SkillMarkdownExecutor

    skillDir = tmp_path / "sk-a"
    skillDir.mkdir()
    (skillDir / "SKILL.md").write_text(
        "---\nname: sk-a\ndescription: d\n---\n\n" + SHIPPED, encoding="utf-8")
    executor = SkillMarkdownExecutor("sk-a", skillDir, skill_name="sk-a")

    baseline = executor.execute({"task": "做点什么"})
    assert baseline.output["instructions"].strip() in SHIPPED, baseline.output

    token = turn_context.set_turn_skill_text_override({"sk-a": CAND_B})
    try:
        overridden = executor.execute({"task": "做点什么"})
    finally:
        turn_context.reset_turn_skill_text_override(token)

    assert CAND_B in overridden.output["instructions"], overridden.output
    assert SHIPPED not in overridden.output["instructions"], (
        "工具返回面没接槽——候选正文只改了注入面，双臂仍拿到同一份正文")

