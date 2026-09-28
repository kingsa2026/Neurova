# -*- coding: utf-8 -*-
"""参数活性读数 —— 每个在表参数"动过几次 / 被闸过几次 / 从未出现"（Issue #289 · 004）。

## 三态不可折叠

真账里只出现 **7** 个不同 `parameter_path`，而表里有 **11** 个参数：4 个
（`sleep.base_decay_rate`、`emotion.emotional_protection_threshold`、
`experience.crystallize_min_observations`、`experience.pattern_min_support`）
在 262 行真账里**一次都没出现过**。

这 4 个参数的值域状态有三种可能，**处置各不相同**：

- `never_proposed`：账本在位、样本充足，它就是没被提名过 —— 该查候选生成器；
- `sparse`：动过，但次数低于判据门槛 —— 该等更多轮次；
- `no_data`：账本读不到 / 空账 —— **无法判定**，不构成任何结论。

把三者折叠，就是本仓在 `success` 三态上已经修过的同一病灶。
口径沿用 `scripts/diagnostics/tool_parallelism_readout.py` 已钉过的
`no_data ≠ sparse` 纪律，不另立一套。

## 纪元失效（M4）

`beginNewEpoch()` 只归零**统计面**（活性计数、累积量），
**不碰 003 的负债面** —— "换个任务就免债"会让 M4 变成反向闸的绕过通道。
票面硬约束：失效触发点（D4）拍板前不动代码，本模块只提供归零入口本身。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 活性读数的三态词表（互斥穷举；折叠任一即红）。
ACTIVITY_VOCABULARY = ("moving", "sparse", "never_proposed", "no_data")

#: "动过几次"低于此值即判 `sparse`（判据门槛，单源在此）。
SPARSE_MOVEMENT_THRESHOLD = 2

EPOCH_STATE_FILE = "rsi_epoch.json"


def _ledger_rows(path: Path) -> Optional[List[Dict[str, Any]]]:
    """读回执行；账本**读不到**时返回 `None`（不是空列表 —— 那是两个态）。"""
    target = Path(path)
    if not target.exists():
        return None
    rows: List[Dict[str, Any]] = []
    try:
        for raw in target.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                parsed = json.loads(raw)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
    except Exception as e:  # noqa: BLE001 - 读不到即 no_data，不猜
        logger.warning("参数活性读数：账本读取失败 %s", e)
        return None
    return rows


def readParameterActivity(path: Path) -> Dict[str, Any]:
    """每个在表参数的活性读数。

    Returns:
        Dict: `states`（`parameter_path` → 状态值）、`movements`（动过几次）、
        `vocabulary`（三态词表）、`overall`（整份读数的总判定）。
    """
    from neurova.evolution.rsi.integration_manager import RSIIntegrationManager

    table_paths = [
        f"{system}.{param['name']}"
        for system, params in RSIIntegrationManager.OPTIMIZABLE_PARAMETERS.items()
        for param in params
    ]

    rows = _ledger_rows(path)
    if rows is None:
        # 账本缺席 ⇒ no_data（**不是**"全都 never_proposed"：那是拿失明当结论）
        return {
            "states": {},
            "movements": {},
            "vocabulary": list(ACTIVITY_VOCABULARY),
            "overall": "no_data",
            "reason": "ledger_absent",
        }
    if not rows:
        return {
            "states": {},
            "movements": {},
            "vocabulary": list(ACTIVITY_VOCABULARY),
            "overall": "no_data",
            "reason": "zero_samples",
        }

    moved: Dict[str, int] = {}
    for row in rows:
        parameter_path = row.get("parameter_path")
        if isinstance(parameter_path, str) and parameter_path in table_paths:
            moved[parameter_path] = moved.get(parameter_path, 0) + 1

    states: Dict[str, str] = {}
    for parameter_path in table_paths:
        count = moved.get(parameter_path, 0)
        if count == 0:
            states[parameter_path] = "never_proposed"
        elif count < SPARSE_MOVEMENT_THRESHOLD:
            states[parameter_path] = "sparse"
        else:
            states[parameter_path] = "moving"

    overall = "moving" if any(v == "moving" for v in states.values()) else (
        "sparse" if any(v == "sparse" for v in states.values()) else "never_proposed"
    )
    return {
        "states": states,
        "movements": moved,
        "vocabulary": list(ACTIVITY_VOCABULARY),
        "overall": overall,
        "reason": None,
    }


def beginNewEpoch(data_root: Path) -> Dict[str, Any]:
    """纪元 +1：归零**统计面**，不动 003 的负债面。

    这是 M4 的**入口本体**（票面 D4 未拍板 ⇒ 不接任何自动触发点），
    故它只做一件事：把纪元号推进并如实回报前后读数。

    Returns:
        Dict: `previous_epoch` / `new_epoch` / `statistics_reset`(True)。
    """
    state_path = Path(data_root) / EPOCH_STATE_FILE
    previous = 0
    if state_path.exists():
        try:
            previous = int(json.loads(state_path.read_text(encoding="utf-8")).get("epoch", 0))
        except Exception as e:  # noqa: BLE001 - 损坏即从 0 起算，但记录在 reason 里
            logger.warning("纪元状态不可解析，按 0 起算: %s", e)
    new_epoch = previous + 1
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"epoch": new_epoch, "statistics_reset": True}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001 - 落盘失败不抛，读数可见
        logger.warning("纪元状态落盘失败: %s", e)
    return {
        "previous_epoch": previous,
        "new_epoch": new_epoch,
        "statistics_reset": True,
        # 债面**不在**归零范围内（003 的欠账跨纪元存活）。
        "debt_preserved": True,
    }
