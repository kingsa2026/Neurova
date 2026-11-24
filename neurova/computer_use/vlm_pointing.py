# -*- coding: utf-8 -*-
"""VLM 指向接地（T2，reference_af 拆解卡）——第三档定位：UIA 树 → SOM → VLM 指向。

能力对齐 Agent-S 的 ``generate_coords``（gui_agents/s3/agents/grounding.py:230-246：
目标描述+截图 → 指向模型 → 坐标），并反向对齐其弱点——坐标解析多格式容错、
失败重问一次、失败结构化上报（不编坐标）。

边界：
- **默认关**：env ``NEUROVA_CU_VLM_POINTING``（1/true/yes/on 开启），灰度接入，
  防评测/生产成本意外（每次指向是一次 VLM 调用）。
- **纯逻辑无 IO**：vlmFn / uiaLookup 全部注入，本模块不发请求、不碰桌面；
  生产装配在 tool_executor 的 computer_point_at 处理器。
- **只读**：指向只产出坐标读数，不执行任何桌面动作；点击仍走既有点击链。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, Optional, Tuple

__all__ = [
    "VLM_POINTING_ENV",
    "vlmPointingEnabled",
    "parsePointReply",
    "vlmPointingLookup",
    "resolveTargetPoint",
]

#: VLM 指向档开关（灰度；缺省关）。
VLM_POINTING_ENV = "NEUROVA_CU_VLM_POINTING"


def vlmPointingEnabled() -> bool:
    """VLM 指向档是否开启（env 显式值，缺省关）。"""
    raw = str(os.environ.get(VLM_POINTING_ENV, "")).strip().lower()
    return raw in ("1", "true", "yes", "on")


def _clampPoint(x: int, y: int, width: int, height: int) -> Tuple[int, int]:
    return (max(0, min(width - 1, x)), max(0, min(height - 1, y)))


def parsePointReply(
    reply: Any, width: int, height: int
) -> Optional[Tuple[int, int]]:
    """从模型回复里容错解析一个坐标点（越界 clamp 到画面内；解析失败 None）。

    依次尝试：JSON 对象（含嵌在散文里的 {...}）→ ``x=.. y=..`` 键值形态 →
    前两个整数。任一形态命中即返回，全不中返回 None（调用方决定重问/降级）。
    """
    text = str(reply or "")
    for m in re.finditer(r"\{[^{}]*\}", text):
        try:
            obj = json.loads(m.group(0))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, dict):
            x, y = obj.get("x"), obj.get("y")
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                return _clampPoint(int(x), int(y), width, height)
    kv = re.search(r"x\s*[=:]\s*(-?\d+)[^\d-]+y\s*[=:]\s*(-?\d+)", text, re.IGNORECASE)
    if kv:
        return _clampPoint(int(kv.group(1)), int(kv.group(2)), width, height)
    nums = re.findall(r"-?\d+", text)
    if len(nums) >= 2:
        return _clampPoint(int(nums[0]), int(nums[1]), width, height)
    return None


def vlmPointingLookup(
    pngBytes: bytes,
    targetDescription: str,
    vlmFn: Callable[[str, bytes], str],
    width: int = 1920,
    height: int = 1080,
    maxAttempts: int = 2,
) -> Dict[str, Any]:
    """VLM 指向：构造 prompt → vlmFn(prompt, png_bytes) → 容错解析。

    解析失败重问一次（附纠正说明）。返回::

        {"state": "measured", "x": int, "y": int, "source": "vlm", "attempts": n}
        {"state": "grounding_failed", "reason": str, "attempts": n}

    失败不携带 x/y——不编坐标（教义：诚实形态）。
    """
    base_prompt = (
        "在截图中找到符合下述描述的目标，输出它的中心点坐标。\n"
        f"目标描述：{str(targetDescription or '').strip()}\n"
        f"画面尺寸：宽 {width}、高 {height}（坐标不得超出边界）。\n"
        "只输出一个坐标点，格式：x,y"
    )
    corrective = ""
    attempts = 0
    last_reply = ""
    for attempt in range(1, max(1, int(maxAttempts)) + 1):
        attempts = attempt
        reply = str(vlmFn(base_prompt + corrective, pngBytes) or "")
        last_reply = reply
        point = parsePointReply(reply, width, height)
        if point is not None:
            return {
                "state": "measured",
                "x": point[0],
                "y": point[1],
                "source": "vlm",
                "attempts": attempt,
            }
        corrective = "\n（上一次回复无法解析出坐标，请严格只输出一个坐标点，格式 x,y）"
    return {
        "state": "grounding_failed",
        "reason": f"{attempts} 次均未能从回复解析出坐标（末次回复截断：{last_reply[:80]!r}）",
        "attempts": attempts,
    }


def resolveTargetPoint(
    pngBytes: bytes,
    targetDescription: str,
    *,
    uiaLookup: Optional[Callable[[str], Optional[Tuple[int, int]]]] = None,
    vlmFn: Optional[Callable[[str, bytes], str]] = None,
    width: int = 1920,
    height: int = 1080,
) -> Dict[str, Any]:
    """三档定位链（UIA → VLM）：

    1. ``uiaLookup(描述)`` 命中（如 UIA 控件树按名称匹配到元素中心）→ 直接用，
       **不调 VLM**（确定性优先）；
    2. 未命中且 VLM 档开启 → :func:`vlmPointingLookup`；
    3. 未开启 / vlmFn 缺席 → ``{"state": "unavailable", "reason": ...}``
       （诚实缺席，不冒充坐标）。

    uiaLookup 抛异常按未命中处理（器械故障不阻断链路，降级到下一档）。
    """
    if uiaLookup is not None:
        try:
            hit = uiaLookup(str(targetDescription or ""))
        except Exception:  # noqa: BLE001 - UIA 器械故障降级到下一档
            hit = None
        if hit:
            x, y = int(hit[0]), int(hit[1])
            return {"state": "measured", "x": x, "y": y, "source": "uia"}
    if not vlmPointingEnabled():
        return {
            "state": "unavailable",
            "reason": "VLM 指向未启用（NEUROVA_CU_VLM_POINTING 关）",
        }
    if vlmFn is None:
        return {"state": "unavailable", "reason": "VLM 通道不可用（llm_client 缺席）"}
    return vlmPointingLookup(pngBytes, targetDescription, vlmFn, width, height)
