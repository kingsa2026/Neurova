"""四条自动化前置的读数面（§8「前置要落成判据，不落成口头条件」）。

判据三件事：旗标不得与探针脱节（反谎）、探针不得恒真（反空转）、
未满足必须点名而不是折叠成布尔。
"""

import asyncio

import pytest

from neurova.evolution.rsi.automation_prerequisites import (
    automationPrerequisites,
    automationPrerequisiteVerdict,
)

EXPECTED_KEYS = {"caseLevelGate", "realTrajectoryExecutor",
                 "presentationLedger", "failClosedOnMissingEvidence"}


def _satisfied(key):
    return automationPrerequisites()[key]["satisfied"]


def test_registryCoversAllFourPrerequisites():
    """四条一项不能少：少一条等于把前置清单偷偷缩短。"""
    registry = automationPrerequisites()
    assert set(registry) == EXPECTED_KEYS
    for key, item in registry.items():
        assert set(item) >= {"title", "satisfied", "reason"}, key
        assert isinstance(item["satisfied"], bool), key


def test_flagsAgreeWithTheirOwnProbes():
    """反谎：旗标必须等于该条探针的运行期结果。"""
    for key, item in automationPrerequisites().items():
        assert item["satisfied"] is bool(item["probe"]()), (
            f"{key}：旗标 {item['satisfied']} 与探针结果不一致")


def test_caseLevelGateProbeFailsWhenTheGateIsGone(monkeypatch):
    """反空转：把例级门那道读数摘掉，探针必须报不满足。"""
    from neurova.evolution.eval import runner as evalRunner

    monkeypatch.delattr(evalRunner, "_caseRegressionReadout")
    assert automationPrerequisites()["caseLevelGate"]["probe"]() is False


def test_presentationLedgerProbeFailsWhenAccountingIsGone(monkeypatch):
    """反空转：把呈现归因函数摘掉，探针必须报不满足。"""
    from neurova.skills import skill_service as skillService

    monkeypatch.delattr(skillService, "compute_skill_funnel_update")
    assert automationPrerequisites()["presentationLedger"]["probe"]() is False


def test_failClosedProbeFailsOnZeroThreshold(monkeypatch):
    """反空转：`min_improvement` 退回 0 就是当年"0/0 相等被当零增益放行"的形态。"""
    from neurova.evolution.eval import config as evalConfig

    monkeypatch.setattr(evalConfig, "EvolutionConfig",
                        lambda *a, **kw: type("C", (), {"min_improvement": 0.0})())
    assert automationPrerequisites()["failClosedOnMissingEvidence"]["probe"]() is False


def test_realTrajectoryFlagIsFalseWhileDefaultExecutorStillEchoes():
    """反谎（声明项）：默认执行器还在回显 ⇒ 这条前置必须写着不满足。

    控制器判据是同步路径、可能跑在已运行的事件循环里，所以运行期探针不能自己
    `asyncio.run`；本条改为"声明 + 异步反证"，由这一格在测试里把声明钉回事实。
    """
    from neurova.evolution.eval.runner import _DefaultAgent

    async def _echoes():
        agent = _DefaultAgent()
        return await agent.run(skill_text="正文原文", task_input="任务") == "正文原文"

    echoes = asyncio.run(_echoes())
    item = automationPrerequisites()["realTrajectoryExecutor"]
    assert item["satisfied"] is False, "默认执行器仍回显，旗标却写了真"
    assert echoes is True


def test_unmetPrerequisiteIsNamedNotSilent():
    """未满足 ⇒ failed 且点名是哪一条（不折叠成"没证据"）。"""
    verdict = automationPrerequisiteVerdict()
    assert verdict.state == "failed", verdict.state
    assert "realTrajectoryExecutor" in verdict.reason, verdict.reason


def test_verdictPassesWhenAllPrerequisitesHold():
    """放行路径也得能到：证明上面那格 failed 是这一格判的，不是恒红。"""
    allHold = {k: {"title": k, "satisfied": True, "reason": ""}
               for k in EXPECTED_KEYS}
    verdict = automationPrerequisiteVerdict(allHold)
    assert verdict.state == "passed", verdict.reason

    oneMissing = {**allHold,
                  "realTrajectoryExecutor": {"title": "真轨迹", "satisfied": False,
                                             "reason": "默认执行器仍回显"}}
    verdict = automationPrerequisiteVerdict(oneMissing)
    assert verdict.state == "failed"
    assert "realTrajectoryExecutor" in verdict.reason, verdict.reason
