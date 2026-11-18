# -*- coding: utf-8 -*-
"""覆盖率棘轮（QwenPaw 对照批 C6）。

语义：**只升不降**。合并后的实际覆盖率
- 低于棘轮记录值 → 门禁失败（退出 1）；
- 达到/超过记录值 → 通过，并把记录值上调为实际值（棘轮只咬合不倒转）。

绝对下限（--floor，默认 60）独立生效：即使棘轮文件被误删/清零，低于
下限依旧失败。记录文件 `scripts/ci/coverage_ratchet.json` 随棘轮上调
提交入库——演进史就是它的提交历史。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Tuple

# 脚本自举：仓库根进 sys.path（本脚本不在包内，cwd=仓库根直跑时
# scripts/ci 才是 sys.path[0]，neurova 包需显式可达）
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logger = logging.getLogger("coverage_ratchet")

DEFAULT_FLOOR = 60.0


def judgeAndUpdate(actual: float, recorded: float, floor: float) -> Tuple[bool, float]:
    """棘轮判定（纯函数）：返回 (是否通过, 新记录值)。

    - actual < recorded → 不通过（退步即红）；
    - actual < floor → 不通过（绝对下限独立生效）；
    - 否则通过，记录值上调为 max(actual, recorded)（只升不降）。
    """
    if actual < recorded or actual < floor:
        return False, recorded
    return True, max(actual, recorded)


def loadRatchet(path: Path) -> float:
    """读棘轮记录；文件缺失/损坏回落 DEFAULT_FLOOR（并如实告警）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = float(data.get("fail_under"))
        if value <= 0:
            raise ValueError(value)
        return value
    except FileNotFoundError:
        logger.warning("棘轮文件不存在，使用默认下限 %.0f：%s", DEFAULT_FLOOR, path)
        return DEFAULT_FLOOR
    except (ValueError, OSError) as e:
        logger.warning("棘轮文件不可读（%s），使用默认下限 %.0f：%s", e, DEFAULT_FLOOR, path)
        return DEFAULT_FLOOR


def saveRatchet(path: Path, value: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"fail_under": round(value, 2)}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="覆盖率棘轮门禁（只升不降）")
    parser.add_argument("--data-dir", default="data/coverage",
                        help="合并后的 coverage 数据目录（.coverage 文件所在）")
    parser.add_argument("--ratchet", default="scripts/ci/coverage_ratchet.json",
                        help="棘轮记录文件（JSON：{\"fail_under\": N}）")
    parser.add_argument("--floor", type=float, default=DEFAULT_FLOOR,
                        help="绝对下限（棘轮文件缺失/清零时的兜底）")
    args = parser.parse_args(argv)

    from neurova.ci.ci_ratchet_core import (
        combineCoverageFiles,
        judgeAndUpdate,
        measureCoveragePercent,
    )

    data_dir = Path(args.data_dir)
    target = data_dir / ".coverage.combined"
    combineCoverageFiles(data_dir, target)
    actual = measureCoveragePercent(target)
    if actual is None:
        logger.error("无法从 %s 计算覆盖率（无可测数据）", data_dir)
        return 1

    ratchet_path = Path(args.ratchet)
    recorded = loadRatchet(ratchet_path)
    passed, new_record = judgeAndUpdate(actual, recorded, args.floor)
    if not passed:
        logger.error(
            "覆盖率棘轮门禁失败：实际 %.2f%% < 记录 %.2f%%（或低于下限 %.0f%%）。"
            "覆盖率只升不降——修复覆盖率后再合并。",
            actual, recorded, args.floor)
        return 1
    if new_record > recorded:
        saveRatchet(ratchet_path, new_record)
        logger.info("棘轮上调：%.2f%% → %.2f%%（已写回 %s）", recorded, new_record, ratchet_path)
    logger.info("覆盖率棘轮通过：实际 %.2f%% ≥ 记录 %.2f%%", actual, new_record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
