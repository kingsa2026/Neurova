# -*- coding: utf-8 -*-
"""前端 bundle 体积预算的核心计量与判定（QwenPaw 对照批 C6）。

可单测的纯逻辑在此；`scripts/ci/bundle_budget.py` 只是薄壳。
"""

from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

#: 计入预算的产物后缀（JS/CSS 是体积主体； sourcemap/水印等不入账）
BUDGET_SUFFIXES = {".js", ".mjs", ".css"}


def collectBundleStats(dist_dir: str | Path) -> Dict[str, Any]:
    """扫构建产物目录：返回 {files: [{path, gzip_kb}], total_gzip_kb}。

    目录不存在 → {"files": [], "total_gzip_kb": 0, "missing": True}
    （调用方据此走「首跑标定」而不是误判为 0 体积通过）。
    """
    root = Path(dist_dir)
    if not root.is_dir():
        return {"files": [], "total_gzip_kb": 0.0, "missing": True}
    files: List[Dict[str, Any]] = []
    total = 0.0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in BUDGET_SUFFIXES:
            continue
        raw = path.read_bytes()
        gz = gzip.compress(raw)
        kb = round(len(gz) / 1024.0, 1)
        total += kb
        files.append({"path": str(path.relative_to(root)), "gzip_kb": kb})
    return {"files": files, "total_gzip_kb": round(total, 1), "missing": False}


def judgeBudget(total_gzip_kb: float, budget_kb: Optional[float]) -> Tuple[bool, str]:
    """判定：预算未标定（None）→ 通过并要求写回标定值；超预算 → 不通过。"""
    if budget_kb is None:
        return True, "calibrate"
    if float(total_gzip_kb) > float(budget_kb):
        return False, "over_budget"
    return True, "ok"
