# -*- coding: utf-8 -*-
"""前端 bundle 体积预算门（QwenPaw 对照批 C6）。

扫构建产物（JS/CSS，gzip 后 KB）对比 `NeurUI/bundle-budget.json` 的
`max_gzip_kb`：超预算退出 1；预算未标定（null）→ 写回实测值并通过
（首跑标定轮，此后只降不升的预算开始咬合）。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import sys as _sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from neurova.ci.bundle_budget_core import collectBundleStats, judgeBudget

logger = logging.getLogger("bundle_budget")

DEFAULT_BUDGET_FILE = "NeurUI/bundle-budget.json"


def loadBudget(path: Path) -> "tuple[Optional[float], dict]":
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        budget = data.get("max_gzip_kb")
        return (float(budget) if budget is not None else None), data
    except FileNotFoundError:
        logger.warning("预算文件不存在，进入首跑标定：%s", path)
        return None, {}
    except (ValueError, OSError) as e:
        logger.warning("预算文件不可读（%s），进入首跑标定：%s", e, path)
        return None, {}


def saveBudget(path: Path, total_gzip_kb: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"max_gzip_kb": total_gzip_kb,
                    "note": "JS/CSS gzip 合计上限（KB）；只降不升，超限即红"},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="前端 bundle 体积预算门")
    parser.add_argument("--dist", default="NeurUI/dist",
                        help="构建产物目录（vite build 输出）")
    parser.add_argument("--budget", default=DEFAULT_BUDGET_FILE,
                        help="预算文件（JSON：{\"max_gzip_kb\": N|null}）")
    args = parser.parse_args(argv)

    stats = collectBundleStats(args.dist)
    if stats.get("missing"):
        logger.error("构建产物目录不存在：%s（先 npm run build）", args.dist)
        return 1

    budget_path = Path(args.budget)
    budget, _ = loadBudget(budget_path)
    total = stats["total_gzip_kb"]
    ok, mode = judgeBudget(total, budget)

    if mode == "calibrate":
        saveBudget(budget_path, total)
        logger.info("bundle 预算首跑标定：total_gzip_kb=%s（已写回 %s，此后超限即红）",
                    total, budget_path)
        return 0
    if not ok:
        logger.error("bundle 预算超限：gzip 合计 %.1fKB > 预算 %.1fKB（只降不升）",
                     total, budget)
        return 1
    logger.info("bundle 预算通过：gzip 合计 %.1fKB ≤ 预算 %.1fKB", total, budget)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
