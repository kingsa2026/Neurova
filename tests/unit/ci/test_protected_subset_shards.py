# -*- coding: utf-8 -*-
"""受保护子集必须分片执行，且分片之间不得漏条目、不得重复跑（CI `unit-tests` 那条腿）。

## 为什么改成分片：一次真实事故

构建 `cnb-v9p-1k5pkvplt` 的 `unit-tests`（PR #365）：

    tests/unit/api/test_channelWebhookResolvesAdapterByAgentTable.py ...
    Killed
    Finished, code: 137, duration: 29m 2s

`code 137` = SIGKILL，日志里**一条失败墙都没有**——不是"有测试红了"，是跑测进程被整段掐断。
用同一份 `requirements-ci.lock` 在本机复跑同一份清单，读数落到同一根因：

    口径              耗时        进程峰值 RSS
    --no-cov          17m32s      2.74 GiB（仍在爬升，未见平台期）
    --cov（CI 那一形） 26m03s      2.78 GiB

`unit-tests` 声明 `cpus: 4`，按平台语法「内存 = CPU 核数 × 2 GiB」＝ **8 GiB** 上限。
峰值贴着额度往上爬，任何一处抖动（依赖面变大、缓存状态不同）都能把它推过去。

## 修法为什么是"分片"而不是"等等看"

峰值与耗时来自**同一个串行进程**：一张清单塞进一次 pytest，收集期要把 7.9k 项全建出来，
跑起来后各模块的常驻态（单例、连接池、内存索引）在一场里累积，谁也不释放。
分成几片各起一个进程，两个读数按片回落。**判据与放行标准一条不动**：
每片仍跑同一把 `--cov-fail-under=60`、仍跑清单里的全部文件。

## 判据四条（都可证伪）

1. **并集相等**：各分片清单的并集 ≡ 索引的并集 ≡ 原单一清单。漏一条、多一条、重一条都红。
   索引保留原清单逐行原貌（含注释与顺序），作业从索引派生清单号——
   分片号不在作业里手抄第二份（教义第 6 条）。
2. **两侧同片数**：cnb 与 GitHub 只有一个放行标准，一侧单片一侧分片即分叉。
3. **每片都带覆盖率门禁**：分片不许把 `--cov-fail-under=60` 顺手摘掉（教义第 2 条）。
4. **不退回单进程全量**：清单不得重新收成单一文件（那正是被 SIGKILL 的形态）。

反向控制（本文件自带，防判定空转）：合成一份"漏了一条"的分片集、一份"多了一条"的、
一份"两条分片重复登记同一文件"的——三种都必须被抓，且抓的理由各不相同。
"""

from __future__ import annotations

import io
import re
import pathlib
import shutil
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests import ast_scan  # noqa: E402  清单取的唯一读法（本档不另开一份）

CI_DIR = PROJECT_ROOT / "scripts" / "ci"
INDEX = CI_DIR / "protected_tests.txt"
CNB = PROJECT_ROOT / ".cnb.yml"
GHW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"

#: `unit-tests` 这条腿的流水线名 / job 名（与 EXPECTED_MAP 同源，不在此抄映射表）。
LEG_NAME = "unit-tests"


def _entries(path: Path) -> list:
    """清单条目：剥注释与空行，保持原序。

    读法不在这里另写一把：受保护子集清单的取数口是 `ast_scan.protectedSubsetEntries()`，
    它对**任意一份** `scripts/ci/protected_tests*.txt` 同形作答（分片清单与索引同一格式）。
    """
    return ast_scan.protectedSubsetEntries(
        path.parents[2] if len(path.parents) > 2 else PROJECT_ROOT, path.name)


def shardFiles(directory: Path = CI_DIR) -> list:
    """分片清单文件名（按编号排序；编号用整数比，不用字符串比）。"""
    found = []
    for path in directory.glob("protected_tests.*.txt"):
        match = re.fullmatch(r"protected_tests\.(\d+)\.txt", path.name)
        if match:
            found.append((int(match.group(1)), path))
    return [path for _, path in sorted(found)]


def shardCounts(directory: Path = CI_DIR) -> list:
    """各分片的编号（**分片号的事实源**：目录里有哪几片，作业按它派生）。"""
    return [int(re.fullmatch(r"protected_tests\.(\d+)\.txt", p.name).group(1))
            for p in shardFiles(directory)]


def _load(path: Path) -> dict:
    return yaml.safe_load(io.open(path, encoding="utf-8").read())


def _cnbPipeline(name: str = LEG_NAME) -> dict:
    for pipe in _load(CNB)["main"]["push"]:
        if isinstance(pipe, dict) and pipe.get("name") == name:
            return pipe
    raise AssertionError(f".cnb.yml 的 main.push 里没有流水线 {name!r}")


def _ghwJob(name: str = LEG_NAME) -> dict:
    jobs = _load(GHW)["jobs"]
    assert name in jobs, f".github/workflows/ci.yml 缺 job {name!r}"
    return jobs[name]


def _cnbScripts(pipe: dict) -> str:
    return "\n".join(str(stage.get("script", "")) for stage in pipe.get("stages") or []
                     if isinstance(stage, dict))


def _ghwRuns(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) for step in job.get("steps") or []
                     if isinstance(step, dict))


class TestShardFilesCoverTheWholeSubset:
    def testIndexAndShardsAgreeOnEveryEntry(self):
        """索引的并集 ≡ 各分片的并集，且无重复登记。"""
        indexed = set(_entries(INDEX))
        seen, duplicated = [], []
        for path in shardFiles():
            for entry in _entries(path):
                if entry in seen:
                    duplicated.append(f"{entry}（{path.name} 重复登记）")
                seen.append(entry)
        assert not duplicated, (
            "同一文件在两片里各跑一遍——分片把「跑几遍」翻了倍，却一条判据都没多：\n  "
            + "\n  ".join(duplicated))
        missing = sorted(indexed - set(seen))
        extra = sorted(set(seen) - indexed)
        assert not missing and not extra, (
            "分片与索引对不上（漏跑/多跑都等于放行标准变了）：\n  漏: "
            + ", ".join(missing[:10]) + f"（共 {len(missing)}）\n  多: "
            + ", ".join(extra[:10]) + f"（共 {len(extra)}）")

    def testShardCountIsWhatTheDirectorySays(self):
        """分片号连续且从 1 起：断号会是"某一片从没跑过"的静默形态。"""
        numbers = shardCounts()
        assert numbers, "scripts/ci/ 下一个分片清单都没有——受保护子集没在跑"
        assert numbers == list(range(1, len(numbers) + 1)), (
            f"分片号 {numbers} 不连续或不是从 1 起：作业按目录派生片号，断号即整片静默不跑")

    def testSubsetIsNotFoldedBackIntoOneProcess(self):
        """反空转：清单不得重新收成单一文件跑（那正是被 SIGKILL 的形态）。"""
        assert sum(len(_entries(p)) for p in shardFiles()) > 500, (
            "分片合计条目太少＝分片没真抄到清单，或清单被「顺手整理」过")


class TestBothSidesRunTheSameShards:
    def testCnbLegFansOutOverEveryShard(self):
        scripts = _cnbScripts(_cnbPipeline())
        assert "protected_tests.1.txt" not in scripts, (
            "cnb 侧把片号手抄在作业里了——片号的事实源是 `scripts/ci/` 目录下有几个分片文件，"
            "抄进配置就会与目录脱钩（加了一片而 CI 不跑它，且没有任何红）")
        assert "for " in scripts and "shard" in scripts.lower(), (
            "cnb 侧没有按分片循环——受保护子集仍是一条龙全量跑，峰值与耗时原样回来")
        assert "$TESTS" in scripts or "TESTS=" in scripts, (
            "cnb 侧的分片循环没有把分片清单喂给 pytest")

    def testGithubLegFansOutOverEveryShard(self):
        job = _ghwJob()
        matrix = (job.get("strategy") or {}).get("matrix") or {}
        shards = matrix.get("shard")
        assert shards, (
            "GitHub 侧没有分片矩阵：同一份清单在两侧要跑同样的片数，"
            "一侧单片一侧分片即放行标准分叉")
        runs = _ghwRuns(job)
        assert "matrix.shard" in runs, "GitHub 侧的矩阵没被用在跑测命令上"

    def testCoverageGateSurvivesAndIsJudgedOnceOverTheWholeSubset(self):
        """分片不许把覆盖率门禁顺手摘掉；门禁必须落在**合并之后**，不是逐片各判一次。

        实测（本机、同一份锁）：单片判 60% 会**假红**——分片 1 的 TOTAL 是
        `6771 语句 / 3429 未覆盖 = 49%`，而整份子集是 `12940 / 1603 = 88%`。
        门禁的语义是"受保护子集整体覆盖了多少"，它不认识分片这件事：
        分片把跑测切小，不该把门禁切碎。
        """
        cnb = _cnbScripts(_cnbPipeline())
        github = _ghwRuns(_ghwJob()) + _ghwRuns(_ghwJob("coverage"))
        for side, scripts in (("cnb", cnb), ("github", github)):
            assert "coverage_report.py --fail-under 60" in scripts, (
                f"{side} 侧分片后不见了覆盖率门禁——判据被顺手放宽"
                "（阈值由 scripts/ci/coverage_report.py 单点持有，不在此另写一份）")
            assert "--cov-report= --cov-fail-under=0" in scripts, (
                f"{side} 侧的跑测步仍在逐片判阈值——单片实测 49%、整份 88%，"
                "逐片判 60% 会假红；分片只该攒数据")


class TestDetectorIsNotVacuous:
    """反向控制：三种分片缺陷必须各被抓到，否则上面几条是快照不是判据。"""

    def _fakeTree(self, tmp_path: Path, shards: dict) -> Path:
        """造一棵合成的仓根：`scripts/ci/` 放索引与给定的分片（专供这几格的反向控制）。

        返回的是**仓根**而不是 `scripts/ci`：清单取数口收的是仓根（与 `REPO_ROOT` 同层级）。
        """
        directory = tmp_path / "scripts" / "ci"
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copy(INDEX, directory / "protected_tests.txt")
        for name, body in shards.items():
            (directory / name).write_text(body, encoding="utf-8")
        return pathlib.Path(tmp_path)

    def testMissingEntryIsCaught(self, tmp_path):
        allEntries = _entries(INDEX)
        cut = allEntries[:-1]
        root = self._fakeTree(tmp_path, {"protected_tests.1.txt": "\n".join(cut) + "\n"})
        indexed = set(_entries(root / "scripts" / "ci" / "protected_tests.txt"))
        seen = {e for p in shardFiles(root / "scripts" / "ci") for e in _entries(p)}
        assert indexed - seen, "漏掉一条而判据没反应——上面那条并集判据是快照"

    def testDuplicateAcrossShardsIsCaught(self, tmp_path):
        allEntries = _entries(INDEX)
        half = len(allEntries) // 2
        root = self._fakeTree(tmp_path, {
            "protected_tests.1.txt": "\n".join(allEntries[:half + 1]) + "\n",
            "protected_tests.2.txt": "\n".join(allEntries[half:]) + "\n",
        })
        counted = [e for p in shardFiles(root / "scripts" / "ci") for e in _entries(p)]
        assert len(counted) != len(set(counted)), "跨片重复登记没被抓到"

    def testListedShardCountMatchesDirectory(self, tmp_path):
        root = self._fakeTree(tmp_path, {
            "protected_tests.1.txt": "", "protected_tests.3.txt": "",
        })
        assert shardCounts(root / "scripts" / "ci") == [1, 3], "断号没被读出来"
        assert shardCounts(root / "scripts" / "ci") != list(range(1, 3)), "断号被当成了连续"
