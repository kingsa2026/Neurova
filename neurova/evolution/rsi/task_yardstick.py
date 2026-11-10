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
    B1 起该边界配"分布漂移告警读数"(stationarity_drift,窗口时间分半的
    成功率差)——假设破裂时读数自己说,不静默;
  - decay_rate 在快重放中不可观测(重放无闲置间隔),其遗忘带宽由
    eval_harness 的专用用例把守;
  - 与 gain 的关系:B1 起**升半判据**——对齐差分进回滚判据(e2e_gain 轴,
    只否决不奖励:行为分涨而结局对齐崩必判否;对齐涨不单凭它接受),
    接受判据仍归 eval_harness(行为地板)与 B3 置信区间。

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

    # B1 前置处置：平稳性边界的告警读数——窗口时间分半的成功率差。
    # 重放假设"历史成败预测后续成败"：前半与后半的分布漂移大时该假设失真，
    # 对齐分的稳定性随之存疑。|drift| ≥ 0.2 点名 suspect（阈值暂定值，
    # 有校准数据后另调）；这是**读数不是判据**——告警不改判分、不阻断。
    half = len(entries) // 2
    older_rate = (sum(1 for _ts, _t, ok in entries[:half] if ok) / half) if half else 0.0
    recent_rate = (sum(1 for _ts, _t, ok in entries[half:] if ok)
                   / (len(entries) - half)) if len(entries) > half else 0.0
    drift_value = round(recent_rate - older_rate, 4)

    return {
        "state": "measured",
        "score": round(score, 6),
        "entries": len(entries),
        "tools": n,
        "stationarity_drift": {
            "value": drift_value,
            "suspect": abs(drift_value) >= 0.2,
            "detail": f"窗口后半成功率 {recent_rate:.2f} − 前半 {older_rate:.2f}",
        },
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
