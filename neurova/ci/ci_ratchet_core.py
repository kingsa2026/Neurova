# -*- coding: utf-8 -*-
"""CI 门禁核心逻辑（对照批 C6）：覆盖率棘轮的判定与计量。

可单测的纯逻辑在此；`scripts/ci/coverage_ratchet.py` 只是薄壳。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple


def judgeAndUpdate(actual: float, recorded: float, floor: float) -> Tuple[bool, float]:
    """棘轮判定（纯函数）：返回 (是否通过, 新记录值)。

    - actual < recorded → 不通过（退步即红）；
    - actual < floor → 不通过（绝对下限独立生效）；
    - 否则通过，记录值上调为 max(actual, recorded)（只升不降）。
    """
    if actual < recorded or actual < floor:
        return False, recorded
    return True, max(actual, recorded)


def measureCoveragePercent(coverage_file: Path) -> Optional[float]:
    """从单个合并后的 coverage 数据文件读总覆盖率（%）；无数据返回 None。"""
    from coverage import Coverage
    from coverage.exceptions import NoDataError

    measured = Coverage(data_file=str(coverage_file))
    measured.load()
    try:
        return measured.report(file=None)
    except NoDataError:
        return None


def combineCoverageFiles(directory: Path, target: Path) -> None:
    """把 `directory` 下的分片 coverage 数据合进 `target` 单文件。

    与 `scripts/ci/coverage_report.py::combineCoverage` 同一语义（显式交出逐片
    文件、strict=True 让"一片都没合到"响亮失败）——脚本薄壳只做参数与退出码。
    """
    from coverage import Coverage

    shards = [p for p in Path(directory).glob(".coverage*") if p.is_file()]
    merged = Coverage(data_file=str(target))
    merged.combine(data_paths=[str(p) for p in shards], strict=True)
    merged.save()
