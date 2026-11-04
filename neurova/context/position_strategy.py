"""上下文位置策略——lost-in-the-middle 缓解（候选 C5）。

检索证据条目在长上下文中段时最容易被模型忽略（lost in the middle）。
本模块把抽屉已排好序的证据序列按 **primacy-recency** 重新发牌：
最优置首、次优置尾、三优次首……最弱自然落在中段——同一批内容、
同样的取舍，只改「放哪里」。

排序事实源纪律（教义第 6 条）：**rank = 输入顺序**——上游
（`SemanticMatchDrawer.draw`：查询命中数 → priority → 插入序）已经是
唯一的排序裁决处，这里不造第二份打分；只做位置重排。

开关：`app_settings` advanced 分区 `lost_in_middle_enabled`（默认关——
行为变更显式开启，工单 015 口径）；env `NEUROVA_LOST_IN_MIDDLE`
显式 0/1 最优先。关闭时恒等映射（返回原列表，零行为漂移）。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def isLostInMiddleEnabled(path: Any = None) -> bool:
    """读开关：env 显式 0/1 最优先 > 治理/应用设置值 > 内置默认（关）。"""
    env = (os.environ.get("NEUROVA_LOST_IN_MIDDLE") or "").strip()
    if env == "1":
        return True
    if env == "0":
        return False
    try:
        from neurova.core.app_settings import load_app_settings

        advanced = load_app_settings(path).get("advanced") or {}
        return bool(advanced.get("lost_in_middle_enabled", False))
    except Exception:  # noqa: BLE001 - 读设置失败回落默认关
        return False


def applyLostInMiddleMitigation(items: List[Any]) -> List[Any]:
    """按输入序（=上游排序裁决）两端发牌：首/尾/次首/次尾……
    等价映射（≤2 条时重排恒等），任何异常回落原序（fail-open）。"""
    if not items or len(items) <= 2:
        return list(items)
    try:
        n = len(items)
        result: List[Any] = [None] * n
        lo, hi = 0, n - 1
        place_low = True  # True → 下一枚放前端（lo 指针）；False → 尾端（hi 指针）
        for item in items:  # 输入序即 rank 序
            if place_low:
                result[lo] = item
                lo += 1
            else:
                result[hi] = item
                hi -= 1
            place_low = not place_low
        return result
    except Exception:  # noqa: BLE001 - 缓解失败回落原序，不阻断装配
        logger.debug("lost-in-the-middle 发牌失败（回落原序）", exc_info=True)
        return list(items)


__all__ = ["applyLostInMiddleMitigation", "isLostInMiddleEnabled"]
