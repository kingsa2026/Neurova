# -*- coding: utf-8 -*-
"""自适应污染监测（D4，survey §10.2）——"反复选择适应该验证集"的可观测形态。

holdout 是选择过程的判据集（会被搜索反复比较），heldout 是密封验收证据
（永不参与判定，P0-2/D1）。搜索若在适应判据集：holdout 增益独涨而 heldout
增益不动——两者差值就是污染的可观测形态。本模块逐轮记录该差值并点名
suspect 轮次；**监测是纯读数**：不改判定、不阻断进化（处置归人工审批面）。
"""

from typing import Any, Dict, List

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 选择面增益需超过此值才参与污染判定（量不出来的微增益不当污染信号）。
MIN_SELECTION_GAIN = 0.01
#: 差值越界阈值：选择面涨到这个幅度而密封面没跟上 ⇒ suspect。
GAP_ALERT_THRESHOLD = 0.05

#: 阈值口径说明：0.05 ≈ 2.5×min_improvement（出厂 0.01）——比"有改善"严、
#: 比噪声带宽松；暂定值，有校准数据后另调（与 stationarity_drift 同款留档）。


def adaptationGap(*, selection_gain: float, sealed_gain: float) -> float:
    """逐轮污染差值：选择面增益 − 密封面增益（带符号）。"""
    return float(selection_gain) - float(sealed_gain)


def adaptationSuspect(*, selection_gain: float, sealed_gain: float) -> bool:
    """单轮污染判定：选择面真涨（超量）而密封面没跟上 ⇒ suspect。

    密封面独涨（真实改善）不是污染；两侧都不动不是污染；选择面微增益
    （低于 MIN_SELECTION_GAIN）不当污染信号。
    """
    if float(selection_gain) < MIN_SELECTION_GAIN:
        return False
    return adaptationGap(selection_gain=selection_gain,
                         sealed_gain=sealed_gain) > GAP_ALERT_THRESHOLD


class AdaptationMonitor:
    """逐轮污染曲线（纯读数；suspect 轮次点名）。"""

    def __init__(self) -> None:
        self._curve: List[Dict[str, Any]] = []

    def record(self, *, selection_gain: float, sealed_gain: float) -> None:
        gap = adaptationGap(selection_gain=selection_gain, sealed_gain=sealed_gain)
        suspect = adaptationSuspect(selection_gain=selection_gain,
                                    sealed_gain=sealed_gain)
        self._curve.append({
            "selection_gain": round(float(selection_gain), 6),
            "sealed_gain": round(float(sealed_gain), 6),
            "gap": round(gap, 6),
            "suspect": bool(suspect),
        })
        if suspect:
            logger.warning(
                "自适应污染嫌疑：选择面涨 %.3f 而密封面 %.3f（gap %.3f 越界）",
                selection_gain, sealed_gain, gap)

    def readout(self) -> Dict[str, Any]:
        suspect_rounds = [i for i, entry in enumerate(self._curve) if entry["suspect"]]
        return {
            "state": "measured" if self._curve else "insufficient_data",
            "curve": list(self._curve),
            "suspect_rounds": suspect_rounds,
            "thresholds": {
                "min_selection_gain": MIN_SELECTION_GAIN,
                "gap_alert": GAP_ALERT_THRESHOLD,
            },
        }
