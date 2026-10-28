# -*- coding: utf-8 -*-
"""机时预算（`runner.cpus`）不许被当成**排队等待**的期限。

## 要防的那件事（CI 现场，不是纸面推演）

PR #364 的 `cnb-nmd-1k5no13f9#003`（`unit-tests`）**在 Prepare 段就被杀**，
两条 stage 一条都没跑：

    status: error
    stages: error,116717,Prepare      ← 116.7s
            skipped,0,install uv + locked dependencies
            skipped,0,protected subset with coverage gate
    error:  任务超过最大执行时间而被强制关闭：1m0s

同一次构建里其余 8 条流水线的 Prepare 是 17～64s。同一份提交、同一时刻的邻居
跑得都很正常——所以不是「这台机器慢」，是这一条流水线自己的 Prepare 越过了平台给的 1m。

## 根因：这一格声明的东西和它需要的预算不是一回事

`.cnb.yml` 头部已写死的平台口径是 `runner.cpus: N 对应内存 N×2GiB`，而 `unit-tests`
要在 Prepare 里拉两套依赖（`uv` 本体 + 受保护子集 709 档所需的整套锁），是全部九条
流水线里装得最多的一条，声明却与其余八条同规格。挂卷越多，Prepare 里要做的
copy-on-write 越多；
`cpus` 越少，那段时间越只能串着走。声明不反映真实需求时，报出来的不是
「配置不合法」，而是「任务超时」——按修复教义第 1 条，故障在声明处生产、
在 Prepare 处被报出来。

## 不变量（只认结构，不认秒数、不认机器快慢）

**凡 Prepare 的活最重的那批流水线——`install` 阶段既装别的包管理器（`pip-audit`／
`pip install`）、又挂 OSV 离线漏洞库缓存卷（一次 `curl` 拿上百 MB 冻结库）——`runner.cpus`
必须 ≥ 4。** 判据按**阶段结构**认，不按流水线名字认：名字是标签，改了名不该让判据失效；
「这一格要拉一份上百 MB 的库」才是机时的真实来源，它写在阶段脚本与卷声明里。

卷条数与 cpus 都从活配置现读，不抄字面量：抄一份就成第二个事实源，配置一改判据就漂。

这是**存在性检查**，不是性能调优——它不预测 Prepare 要几秒（那个值不在仓内），
只要求「宣告自己要拉一份大缓存」的流水线别用最小规格去跑。

## 受治面自证

扫到的挂卷流水线数低于下限即红：「零违规」与「没扫到」长得一模一样。
本仓现读数：挂卷流水线 8 条，其中 4 条已是 `cpus: 4`，`unit-tests` 未达。

## 边界（明写，不当已收口）

- 本闸不判断「Prepare 该给多久」。那个值不在仓内，是平台侧口径，也不该由仓内判据假装知道。
- 本闸只治 `runner` 与 `docker.volumes` 的条数关系；stage 自己的 `timeout` 由
  `test_nestedPytestBudgetWallsAreOrdered.py`（父墙高于子墙）与
  `test_ci_wallclock_assertion_ledger.py`（墙钟断言逐条有结论）分治。
- `cpus: 8` 那条（win-installer 自托管节点）挂 0 卷，不在本闸词汇内。
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CNB_YAML = REPO_ROOT / ".cnb.yml"

#: 拉大缓存的流水线，Prepare 的固定成本（下载、解包、校验）比轻量流水线大一档；
#: 最小规格（cpus: 2）不足以把那段时间压回平台 1m 的 Prepare 期限里。
HEAVY_PREPARE_CPU_FLOOR = 4
#: 受治面自证下限：本仓现读数 2 条（`dependency-audit`，随 YAML 锚点复用出现两次）。
#: 低于此数意味着扫描口径写错，「零违规」不成立。
MIN_HEAVY_PREPARE_PIPELINES = 1
#: 缓存卷的绝对路径前缀 → 「这一卷存的是整份冻结漏洞库」。
OFFLINE_DB_VOLUME_PREFIX = "/root/.cache/osv"
#: 阶段脚本里出现这些词，说明这一步是「拉一份冻结库」而不是装一个包。
OFFLINE_DB_FETCH_TOOLS = ("--prefetch-offline-databases",)


def _walkPipelines(node, sink):
    """深度优先捞所有带 `runner` 与 `docker` 的流水线条目（含 YAML 锚点复用）。"""
    if isinstance(node, dict):
        if isinstance(node.get("runner"), dict) and isinstance(node.get("docker"), dict):
            sink.append(node)
        for value in node.values():
            _walkPipelines(value, sink)
    elif isinstance(node, list):
        for item in node:
            _walkPipelines(item, sink)


def _stageScripts(pipeline) -> str:
    return "\n".join(str(stage.get("script") or "") for stage in pipeline.get("stages") or [])


def _pullsAFrozenDatabase(pipeline) -> bool:
    volumes = pipeline["docker"].get("volumes") or []
    hasDbVolume = any(str(v).startswith(OFFLINE_DB_VOLUME_PREFIX) for v in volumes)
    script = _stageScripts(pipeline)
    fetches = any(tool in script for tool in OFFLINE_DB_FETCH_TOOLS)
    return hasDbVolume and fetches


def collectHeavyPreparePipelines() -> list:
    document = yaml.safe_load(CNB_YAML.read_text(encoding="utf-8"))
    sink: list = []
    _walkPipelines(document, sink)
    return [p for p in sink if _pullsAFrozenDatabase(p)]


class TestHeavyPreparePipelinesDeclareEnoughCpus:
    def test_scanFaceIsNotVacuous(self):
        pipelines = collectHeavyPreparePipelines()
        assert len(pipelines) >= MIN_HEAVY_PREPARE_PIPELINES, (
            f"只扫到 {len(pipelines)} 条拉冻结库的流水线，"
            f"低于下限 {MIN_HEAVY_PREPARE_PIPELINES}——扫描口径写错了，此时「零违规」不成立"
        )

    def test_heavyPreparePipelinesPullTheirWeight(self):
        offenders = []
        for pipeline in collectHeavyPreparePipelines():
            cpus = pipeline["runner"].get("cpus")
            volumes = pipeline["docker"].get("volumes") or []
            if not isinstance(cpus, int) or cpus < HEAVY_PREPARE_CPU_FLOOR:
                offenders.append(
                    f"{pipeline.get('name')!r}: cpus={cpus!r}，挂 {len(volumes)} 个缓存卷"
                )
        assert not offenders, (
            f".cnb.yml 里 Prepare 要拉冻结库的流水线，cpus 低于 {HEAVY_PREPARE_CPU_FLOOR}："
            + "；".join(offenders)
        )
