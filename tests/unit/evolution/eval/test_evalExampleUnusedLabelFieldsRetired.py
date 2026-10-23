# -*- coding: utf-8 -*-
"""评测用例的两个只写不读标签字段必须退役（ModularRSI 对照 §4 M-D，裁定乙）。

## 缺陷形态

`EvalExample.difficulty` / `.category`（`neurova/evolution/eval/dataset.py:27-28`）由
`synthetic.py:99-100`、`miner.py:198-199` 写入，`to_dict()` 序列化投影出去，但
**split（`dataset.py:80-111`）与 runner 判定链都不按它们筛或分组**——全仓零读取点。
`synthetic.py:26-27` 甚至专门在 prompt 里要求 LLM 产出这两个没人取用的标签。

按 AGENTS.md §2 断点条款，「只写不读」要么接线要么删除，不许静默留着。裁定走退役：
字段本身、序列化投影、两处产出要求（含 `miner.py:121` 的无 llm 兜底字典）一并删净。

## 本守卫钉四件事（缺任一条即红）

- **A 表示面**：`EvalExample` 的 dataclass 字段恰为 `task_input` / `expected_behavior` /
  `source` 三项——多一格就是复活（`source` 的存废另议，见下方说明，不属本批）。
- **B 传输面**：`to_dict()` 的键集合同上。字段删了但投影还出，等于对外继续宣称有这个维度。
- **C 写侧不再产标签**：三个生产文件里 `difficulty` / `category` 两个词**一次都不许出现**
  （含 prompt 文本——「让 LLM 产一个没人读的标签」与「留个空字段」是同一根因的两面）。
- **D 构造点**：AST 扫全仓 `EvalExample(...)` 调用，带这两个关键字实参的命中数必须是 0，
  且扫描面（三个生产文件 + 本目录）不得缩水——命中数下限钉 0、文件清单下限钉住，
  否则「扫不到了」会被读成「改干净了」。
"""
from __future__ import annotations

import ast
import dataclasses
import re
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[4]
EVAL_PKG = PROJECT_ROOT / "neurova" / "evolution" / "eval"
DATASET_PY = EVAL_PKG / "dataset.py"
SYNTHETIC_PY = EVAL_PKG / "synthetic.py"
MINER_PY = EVAL_PKG / "miner.py"

#: C 档扫描面——建档时已知的全部落点；少一个文件就是扫描面缩水。
WRITER_SURFACE = (DATASET_PY, SYNTHETIC_PY, MINER_PY)

RETIRED_FIELDS = ("difficulty", "category")
#: 留下的三项：两项是用例本体，`source` 是用例出处（synthetic|history|golden）。
#: source 生产侧暂无读取点，与本次退役**同根因但不同判定**——它是对照报告 §3.6 记为
#: 本仓既有优势的出处标记，删它即抹掉证据维度，属需人裁（已登记，不在本批擅动）。
SURVIVING_FIELDS = ("task_input", "expected_behavior", "source")


def _evalExampleFields() -> tuple[str, ...]:
    from neurova.evolution.eval.dataset import EvalExample

    return tuple(f.name for f in dataclasses.fields(EvalExample))


def _callSitesAsEvalExampleKeywords(py: Path) -> list[str]:
    """AST 里 `EvalExample(...)` 调用上挂的两个退役关键字实参（只认构造调用形态）。"""
    tree = ast.parse(py.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        name = getattr(callee, "id", None) or getattr(callee, "attr", None)
        if name != "EvalExample":
            continue
        for kw in node.keywords:
            if kw.arg in RETIRED_FIELDS:
                hits.append(f"{py.name}:{node.lineno} {kw.arg}")
    return hits


def _trackedScanFace(scanRoots: tuple[str, ...]) -> list[Path]:
    """构造点扫描的取数面＝**跟踪集**（`git ls-files`），不是工作树目录 glob。

    为什么改：常驻格按工作树 glob 取数时，并发会话半写的未跟踪文件会被读成我的回归
    （形态集第 199 条），而这一格比那更糟——它 `ast.parse` 未跟踪的坏档直接抛
    `SyntaxError`，红报在我的档上、真 offender 在别人的在途档里，读的人会被送错地方。
    能进 CI 的文件都必然先被跟踪，因此收口到跟踪集**不丢任何真命中点**；
    未跟踪的在途档自有它的收集错误来报，不该由本档代报。
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", *scanRoots],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, encoding="utf-8",
    )
    assert listed.returncode == 0, f"git ls-files 失败：{listed.stderr}"
    # 只留工作树里真在的：索引与工作树的差是在途改名/刚删的中间态，读到一条指不到文件的
    # 路径就是 FileNotFoundError——扫描面成了"跑的时刻撞不撞上在途改动"的运气
    # （同一取数口径见 `tests/ast_scan.trackedPyPaths`）。
    return [PROJECT_ROOT / rel for rel in sorted(listed.stdout.split("\0"))
            if rel.endswith(".py") and (PROJECT_ROOT / rel).is_file()]


class TestEvalExampleUnusedLabelFieldsRetired:
    """两个标签字段的表示面、传输面、写侧、构造点四档一并归零。"""

    def testA_dataclassCarriesOnlyTheTwoLiveFields(self):
        assert _evalExampleFields() == SURVIVING_FIELDS, (
            f"EvalExample 字段面应为 {SURVIVING_FIELDS}，现值 {_evalExampleFields()}；"
            "difficulty/category 是全仓零读取点的只写不读标签（AGENTS.md §2 断点条款）"
        )

    def testB_toDictDoesNotProjectRetiredKeys(self):
        from neurova.evolution.eval.dataset import EvalExample

        projected = EvalExample(task_input="t", expected_behavior="e").to_dict()
        assert set(projected) == set(SURVIVING_FIELDS), (
            f"to_dict() 键集合应恰为 {set(SURVIVING_FIELDS)}，现值 {set(projected)}"
        )

    @pytest.mark.parametrize("py", WRITER_SURFACE, ids=lambda p: p.name)
    def testC_writersNoLongerEmitTheLabels(self, py: Path):
        assert py.exists(), f"扫描面锚点丢失：{py}——文件被改名/移动时本判据不得静默通过"
        text = py.read_text(encoding="utf-8")
        for word in RETIRED_FIELDS:
            hits = [
                line for line in text.splitlines()
                if re.search(rf"\b{word}\b", line)
            ]
            assert not hits, (
                f"{py.name} 仍出现 {word} {len(hits)} 行（首行："
                f"{hits[0].strip() if hits else ''}）；写侧不得再产出无人取用的标签"
            )

    def testD_noCallSitePassesRetiredKeywords(self):
        scanRoots = ("neurova", "tests", "scripts")
        hits: list[str] = []
        broken: list[str] = []
        for py in _trackedScanFace(scanRoots):
            try:
                hits.extend(_callSitesAsEvalExampleKeywords(py))
            except SyntaxError as e:
                broken.append(f"{py.relative_to(PROJECT_ROOT)}: {e}")
        assert broken == [], "跟踪集里有 AST 解析不了的文件，本档的构造点扫描对它看不见：" + broken
        assert hits == [], "EvalExample(...) 构造点仍传退役关键字：" + "; ".join(hits)

    def testE_scanSurfaceHasNotShrunk(self):
        """下限钉：三个写侧文件必须都还在原位置（掉出一个就把「扫不到」读成「已扫净」）。"""
        present = [py.name for py in WRITER_SURFACE if py.exists()]
        assert present == [py.name for py in WRITER_SURFACE], (
            f"M-D 扫描面应含全部三份写侧文件，现仅 {present}"
        )
