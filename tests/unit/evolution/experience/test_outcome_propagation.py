"""真实成败必须走进经验语义（工单 003）。

审计事实（`docs/specs/2026-09-19-experience-quality-gate-audit.md` L1-③）：
`closed_loop.py:506-510` 算出了 `outcome` 却没传给 `process_experience`，
后者在 `experience_feedback.py:261` 自行按关键词分类，而 `:164` 在关键词零命中时
`return "success"`。于是"客观失败"与"没有任何回执"都被洗成成功票，
而 `success_rate` 正是结晶入库门槛的唯一输入。
"""

import pytest

from neurova.evolution.closed_loop import EvolutionOrchestrator

TASK = "导出季度报表"
MENTION = "pdf_export 已用于导出"


def _assoc(orchestrator):
    associations = orchestrator.experience_feedback._associations.get(TASK, {})
    assert associations, "未产生任务-工具关联，用例无法判据计数"
    return next(iter(associations.values()))


def test_objective_failure_beats_success_keywords():
    """客观回执说失败，关键词说成功 —— 必须听客观的。"""
    orchestrator = EvolutionOrchestrator()

    orchestrator.on_experience_recorded(
        text=f"{MENTION}，任务执行成功并完成", task=TASK, tools=["pdf_export"],
        success=False,
    )

    assoc = _assoc(orchestrator)
    assert assoc.failure_count == 1, (
        f"客观失败被关键词洗成成功票：{assoc.to_dict()}")
    assert assoc.success_count == 0, f"success 位仍被抬高：{assoc.to_dict()}"


def test_no_evidence_attempt_votes_neither_way():
    """无回执轮：计入尝试数，但不得投成功票也不得投失败票。

    "确实没问题"、"这轮没测量"、"确证失败"是三件事 —— 混成一票，
    门槛与降权就都失去依据（工单 006/007 依赖这一区分）。
    """
    orchestrator = EvolutionOrchestrator()

    orchestrator.on_experience_recorded(
        text=MENTION, task=TASK, tools=["pdf_export"], success=None,
    )

    assoc = _assoc(orchestrator)
    assert assoc.total_count == 1
    assert assoc.success_count == 0 and assoc.failure_count == 0, (
        f"无证据轮投了票：{assoc.to_dict()}")


def test_keyword_fallback_labels_but_does_not_vote():
    """003 的反向锁 + 010 的收紧：关键词仍做分类，但不得投出成败票。

    本用例 003 版断言的是 `failure_count == 1`，与工单 010 §涉及层直接冲突 ——
    关键词粗分退到最后一格后，其结论不得再进 `success_rate`（口径同 005 的观察票：
    记账不投票）。改写而非删除：003 要锁的"别把关键词一刀砍死"由洞察标签继续
    满足，投票权这一半按 010 收回。
    """
    orchestrator = EvolutionOrchestrator()

    orchestrator.on_experience_recorded(
        text=f"{MENTION}，但执行失败并报错", task=TASK, tools=["pdf_export"],
        success=None,
    )

    assoc = _assoc(orchestrator)
    assert assoc.failure_count == 0, f"关键词粗分仍在投失败票：{assoc.to_dict()}"
    assert assoc.total_count == 1, "尝试数照记（003：无回执不得从分母消失）"
    assert orchestrator.experience_feedback._insights[-1].outcome == "failure", (
        "关键词标签被顺手删了，003 的反向锁失效")


def test_process_experience_accepts_explicit_outcome():
    """`process_experience` 必须能被显式告知成败（契约接缝本身）。"""
    from neurova.evolution.experience_feedback import ExperienceFeedback

    feedback = ExperienceFeedback()

    feedback.process_experience(
        experience_text=f"{MENTION}，任务执行成功", task_type=TASK, outcome="failure",
    )

    assoc = next(iter(feedback._associations[TASK].values()))
    assert assoc.failure_count == 1 and assoc.success_count == 0, assoc.to_dict()


@pytest.mark.parametrize("bad", ["", "   "])
def test_blank_task_still_separable(bad):
    """空任务串不得把无证据轮折叠成同一把票（键位归一由 011 处理，这里只保证不崩）。"""
    orchestrator = EvolutionOrchestrator()

    orchestrator.on_experience_recorded(text=MENTION, task=bad, tools=["pdf_export"],
                                        success=None)

    assert orchestrator.experience_feedback._associations
