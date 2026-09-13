"""SOM（Set-of-Marks）视觉标注核心（CUA Phase 3 立项 R3-1）

无 UIA 树桌面（自绘 UI/游戏/远程像素流）的语义中间档：把截图标注成编号可交互
区域图 + id2xy 映射，VLM 看编号图说话，computer_click_mark 按编号解算坐标点击。

检测器可注入：默认确定性启发式（边缘 + 连通域，scipy.ndimage），真实 ONNX 图标
模型 / OCR 文本框（vision*.py 吸收件）就绪后替换 detector 即可，上层零改动。

编号稳定：md5(量化中心格 + label)（**不用内置 hash()**——PYTHONHASHSEED 逐进程
随机，会破坏跨轮/跨进程一致性）。
"""

from __future__ import annotations

import base64
import hashlib
import io
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 默认检测器超参
_MIN_AREA = 400
_MAX_MARKS = 60
_GRID = 8  # 编号稳定用的中心量化格（像素）


def stable_id(cx: int, cy: int, label: str, grid: int = _GRID) -> int:
    """确定性编号：同格 + 同 label → 同 id（跨调用/跨进程稳定）。"""
    key = f"{cx // grid},{cy // grid},{label}"
    return int(hashlib.md5(key.encode("utf-8")).hexdigest()[:8], 16) % 100000 + 1


def default_detector(png_bytes: bytes) -> List[Dict[str, Any]]:
    """确定性启发式检测器：边缘幅值阈值 → 膨胀连通 → 标号 → 外接框。

    真实检测器（YOLO/OCR）就绪后以 detector= 注入替换本函数。
    """
    import numpy as np
    from PIL import Image
    from scipy import ndimage

    img = Image.open(io.BytesIO(png_bytes)).convert("L")
    arr = np.asarray(img, dtype=np.float32)
    gy, gx = np.gradient(arr)
    mag = np.hypot(gx, gy)
    thr = max(20.0, float(np.percentile(mag, 98.0)))
    mask = mag >= thr
    mask = ndimage.binary_dilation(mask, iterations=3)
    labeled, _n = ndimage.label(mask)
    regions: List[Dict[str, Any]] = []
    for i, sl in enumerate(ndimage.find_objects(labeled), 1):
        if sl is None:
            continue
        y0, y1 = int(sl[0].start), int(sl[0].stop)
        x0, x1 = int(sl[1].start), int(sl[1].stop)
        if (y1 - y0) * (x1 - x0) < _MIN_AREA:
            continue
        regions.append({"bbox": (x0, y0, x1, y1), "label": f"region{i}"})
    regions.sort(key=lambda r: -((r["bbox"][2] - r["bbox"][0]) * (r["bbox"][3] - r["bbox"][1])))
    return regions[:_MAX_MARKS]


def mark_screenshot(
    png_bytes: bytes,
    detector: Optional[Callable[[bytes], List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """截图 → 编号标注图 + marks + id2xy。

    Returns:
        {annotated_png_b64, marks:[{id,bbox,center,label}], id2xy:{id:(x,y)}}
    """
    det = detector or default_detector
    try:
        regions = det(png_bytes) or []
    except Exception as e:  # noqa: BLE001 — 检测失败降级为无标注（不抛）
        logger.warning("SOM 检测器失败（返回空标注）: %s", e)
        regions = []

    from PIL import Image, ImageDraw

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    draw = ImageDraw.Draw(img)
    marks: List[Dict[str, Any]] = []
    id2xy: Dict[str, List[int]] = {}
    for r in regions:
        try:
            x0, y0, x1, y1 = (int(v) for v in r["bbox"])
        except (KeyError, ValueError, TypeError):
            continue
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        label = str(r.get("label", ""))
        mid = stable_id(cx, cy, label)
        draw.rectangle([x0, y0, x1, y1], outline=(255, 0, 0), width=2)
        draw.text((x0 + 2, y0 + 2), str(mid), fill=(255, 0, 0))
        marks.append({"id": mid, "bbox": [x0, y0, x1, y1], "center": [cx, cy], "label": label})
        id2xy[str(mid)] = [cx, cy]

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {
        "annotated_png_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
        "marks": marks,
        "id2xy": id2xy,
    }


__all__ = ["mark_screenshot", "default_detector", "stable_id"]
