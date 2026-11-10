# -*- coding: utf-8 -*-
"""迁移读数（C4，survey §10.2）——Eq6 的 τ 两轴起步。

两域各跑一次 yardstick 重放、报差值（论文 §7.5/8.6：迁移是不同域上的对齐
差）。两轴：任务族子集 ×（反馈源：golden vs 在线结局）——观测档形态＝把
同一结局窗口按时间分半当两域（旧域 vs 近域），golden 臂域待 B2 通道出真
结局后接入（诚实登记：家族轴/反馈源轴的完整形态随真臂机器挂载）。

守卫：**同域自比读数必须≈恒等**（防"迁移"读数是噪声）；任一域样本不足
报 insufficient_data（小样本上重放对齐是噪声，yardstick MIN_ENTRIES 同款）。
"""

from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.evolution.rsi.task_yardstick import replay_alignment_score

logger = get_logger(__name__)


def transferReadout(streams_a: Dict[str, List], streams_b: Dict[str, List], *,
                    label_a: str = "domain_a", label_b: str = "domain_b",
                    success_bonus: float = 0.1, failure_penalty: float = 0.05,
                    decay_rate: float = 0.01) -> Dict[str, Any]:
    """两域重放差值（确定性：同输入同读数）。

    domain 自比（streams_a is streams_b 同引用）时守卫恒等：差值必须 ≈0，
    否则重放机器失准（读数是噪声不是迁移）。
    """
    same_domain = streams_a is streams_b
    readout_a = replay_alignment_score(
        streams_a, success_bonus=success_bonus,
        failure_penalty=failure_penalty, decay_rate=decay_rate)
    readout_b = replay_alignment_score(
        streams_b, success_bonus=success_bonus,
        failure_penalty=failure_penalty, decay_rate=decay_rate)
    if readout_a.get("state") != "measured" or readout_b.get("state") != "measured":
        return {
            "state": "insufficient_data",
            "score": None,
            "detail": (f"{label_a}={readout_a.get('state')}({readout_a.get('entries', 0)} 条) / "
                       f"{label_b}={readout_b.get('state')}({readout_b.get('entries', 0)} 条)"
                       "——小样本上迁移读数是噪声"),
            "domains": {label_a: {"entries": readout_a.get("entries", 0)},
                        label_b: {"entries": readout_b.get("entries", 0)}},
        }
    score_a = float(readout_a["score"])
    score_b = float(readout_b["score"])
    delta = round(score_b - score_a, 6)
    if same_domain and abs(delta) > 1e-9:
        raise ValueError(
            f"同域自比差值 {delta} ≠ 0——重放机器失准（迁移读数是噪声），先修标尺")
    return {
        "state": "measured",
        "score": delta,
        "domains": {label_a: {"score": score_a, "entries": readout_a.get("entries")},
                    label_b: {"score": score_b, "entries": readout_b.get("entries")}},
        "detail": f"τ({label_b} − {label_a}) = {delta}（同参数重放，差值即域间对齐差）",
    }


def splitWindowDomains(streams: Dict[str, List]) -> Optional[Dict[str, Any]]:
    """观测档的两域切分：结局窗口按时间中点分半（旧域 vs 近域）。

    返回 {a: 旧域流, b: 近域流}；任一半不足 MIN_ENTRIES 由 transferReadout
    诚实报 insufficient_data。
    """
    entries: List[Any] = []
    for tool, items in (streams or {}).items():
        for item in items or []:
            entries.append((float(item[0]), tool, item[1]))
    entries.sort(key=lambda e: e[0])
    half = len(entries) // 2
    if half <= 0:
        return None
    older: Dict[str, List] = {}
    recent: Dict[str, List] = {}
    for ts, tool, ok in entries[:half]:
        older.setdefault(tool, []).append((ts, ok))
    for ts, tool, ok in entries[half:]:
        recent.setdefault(tool, []).append((ts, ok))
    return {"a": older, "b": recent}
