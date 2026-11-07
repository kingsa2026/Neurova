# -*- coding: utf-8 -*-
"""受保护子集里的「主线基线」必须是 CI **物化出来**的前提，不许指望检出附带。

## 现场（PR #374，`cnb-98o-1k6rpqmf9#003`）

`unit-tests` 第 2 片唯一红的三格，逐字都是同一句：

    FAILED tests/unit/ci/test_npc_branch_cleanup.py::…::testRealRepoMergeRecordYieldsNonAutoPrefixedSourceBranch
      RuntimeError: 读取主线合并记录失败：fatal: ambiguous argument 'origin/main':
      unknown revision or path not in the working tree.
    FAILED tests/unit/ci/test_commitLocClaimMatchesOwnNumstat.py::…::testUnpushedCommitsClaimsAllReconcile
      Failed: origin/main 解析不到——区间取不到基线就等于「无声明」，本格不许据此判绿
    FAILED tests/unit/ci/test_commitLocClaimMatchesOwnNumstat.py::…::testRealBodyWithOneWrongDigitIsCaught
      Failed: origin/main 解析不到——…

本机同一份树、同一份锁、同一条命令全绿。差异不在代码，在**检出形态**——探针构建
`cnb-thk-1k6rrue9d` 在同类检出里逐条读数：

    git branch -a          → 只有 `auto/<PR 分支>` 与 `remotes/origin/auto/<PR 分支>`
    git rev-parse origin/main              → fatal: Needed a single revision
    git rev-parse refs/remotes/origin/main → fatal
    git rev-parse main / refs/heads/main   → fatal
    git cat-file -t 98b0fa42…              → commit        ← 对象在，ref 不在
    git for-each-ref                       → refs/fetched/<sha>…

即：**对象齐全、一个主线 ref 都没有**。平台检出只建被检出分支的 ref，
GitHub 侧那份 `fetch-depth: 0` 的 `actions/checkout` 则自带 `origin/main`。
同一条判据因此在一侧绿、在另一侧红——这是环境前提分叉，不是契约缺陷。

## 修法：在判据的上游把前提物化（教义第 1 条）

不给判据加兜底（那等于让消费方猜「哪条 ref 能当基线」，是下游补丁），
而是在 `unit-tests` 流水线里、跑子集**之前**把 `refs/remotes/origin/main` 取出来：

    git fetch --no-tags origin "+refs/heads/main:refs/remotes/origin/main"

**必须是显式 refspec**：`git fetch origin main` 只写 `FETCH_HEAD`，不建 `origin/main`——
那是最容易被写成"看起来取了、其实没建 ref"的形态，故本文件反向咬住它。

## 判据（都从活配置现读，不抄字面量）

1. `unit-tests` 流水线里有一个 stage 真把基线物化出来（显式 refspec 造 `origin/<默认分支>`）；
2. 它在驱动受保护子集的那个 stage **之前**（ref 不存在时先跑 pytest 就是本单的红）；
3. 那一段带 `set -e`：取不到就当场响，不许把失败留给后面的判据去误报成「判据坏了」；
4. 受治面自证：受保护子集里确实有判据按 `origin/main` 取数（扫不到即本闸空转）。

反向控制：`git fetch origin main`（无 refspec）与 `git fetch --depth=1 …`（浅取，
拿不到合并记录）都必须被判成「没物化」。
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CNB_YAML = PROJECT_ROOT / ".cnb.yml"
SUBSET_DIR = PROJECT_ROOT / "scripts" / "ci"

#: 默认分支名下界——只用来定位 ref，不从 `$` 变量猜（平台注入的 `CNB_DEFAULT_BRANCH`
#: 在配置期不存在，拿它当判据就是让判据随运行态漂）。`.cnb.yml` 的顶层 key 同为 `main`，
#: 两处是同一件事，不是第二份口径。
DEFAULT_BRANCH = "main"

#: 物化基线 ref 的取数形态：显式 refspec，源 `refs/heads/<默认分支>`、目标
#: `refs/remotes/origin/<默认分支>`。`+` 前缀（允许非快进）可有可无。
_REFSPEC_RE = re.compile(
    r"\+?refs/heads/"
    + re.escape(DEFAULT_BRANCH)
    + r":refs/remotes/origin/"
    + re.escape(DEFAULT_BRANCH)
    + r"(?![A-Za-z0-9_./-])"
)


def _loadCnbDocument():
    assert CNB_YAML.exists(), ".cnb.yml 丢失——cnb 门禁退化为无"
    return yaml.safe_load(io.open(CNB_YAML, encoding="utf-8").read())


def _pipelines():
    """`main` 下全部流水线条目（含锚点复用的 push / pull_request 两侧）。"""
    main = _loadCnbDocument().get("main") or {}
    seen, sink = set(), []
    for value in main.values():
        for item in value if isinstance(value, list) else []:
            if isinstance(item, dict) and id(item) not in seen:
                seen.add(id(item))
                sink.append(item)
    return sink


def _unitTestsPipeline():
    target = [p for p in _pipelines() if p.get("name") == "unit-tests"]
    assert len(target) == 1, f"unit-tests 流水线应当恰好一条，实读 {len(target)} 条"
    return target[0]


def materializesBaseline(stage) -> bool:
    """这一格的脚本是否真把 `origin/<默认分支>` 建出来（显式 refspec 才算）。"""
    script = str(stage.get("script") or "")
    if "git fetch" not in script:
        return False
    # 浅取只有一层历史，合并记录取不全 —— 不算物化基线
    if re.search(r"--depth\b", script):
        return False
    return bool(_REFSPEC_RE.search(script))


def _baselineStageIndex(stages):
    return [i for i, s in enumerate(stages) if isinstance(s, dict) and materializesBaseline(s)]


def _subsetStageIndex(stages):
    for i, stage in enumerate(stages):
        if not isinstance(stage, dict):
            continue
        script = str(stage.get("script") or "")
        if "protected_tests" in script and "pytest" in script:
            return i
    return None


class TestBaselineRefIsMaterialized:
    def test_unitTestsPipelineCreatesTheBaselineRef(self):
        pipe = _unitTestsPipeline()
        hits = _baselineStageIndex(pipe.get("stages") or [])
        assert hits, (
            "unit-tests 里没有把 `refs/remotes/origin/"
            f"{DEFAULT_BRANCH}` 物化出来的 stage。平台检出只建被检出分支的 ref，"
            "受保护子集里按 `origin/main` 取数的判据会集体红在「解析不到」上"
            "（构建 cnb-98o-1k6rpqmf9#003 的三格就是这一形态）"
        )

    def test_baselineIsInPlaceBeforeTheSubsetRuns(self):
        pipe = _unitTestsPipeline()
        stages = pipe.get("stages") or []
        baseline, subset = _baselineStageIndex(stages), _subsetStageIndex(stages)
        assert subset is not None, "unit-tests 里找不到驱动受保护子集的那一段"
        assert baseline and min(baseline) < subset, (
            f"物化基线的 stage（下标 {baseline}）必须排在驱动子集的 stage"
            f"（下标 {subset}）之前：ref 还不存在就先跑 pytest，正是本单红的成因"
        )

    def test_baselineStageFailsLoudly(self):
        pipe = _unitTestsPipeline()
        stages = pipe.get("stages") or []
        stage = stages[min(_baselineStageIndex(stages))]
        script = str(stage.get("script") or "")
        assert "set -e" in script, (
            "物化基线的那一格没有 `set -e`：取不到 ref 会被静默放过，"
            "随后判据报「origin/main 解析不到」，成因被推给判据——教义第 2 条"
        )

    def test_fetchTargetsTheDeclaredDefaultBranch(self):
        """ref 名与仓默认分支一致（`main`），不是随手写的另一个分支。"""
        document = _loadCnbDocument()
        assert DEFAULT_BRANCH in document, (
            f"`.cnb.yml` 顶层没有 `{DEFAULT_BRANCH}` 分支键——基线分支名与配置不符，"
            f"实读顶层键为 {sorted(document)}"
        )


class TestGuardsDependingOnBaselineAreCovered:
    """受治面自证：受保护子集里确有判据按 `origin/main` 取数。"""

    def test_protectedSubsetHasGuardsReadingTheBaseline(self):
        listings = sorted(SUBSET_DIR.glob("protected_tests.*.txt"))
        scanned, consumers = 0, []
        for listing in listings:
            for entry in listing.read_text(encoding="utf-8").splitlines():
                entry = entry.strip()
                if not entry or entry.startswith("#"):
                    continue
                path = PROJECT_ROOT / entry
                if not path.exists():
                    continue
                scanned += 1
                if "origin/main" in path.read_text(encoding="utf-8", errors="replace"):
                    consumers.append(entry)
        # 先验面、再谈零命中：清单被截短或 `SUBSET_DIR` 指偏时，`consumers` 为空与
        # 「真没人读基线」在断言里长得一模一样（判据必须自证它这次真扫到了东西）。
        assert scanned > 500, (
            f"只扫到 {scanned} 条受保护子集条目（`scripts/ci/protected_tests.*.txt` "
            f"现读 {len(listings)} 片）—— 根写错或清单被截短时本格的零命中不是结论"
        )
        assert consumers, (
            "受保护子集里已经没有任何判据读 `origin/main` —— 本闸的受治面为空，"
            "要么那批判据被删了（则物化基线的那一格也该一并退役），要么清单换了写法"
        )


class TestNaiveFetchFormsAreRejected:
    """反向控制：两种「看起来取了、其实没建 ref」的写法都必须判成未物化。"""

    @pytest.mark.parametrize(
        "script",
        [
            # 只写 FETCH_HEAD，不建 origin/main —— 最容易被写成的形态
            "set -e\ngit fetch --no-tags origin main\n",
            # 浅取：ref 建得出来，但合并记录只剩一层
            "set -e\ngit fetch --no-tags --depth=1 origin "
            '"+refs/heads/main:refs/remotes/origin/main"\n',
            # 取了别的分支的基线
            "set -e\ngit fetch --no-tags origin "
            '"+refs/heads/release:refs/remotes/origin/release"\n',
            # 压根没取
            "set -e\necho 'origin/main 应该在吧'\n",
        ],
    )
    def test_formIsNotCountedAsMaterialized(self, script):
        assert materializesBaseline({"script": script}) is False

    def test_explicitRefspecIsCounted(self):
        """反向的另一头：显式 refspec（带 `+` 或不带）都必须被认。"""
        for script in (
            'set -e\ngit fetch --no-tags origin "+refs/heads/main:refs/remotes/origin/main"\n',
            "set -e\ngit fetch --no-tags origin refs/heads/main:refs/remotes/origin/main\n",
        ):
            assert materializesBaseline({"script": script}) is True, script
