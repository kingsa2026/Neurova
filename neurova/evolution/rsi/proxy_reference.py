# -*- coding: utf-8 -*-
"""代理分的外部对照（F1，survey §10.2）——setpoint 贴近度的相关性呈报。

performance_score 的 0.7×setpoint 贴近度是自指代理（循环奖励"贴近自己的
设定值"，survey §3.2③/维度 F 的扣分点）。本模块给它第一次外部对照：
逐轮成对采集（代理分, 外部参考分），滚动相关性呈报——代理独自上涨而外部
参考不动时，相关性读数如实下跌，代理不得独自粉饰。

外部参考的观测档形态＝B1 的 e2e 真实结局对齐（重放真实结局流，与 setpoint
代理不同测量族）；B2 任务流的 golden 臂评分（真轨迹面）属升判据档，通道由
task_stream 模块备好，随 A1 真臂机器挂载。

三态：measured（相关性 ∈ [-1,1]）/ insufficient_data（对数不足或序列退化
——方差 0 无相关可言，不硬算）。
"""

import math
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 滚动窗口（对数下限与保留上限同源）：低于此不产出读数。
MIN_PAIRS = 6
WINDOW = 20


def rollingCorrelation(proxy_series: List[float],
                       reference_series: List[float]) -> Dict[str, Any]:
    """皮尔逊滚动相关性（同位对齐；两序列等长截断）。"""
    n = min(len(proxy_series or []), len(reference_series or []))
    if n < MIN_PAIRS:
        return {"state": "insufficient_data", "score": None, "correlation": None,
                "pairs": n,
                "detail": f"成对样本 {n} < {MIN_PAIRS}，不产出读数"}
    xs = [float(v) for v in (proxy_series or [])[-n:]]
    ys = [float(v) for v in (reference_series or [])[-n:]]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        # 常数列的皮尔逊无定义，但读数目的（代理独自上涨要现形）恰好需要
        # "无共动 ⇒ 相关 0"的约定形态——按零相关呈报并点名约定，不静默 nan。
        return {
            "state": "measured", "score": 0.0, "correlation": 0.0, "pairs": n,
            "degenerate": True,
            "detail": "代理或参考为常数列（方差 0）——按零相关约定呈报"
                      "（皮尔逊无定义），无共动即无背书",
        }
    correlation = cov / math.sqrt(var_x * var_y)
    return {
        "state": "measured",
        "score": round(correlation, 6),
        "correlation": round(correlation, 6),
        "pairs": n,
        "detail": (
            f"代理分×外部参考分滚动相关 {correlation:.3f}（窗口 {n}）——"
            "代理独自粉饰会在这里现形"
        ),
    }
