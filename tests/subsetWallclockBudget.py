# -*- coding: utf-8 -*-
"""受保护子集那一格的**墙钟预算**——唯一算式（两个守卫共用，不各答一次）。

## 为什么需要这个模块（不是"再加一把尺"）

同一件事「驱动受保护子集那一格的 `timeout` 该多宽」此前由**两个文件各答一次**：

- `tests/unit/ci/test_unit_tests_runner_has_headroom.py` 给**下界**（预算 ≥ 实测 × 1.1），
  实测取自**分片之前**的一次 SIGKILL 读数 `1333s`；
- `tests/unit/ci/test_protectedSubsetBudgetCoversItsRealCost.py` 给**上界**（≤ 45m 常量）。

两处都是"按一次实测钉出来的数"，而没有一处把**这一格现在到底串着跑几片**算进去。
于是分片落地那天，结构变了、预算没变——构建 `cnb-h8j-1k6s4v3g1#003` 实读：

    shard 1  3125 passed … in 1022.53s (0:17:02)   rc=0
    shard 2  2774 passed … in  810.70s (0:13:30)   rc=0
    shard 3  ……跑到 [ 87%] 时 stage 到点
    error:   任务超过最大执行时间而被强制关闭：45m0s

一片就吃掉 17 分钟，三片串行共用一道 45m 的墙——墙先到点，shard 3 连汇总行都没来得及打。
同一格的上一轮（`cnb-n6l-1k6s1qsq0`）三片共 37.4m 侥幸压线通过。
这不是"某片有测试红了"，是**预算装不下这一格真实的活**：活从"一场"变成了"几场之和"，
预算仍按"一场"定。

## 口径（涨落都由结构驱动，不按一次读数钉死）

    每片预算   = 单片最慢实测 × 抖动余量
    一格预算下界 = 片数 × 每片预算          ← 片数取自目录，串行就得乘
    一格预算上界 = 一格预算下界 × MAX_WINDOW_FACTOR

- 片数**不手抄**：事实源是 `scripts/ci/` 里有几个 `protected_tests.<N>.txt`
  （与 `.cnb.yml` 里那条 `ls … | sort -V`、以及 GitHub 侧矩阵同一口径）；
- 每片实测是唯一需要人维护的数（`PER_SHARD_MEASURED_SECONDS`），刷新时须写明取自哪个构建；
- 余量只给"同一片在不同 slot 上的抖动"，**不含**"再加一片"——加片由片数项自动吃下。

## 两个消费方（同一算式，两种排布）

- `unit-tests` 的 cnb stage：三片**串行**共用一道墙 ⇒ 比的是「片数 × 每片预算」；
- GitHub 的 job：矩阵里**每 job 一片** ⇒ 比的是「每片预算」。

同一份事实两处排布，算式只有一处（教义第 6 条）。

## 边界

- 本模块不预测跑测要几秒（那个值不在仓内）。它只保证：声明的墙**既装得下这一格
  按结构应有的活，又不至于宽到"真撞墙"与"被掐断"在日志里分不清**。
- 内存那一维不在此：内存 = cpus × 2GiB 由 `test_unit_tests_runner_has_headroom.py`
  的内存格管（cpus 是唯一代理量）。
"""

from __future__ import annotations

import io
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CI_DIR = PROJECT_ROOT / "scripts" / "ci"

#: 单片最慢实测（秒）。取构建 `cnb-h8j-1k6s4v3g1#003` 的 shard 1 读数
#: `3125 passed … in 1022.53s (0:17:02)`——分片落地后**真跑到并跑完**的最慢一片。
#: 此前仓内用的是分片之前那一整场的读数 `1333s`：它描述的是"一场"，与"一片"不是同一个量，
#: 拿它乘 1.1 当预算，等于始终只给一场的钱去跑三场。
PER_SHARD_MEASURED_SECONDS = 1022

#: 同一片在不同 slot 上的抖动余量（依赖缓存是否命中、共享 runner 的负载）。
SHARD_JITTER_HEADROOM = 1.25

#: 上界相对下界的倍数：越过去就不是预算而是窗口——"真撞墙"与"被资源掐断"从此分不清。
#: 1.5 的取法：下界本身已含 1.25 的抖动余量，再让一层 1.5 等于允许"比最坏情况还慢一半"，
#: 再宽就只是把撞墙延后一次，读的人仍分不清是墙到点还是资源到点。
MAX_WINDOW_FACTOR = 1.5

_TIMEOUT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([hms])\s*$")
_SUBSET_STAGE_HINT = "protected_tests"


def subsetShardFiles(directory: Path = CI_DIR) -> list:
    """分片清单文件名（按编号整数排序）。片号的事实源是目录，不是任何配置里的字面量。"""
    found = []
    for path in directory.glob("protected_tests.*.txt"):
        match = re.fullmatch(r"protected_tests\.(\d+)\.txt", path.name)
        if match:
            found.append((int(match.group(1)), path))
    return [path for _, path in sorted(found)]


def subsetShardCount(directory: Path = CI_DIR) -> int:
    """这一格会串着跑几片。"""
    return len(subsetShardFiles(directory))


def perShardBudgetSeconds() -> float:
    """单片预算：单片最慢实测 × 抖动余量（GitHub 矩阵里每个 job 的口径）。"""
    return PER_SHARD_MEASURED_SECONDS * SHARD_JITTER_HEADROOM


def requiredSubsetBudgetSeconds(directory: Path = CI_DIR) -> float:
    """一格预算下界：片数 × 单片预算（cnb 里三片串行共用一道墙的口径）。"""
    return subsetShardCount(directory) * perShardBudgetSeconds()


def maxSubsetBudgetSeconds(directory: Path = CI_DIR) -> float:
    """一格预算上界：越过去就不是预算而是窗口。"""
    return requiredSubsetBudgetSeconds(directory) * MAX_WINDOW_FACTOR


def parseTimeoutSeconds(value) -> float:
    """把 `timeout` 读成秒。读不懂就抛——读不懂不许当成"合规"。"""
    if value is None:
        return float("inf")
    match = _TIMEOUT_RE.match(str(value))
    assert match, f"timeout={value!r} 读不懂（形如 30m / 1h / 90s）"
    amount, unit = float(match.group(1)), match.group(2)
    return {"h": amount * 3600.0, "m": amount * 60.0, "s": amount}[unit]


def drivesProtectedSubset(stage) -> bool:
    """这一格是不是"把受保护子集塞进 pytest"——按结构特征认，不按流水线名字认。"""
    script = str((stage or {}).get("script") or "")
    return _SUBSET_STAGE_HINT in script and "pytest" in script


def driverStage(pipeline):
    for stage in (pipeline or {}).get("stages") or []:
        if isinstance(stage, dict) and drivesProtectedSubset(stage):
            return stage
    return None


def collectSubsetPipelines(document) -> list:
    """捞出「有 stage 驱动受保护子集」的流水线条目（含 YAML 锚点复用）。"""
    sink: list = []

    def walk(node):
        if isinstance(node, dict):
            stages = node.get("stages")
            if isinstance(stages, list) and any(
                isinstance(stage, dict) and drivesProtectedSubset(stage) for stage in stages
            ):
                sink.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(document)
    return sink


def loadCnbDocument(path: Path | None = None):
    import yaml  # 惰性：本模块被 import 时不该要求 yaml 在场

    return yaml.safe_load(io.open(path or (PROJECT_ROOT / ".cnb.yml"), encoding="utf-8").read())
