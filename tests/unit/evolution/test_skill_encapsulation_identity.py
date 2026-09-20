"""封装模板的去重键与落盘键必须是同一个值（工单 015）。

`AutoSkillBuilder` 内并存两套 ID 构造：命中判定按 `f"skill_{pattern_id}"`
（`pattern_id` 是 64 位指纹全串），落盘/建键按 `canonical_skill_id()`
（`skill_{指纹[:16]}`）。两者**永不相等**，于是同一模式每被 observe 一轮都判
"新模板"，重新封装并把 `is_active` 重置回 False —— 上一轮人工批准的模板
本轮重回待审队列，内存态与磁盘态每轮漂移一次。生产者是真的
（`creation_governance.finish_task` 驱动 `builder.observe`），所以这是活着的自噬循环。

本套件钉三件事：

- 批准之后再来一轮观察，模板**不得**回到 pending；
- 内存模板 id 必须能在磁盘 manifest 里逐值取到（一套身份，不是两套）；
- `f"skill_{` 这种身份拼接在一个模块里只能存在一处构造点。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from neurova.evolution.skill_encapsulation import AutoSkillBuilder
from neurova.skills.skill_service import SkillService

SEQ = ["memory_search", "file_read", "file_write"]
PURPOSE = "读改写同一文件"
SOURCE = Path("neurova/evolution/skill_encapsulation.py")


def _observe_round(builder, service, *, tasks):
    """喂一轮独立任务证据并观察（模拟 finish_task 每轮驱动一次）。"""
    for task_id in tasks:
        service.creation_evidence.record(task_id, SEQ, PURPOSE, True)
        builder.observe(
            tool_sequence=SEQ,
            context=PURPOSE,
            success=True,
            duration=0.5,
            metadata={"source_key": task_id},
        )


@pytest.fixture
def harness(tmp_path):
    service = SkillService(agent_id="encapsulation-identity", skills_dir=str(tmp_path))
    builder = AutoSkillBuilder(
        min_pattern_occurrences=3, min_success_rate=0.7, evidence_store=service.creation_evidence
    )
    return builder, service


def test_approved_template_is_not_resurrected_as_pending(harness):
    """票面终点用例：批准过的模板不得被第二轮观察打回待审（当前必红）。"""
    builder, service = harness
    _observe_round(builder, service, tasks=["t1", "t2", "t3"])

    pending = builder.list_pending_templates()
    assert len(pending) == 1, f"三轮独立证据应恰好封装 1 个模板，实得 {pending}"
    template_id = pending[0]["template_id"]
    assert builder.approve_template(template_id) is True

    _observe_round(builder, service, tasks=["t4", "t5"])

    assert builder.list_pending_templates() == [], (
        "同一模式再来一轮就重新封装并重置 is_active ⇒ 人工批准每轮被撤销")
    assert builder._templates[template_id].is_active is True


def test_reobservation_does_not_grow_the_template_set(harness):
    """命中既有模板时集合大小与对象身份都不变（不产生第二条影子）。"""
    builder, service = harness
    _observe_round(builder, service, tasks=["t1", "t2", "t3"])
    first = dict(builder._templates)
    assert len(first) == 1

    _observe_round(builder, service, tasks=["t4", "t5", "t6"])

    assert set(builder._templates) == set(first), (
        f"第二轮多出模板：{set(builder._templates) - set(first)}")
    kept = builder._templates[next(iter(first))]
    assert kept is next(iter(first.values())), "命中既有模板却换了对象 ⇒ 批准态随旧对象丢失"


def test_legacy_keyed_template_is_recognised_as_the_same_identity(harness):
    """跨重启的旧命名模板也算命中。

    旧版本把模板存成 `skill_<pattern_id>`（64 位全串），从落盘态恢复后仍在表里；
    只比规范 ID 会把它当新模板再封装一遍。命中判定必须按**指纹身份**认它。
    """
    builder, service = harness
    from neurova.evolution.skill_encapsulation import SkillTemplate

    legacy_id = "skill_" + "a" * 64
    builder._templates[legacy_id] = SkillTemplate(
        template_id=legacy_id,
        name="legacy_template",
        description="旧命名恢复出的模板",
        tool_sequence=list(SEQ),
        context_template=PURPOSE,
        is_active=True,
    )

    _observe_round(builder, service, tasks=["t1", "t2", "t3"])

    assert set(builder._templates) == {legacy_id}, (
        f"旧命名模板未被认成同一身份，又封了一条：{set(builder._templates)}")
    assert builder._templates[legacy_id].is_active is True


def test_memory_template_id_resolves_on_disk(harness):
    """注册之后，内存模板 id 必须能在磁盘 manifest 里逐值取到（一套身份两个视图）。"""
    from neurova.skill_system import SkillRegistry

    builder, service = harness
    _observe_round(builder, service, tasks=["t1", "t2", "t3"])
    for template_id in list(builder._templates):
        assert builder.approve_template(template_id) is True

    assert builder.register_to_skill_registry(SkillRegistry(), skill_service=service) > 0
    for template_id in builder._templates:
        assert service.get_skill_info(template_id) is not None, (
            f"内存里叫 {template_id}，磁盘上取不到 ⇒ 重启后按磁盘 id 恢复的模板与内存对不上")


def test_skill_id_concatenation_has_a_single_construction_point():
    """身份拼接只能有一处构造点，否则两套键域迟早再长回来。"""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        head = node.values[0]
        if isinstance(head, ast.Constant) and str(head.value).startswith("skill_"):
            offenders.append(f"{SOURCE}:{node.lineno} 自造 skill_ 身份串")
    assert len(offenders) <= 1, (
        f"存在多处身份串构造点，去重键与落盘键会再次分叉：{offenders}")
