#!/usr/bin/env python3
"""认知层「现役组件表」生成器：从代码现读，不手维护。

为什么要有它：`NEUROVA_CogArch_2.0.md` §8.2 是 2026-05-12 的手工映射表，2026-10-20 复算
70 条路径里 44 条已不存在（台账 §6-362）。CogArch 已降为沿革档，认知层的**现役**状态
改由本生成器的输出承担：表里每一行都由当次代码扫描得出，判据
`tests/unit/ci/test_cognitiveComponentTable.py` 逐字比对文档机读区，并抽样与
`tests/ast_scan.importersOfModule`（单目标取数口）交叉验证。

口径（避免第二套解释）：
- 组件＝`neurova/cognitive_layers/` 下**跟踪态**的 `.py`（不含 `__init__.py`）；
  子层取路径的下一层目录名，根目录文件归「（根）」。
- **层外读者**＝`neurova/` 内、但不在 `neurova/cognitive_layers/` 之下的导入者文件数（去重）；
  **层内读者**＝同层内、该模块自身之外的导入者文件数；**测试读者**＝`tests/` 内的导入者文件数。
- 状态四态：`在役`（层外读者 ≥1）／`仅层内`（只被同层读到）／`仅测试`／`零读者`。
  为什么把"层外"单列：被同层读在死码口径里只证明内部接线，不证明在服（台账 §6-359/§6-360）。
- 本文件是**聚合索引**（单趟建边，避免 106 个目标各扫一遍全仓）。**单目标判定不要用这里**，
  一律走 `tests/ast_scan.importersOfModule`——两者由判据的抽样格钉在一起。

用法：
    python scripts/ci/cognitive_component_table.py            # 打印两个机读区
    python scripts/ci/cognitive_component_table.py --write    # 写回文档
"""
from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import ast_scan  # noqa: E402  （仓内唯一 AST 扫描入口）

DOC = REPO_ROOT / "docs" / "01-architecture" / "cognitive-component-table.md"
LAYER = "neurova/cognitive_layers"

SUMMARY_BEGIN = "<!-- COGNITIVE:SUMMARY:BEGIN -->"
SUMMARY_END = "<!-- COGNITIVE:SUMMARY:END -->"
TABLE_BEGIN = "<!-- COGNITIVE:TABLE:BEGIN -->"
TABLE_END = "<!-- COGNITIVE:TABLE:END -->"

STATUSES = ("在役", "仅层内", "仅测试", "零读者")


def _trackedPy(pathspec: str):
    return ast_scan.trackedPyPaths(pathspec)


def _moduleName(rel: str) -> str:
    return rel[:-3].replace("/", ".")


def componentRows() -> list:
    """逐模块现读一行；排序固定（子层名、路径），保证输出可逐字比对。"""
    componentPaths = [p for p in _trackedPy(LAYER) if not p.endswith("/__init__.py")]
    knownModules = {_moduleName(p) for p in _trackedPy("neurova")}
    importers: dict = {}
    for path, tree in ast_scan.trackedModules():
        rel = ast_scan.relativeToRepo(path)
        for node in ast.walk(tree):
            targets = set()
            if isinstance(node, ast.Import):
                targets.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = ast_scan.resolveImportModule(rel, node)
                if not base:
                    continue
                targets.add(base)
                targets.update(f"{base}.{alias.name}" for alias in node.names)
            targets &= knownModules
            if targets:
                importers.setdefault(rel, set()).update(targets)

    rows = []
    for rel in componentPaths:
        module = _moduleName(rel)
        readers = {src for src, targets in importers.items() if module in targets}
        outside = {src for src in readers
                   if src.startswith("neurova/") and not src.startswith(LAYER + "/")}
        inside = {src for src in readers
                  if src.startswith(LAYER + "/") and src != rel}
        tests = {src for src in readers if src.startswith("tests/")}
        sub = rel[len(LAYER) + 1:].split("/")
        sublayer = sub[0] if len(sub) > 1 else "（根）"
        status = ("在役" if outside else
                  "仅层内" if inside else
                  "仅测试" if tests else "零读者")
        rows.append({
            "path": rel,
            "sublayer": sublayer,
            "loc": len(ast_scan.sourceCode(REPO_ROOT / rel).splitlines()),
            "outsideReaders": len(outside),
            "insideReaders": len(inside),
            "testReaders": len(tests),
            "status": status,
        })
    return sorted(rows, key=lambda r: (r["sublayer"], r["path"]))


def renderSummary(rows: list) -> str:
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    perLayer: dict = {}
    for row in rows:
        bucket = perLayer.setdefault(row["sublayer"], {"n": 0, "loc": 0})
        bucket["n"] += 1
        bucket["loc"] += row["loc"]
    lines = [SUMMARY_BEGIN,
             f"共 **{len(rows)}** 个模块 / **{sum(r['loc'] for r in rows)}** 行。"
             f"按状态：**在役 {counts['在役']}** · **仅层内 {counts['仅层内']}** · "
             f"**仅测试 {counts['仅测试']}** · **零读者 {counts['零读者']}**。",
             "",
             "| 子层 | 模块数 | 行数 |",
             "|---|---|---|"]
    for name in sorted(perLayer):
        lines.append(f"| `{name}` | {perLayer[name]['n']} | {perLayer[name]['loc']} |")
    lines.append(SUMMARY_END)
    return "\n".join(lines)


def renderTable(rows: list) -> str:
    lines = [TABLE_BEGIN]
    current = None
    for row in rows:
        if row["sublayer"] != current:
            current = row["sublayer"]
            lines += ["", f"### `{current}`", "",
                      "| 模块 | 行数 | 层外读者 | 层内读者 | 测试读者 | 状态 |",
                      "|---|---|---|---|---|---|"]
        lines.append(f"| `{row['path']}` | {row['loc']} | {row['outsideReaders']} | "
                     f"{row['insideReaders']} | {row['testReaders']} | {row['status']} |")
    lines.append("")
    lines.append(TABLE_END)
    return "\n".join(lines)


def extractBlock(text: str, begin: str, end: str) -> str:
    start = text.find(begin)
    stop = text.find(end, start + len(begin)) if start != -1 else -1
    if start == -1 or stop == -1:
        return ""
    return text[start:stop + len(end)]


def applyBlocks(text: str) -> str:
    rows = componentRows()
    for begin, end, rendered in (
        (SUMMARY_BEGIN, SUMMARY_END, renderSummary(rows)),
        (TABLE_BEGIN, TABLE_END, renderTable(rows)),
    ):
        current = extractBlock(text, begin, end)
        if not current:
            continue
        text = text.replace(current, rendered)
    return text


def writeDoc() -> int:
    current = io.open(DOC, encoding="utf-8").read()
    updated = applyBlocks(current)
    if updated != current:
        with io.open(DOC, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(updated)
    return 2


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--write" in argv:
        print(f"组件表机读区已重生成：{DOC.relative_to(REPO_ROOT)}（2 个区块）")
        writeDoc()
        return 0
    rows = componentRows()
    print(renderSummary(rows))
    print()
    print(renderTable(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
