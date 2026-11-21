"""门禁链编排器（计划书 §3.4 / §6 P1 批 P1-1）。

设计出处：docs/04-plans/2026-11-21-recursive-self-evolution-plan.md
§2.0 总体纲要（跑不通自动处置）、§2.1 三原则、§3.4 gate_chain 设计、
§6 P1 批 P1-1（门禁链编排，L1 范围 G0-G3，G4 教义门仅 L2 代码态）。

定位：世代流水线"影子验证 → 门禁裁决"一环的**编排件**。按序编排
G0 存活 → G1 契约 → G2 业务 → G3 回归 → G4 教义，把各门禁的判据集
聚合为单一三态结论（沿 GateVerdict 契约）。

设计约束（§3.4 与本卡任务书）：

- **纯编排**：判据的产出由调用方注入（``run`` 的各 verdicts 参数即注入
  面）——本模块不做 IO、不跑测试、不建应用。单测用构造的 GateVerdict
  直接钉死编排语义；真实数据源接线（survival_probe / eval_harness /
  A&B 自证）是 P1-3 世代编排器的事。
- **G0 短路**：存活判据任一 failed / unevidenced → 该世代没资格参评
  业务判据，G1-G4 不执行（结果不含其键），overall 取 G0 的聚合态。
- **三态聚合**：failed 压过 unevidenced，unevidenced 压过 passed；
  空判据集 = 证据缺失（unevidenced），绝不空转成 passed——与
  gate_verdict 契约"取不到数据不得冒充通过"同源。
- **G4 教义门仅 L2 代码态提供**；L1 对象传 None → 结果不含 g4 键、
  不参与聚合。
- G1-G3 任一 failed → 后续门禁仍执行（结果完整可审计），但
  overall=failed（一票否决语义落在聚合层，不落在执行层）。

返回形态：``dict[str, list[GateVerdict]]``，键为 g0..g4（未提供的门禁
不出键）+ ``overall``（单元素列表，承载聚合结论、各门分布证据与短路
标记，供世代账本与治理读面直接消费）。
"""

from __future__ import annotations

from typing import Iterable, Optional

from neurova.evolution.rsi.gate_verdict import (
    STATE_FAILED,
    STATE_PASSED,
    STATE_UNEVIDENCED,
    GateVerdict,
)

__all__ = [
    "GateChain",
    "aggregateGateState",
    "GATE_SURVIVAL",
    "GATE_CONTRACT",
    "GATE_BUSINESS",
    "GATE_REGRESSION",
    "GATE_DOCTRINE",
    "GATE_OVERALL",
]

# ---------------------------------------------------------------------------
# 门禁键名（世代账本 verdicts 映射与治理读面的消费契约，见计划书 §2.3）
# ---------------------------------------------------------------------------

GATE_SURVIVAL = "g0"
GATE_CONTRACT = "g1"
GATE_BUSINESS = "g2"
GATE_REGRESSION = "g3"
GATE_DOCTRINE = "g4"
GATE_OVERALL = "overall"

#: 三态严重度序：failed > unevidenced > passed（聚合取最高严重度）。
_STATE_SEVERITY = {
    STATE_PASSED: 0,
    STATE_UNEVIDENCED: 1,
    STATE_FAILED: 2,
}


def _aggregateStates(states: Iterable[str]) -> str:
    """三态聚合的**单一出处**：取最高严重度；空集 = unevidenced。"""
    collected = list(states)
    if not collected:
        return STATE_UNEVIDENCED
    return max(collected, key=lambda state: _STATE_SEVERITY[state])


def aggregateGateState(verdicts: Iterable[GateVerdict]) -> str:
    """把一道门禁的判据集聚合为单一三态。

    空判据集 = 判据所需数据一件都没取到 → unevidenced（契约：不得冒充
    passed，那正是 gate_verdict 模块注释里钉死的旧病形态）。
    """
    return _aggregateStates(verdict.state for verdict in verdicts)


def _overallVerdict(
    gateStates: dict[str, str], *, shortCircuit: bool
) -> GateVerdict:
    """构造 overall 聚合结论（含各门分布证据，供账本/读面直接消费）。"""
    state = _aggregateStates(gateStates.values())
    distribution = ", ".join(
        f"{gate}={gateState}" for gate, gateState in sorted(gateStates.items())
    )
    if shortCircuit:
        reason = f"门禁链在 G0 短路：该世代没资格参评业务判据（{distribution}）"
    elif state == STATE_PASSED:
        reason = f"门禁链全绿（{distribution}）"
    else:
        reason = f"门禁链未整体通过（{distribution}）"
    evidence = {
        "gates": dict(sorted(gateStates.items())),
        "shortCircuit": shortCircuit,
    }
    return GateVerdict.of(state, reason, evidence)


class GateChain:
    """G0→G4 门禁链编排器（计划书 §3.4）。

    用法（P1-3 世代编排器将按此喂入真实判据）::

        result = GateChain().run(
            survivalVerdicts=SurvivalProbe().probe(workspace, dataRoot),
            contractVerdicts=contractGuardVerdicts,
            businessVerdicts=evalHarnessVerdicts,
            regressionVerdicts=abVerdicts,
            doctrineVerdicts=None,  # L1 对象无教义门；L2 传证据判据
        )
        if result["overall"][0].state != "passed":
            ...  # 拒绝晋升；G0 短路时结果只含 g0 与 overall
    """

    def run(
        self,
        *,
        survivalVerdicts: list[GateVerdict],
        contractVerdicts: Optional[list[GateVerdict]] = None,
        businessVerdicts: Optional[list[GateVerdict]] = None,
        regressionVerdicts: Optional[list[GateVerdict]] = None,
        doctrineVerdicts: Optional[list[GateVerdict]] = None,
    ) -> dict[str, list[GateVerdict]]:
        """按序编排 G0→G4，返回各门禁判据列表 + overall 聚合结论。

        - ``survivalVerdicts`` 必填（G0 是第 0 道门，缺席无从判定
          "跑不跑得起来"，传 None 直接拒绝——fail-closed，不静默放行）；
        - 其余各门传 None = 本世代不设该门（不出键、不参与聚合）；
          传空列表 = 该门跑了但零证据（键存在，聚合为 unevidenced）。
        """
        if survivalVerdicts is None:
            raise ValueError(
                "G0 存活判据必填：survivalVerdicts 不可为 None"
                "（第 0 道门缺席即无从判定世代是否跑得起来）"
            )

        result: dict[str, list[GateVerdict]] = {
            GATE_SURVIVAL: list(survivalVerdicts),
        }
        g0State = aggregateGateState(result[GATE_SURVIVAL])

        # G0 短路（§2.0 总纲"没资格参评"）：存活门不过，业务判据一律不跑。
        if g0State != STATE_PASSED:
            result[GATE_OVERALL] = [
                _overallVerdict({GATE_SURVIVAL: g0State}, shortCircuit=True)
            ]
            return result

        gateStates = {GATE_SURVIVAL: g0State}
        for gateKey, verdicts in (
            (GATE_CONTRACT, contractVerdicts),
            (GATE_BUSINESS, businessVerdicts),
            (GATE_REGRESSION, regressionVerdicts),
            (GATE_DOCTRINE, doctrineVerdicts),
        ):
            if verdicts is None:
                continue  # 未提供的门禁不出键、不参与聚合
            result[gateKey] = list(verdicts)
            gateStates[gateKey] = aggregateGateState(result[gateKey])

        # G1-G3 任一 failed 也把后续门跑完（结果完整可审计），
        # 一票否决语义落在 overall 聚合层。
        result[GATE_OVERALL] = [_overallVerdict(gateStates, shortCircuit=False)]
        return result
