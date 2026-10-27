# -*- coding: utf-8 -*-
"""受保护子集那一腿必须真的装得下它自己：内存与墙钟都要有可作答的余量。

## 触发实例（不是假设）

构建 `cnb-rja-1k5pv9gbl#003`（PR #367，2026-10-25）：受保护子集跑到 **82%** 时
pytest 进程被 SIGKILL，`Finished, code: 137, duration: 22m 13s`。日志里一条失败墙
都没有——这不是"有测试红了"，是宿主内存超限把进程掐掉。

那一刻的配置是 `runner.cpus: 4`（= 8GiB）而 `protected_tests.txt` 现算 716 条目。
同一道墙此前还有一次记录在案的撞法：30m 墙钟被平台强杀（台账 §6-4xx 那段注释）。
两次的形状相同：**判据没变，容器装不下它自己**。

## 为什么这两条得是常驻判据

内存与墙钟都不是"跑一次看结果"能兜住的：

- 一次 137 可以被顺手重跑过去（换个 slot 就差分毫），于是没人会去改配置；
- 墙钟同理，`timeout: 90m` 是通过一次撞墙抬上来的，抬它的理由只写在注释里，
  下一次有人加十个重量级测试档进子集，没有任何东西会响。

故本档把「容器资源 ≥ 子集体量」与「墙钟 ≥ 整场实测」两条写成比值断言，
读数取两处活配置（`.cnb.yml` 的 `runner.cpus`、受保护子集真条目数），
不抄数。

## 这条判据不证什么

它不证"抬到 8 核 16GiB 就一定能跑完"，也不重复
`tests/unit/ci/test_ci_wallclock_assertion_ledger.py` 管的"断言里不许绑死秒数"。
它证的是**配置侧不欠账**：需求与供给之间有明确倍数关系，且这个倍数被钉住。
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CNB = PROJECT_ROOT / ".cnb.yml"
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: 平台口径（官方《自定义云原生开发流水线》）：内存 GiB = cpus × 2。
#: 写在这里是因为它是**平台契约**，不是本仓的选择——本仓能选的是 cpus 取几。
GIB_PER_CPU = 2

#: 每个测试档在容器里的一份私有足迹（导入 + 夹具 + 数据根）。
#: 0.012GiB = 12.3MiB：实测 8GiB 在 716 档跑到 82% 时 OOM，而那份足迹还要叠加
#: numpy/onnxruntime 这类常驻共享页（一次性占用，不随档数线性增长，见 `BASE_GIB`）。
GIB_PER_ENTRY = 0.012

#: 解释器 + 依赖 + coverage 插桩的常驻底噪。
BASE_GIB = 1.5

#: 内存余量倍数：低于它就算"刚好装下"，而"刚好装下"在共享 runner 上等于会 OOM。
MEMORY_HEADROOM = 1.25

#: 整场墙钟的最新实测（秒）。取构建 `cnb-rja-1k5pv9gbl#003` 被 SIGKILL 时的读数
#: ——那一场还没跑完，故它是**下界**，判据只拿它算"至少需要多少"。
MEASURED_WALLCLOCK_SECONDS = 1333


def _pipelines() -> dict:
    data = yaml.safe_load(io.open(CNB, encoding="utf-8").read())
    return {
        pipe["name"]: pipe
        for pipe in data["main"]["push"]
        if isinstance(pipe, dict) and pipe.get("name")
    }


def _protectedSubsetEntries(path: Path | None = None) -> int:
    """**单进程**要一次装下的条目数。

    分片之后这个数不再是索引总量：每个片各起一个进程，峰值随片内条目数走。
    故取**最重那一片**——它是唯一会去撞 137 的那一场，拿索引总量算会把需求放大三倍
    （那是另一个方向的失真：读数虚高，改配置的理由也跟着虚高）。
    片号的事实源是目录里有哪几片（与 `.cnb.yml` 的通配派生同一口径，不手抄 `1 2 3`）。
    """
    if path is not None:
        return _countEntries(path)
    shards = sorted((PROJECT_ROOT / "scripts" / "ci").glob("protected_tests.*.txt"))
    shards = [s for s in shards if re.fullmatch(r"protected_tests\.\d+\.txt", s.name)]
    # 面自证（`tests/unit/ci/test_scanCriterionMustProveItsOwnSurfaceRatchet.py` 的面自证棘轮）：
    # 这一次枚举就是本档的扫描面，零片时下面那句 `max(...)` 会空序列报错、而不是"零命中恒绿"，
    # 但读数本身要被**断言**出来——根被改窄时「没命中」与「没扫到」必须长得不一样。
    assert len(shards) >= 1, f"scripts/ci/ 下一个分片清单都没有（现读 {len(shards)}）——受保护子集没在跑"
    heaviest = max(_countEntries(s) for s in shards)
    assert heaviest > 0, "最重那一片现读 0 条目——清单被清空或读法变了"
    return heaviest


def _countEntries(path: Path) -> int:
    """清单的真条目数（跳过注释与空行，与 .cnb.yml 里的 grep 同口径）。"""
    lines = io.open(path, encoding="utf-8").read().splitlines()
    return len([line for line in lines if line.strip() and not line.strip().startswith("#")])


def _isSubsetStage(stage: dict) -> bool:
    """是不是跑受保护子集的那一段。

    分片之后命令里认的是**分片通配**（`protected_tests.<N>.txt`，作业按目录派生），
    不再是单一清单文件名；索引名仍收，读法一处（`scripts/ci/protected_tests` 前缀）。
    """
    script = str(stage.get("script", ""))
    return "protected_tests" in script and "pytest" in script


def _unitTestPipeline(pipelines: dict | None = None) -> dict:
    found = [name for name in (pipelines or _pipelines()) if name.startswith("unit-tests")]
    assert len(found) == 1, f"受保护子集应有且只有一条流水线，实际：{found}"
    return (pipelines or _pipelines())[found[0]]


def _cpus(pipe: dict) -> int:
    value = (pipe.get("runner") or {}).get("cpus")
    assert isinstance(value, int) and value > 0, (
        "unit-tests 未声明 `runner.cpus`——容器有多大无从作答，落到平台默认值。"
    )
    return value


def _coverageStageTimeoutSeconds(pipe: dict) -> int:
    """受保护子集那一段的 `timeout`（秒）。`90m` / `5400s` 两种写法都收。"""
    for stage in pipe.get("stages") or []:
        if not isinstance(stage, dict) or not _isSubsetStage(stage):
            continue
        raw = str(stage.get("timeout", "")).strip()
        match = re.fullmatch(r"(\d+)([smh])", raw)
        assert match, (
            f"受保护子集那一段的 timeout 读不出秒数：{raw!r}——"
            "墙钟余量判据无从作答；请写成 `<n>m` 或 `<n>s`。"
        )
        scale = {"s": 1, "m": 60, "h": 3600}[match.group(2)]
        return int(match.group(1)) * scale
    raise AssertionError("unit-tests 里找不到跑受保护子集的那一段（protected_tests）")


class TestUnitTestLegContainerFitsItsOwnSubset:
    def testContainerMemoryCoversTheSubsetWithHeadroom(self):
        pipe = _unitTestPipeline()
        memory = _cpus(pipe) * GIB_PER_CPU
        entries = _protectedSubsetEntries()
        needed = (BASE_GIB + entries * GIB_PER_ENTRY) * MEMORY_HEADROOM
        assert memory >= needed, (
            f"受保护子集 {entries} 档需要约 {needed:.1f}GiB（含 {MEMORY_HEADROOM}× 余量），"
            f"而 runner.cpus={_cpus(pipe)} 只给到 {memory}GiB。\n"
            "构建 cnb-rja-1k5pv9gbl#003 就是这么被 SIGKILL 的：跑到 82% "
            "`code: 137`，日志里一条失败墙都没有——那不是红，是容器装不下自己。\n"
            f"若要维持 {memory}GiB，子集条目数须 ≲ "
            f"{int((memory / MEMORY_HEADROOM - BASE_GIB) / GIB_PER_ENTRY)} 档；"
            "要么抬 cpus，要么把重量级档移出子集——别靠重跑碰运气。"
        )

    def testDetectorIsNotVacuous(self):
        """反向控制：把供给压到需求以下时必须咬得住（判定不是对某份固件的快照）。

        反向控制的**形状要跟着判据的口径走**：分片之后单进程要装的是「最重那一片」
        （238 档），需求约 5.7GiB——8GiB 如今确实够用，那是分片修好的结果，不是门槛软化。
        仍拿「4 核 8GiB 必须红」当反证，等于钉住了被修掉的那一版配置。
        故这里按需求现算一个**确实不够**的供给（需求的 0.8），它必须被判红；
        再证 8 核 16GiB 被判绿——否则判据是「全红」，同样没有说话。
        """
        entries = _protectedSubsetEntries()
        needed = (BASE_GIB + entries * GIB_PER_ENTRY) * MEMORY_HEADROOM
        undersupplied = int(needed * 0.8 / GIB_PER_CPU)
        assert undersupplied * GIB_PER_CPU < needed, "反向控制自证失败：算出来的供给并不欠账"
        assert 8 * GIB_PER_CPU >= needed, (
            f"现行 8 核 16GiB 已装不下最重那一片（需 {needed:.1f}GiB）——"
            "这才是要人看的那一格：要么抬 cpus，要么把重量级档移出子集"
        )


class TestUnitTestLegWallclockCoversTheWholeRun:
    def testStageTimeoutExceedsTheMeasuredRun(self):
        pipe = _unitTestPipeline()
        budget = _coverageStageTimeoutSeconds(pipe)
        assert budget >= MEASURED_WALLCLOCK_SECONDS * 3, (
            f"受保护子集那一段给 {budget}s，而最新实测单场已 {MEASURED_WALLCLOCK_SECONDS}s"
            f"（构建 cnb-rja-1k5pv9gbl#003，被 SIGKILL 时读数，仍是下界）——"
            "余量不足 3×。墙钟撞墙的日志形态与失败墙一模一样（整段被掐断、"
            "一条红都没有），故这条必须留足，别让'超时'冒充'有测试红了'。"
        )

    def testDetectorIsNotVacuous(self, tmp_path):
        """反向控制：把 timeout 写成 30m 时必须读得出是个不足的数。"""
        pipes = _pipelines()
        name = [n for n in pipes if n.startswith("unit-tests")][0]
        pipe = pipes[name]
        stages = [
            dict(stage, timeout="30m") if _isSubsetStage(stage) else stage
            for stage in pipe["stages"]
        ]
        assert _coverageStageTimeoutSeconds(dict(pipe, stages=stages)) == 1800
