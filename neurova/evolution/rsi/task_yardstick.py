"""RSI 工具选择端到端标尺(P1-2,2026-10-06)—— 历史结局流重放评估。

缺口(本仓 eval_harness.py:5-6 自认):gain 来自 setpoint 梯度的信号估算,
缺"整个 agent 是否变好"的端到端标尺。本模块给出第一块行为读数:
把 AdaptiveToolWeights 滑动窗口里的真实结局流(逐工具 (ts, ok))按时间
归并,在给定参数下经**真实排名代码路径**(get_effective_weight)重放,
量"结局与权重排名的对齐度":
  - 成功结局的工具应排得靠前(百分位越高越好);
  - 失败结局的工具应排得靠后(百分位越低越好);
  - 每条结局的对齐分 = p(成功) / 1-p(失败),p 为中位秩百分位(并列取半,
    全并列时恰 0.5——参数分不分化时的诚实基线)。

诚实边界:
  - 这是重放评估(offline evaluation):假设历史成败可预测后续成败(平稳性);
  - decay_rate 在快重放中不可观测(重放无闲置间隔),其遗忘带宽由
    eval_harness 的专用用例把守;
  - 与 gain 的关系:**并列呈报,不参与 gain 判定与回滚** —— 它是观测面,
    不是判据(判据仍归 eval_harness 与 rollback_manager)。

数据面:窗口本就随 tool_weights.json 持久化(单一事实源,不新增文件);
本模块零 LLM、纯内存、确定性(同输入同读数)。
"""

from typing import Any, Dict, List, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 低于该结局数不产出读数(小样本上百分位对齐是噪声)
MIN_ENTRIES = 10


def replay_alignment_score(
    outcome_streams: Dict[str, List[Tuple[float, bool]]], *,
    success_bonus: float,
    failure_penalty: float,
    decay_rate: float,
    window_size: int = 100,
) -> Dict[str, Any]:
    """在给定参数下重放结局流,返回对齐度读数。

    三态:``measured``(score ∈ [0,1])/ ``insufficient_data``(score=None)。
    同一结局流 + 同一参数 → 同一读数(确定性,可测试可复现)。
    """
    entries: List[Tuple[float, str, bool]] = []
    for tool, items in (outcome_streams or {}).items():
        for ts, ok in items or []:
            entries.append((float(ts), tool, bool(ok)))
    entries.sort(key=lambda e: e[0])

    tools = sorted(outcome_streams or {})
    if len(entries) < MIN_ENTRIES:
        return {
            "state": "insufficient_data",
            "score": None,
            "entries": len(entries),
            "tools": len(tools),
            "detail": f"结局 {len(entries)} < {MIN_ENTRIES},不产出读数",
        }

    from neurova.evolution.closed_loop import AdaptiveToolWeights

    weights = AdaptiveToolWeights(
        success_bonus=float(success_bonus),
        failure_penalty=float(failure_penalty),
        decay_rate=float(decay_rate),
        window_size=max(1, int(window_size)),
    )

    n = len(tools)
    scores: List[float] = []
    for _ts, tool, ok in entries:
        eff = {name: weights.get_effective_weight(name) for name in tools}
        value = eff[tool]
        strict = sum(1 for v in eff.values() if v < value)
        ties = sum(1 for v in eff.values() if v == value) - 1
        percentile = (strict + 0.5 * ties) / (n - 1) if n > 1 else 1.0
        scores.append(percentile if ok else 1.0 - percentile)
        weights.update_weight(tool, ok)

    score = sum(scores) / len(scores)
    return {
        "state": "measured",
        "score": round(score, 6),
        "entries": len(entries),
        "tools": n,
        "detail": f"重放 {len(entries)} 条结局 / {n} 工具",
    }


def measure_tool_selection(weights: Any) -> Dict[str, Any]:
    """从活权重对象取端到端读数(编排器装配点的唯一入口)。

    接受 AdaptiveToolWeights 本体,或持有 ``.tool_weights`` 的闭环系统
    (EvolutionOrchestrator);两者都不暴露窗口时诚实报 insufficient_data。
    """
    inner = getattr(weights, "tool_weights", weights)
    streams_fn = getattr(inner, "outcome_streams", None)
    if not callable(streams_fn):
        return {
            "state": "insufficient_data",
            "score": None,
            "entries": 0,
            "tools": 0,
            "detail": "权重对象未暴露结局窗口",
        }
    return replay_alignment_score(
        streams_fn(),
        success_bonus=getattr(inner, "success_bonus", 0.1),
        failure_penalty=getattr(inner, "failure_penalty", 0.05),
        decay_rate=getattr(inner, "decay_rate", 0.01),
        window_size=getattr(inner, "window_size", 100),
    )
