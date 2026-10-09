"""四条自动化前置的读数面（§8「前置要落成判据，不落成口头条件」）。

判据三件事：旗标不得与探针脱节（反谎）、探针不得恒真（反空转）、
未满足必须点名而不是折叠成布尔。
"""

import asyncio

import pytest

from neurova.evolution.rsi.deployment_controller import RSIDeploymentController
from neurova.evolution.rsi.automation_prerequisites import (
    automationPrerequisites,
    automationPrerequisiteVerdict,
)

EXPECTED_KEYS = {"caseLevelGate", "realTrajectoryExecutor",
                 "presentationLedger", "failClosedOnMissingEvidence"}


@pytest.fixture(autouse=True)
def _automationPrerequisitesHeldForEvidenceAxes():
    """本模块**不**用根 conftest 那枚脚手架：这里要测的就是未桩掉的真实否决。

    同名夹具由 pytest 按"就近定义遮蔽外层"处理，是确定行为；因此本文件里的
    用例看到真实读数（前置 2 未满足 ⇒ 自动执行档硬挡）。
    """
    return None


def test_scaffoldFixtureExistsAndIsOptOutable():
    """脚手架被静默摘掉 ⇒ 44 格会变成无主红墙。这一格钉住它的存在与可遮蔽性。"""
    import tests.conftest as rootConftest

    scaffold = getattr(rootConftest, "_automationPrerequisitesHeldForEvidenceAxes", None)
    assert scaffold is not None, (
        "tests/conftest.py 里的前置脚手架不见了：晋升判据会在链首硬否决，"
        "大量在测其它证据轴的既有用例走不到自己的断言（实测 44 格）。"
        "有效性守卫在 test_automationPrerequisiteScaffold.py——本格只按名确认它在，"
        "不钉 pytest 内部属性（pytest 9 已把夹具对象换掉，钉内部属性下次升级即碎）")



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


class TestControllerCarriesThePrerequisiteCell:
    """Task 2：前置格绑在晋升目标 phase ∈ {2,3,4}（本模块不吃脚手架）。"""

    def test_observationToManualIsNotBlocked(self):
        """0→1 只是"生成建议给人看"，不授自动权 ⇒ 不该被全自动的前置挡住。

        否则前置清单会把观察期一起锁死：观察档产不出执行证据，
        正是工单 006 立过裁决的那条循环依赖。
        """
        verdict = RSIDeploymentController(initial_phase=0).evaluate_phase_transition({})

        assert bool(verdict) is True, f"0→1 被前置挡住了：{verdict.state} / {verdict.reason}"

    def test_firstAutonomyPhaseIsVetoedAndNamed(self):
        """1→2 是"低风险自动执行"的起点 ⇒ 前置未满足必须硬否决并点名。"""
        verdict = RSIDeploymentController(initial_phase=1).evaluate_phase_transition({
            "days_without_rollback": 8, "roi": None, "convergence_status": "insufficient_data",
        })

        assert verdict.state == "failed", f"{verdict.state} / {verdict.reason}"
        assert "realTrajectoryExecutor" in verdict.reason, verdict.reason

    def test_cellIsWhatBlocksNotSomethingElse(self, monkeypatch):
        """把前置格换成"全满足"，同一份证据就该放行 ⇒ 红确实咬在这一格上。"""
        from neurova.evolution.rsi import deployment_controller as controllerModule
        from neurova.evolution.rsi.gate_verdict import GateVerdict

        monkeypatch.setattr(controllerModule, "automationPrerequisiteVerdict",
                            lambda *a, **kw: GateVerdict.passed("反证：假装四条都在位"))
        verdict = RSIDeploymentController(initial_phase=1).evaluate_phase_transition({
            "days_without_rollback": 8, "roi": None, "convergence_status": "insufficient_data",
        })

        assert bool(verdict) is True, f"{verdict.state} / {verdict.reason}"


def test_verdictShapeIsCarriableByTheExistingStatusSurface():
    """Task 4：不新建通道 —— 前置结论经既有 `phase_verdict` 外露。

    `orchestrator.py:541` 把晋升判据原样 `to_dict()` 挂进状态面（`:569`/`:594`），
    所以这里只钉"序列化后点名与逐条布尔都还在"；端到端（真 orchestrator + 真 HTTP）
    留到 Task 5 活体验证，不在这里冒充。
    """
    payload = automationPrerequisiteVerdict().to_dict()

    assert payload["state"] == "failed"
    assert "realTrajectoryExecutor" in payload["reason"]
    assert set(payload["evidence"]) == EXPECTED_KEYS
    assert all(isinstance(v, bool) for v in payload["evidence"].values())
