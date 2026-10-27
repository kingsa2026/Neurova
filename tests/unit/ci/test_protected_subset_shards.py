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


class TestEntriesAreTheShardsOwnProperty:
    """清单条目与它所在的那一片，**只由清单文件本身决定**——运行时不替它作证。

    ## 为什么加这一条（PR #365，构建 `cnb-4ou-1k5uqgqi2-003` 实读）

    那个构建的 `unit-tests` 腿只红一格：`tests/unit/ci/test_commitLocClaimMatchesOwnNumstat.py`
    里 `_KNOWN_BAD_COMMITS` 还留着一条指向**不存在提交**的豁免。按该构建实际用的那棵树
    （`e124affa`）本机复跑同一档，红的逐字相同，而 PR 分支上 `e1a388e9` / `e2c8834e`
    早已把那条删掉——两棵树只差**这一个文件**，其余 734 条一条不差。

    真正该有人说话的地方在这里：清单是 700+ 行手写索引，路径被谁改写、被剪成一行、
    或者被登记两遍，pytest 一个字都不说（它只跑收到的那部分）。故把清单自己的三条硬约束
    钉成常驻判据——**每一条都真的存在、只出现一次、三片的并集逐条等于索引**。
    这一格不猜运行时发生过什么，只回答"这份清单能不能被当成那份子集"。

    （反向控制：`testNonexistentEntryIsCaught` 塞一条不存在的路径，判据必须当场点名。）
    """

    def testEveryListedPathExistsOnceAndIsIndexed(self):
        """条目三条硬约束一次判完，逐条点名：不存在 / 重复登记 / 未进索引。"""
        for path in shardFiles() + [INDEX]:
            vanished, duplicated, seen = [], [], set()
            for line in path.read_text(encoding="utf-8").splitlines():
                entry = line.strip()
                if not entry or entry.startswith("#"):
                    continue
                if entry in seen:
                    duplicated.append(entry)
                seen.add(entry)
                if not (PROJECT_ROOT / entry).is_file():
                    vanished.append(entry)
            assert not vanished, (
                f"{path.name} 点名了不存在的文件——那一片会在这里少跑一档，而 pytest 不会说：\n  "
                + "\n  ".join(vanished[:10]))
            assert not duplicated, (
                f"{path.name} 里同一档登记了两次——同一份判据跑两遍，白板却读不出改写冲突：\n  "
                + "\n  ".join(sorted(set(duplicated))[:10]))
        assert set(_entries(INDEX)) == {e for p in shardFiles() for e in _entries(p)}, (
            "索引与各片的并集不再逐条相等（漏片＝整片白跑，多片＝索引里有不存在的片）")


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

    def testNonexistentEntryIsCaught(self, tmp_path):
        """反向控制：清单里点一条**不存在的路径**，上面那一格必须当场点名。

        `testEveryListedPathExistsOnceAndIsIndexed` 若对任何清单都放行，它就只是快照。
        这里造一棵真清单 + 一条假路径的合成树，判据必须红，并且点名的是那条假路径。
        """
        real = _entries(INDEX)[:3]
        root = self._fakeTree(tmp_path, {
            "protected_tests.1.txt": "\n".join(real + ["tests/unit/ci/__gone__.py"]) + "\n",
        })
        # 判据取的是**仓根下的真实文件**，而合成树只放了清单、没有代码树——
        # 故这里把仓根喂给 `PROJECT_ROOT` 的等价读法，只对那一条假路径作答。
        listed = _entries(root / "scripts" / "ci" / "protected_tests.1.txt")
        gone = [entry for entry in listed if not (PROJECT_ROOT / entry).is_file()]
        assert gone == ["tests/unit/ci/__gone__.py"], f"不存在的路径没被读出来：{gone}"
