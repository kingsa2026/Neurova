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
2. **驱动受保护子集那一格的 `timeout` 必须落在预算区间里**：既 ≥ 「片数 × 每片预算」
   （装得下这一格按结构应有的活），又 ≤ 该值的 `MAX_WINDOW_FACTOR` 倍
   （越过去就不是预算而是窗口，"真撞墙"与"被资源掐断"从此分不清）。
   诚实形态是让**诚实超时先说话**（单格父墙 `pytest.mark.timeout(120)` 远小于它），
   而不是让平台在中间把进程 Killed 掉、留下一句无从追问的 `code: 137`。

第 2 条此前是**上半截**：只钉了上界（`SUBSET_STAGE_TIMEOUT_CAP_MIN = 45`），没有下界，
且那个 45m 是分片**之前**按"一场"的实测定的。分片落地后活变成"三场串行"，而预算没跟着
变——构建 `cnb-h8j-1k6s4v3g1#003` 实读 shard 1 `1022s`、shard 2 `811s`、shard 3 跑到 87%
时撞 `45m0s` 被强杀。上一轮（`cnb-n6l-1k6s1qsq0`）三片共 37.4m 侥幸压线。

故口径收口到 `tests/subsetWallclockBudget.py` **一处算式**（教义第 6 条）：
片数从目录现读、每片预算 = 单片最慢实测 × 抖动余量、上界 = 下界 × 窗口倍数。
本档判"cnb 那条串行腿"（三片共用一道墙），GitHub 矩阵每 job 一片由
`test_unit_tests_runner_has_headroom.py` 按同一算式的单片口径判——同一事实两种排布，
算式只有一处。

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

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests import subsetWallclockBudget as budget  # noqa: E402  墙钟预算的唯一算式

CNB_YAML = PROJECT_ROOT / ".cnb.yml"

#: 官方《构建节点》：`cnb:arch:amd64` 核数范围 1~64，同档节点默认 8 核。
#: 跑整份受保护子集（装整份锁 + 串行 716 条 + 每格 `--cov`）不许低于这个数。
HEAVY_SUBSET_CPU_FLOOR = 8
#: 受治面自证下限：本仓现读数 2 条（`main.pull_request` 与 `pull_request` 事件各自的
#: 同名流水线，同一份定义经 YAML 锚点复用）。低于此数意味着扫描口径写错。
MIN_SUBSET_PIPELINES = 1


def _load():
    return budget.loadCnbDocument(CNB_YAML)


class TestWholeProtectedSubsetBudget:
    def test_scanFaceIsNotVacuous(self):
        pipelines = budget.collectSubsetPipelines(_load())
        assert len(pipelines) >= MIN_SUBSET_PIPELINES, (
            f"只扫到 {len(pipelines)} 条驱动受保护子集的流水线，低于下限 {MIN_SUBSET_PIPELINES}"
            "——扫描口径写错了，此时「零违规」不成立"
        )

    def testDriverStageBudgetCoversTheShardsItRunsSerially(self):
        """下界：三片串行共用一道墙，墙必须装得下「片数 × 每片预算」。

        构建 `cnb-h8j-1k6s4v3g1#003` 的红就是这一半缺失造成的：
        shard 1 `1022s` + shard 2 `811s` 已 30.5m，shard 3 跑到 87% 时撞 `45m0s` 被强杀。
        此前这一档只有上界（≤ 45m），没有任何一处回答"45m 装不装得下三片串行"。
        """
        required = budget.requiredSubsetBudgetSeconds()
        offenders = []
        for pipeline in budget.collectSubsetPipelines(_load()):
            stage = budget.driverStage(pipeline)
            seconds = budget.parseTimeoutSeconds(stage.get("timeout"))
            if seconds < required:
                offenders.append(
                    f"{pipeline.get('name')!r}: timeout={stage.get('timeout')!r}"
                    f"（{seconds:.0f}s < {required:.0f}s）"
                )
        assert not offenders, (
            f"驱动受保护子集那一格的墙装不下它自己：现读 "
            f"{budget.subsetShardCount()} 片串行 × 每片 {budget.perShardBudgetSeconds():.0f}s "
            f"= {required:.0f}s（{required / 60:.1f}m），"
            + "；".join(offenders)
            + "。片数从 `scripts/ci/protected_tests.<N>.txt` 现读、每片预算取单片最慢实测"
            "（`tests/subsetWallclockBudget.py` 一处算式）——加片或变慢都会让这条当场响，"
            "不必等到 CI 撞墙才有人回头找。"
        )

    def testDriverStageTimeoutIsABudgetNotAWindow(self):
        """上界：越过去就不是预算而是窗口——"真撞墙"与"被掐断"从此分不清。"""
        ceiling = budget.maxSubsetBudgetSeconds()
        offenders = []
        for pipeline in budget.collectSubsetPipelines(_load()):
            stage = budget.driverStage(pipeline)
            seconds = budget.parseTimeoutSeconds(stage.get("timeout"))
            if seconds > ceiling:
                offenders.append(
                    f"{pipeline.get('name')!r}: timeout={stage.get('timeout')!r}"
                    f"（{seconds:.0f}s > {ceiling:.0f}s）"
                )
        assert not offenders, (
            f"驱动受保护子集那一格的 timeout 超出预算上界 {ceiling / 60:.1f}m："
            + "；".join(offenders)
            + "。上限与「片数 × 每片预算」脱离时，'真撞墙'与'被资源杀掉'在日志里长得一模一样。"
        )

    def testHeavySubsetPipelineDeclaresItsMemoryBudget(self):
        offenders = []
        for pipeline in budget.collectSubsetPipelines(_load()):
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


class TestBudgetArithmeticFollowsStructure:
    """算式本身的三条自证（判据不许是对某份固件的快照）。"""

    def testShardCountComesFromTheDirectory(self, tmp_path):
        """片数从目录现读：加一片预算就自动涨，不需要人去改任何常量。"""
        for name in ("protected_tests.1.txt", "protected_tests.2.txt"):
            (tmp_path / name).write_text("x\n", encoding="utf-8")
        assert budget.subsetShardCount(tmp_path) == 2
        assert budget.requiredSubsetBudgetSeconds(tmp_path) == pytest.approx(
            2 * budget.perShardBudgetSeconds())

    def testRequiredBudgetIsStrictlyBelowTheWindowCeiling(self):
        """下界必须严格低于上界，否则这一档自相矛盾（任何取值都过不了）。"""
        assert budget.requiredSubsetBudgetSeconds() < budget.maxSubsetBudgetSeconds()

    def testDetectorIsNotVacuous(self):
        """反证：把 timeout 写成 5m 时，下界那格必须咬得住。"""
        too_tight = budget.parseTimeoutSeconds("5m")
        assert too_tight < budget.requiredSubsetBudgetSeconds(), (
            "5m 竟被判成装得下三片串行——算式写坏了，下界格会恒绿"
        )
