# -*- coding: utf-8 -*-
"""整场受保护子集的机时预算：声明值必须覆盖这活的最小成本，且不许吃满窗口。

## 现场（PR #364，`cnb-n45-1k5oultjs#003` —— 第三次同形态）

`unit-tests` 的 `protected subset with coverage gate` 跑到 **83%** 被平台强杀：

    tests/unit/skills/test_marketInstalledStateIsReadBack.py .........  [ 83%]
    Killed
    Finished, code: 137, duration: 29m 23s

`code: 137` 是 SIGKILL，发生在 **29m23s**——比这一格自己声明的 90m 少了整整一小时。
日志里一条失败墙都没有：不是"有测试红了"，是整段跑到点被掐断。同一份提交里
另外 8 条流水线全绿，所以也不是"这台机器慢"。

## 两个根因，同一个病：预算的两层数没对过表

**一、核数写小了（声明处生产，跑测处被报出来）**。`runner.cpus: 4` 是仓内九条流水线里
的最高档，但 `unit-tests` 是唯一一条要"装整份锁 + 串行跑 716 条清单 + 每格都带 `--cov`
插桩"的流水线。官方《语法手册》`runner.cpus` 一节写死：*内存 = CPU 核数 × 2 GiB*，
*未配置时可用核数由分配到的构建节点决定*；官方《构建节点》给出 `cnb:arch:amd64` 的
核数范围是 **1 ~ 64**、同档节点**默认 8 核**。⇒ `cpus: 4` 不是上限，是把这一格
按最小可用档压到了 8GiB，而进程被 SIGKILL 的典型形态正是内存压力下的 OOM kill。
声明不反映真实需求时，报出来的不会是"配置偏小"，只会是"Killed"。

**二、窗口被吃满（可观测值与预算同量级）**。跑到 83% 已用 29m23s ⇒ 整场按此速率约
35m20s。被终止的位置距该格声明的 90m 有 60m 富余，故可以排除"上限太窄"这一支：
在 90m 里被提前杀，剩下的解释只有资源（内存/核数）而非时间。反过来说，
35m 的活去申请 90m，也让"上限"失去了作为预算的意义——它在正常路径上永不生效。

## 不变量（只认结构，不认秒数）

1. **单个测试进程的声明预算（内存 = cpus × 2GiB）不得低于所有 stage 的 `timeout`
   所能容纳的活的下限**——一句话：`cpus` 不得低于 `HEAVY_SUBSET_CPU_FLOOR`。
   按**阶段结构**认（有没有 `scripts/ci/protected_tests.txt` 的清单驱动），不按
   流水线名字认：名字是标签，改名不该让判据失效。
2. **驱动受保护子集那一格的 `timeout` 不得超过 `SUBSET_STAGE_TIMEOUT_CAP_MIN`**。
   理由不是"跑得快"，是"上限要么是真的预算，要么就不是上限"：一个量级远超实测的
   上限，会让"下一轮真撞墙"与"这一轮被资源杀掉"在日志里长得一模一样。
   诚实形态是让**诚实超时先说话**（单格父墙 `pytest.mark.timeout(120)` 远小于它），
   而不是让平台在中间把进程 Killed 掉、留下一句无从追问的 `code: 137`。

两条都从活配置现读，不抄字面量；受治面自证：扫到的清单驱动流水线为 0 条即红。

## 边界（明写，不当已收口）

- 本闸不预测一场跑测要几秒（那个值不在仓内，且随机器抖动）。它只要求声明别把
  这一格压到最小可用档、且上限别与实测量级脱钩。
- 内存不是可直接声明的字段（`runner` 只有 tags/cpus/namespace），故本闸以 `cpus`
  为代理量与唯一事实源；两者的换算关系来自官方文档，不在仓内手抄第二份。
- 单格红/绿、嵌套子进程的墙钟关系由 `test_nestedPytestBudgetWallsAreOrdered.py`
  与 `test_ci_wallclock_assertion_ledger.py` 分治。
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CNB_YAML = PROJECT_ROOT / ".cnb.yml"
PROTECTED_LIST = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: 官方《构建节点》：`cnb:arch:amd64` 核数范围 1~64，同档节点默认 8 核。
#: 跑整份受保护子集（装整份锁 + 串行 716 条 + 每格 `--cov`）不许低于这个数。
HEAVY_SUBSET_CPU_FLOOR = 8
#: 驱动受保护子集那一格的 `timeout` 上限：与实测量级（≈35m）脱离即视为"不是预算"。
SUBSET_STAGE_TIMEOUT_CAP_MIN = 45
#: 受治面自证下限：本仓现读数 2 条（`main.pull_request` 与 `pull_request` 事件各自的
#: 同名流水线，同一份定义经 YAML 锚点复用）。低于此数意味着扫描口径写错。
MIN_SUBSET_PIPELINES = 1

_TIMEOUT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([hms])\s*$")


def _timeoutMinutes(value) -> float:
    """把 stage 的 `timeout` 解析成分钟。解析不了就抛——读不懂不许当成"合规"。"""
    if value is None:
        return float("inf")
    match = _TIMEOUT_RE.match(str(value))
    assert match, f"driver stage 的 timeout={value!r} 读不懂（形如 30m / 1h / 90s）"
    amount, unit = float(match.group(1)), match.group(2)
    return {"h": amount * 60.0, "m": amount, "s": amount / 60.0}[unit]


def _drivesProtectedSubset(stage) -> bool:
    """这一格是不是"把受保护子集塞进一次 pytest"。

    认的是**清单驱动**这个结构特征（`scripts/ci/protected_tests.txt`），不是流水线名字。
    """
    return PROTECTED_LIST.name in str(stage.get("script") or "") and "protected_tests" in str(
        stage.get("script") or ""
    )


def collectSubsetPipelines(document) -> list:
    """捞出「有 stage 驱动受保护子集」的流水线条目（含 YAML 锚点复用）。"""
    sink: list = []

    def walk(node):
        if isinstance(node, dict):
            stages = node.get("stages")
            if isinstance(stages, list) and any(
                isinstance(stage, dict) and _drivesProtectedSubset(stage) for stage in stages
            ):
                sink.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(document)
    return sink


def _driverStage(pipeline):
    for stage in pipeline.get("stages") or []:
        if isinstance(stage, dict) and _drivesProtectedSubset(stage):
            return stage
    return None


def _load():
    return yaml.safe_load(io.open(CNB_YAML, encoding="utf-8").read())


class TestWholeProtectedSubsetBudget:
    def test_scanFaceIsNotVacuous(self):
        pipelines = collectSubsetPipelines(_load())
        assert len(pipelines) >= MIN_SUBSET_PIPELINES, (
            f"只扫到 {len(pipelines)} 条驱动受保护子集的流水线，低于下限 {MIN_SUBSET_PIPELINES}"
            "——扫描口径写错了，此时「零违规」不成立"
        )

    def testDriverStageTimeoutIsABudgetNotAWindow(self):
        offenders = []
        for pipeline in collectSubsetPipelines(_load()):
            stage = _driverStage(pipeline)
            minutes = _timeoutMinutes(stage.get("timeout"))
            if minutes > SUBSET_STAGE_TIMEOUT_CAP_MIN:
                offenders.append(
                    f"{pipeline.get('name')!r}: timeout={stage.get('timeout')!r}"
                    f"（{minutes:g}m > {SUBSET_STAGE_TIMEOUT_CAP_MIN}m）"
                )
        assert not offenders, (
            f"驱动受保护子集那一格的 timeout 超出 {SUBSET_STAGE_TIMEOUT_CAP_MIN}m："
            + "；".join(offenders)
            + "。上限与实测量级（≈35m）脱离时，'真撞墙'与'被资源杀掉'在日志里长得一模一样。"
        )

    def testHeavySubsetPipelineDeclaresItsMemoryBudget(self):
        offenders = []
        for pipeline in collectSubsetPipelines(_load()):
            runner = pipeline.get("runner") or {}
            cpus = runner.get("cpus")
            if not isinstance(cpus, int) or cpus < HEAVY_SUBSET_CPU_FLOOR:
                # 内存不是可声明字段：内存 = cpus × 2GiB 是官方口径，cpus 是唯一代理量。
                offenders.append(
                    f"{pipeline.get('name')!r}: cpus={cpus!r}"
                    f"（内存 {(cpus or 0) * 2}GiB < {HEAVY_SUBSET_CPU_FLOOR * 2}GiB）"
                )
        assert not offenders, (
            f"跑整份受保护子集的流水线，cpus 低于 {HEAVY_SUBSET_CPU_FLOOR}"
            "（官方：内存 = cpus × 2GiB；同档节点默认 8 核，4 核是把它压到最小可用档的一半）："
            + "；".join(offenders)
        )
