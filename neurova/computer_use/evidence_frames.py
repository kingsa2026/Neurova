# -*- coding: utf-8 -*-
"""动作证据帧（T5，reference_af 拆解卡）——前台点动作的前/后帧 + 动作点局部裁剪。

对齐 Agent-S BBoN narrator 的取证读数思路
（gui_agents/s3/bbon/behavior_narrator.py:36-168：动作前帧画标记、动作点局部
放大），本仓把它做成动作结果的**证据面**：开启档下，click/drag 采集动作前后
帧并按动作点裁 300×300 局部图，存入有界证据库（LRU 32）供审批/失败归因/面板
消费。

边界：
- **默认关**：env ``NEUROVA_CU_EVIDENCE_FRAMES`` 灰度（开启后每个点动作多两次
  截图，成本自知）；
- **像素不进 LLM 结果面**：工具结果只挂元数据（evidence_id/point/crop_size），
  与 computer_screenshot "base64 撑爆上下文" 纪律同源；
- **护栏拒绝的动作不产帧**（帧采集在车道持有窗口内进行，拒绝路径无帧）；
- 覆盖面：click/drag（有动作点的点动作）；key/paste 无坐标点，不产帧。
"""

from __future__ import annotations

import base64
import io
import os
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "EVIDENCE_FRAMES_ENV",
    "evidenceFramesEnabled",
    "buildEvidenceCrop",
    "buildEvidencePair",
    "storeEvidence",
    "getEvidence",
    "attachToResult",
]

#: 证据帧档开关（灰度；缺省关）。
EVIDENCE_FRAMES_ENV = "NEUROVA_CU_EVIDENCE_FRAMES"

#: 局部裁剪窗（正方形边长，像素）。
EVIDENCE_CROP_SIZE = 300

#: 证据库容量（LRU；超限淘汰最旧）。
_EVIDENCE_STORE_MAX = 32

_storeLock = threading.RLock()
_store: Dict[str, Dict[str, Any]] = {}


def evidenceFramesEnabled() -> bool:
    """证据帧档是否开启（env 显式值，缺省关）。"""
    raw = str(os.environ.get(EVIDENCE_FRAMES_ENV, "")).strip().lower()
    return raw in ("1", "true", "yes", "on")


def buildEvidenceCrop(
    pngBytes: Optional[bytes],
    point: Tuple[float, float],
    cropSize: int = EVIDENCE_CROP_SIZE,
    label: str = "",
) -> Optional[Dict[str, Any]]:
    """按动作点裁局部图（越界 clamp；画面小于裁剪窗按整幅取）。

    Returns:
        {"point": [x, y], "crop_box": [l, t, r, b], "crop_size": n,
         "png_b64": str, "label": str}；输入空/解码失败返回 None。
    """
    if not pngBytes:
        return None
    try:
        img = Image.open(io.BytesIO(pngBytes)).convert("RGB")
    except Exception as exc:  # noqa: BLE001 - 坏帧不阻断动作结果
        logger.debug("证据帧解码失败: %s", exc)
        return None
    screenW, screenH = img.size
    px, py = int(point[0]), int(point[1])
    half = max(1, int(cropSize)) // 2
    left = min(max(px - half, 0), max(0, screenW - int(cropSize)))
    top = min(max(py - half, 0), max(0, screenH - int(cropSize)))
    right = min(left + int(cropSize), screenW)
    bottom = min(top + int(cropSize), screenH)
    crop = img.crop((left, top, right, bottom))
    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    return {
        "point": [px, py],
        "crop_box": [left, top, right, bottom],
        "crop_size": int(cropSize),
        "png_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
        "label": label,
    }


def buildEvidencePair(
    beforeBytes: Optional[bytes],
    afterBytes: Optional[bytes],
    point: Tuple[float, float],
    cropSize: int = EVIDENCE_CROP_SIZE,
) -> Optional[Dict[str, Any]]:
    """动作前/后帧 → 证据对（任一侧裁剪失败仍保留另一侧）。"""
    before = buildEvidenceCrop(beforeBytes, point, cropSize, label="before")
    after = buildEvidenceCrop(afterBytes, point, cropSize, label="after")
    if before is None and after is None:
        return None
    return {
        "evidence_id": f"ev_{uuid.uuid4().hex[:12]}",
        "point": [int(point[0]), int(point[1])],
        "crop_size": int(cropSize),
        "before": before,
        "after": after,
    }


def storeEvidence(pair: Dict[str, Any]) -> str:
    """证据对入有界库（LRU 32），返回 evidence_id。"""
    with _storeLock:
        _store[pair["evidence_id"]] = pair
        while len(_store) > _EVIDENCE_STORE_MAX:
            _store.pop(next(iter(_store)))
    return pair["evidence_id"]


def getEvidence(evidenceId: str) -> Optional[Dict[str, Any]]:
    """按 id 取证据对（审批/失败归因/面板消费面）；不存在返回 None。"""
    with _storeLock:
        return _store.get(str(evidenceId or ""))


def attachToResult(result: Dict[str, Any], pair: Dict[str, Any]) -> None:
    """把证据**元数据**挂到动作结果（像素留证据库，不进 LLM 上下文）。"""
    result["evidence_frames"] = {
        "evidence_id": pair["evidence_id"],
        "point": list(pair["point"]),
        "crop_size": pair["crop_size"],
    }
