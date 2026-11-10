# -*- coding: utf-8 -*-
"""部署摊销读数（E5，survey §10.2）——C_total(N) = C_dev + N·c̄_task。

开发成本（RSI/文本进化侧的 cost vector tokens 总额，E1 单源）＋部署视野 N 个
任务的服务成本（c̄_task = serving 每次调用的实测均值，从 usage 记账链取数
——按发送者记账的那套，不新算）。无 serving 样本（calls=0）⇒ N·c̄ 报
unevidenced，不拿 0 冒充。
"""

from typing import Any, Dict, List

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def deploymentAmortization(dev_tokens: int, horizon: int, *,
                           usage_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """摊销读数：C_total(N)＝C_dev + N·c̄（c̄ 从 usage 快照实测）。

    usage_snapshot 形态＝`usage_accounting.snapshot()["total"]`
    （calls/prompt_tokens/completion_tokens/total_tokens...）。
    calls=0 ⇒ c̄ 无样本 ⇒ N·c̄ 段报 unevidenced（C_dev 段照实报）。
    """
    total = (usage_snapshot or {}).get("total") or {}
    calls = int(total.get("calls") or 0)
    total_tokens = int(total.get("total_tokens") or 0)
    c_bar: Any = None
    state = "measured"
    missing: List[str] = []
    if calls <= 0:
        c_bar = None
        state = "insufficient_data"
        missing.append("c_bar_task")
        serving_cost = None
    else:
        c_bar = total_tokens / calls
        serving_cost = c_bar * int(horizon)
    dev = int(max(0, dev_tokens))
    readout: Dict[str, Any] = {
        "state": state,
        "dev_tokens": dev,
        "horizon": int(horizon),
        "serving_samples": calls,
        "c_bar_task": (round(c_bar, 2) if c_bar is not None else None),
        "missing": missing,
        "basis": "usage_accounting.snapshot()（serving 真实事件，可回溯）"
                 if calls > 0 else "无 serving 样本",
    }
    if serving_cost is not None:
        readout["c_total_n"] = dev + round(serving_cost, 2)
        readout["serving_cost_n"] = round(serving_cost, 2)
    else:
        readout["c_total_n"] = None
        readout["serving_cost_n"] = None
    return readout
