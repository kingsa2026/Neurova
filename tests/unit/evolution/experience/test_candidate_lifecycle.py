"""候选生命周期：不自喂、不绕过裁决、丢弃必须可见（工单 005）。

四条现状（审计 G6/G7/G8，见
`docs/specs/2026-09-19-experience-quality-gate-audit.md`）：
- `pattern_crystallizer.py:305-311` 结晶成功后回灌 `record_experience(..., True, ...)`
  —— 给自己投一张任务成功票，还会反过来抬高下一次结晶的成功率；
- `:264-271` LLM judge 未注入时候选**直写**入库 ⇒ 裁决前的候选永远绕过裁决；
- `:332-341` 超龄候选"自动放行"⇒ 给绕过裁决留了个 48 小时后门；
- `:329-330` 时间戳解析失败返回 `0.0` ⇒ 该候选既永不过期，也永不进裁决。
"""

import asyncio
from datetime import datetime, timedelta, timezone

from neurova.evolution.closed_loop import EvolutionOrchestrator

CONTEXT = "导出季度报表到 PDF"


def _three_success_observations(cryst):
    for _ in range(3):
        cryst.observe(tool_name="pdf_export", context=CONTEXT, success=True)


def _association_votes(orchestrator) -> int:
    return sum(a.total_count
               for per_tool in orchestrator.experience_feedback._associations.values()
               for a in per_tool.values())


def test_approved_crystallization_votes_nothing(make_crystallizer, approving_judge):
    """入库一条模式，不得顺手给它投一张成功票。

    旧路径在 `_store_candidate` 里回调 `record_experience(..., True, ...)`，
    等于门槛自己给自己加分 —— 结晶次数越多，`success_rate` 越好看。
    """
    cryst, engine = make_crystallizer()
    orchestrator = EvolutionOrchestrator()
    cryst.evolution = orchestrator
    orchestrator.crystallizer = cryst

    _three_success_observations(cryst)
    asyncio.run(cryst.review_pending_with_llm(llm_client=approving_judge))

    assert len(engine.stored) == 1, "前置失效：候选未真正入库，本用例无从判据自喂"
    assert _association_votes(orchestrator) == 0, (
        f"结晶回灌被当成经验票计入关联：votes={_association_votes(orchestrator)}")


def test_candidate_not_written_without_judge(make_crystallizer):
    """judge 未注入时不得直写：裁决缺席必须显式，不能等于放行。"""
    cryst, engine = make_crystallizer()

    _three_success_observations(cryst)

    assert engine.stored == [], "无 judge 仍直写入库 —— 首批候选永远绕过裁决"
    assert cryst.list_pending(), "候选应留在待裁决队列里等裁决"


def test_expired_candidate_is_dropped_not_released(make_crystallizer):
    """超龄候选不得"自动放行"入库；丢弃必须计数可见。"""
    cryst, engine = make_crystallizer()

    _three_success_observations(cryst)
    stale = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
    for candidate in cryst._pending:
        candidate["queued_at"] = stale

    dropped = cryst._prune_expired_pending(max_age_hours=48.0)

    assert dropped >= 1, "超龄候选没有被计入丢弃（静默消失 = 没人知道裁决没跑）"
    assert engine.stored == [], "超龄候选被自动放行入库 —— 后门比绕过裁决更糟"
    assert cryst.pending_dropped >= dropped


def test_unparsable_timestamp_is_not_immortal(make_crystallizer):
    """时间戳不可解析的候选不得变成"永不过期、也永不裁决"的僵尸。"""
    cryst, engine = make_crystallizer()

    _three_success_observations(cryst)
    for candidate in cryst._pending:
        candidate["queued_at"] = "not-a-time"

    dropped = cryst._prune_expired_pending(max_age_hours=48.0)

    assert dropped >= 1 and cryst.list_pending() == [], (
        "不可判龄的候选被留在队里既不超龄也不裁决 —— 僵尸候选")
    assert engine.stored == [], "僵尸候选也不得被放行入库"


def test_queue_overflow_drop_is_counted(make_crystallizer):
    """队列有界；静默丢最旧等于观察面看不见任何丢失。"""
    cryst, engine = make_crystallizer()

    for index in range(25):
        cryst._pending.append({"key": f"模式{index}", "primary_tool": "pdf_export",
                               "rate": 1.0, "sample_count": 3, "sample_context": CONTEXT,
                               "queued_at": datetime.now(timezone.utc).isoformat()})
    cryst._enforce_pending_bound()

    assert cryst.pending_dropped > 0, (
        f"溢出静默丢候选：pending={len(cryst._pending)}")
