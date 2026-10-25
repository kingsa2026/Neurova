#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""受保护子集分片后的覆盖率合判：把各片落的 `.coverage.*` 合并，再判一次阈值。

## 为什么必须有这一步

覆盖率门禁的语义是"**受保护子集整体**覆盖了多少"。分片把跑测切小了，
不该把门禁切碎——实测（本机、同一份 `requirements-ci.lock`）：

    分片 1 单独判：TOTAL 6771 语句 / 3429 未覆盖 = **49%**  → 单片 `--cov-fail-under=60` 假红
    整份子集合并：TOTAL 12940 / 1603 = **88%**            → 这才是门禁要判的那个数

于是分片跑测那一步只**攒数据**（`--cov-report=` 不出报告），阈值与合并口径都收在本文件。
阈值本身不在这里写死第二份：缺省从 CI 命令行同源的 `--fail-under` 传入，
`pyproject.toml` 的 `[tool.coverage.report]` 若写了一份 `fail_under` 会被
`tests/unit/ci/test_context_coverage_scope.py` 判红（阈值只允许一处定义）。

## 用法

    python scripts/ci/coverage_report.py --fail-under 60

数据文件由各片的 `--cov` 落在 `COVERAGE_DIR`（缺省 `data/coverage`，CI 上由作业
显式传给两处，避免各自猜路径）。合并用 `coverage combine` 的官方工具，
不自己实现"把 N 份 sqlite 加成一份"。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def coverageFiles(directory: Path) -> list:
    """目录下的覆盖率数据文件（`coverage combine` 认 `.coverage*`，但 `data/` 其它文件不许碰）。"""
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and p.name.startswith(".coverage"))


def combineCoverage(directory: Path, target: Path) -> None:
    """把 `directory` 下的分片数据合进 `target`（单文件），合并后清掉分片，避免下一批串味。

    `combine` 按「目标文件名 + `.` + `*`」在目录里找同名族：目标叫
    `.coverage.merged` 时它找的是 `.coverage.merged.*`，而各片落的是
    `.coverage.<host>.<pid>.<rand>`——族名对不上就是"合并成功但一份都没读到"。
    故这里把**逐片文件**显式交给它（`data_paths` 收文件也收目录），
    并以 `strict=True` 把"一片都没合到"变成响亮失败。
    """
    from coverage import Coverage

    shards = coverageFiles(directory)
    # `combine` 默认合并完就删掉输入片（`keep=False`），故这里不再自己清理一遍——
    # 清理与合并不是两件事，写两遍就会在"已经被删了"上抛 FileNotFoundError。
    merged = Coverage(data_file=str(target))
    merged.combine(data_paths=[str(p) for p in shards], strict=True)
    merged.save()


def reportCoverage(target: Path, failUnder: float) -> int:
    """出报告并判阈值：返回进程退出码（0 达标 / 1 未达标），未达标明细由 coverage 自己打印。"""
    from coverage import Coverage

    measured = Coverage(data_file=str(target))
    measured.load()
    percent = measured.report(file=sys.stdout)
    if percent is None:
        # 一份数据都没有＝没测量，这不是"通过"：静默放行正是教义第 2 条禁的形态
        print("覆盖率数据为空：没有合并到任何一片的数据，无法回答覆盖率", file=sys.stderr)
        return 1
    if percent + 1e-9 < failUnder:
        print(f"FAIL Required test coverage of {failUnder}% not reached. "
              f"Total coverage: {percent:.2f}%", file=sys.stderr)
        return 1
    print(f"Required test coverage of {failUnder}% reached. Total coverage: {percent:.2f}%")
    return 0


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="合并受保护子集的分片覆盖率后再判阈值")
    parser.add_argument("--data-dir", default="data/coverage",
                        help="各片 .coverage* 所在目录（与跑测步的 --cov 落点一致）")
    parser.add_argument("--merged", default="data/coverage/.coverage.merged",
                        help="合并后的数据文件落点")
    parser.add_argument("--fail-under", type=float, required=True,
                        help="覆盖率阈值（与 CI 命令行同源，不在本文件写死第二份）")
    args = parser.parse_args(argv)

    directory = Path(args.data_dir)
    if not directory.is_absolute():
        directory = REPO_ROOT / directory
    target = Path(args.merged)
    if not target.is_absolute():
        target = REPO_ROOT / target

    if not coverageFiles(directory):
        print(f"没有找到任何覆盖率数据（{directory}）：跑测那一批没把数据落下来，"
              "先查 --cov 与 --cov-report= 的落点，不要把它读成“通过”", file=sys.stderr)
        return 1

    combineCoverage(directory, target)
    exitCode = reportCoverage(target, args.fail_under)
    shutil.rmtree(directory, ignore_errors=True)
    return exitCode


if __name__ == "__main__":
    raise SystemExit(main())
