"""门禁链编排器（P1-1，计划书 §3.4 / §6 P1 批）单测。

编排语义逐条钉死：
- G0（存活）任一 failed/unevidenced → 短路：结果只含 g0 与 overall，
  g1-g4 键不存在（总纲"没资格参评业务判据"）；
- G1 契约 / G2 业务 / G3 回归：任一 failed → 后续门禁仍执行，但 overall=failed；
  unevidenced 聚合为 unevidenced（failed 压过 unevidenced）；
- G4 教义：仅当调用方提供（L2 代码态）；传 None → 结果不含 g4 键；
- 三态聚合 dominance：failed > unevidenced > passed；空列表 = 证据缺失（unevidenced），
  绝不空转成 passed——与 gate_verdict 契约"取不到数据不得冒充通过"同源。

本文件只测**纯编排逻辑**：判据产出由测试构造 GateVerdict 直接注入，
不触 IO、不跑测试、不建应用（真实数据源接线属 P1-3）。
"""

import pytest

from neurova.evolution.rsi.gate_chain import (
    GATE_BUSINESS,
    GATE_CONTRACT,
    GATE_DOCTRINE,
    GATE_OVERALL,
    GATE_REGRESSION,
    GATE_SURVIVAL,
    GateChain,
    aggregateGateState,
)
from neurova.evolution.rsi.gate_verdict import GateVerdict


def _passed(reason: str = "判据通过") -> GateVerdict:
    return GateVerdict.passed(reason=reason)


def _failed(reason: str = "判据失败") -> GateVerdict:
    return GateVerdict.failed(reason=reason)


def _unevidenced(reason: str = "证据缺失") -> GateVerdict:
    return GateVerdict.unevidenced(reason=reason)


def _allPassed(count: int) -> list:
    return [_passed(f"判据{i}通过") for i in range(count)]


# ── 三态聚合 dominance（编排器的唯一聚合规则，单点钉死）──────────────


def test_aggregateDominanceFailedOverUnevidencedOverPassed():
    assert aggregateGateState([_passed()]) == "passed"
    assert aggregateGateState([_passed(), _passed()]) == "passed"
    assert aggregateGateState([_passed(), _unevidenced()]) == "unevidenced"
    assert aggregateGateState([_unevidenced(), _failed()]) == "failed"
    assert aggregateGateState([_passed(), _failed(), _unevidenced()]) == "failed"


def test_aggregateEmptyListIsUnevidencedNotPassed():
    """空判据集 = 没有任何证据，按契约不得冒充 passed。"""
    assert aggregateGateState([]) == "unevidenced"


# ── G0 短路语义 ────────────────────────────────────────────────────


def test_g0AllPassedProceedsToLaterGates():
    chain = GateChain()
    result = chain.run(
        survivalVerdicts=_allPassed(6),
        contractVerdicts=_allPassed(3),
        businessVerdicts=_allPassed(2),
        regressionVerdicts=[_passed("A/B 零新增失败")],
    )
    assert set(result) == {"g0", "g1", "g2", "g3", "overall"}
    assert result["overall"][0].state == "passed"


def test_g0FailedShortCircuitsAndLaterGateKeysAreAbsent():
    """G0 任一 failed → 没资格参评：g1-g4 键不存在，即使调用方提供了判据。"""
    chain = GateChain()
    result = chain.run(
        survivalVerdicts=_allPassed(5) + [_failed("启动判据失败: [ERROR] 计数 3")],
        contractVerdicts=_allPassed(3),
        businessVerdicts=_allPassed(2),
        regressionVerdicts=[_passed()],
        doctrineVerdicts=[_passed()],
    )
    assert set(result) == {"g0", "overall"}
    assert result["overall"][0].state == "failed"
    assert "短路" in result["overall"][0].reason


def test_g0UnevidencedShortCircuitsWithOverallUnevidenced():
    """G0 无 failed 但有 unevidenced → 同样短路（没证据 ≠ 跑得起来），overall=unevidenced。"""
    chain = GateChain()
    result = chain.run(
        survivalVerdicts=_allPassed(5)
        + [_unevidenced("守卫子集判据无法取证: 守卫文件缺失")],
        contractVerdicts=_allPassed(3),
        businessVerdicts=_allPassed(2),
    )
    assert set(result) == {"g0", "overall"}
    assert result["overall"][0].state == "unevidenced"


def test_g0EmptySurvivalListShortCircuitsAsUnevidenced():
    """空存活判据集 = 一项都没跑成 → unevidenced 短路，不是 passed 放行。"""
    result = GateChain().run(survivalVerdicts=[])
    assert result["g0"] == []
    assert result["overall"][0].state == "unevidenced"


def test_g0SurvivalVerdictsNoneIsRejected():
    """G0 是第 0 道门，缺参是调用方编程错误，fail-closed 拒绝而非静默放行。"""
    with pytest.raises(ValueError):
        GateChain().run(survivalVerdicts=None)  # type: ignore[arg-type]


# ── G1-G3 聚合语义 ─────────────────────────────────────────────────


def test_g2FailedKeepsOverallFailedButLaterGatesStillExecute():
    """G2 业务判据 failed → overall failed；G3 回归仍执行（结果含 g3）。"""
    result = GateChain().run(
        survivalVerdicts=_allPassed(6),
        contractVerdicts=_allPassed(3),
        businessVerdicts=[_passed("决策档 0.82"), _failed("决策档回退 0.13")],
        regressionVerdicts=[_passed("A/B 零新增失败")],
    )
    assert set(result) == {"g0", "g1", "g2", "g3", "overall"}
    assert result["g2"] is not None and len(result["g2"]) == 2
    assert result["g3"][0].state == "passed"
    assert result["overall"][0].state == "failed"


def test_allUnevidencedGatesAggregateOverallUnevidenced():
    result = GateChain().run(
        survivalVerdicts=_allPassed(6),
        contractVerdicts=[_unevidenced("守卫文件缺失")],
        businessVerdicts=[_unevidenced("判据宿主未产出读数")],
        regressionVerdicts=[_unevidenced("父代基线缺失")],
    )
    assert result["overall"][0].state == "unevidenced"


def test_failedDominatesUnevidencedInAggregate():
    result = GateChain().run(
        survivalVerdicts=_allPassed(6),
        contractVerdicts=[_unevidenced("守卫文件缺失")],
        businessVerdicts=[_failed("决策档回退"), _unevidenced("密封档未跑")],
        regressionVerdicts=[_passed()],
    )
    assert result["overall"][0].state == "failed"


def test_emptyLaterGateIsUnevidencedButKeyPresent():
    """后置门禁给空列表 = 提供了但零证据：键存在、聚合 unevidenced。"""
    result = GateChain().run(
        survivalVerdicts=_allPassed(6),
        contractVerdicts=[],
        businessVerdicts=[],
        regressionVerdicts=[],
    )
    assert result["g1"] == []
    assert result["g2"] == []
    assert result["g3"] == []
    assert result["overall"][0].state == "unevidenced"


# ── G4 教义门（仅 L2 提供方）───────────────────────────────────────


def test_g4AbsentWhenNoneProvided():
    """L1 对象不设教义门：doctrineVerdicts=None → 结果不含 g4 键。"""
    result = GateChain().run(
        survivalVerdicts=_allPassed(6),
        contractVerdicts=_allPassed(3),
        businessVerdicts=_allPassed(2),
        regressionVerdicts=[_passed()],
        doctrineVerdicts=None,
    )
    assert "g4" not in result
    assert result["overall"][0].state == "passed"


def test_g4ProvidedParticipatesInAggregate():
    result = GateChain().run(
        survivalVerdicts=_allPassed(6),
        contractVerdicts=_allPassed(3),
        businessVerdicts=_allPassed(2),
        regressionVerdicts=[_passed()],
        doctrineVerdicts=[_failed("缺红灯→绿灯实测证据")],
    )
    assert "g4" in result
    assert result["overall"][0].state == "failed"


def test_g4PassedKeepsOverallPassed():
    result = GateChain().run(
        survivalVerdicts=_allPassed(6),
        contractVerdicts=_allPassed(3),
        businessVerdicts=_allPassed(2),
        regressionVerdicts=[_passed()],
        doctrineVerdicts=[_passed("红绿证据齐备"), _passed("live-verify 留痕")],
    )
    assert result["overall"][0].state == "passed"


def test_g4EmptyListIsUnevidenced():
    """提供 g4 但零证据 → unevidenced（不因"门存在"而 vacuous passed）。"""
    result = GateChain().run(
        survivalVerdicts=_allPassed(6),
        contractVerdicts=_allPassed(3),
        businessVerdicts=_allPassed(2),
        regressionVerdicts=[_passed()],
        doctrineVerdicts=[],
    )
    assert result["g4"] == []
    assert result["overall"][0].state == "unevidenced"


# ── None 边界：未提供的门禁不出键、不参与聚合 ───────────────────────


def test_noneGatesAreOmittedAndDoNotBlockOverall():
    result = GateChain().run(
        survivalVerdicts=_allPassed(6),
        contractVerdicts=None,
        businessVerdicts=None,
        regressionVerdicts=None,
    )
    assert "g1" not in result
    assert "g2" not in result
    assert "g3" not in result
    assert result["overall"][0].state == "passed"


# ── overall 形态 ───────────────────────────────────────────────────


def test_overallIsSingleVerdictWithGateDistributionEvidence():
    result = GateChain().run(
        survivalVerdicts=_allPassed(6),
        contractVerdicts=_allPassed(3),
        businessVerdicts=[_failed("决策档回退")],
        regressionVerdicts=[_passed()],
    )
    overall = result["overall"]
    assert isinstance(overall, list) and len(overall) == 1
    verdict = overall[0]
    assert isinstance(verdict, GateVerdict)
    assert verdict.state == "failed"
    assert verdict.reason.strip()
    assert verdict.evidence["gates"] == {
        "g0": "passed",
        "g1": "passed",
        "g2": "failed",
        "g3": "passed",
    }


def test_gateKeyConstantsAreStableContract():
    """g0..g4 与 overall 键名是世代账本/治理面的消费契约，不得随手改名。"""
    assert GATE_SURVIVAL == "g0"
    assert GATE_CONTRACT == "g1"
    assert GATE_BUSINESS == "g2"
    assert GATE_REGRESSION == "g3"
    assert GATE_DOCTRINE == "g4"
    assert GATE_OVERALL == "overall"
