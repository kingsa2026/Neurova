# -*- coding: utf-8 -*-
"""评测回合（save_memory=False）不得写技能漏斗账本，也不得触发 RSI 迭代。

票面：`docs/04-plans/2026-10-09-双臂试评接真轨迹-前置2落地实施方案.md` Task 3。
用户 2026-10-09 裁 D3：给这两步补 `save_memory` 尊重，**不新造** `eval_mode` 旗标
（那会成为"评测态"的第二处定义，顶教义第 6 条）。

为什么判据必须打在整条 `process()` 的**外部可观察写入**上，而不是只测步骤内部：
缺陷在派发层——`post_chat_pipeline.py:797` 与 `:831` 这两条 lambda 没把 `save_memory`
传下去，而同文件另外四处（`:963/:1104/:1686/:1981`）都传了。只测步骤内部，红的会是
"今天根本不会被走到的分支"，改完照样绿——本仓 §6-97 记过同形错误。

两处判据各取其第一步动作：
· 漏斗侧：账本服务 `library_service.get_library(...).record_skill_funnel`；
· RSI 侧：`skill_improver.get_skill_improver` 是 RSI 步进入实质工作的第一动作。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.core import turn_context
from neurova.post_chat_pipeline import PostChatPipeline, StepStatus


class _FakePipeline(PostChatPipeline):
    """只桩掉与本判据无关的步骤，**保留** funnel/rsi 两步的真实实现。

    走真实 `__init__`（它只做字段赋值），因为 `_agt`/`_bg_tasks`/`_step_results`
    都是只读 property——私赋会当场 AttributeError，而 `agent_ref` 门（AGENTS.md §3）
    本来就是这条链的装配形态。
    """

    async def _step_save_session(self, *args, **kwargs):
        return "sess-1"

    async def _step_save_memory(self, *args, **kwargs):
        return None

    async def _step_generate_tts(self, *args, **kwargs):
        return (None, None)

    async def _step_cognitive_analysis(self, *args, **kwargs):
        return 0.0

    async def _step_proactive_question(self, *args, **kwargs):
        return None

    def _step_update_memory_temperature(self):
        return None


def _fakePipeline() -> _FakePipeline:
    config = SimpleNamespace(agent_id="a-eval", user_id="u-eval", enable_tts=False)
    agentRef = SimpleNamespace(config=config, session_id="sess-1", _skill_registry=None)
    return _FakePipeline(agentRef)


async def _noop(self, *args, **kwargs):
    return None


for _name in (
    "_step_reflection",
    "_step_record_experience",
    "_step_record_workflow_experience",
    "_step_evocate_generation",
    "_step_p0_post_processing",
    "_step_conflict_detection",
    "_step_version_snapshot",
    "_step_extract_conversation_rules",
    "_step_motivation_observations",
):
    setattr(_FakePipeline, _name, _noop)


def _funnelLedgerSeeded() -> bool:
    """本轮账本里确实有一条会被归因成写入的派条目——没有它，整条判据是空转。"""
    turn_context.record_turn_skill_funnel("sk-eval", applied=True, ok=True)
    from neurova.skills.skill_service import compute_skill_funnel_update

    entries = turn_context.get_turn_skill_funnel()
    return bool(entries) and bool(
        compute_skill_funnel_update(entries, task_completed=True)
    )


@pytest.mark.asyncio
async def test_evalTurnWritesNoSkillFunnelLedger(monkeypatch):
    """save_memory=False 的一轮，技能漏斗账本必须一格都不写。"""
    from neurova.skills import library_service as libService

    monkeypatch.setenv("NEUROVA_POSTCHAT_BACKGROUND", "0")
    assert _funnelLedgerSeeded(), "前置未成立：本轮账本没产出可写入的归因，判据会空转"

    account = MagicMock(name="skillLibraryAccount")
    monkeypatch.setattr(libService, "get_library", lambda *a, **k: account)

    await _fakePipeline().process(
        user_input="评测任务", reply="评测回复", session_id="sess-1",
        save_memory=False, enable_tts=False, metadata={},
    )

    assert account.record_skill_funnel.call_count == 0, (
        "评测回合把派发账本写进了技能库——漏斗从此分不清真用户与评测轮")
    assert account.record_trust_observation.call_count == 0, (
        "评测回合喂了信任状态机一条假观测")


@pytest.mark.asyncio
async def test_evalTurnDoesNotRunRsiIteration(monkeypatch):
    """save_memory=False 的一轮不得进 RSI 迭代（它会改技能正文、落归因台账）。"""
    import neurova.evolution.skill_improver as improverModule

    monkeypatch.setenv("NEUROVA_POSTCHAT_BACKGROUND", "0")
    improverSpy = MagicMock(name="skillImprover")
    monkeypatch.setattr(improverModule, "get_skill_improver", lambda: improverSpy)

    pipeline = _fakePipeline()
    await pipeline.process(
        user_input="评测任务", reply="评测回复", session_id="sess-1",
        save_memory=False, enable_tts=False, metadata={},
    )

    assert improverSpy.method_calls == [], (
        f"评测回合触发了 RSI 迭代：{improverSpy.method_calls}")
    readings = [r for r in pipeline._step_results if r.step_name == "rsi_iteration"]
    assert any(r.status == StepStatus.SKIPPED for r in readings), (
        "RSI 步没有把'因评测而跳过'落成读数——静默跳过与'本轮没跑'同形，"
        "台账读侧无法区分（AGENTS.md §2：写了必须有人读，跳过也要留痕）")


@pytest.mark.asyncio
async def test_realTurnStillWritesBoth(monkeypatch):
    """反证另一半：save_memory=True 的正常轮，两条写入必须照常发生。

    没有这一格，上面两格可以靠"整步摘掉"糊过去——那是降级判据，不是补闸门。
    """
    from neurova.skills import library_service as libService

    monkeypatch.setenv("NEUROVA_POSTCHAT_BACKGROUND", "0")
    assert _funnelLedgerSeeded(), "前置未成立：本轮账本没产出可写入的归因，判据会空转"

    account = MagicMock(name="skillLibraryAccount")
    monkeypatch.setattr(libService, "get_library", lambda *a, **k: account)

    await _fakePipeline().process(
        user_input="真实任务", reply="真实回复", session_id="sess-1",
        save_memory=True, enable_tts=False, metadata={},
    )

    assert account.record_skill_funnel.call_count > 0, (
        "闸门把正常轮也挡了——评测隔离不该变成生产断写")
