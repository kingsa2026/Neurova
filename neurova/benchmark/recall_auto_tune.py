# -*- coding: utf-8 -*-
"""D7 自动调参工具：在合成语料上扫描召回参数候选，择优写入记忆设置。

用法：
    from neurova.benchmark.recall_auto_tune import run_recall_auto_tune
    report = run_recall_auto_tune()                      # 默认五档，择优回写
    report = run_recall_auto_tune(floors=[0.5, 0.6, 0.7], apply=False)

- 语料为合成数据（临时目录），不触碰真实用户记忆；
- 评测走生产融合召回（NeurovaRecallEngine）；
- apply=True 时把最优门限写入记忆设置 recall.temp_channel_relevance_floor
  （运行期即时生效，无需重启）；最近一次报告落盘
  `<数据根>/memory_tuning/last_report.json`。
- 扫描期间会短暂改写进程内记忆设置的单例值（管理端手动触发场景可接受）。
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.benchmark.recall_quality import evaluate_state
from neurova.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_FLOORS = (0.4, 0.5, 0.6, 0.7, 0.8)
LAST_REPORT_FILE = "memory_tuning/last_report.json"


def _last_report_path() -> Path:
    from neurova.core.data_root import get_data_root

    return Path(get_data_root()) / LAST_REPORT_FILE


def load_last_report() -> Optional[Dict[str, Any]]:
    """读取最近一次自动调参报告（无则 None）。"""
    p = _last_report_path()
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("调参报告读取失败: %s", e)
        return None


def _save_last_report(report: Dict[str, Any]) -> None:
    p = _last_report_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def run_recall_auto_tune(
    floors: Optional[List[float]] = None,
    apply: bool = True,
    work_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """在合成语料上扫描温度通道相关性门限候选，按 MRR 择优。

    Args:
        floors: 候选门限列表（缺省 0.4~0.8 五档，自动去重夹取 [0,1]）。
        apply: True 时把最优门限写入记忆设置 recall.temp_channel_relevance_floor
            （运行期即时生效）。False = 只出报告不动配置。
        work_dir: 语料工作目录（缺省临时目录）。

    Returns:
        报告 dict：{baseline_without_temp, candidates:[{floor,mrr,hit5}],
        best:{floor,mrr}, applied}
    """
    from neurova.cognitive_layers.memory_layer.settings_config import (
        get_memory_settings,
    )

    raw = floors if floors else list(DEFAULT_FLOORS)
    # 钳制到 [0,1]（越界候选夹到边界：0=无门控全注入，1=仅近全等）
    candidates = sorted({min(max(float(f), 0.0), 1.0) for f in raw})
    if not candidates:
        candidates = [0.6]

    root = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="recall_tune_"))
    root.mkdir(parents=True, exist_ok=True)

    cfg = get_memory_settings()
    original_floor = cfg.get("recall.temp_channel_relevance_floor")

    baseline = evaluate_state(str(root / "base.db"), "C", drop_temperature_channel=True)
    report: Dict[str, Any] = {
        "baseline_without_temp": baseline["mrr"],
        "candidates": [],
        "best": None,
        "applied": False,
    }
    best_floor: Optional[float] = None
    best_mrr = -1.0
    for floor in candidates:
        cfg.update({"recall.temp_channel_relevance_floor": float(floor)})
        m = evaluate_state(str(root / f"floor_{floor:.2f}.db"), "C")
        entry = {"floor": float(floor), "mrr": m["mrr"], "hit5": m["hit5"]}
        report["candidates"].append(entry)
        if m["mrr"] > best_mrr:
            best_mrr = m["mrr"]
            best_floor = float(floor)

    if best_floor is None:
        best_floor = float(candidates[0])
    report["best"] = {"floor": best_floor, "mrr": best_mrr}

    if apply:
        cfg.update({"recall.temp_channel_relevance_floor": best_floor})
        cfg.save()
        report["applied"] = True
    else:
        cfg.update({"recall.temp_channel_relevance_floor": original_floor})

    try:
        _save_last_report(report)
    except Exception as e:
        logger.warning("调参报告落盘失败: %s", e)
    return report
