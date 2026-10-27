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


class TestCoverageDataLandsWhereTheMergeStepLooks:
    """跑测落的 `.coverage*` 必须落在合并那一步 `--data-dir` 指的目录里。

    事故（构建 `cnb-4gd-1k5us1o1q#003` 实读）：stage 2「protected subset shards」**全绿**
    （`2737 passed`），紧接的 stage 3「coverage gate」报
    `没有找到任何覆盖率数据（/workspace/data/coverage）`，整条 `unit-tests` 因此判红。

    根因是两侧各猜了一次路径：coverage 的缺省落点是**当前目录的 `./.coverage`**，
    而合并那一步（`scripts/ci/coverage_report.py --data-dir data/coverage`）只认那个目录。
    这中间没有任何东西把两者对上——`--cov` 不出报告（`--cov-report=`）时，数据写在哪
    完全由 `COVERAGE_FILE` 决定，而此前**全仓没有任何一处设置它**（`grep COVERAGE_FILE` 零命中）。

    为什么这条要落成判据：症状是"跑测说全绿、合并说没数据"，两个 stage 各说各话，
    中间隔着一层环境变量的缺省值——那正是"配置漂移"最典型的隐身衣，红一次修一次不够。
    """

    @staticmethod
    def _mergeDirectory(scripts: str) -> str:
        """合并步 `--data-dir` 的实参（不是合并脚本自己的缺省值：CI 上它由作业显式传）。"""
        for line in scripts.splitlines():
            if "coverage_report.py" in line:
                parts = line.split()
                if "--data-dir" in parts:
                    return parts[parts.index("--data-dir") + 1].strip("\"'")
        return "data/coverage"      # 与 scripts/ci/coverage_report.py 的缺省同源

    def testCnbLegPointsCoverageFileAtTheMergeDirectory(self):
        scripts = "\n".join(line.split("#", 1)[0]
                            for line in _cnbScripts(_cnbPipeline()).splitlines())
        assert "COVERAGE_FILE=" in scripts, (
            "cnb 侧的跑测步没有设置 `COVERAGE_FILE`：`--cov` 会把数据落在 `./.coverage`，"
            "而合并步只找 `%s`——stage 2 全绿、stage 3 报「没有找到任何覆盖率数据」，"
            "整条 unit-tests 判红（构建 cnb-4gd-1k5us1o1q）。" % self._mergeDirectory(scripts)
        )
        directory = self._mergeDirectory(scripts)
        assert f"COVERAGE_FILE={directory}" in scripts or f'COVERAGE_FILE="{directory}' in scripts, (
            f"`COVERAGE_FILE` 指的不是合并步那个目录（{directory}）：两处各猜一次路径，"
            "对不上时跑测那一侧永远看不出问题"
        )

    def testGithubLegPointsCoverageFileAtTheMergeDirectory(self):
        runs = "\n".join(line.split("#", 1)[0]
                         for line in (_ghwRuns(_ghwJob()) + _ghwRuns(_ghwJob("coverage"))).splitlines())
        assert "COVERAGE_FILE=" in runs, (
            "GitHub 侧同样没设 `COVERAGE_FILE`：`data/coverage/.coverage*` 的上传与合并"
            "会一并落空（`if-no-files-found: error` 才让它露头）"
        )
        assert "COVERAGE_FILE=data/coverage/" in runs, (
            "GitHub 侧的 `COVERAGE_FILE` 没指进 `data/coverage/`——上传那一步只收那个目录"
        )

    def testEveryShardGetsItsOwnCoverageFile(self):
        """同名文件在多片之间互相覆盖：实测三片写同一个 `./.coverage` 只会剩最后一片。

        片号必须进文件名。cnb 侧走 `$(basename "$shard" .txt)`，GitHub 侧走 `matrix.shard`，
        两边都要体现"这一片有它自己的那份"。
        """
        cnb = "\n".join(line.split("#", 1)[0] for line in _cnbScripts(_cnbPipeline()).splitlines())
        assert "COVERAGE_FILE=\"data/coverage/.coverage.$(basename \"$shard\"" in cnb, (
            "cnb 侧三片写同一个数据文件名——后一片把前一片覆盖掉，合并出来只剩一片的读数"
        )
        github = "\n".join(line.split("#", 1)[0]
                          for line in _ghwRuns(_ghwJob()).splitlines())
        assert "matrix.shard" in github.split("COVERAGE_FILE=")[1].splitlines()[0], (
            "GitHub 侧的 `COVERAGE_FILE` 没带片号——矩阵里多个 job 会抢同一个文件"
        )


class TestShardEntriesReachPytestLiterally:
    """清单要**逐条**交到 pytest 手上，缺一条就是静默少跑一条。

    事故（构建 `cnb-1f0-1k5uonjt2-003` 实读）：同一片里前 8 格全绿，第 9 格起
    `test_legacy_ref_ledger_guard` / `test_archive_nav_impact_guard` 两档红在
    「台账与扫描器不一致」，而本机按单文件跑同一批是 44 passed / 1 skipped。
    差别在清单的**喂法**：cnb 侧写成

        TESTS=$(grep -v '^#' "$shard" | tr '\n' ' ')
        python -m pytest ... $TESTS

    `$(...)` 的结果会被 shell 再切一次词，清单里混进一条空行、一个空格、一个 glob 字符，
    后面的条目就整片错位；而 pytest 从不说「你列的文件我少跑了几个」——它只跑收到的那部分。

    修法是**两侧同一口径**：清单先由 `sh` 逐行读到位置参数上（`set --`，引号包住每个路径，
    不过 glob、不再切词），由 pytest 直接收位置参数。这条不变量两头钉住：
    一侧 `$TESTS` 展开、一侧逐行 —— 也是两套放行标准。
    """

    @staticmethod
    def _shellLines(scripts: str) -> str:
        """`script:` 是 **shell**，`#` 之后是注释——注释里讲「旧写法长什么样」不改变行为，
        把注释当成配置读会得出假阳性（本档自己就踩了一次）。故只留命令行。"""
        return "\n".join(line.split("#", 1)[0] for line in scripts.splitlines())

    def testCnbLegPassesTheListLineByLine(self):
        scripts = self._shellLines(_cnbScripts(_cnbPipeline()))
        assert "tr '\\n' ' '" not in scripts and 'tr "\\n" " "' not in scripts, (
            "cnb 侧又把清单压成一行塞进 `$TESTS` 了——`$(...)` 会被 shell 再切一次词，"
            "清单里一条空行就让后面的条目错位，被跳过的文件不会报错，只会安静地不跑"
            "（构建 cnb-1f0-1k5uonjt2-003）。"
        )
        assert "set --" in scripts and '"$@"' in scripts, (
            "cnb 侧没有把清单逐行读到位置参数上（`set -- …` + `pytest … \"$@\"`）："
            "每一条都要原样交给 pytest，路径里带空格也不会被拆开"
        )

    def testGithubLegPassesTheListTheSameWay(self):
        runs = self._shellLines(_ghwRuns(_ghwJob()))
        assert "tr '\\n' ' '" not in runs and 'tr "\\n" " "' not in runs, (
            "GitHub 侧仍在把清单压成一行塞进 `$TESTS`：两侧必须同一口径，"
            "一处逐行、一处切词就是两套放行标准"
        )
        assert "set --" in runs and '"$@"' in runs, (
            "GitHub 侧没有按 cnb 侧同一形态读清单（`set -- …` + `\"$@\"`）"
        )


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
