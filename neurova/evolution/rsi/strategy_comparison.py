# -*- coding: utf-8 -*-
"""三策略离线对比（H2，survey §10.2）——回放/选择性保留/刷新同题同机对比。

三种经验维护策略在同一任务流上的离线对比，**复用 A3/B1 的重放机器**
（RSIEvalHarness.run 唯一评分路径——对比器唯一，不新建第三套框架，教义第
6/7 条）。策略缺档（不足三种）报 unevidenced；策略间分类走 ab_library 的
共享聚合（classifyPairwise，C3 净接线的同一台机器）。

策略形态：调用方供 {策略名: 应用该策略后的活参数态}（replay/选择性保留/
refresh 的实际实施是运维动作，本模块只供对比机器——策略的落地实施另票）。
"""

from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 三策略名单（H2 期望档；缺档 unevidenced）。
STRATEGY_NAMES = ("replay", "selective_retain", "refresh")


def compareStrategies(strategy_params: Dict[str, Dict[str, Any]], *,
                      harness: Any,
                      baseline_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """三策略同题同机对比（确定性：同一 harness、同一批用例）。

    strategy_params = {策略名: 活参数态}；harness = RSIEvalHarness 实例
    （run() 增益唯一来源——对比器唯一）。baseline_params 给定时，各策略
    相对基线的改善/退化经 classifyPairwise 分类出街。
    """
    from neurova.evolution.eval.ab_library import classifyPairwise

    if not isinstance(strategy_params, dict):
        raise ValueError("strategy_params 必须是 {策略名: 活参数态}")
    missing = [name for name in STRATEGY_NAMES if name not in strategy_params]
    if missing:
        return {
            "state": "unevidenced",
            "score": None,
            "missing": missing,
            "reason": f"策略缺档：{missing}——三策略对比不硬算",
        }
    scores: Dict[str, float] = {}
    for name, live_params in strategy_params.items():
        outcome = harness.run(live_params or {})
        score = outcome.get("score")
        scores[name] = (round(float(score), 6)
                        if isinstance(score, (int, float)) else 0.0)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    readout: Dict[str, Any] = {
        "state": "measured",
        "scores": scores,
        "best": ranked[0][0] if ranked else None,
        "detail": "三策略同题同机（RSIEvalHarness.run 唯一评分路径）",
    }
    if baseline_params is not None:
        base_outcome = harness.run(baseline_params or {})
        base_score = base_outcome.get("score")
        base_value = (round(float(base_score), 6)
                      if isinstance(base_score, (int, float)) else 0.0)
        readout["baseline"] = base_value
        keys = list(scores.keys())
        readout["vs_baseline"] = classifyPairwise(
            [base_value] * len(keys), [scores[k] for k in keys], keys)
    return readout
