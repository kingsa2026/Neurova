# -*- coding: utf-8 -*-
"""扫描指定目录下的 Markdown 悬空引用，并对每条给出可达性判定。

判定的三种形态（与 `docs/06-bugfix/历史悬空引用登记台账_2026-09-21.md` 一致）：

- `迁移可达`：引用目标已不在原位，但在仓库内按「同后缀路径」或「全仓唯一同名」
  唯一命中 → 目标可达，只是路径过期。
- `同名歧义`：全仓有多个同名候选（常见于 `docs/X.md` 与 `docs/<领域>/X.md` 并存），
  无法自动裁定该指向哪一个 → 需人工按上下文裁定。
- `源已删除`：全仓零命中 → 目标确实不存在，引用失效。
- `空标签悬空`：`[文字]()` 空目标 / ` `` ` 空反引号 —— 「用清空代替修复」的形态。

只做只读扫描，不改任何文件；供登记台账生成与常驻守卫共用同一份判据
（避免「台账一份口径、守门另一份口径」的双源）。

本文件是**引用扫描与判定的唯一事实源**：台账与守卫都从这里取数，
不在别处复制一套判据。函数与变量按仓库命名规约用 camelCase。
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Markdown 链接 / 反引号路径引用 / 空标签
LINK_PATTERN = re.compile(r"!?\[([^\]]*)\]\(([^)\s]*)\)")
CODE_PATH_PATTERN = re.compile(r"`([^`\s]+)`")
FENCE_PATTERN = re.compile(r"```|~~~")
# 视为「路径引用」的文件后缀（避免把 `foo.bar()` 这类代码片段当路径）
PATH_SUFFIXES = ("py", "md", "yml", "yaml", "json", "toml", "sh", "bat", "js", "ts", "vue", "html", "css")
# 通配/占位形态（`bugfix-*.md`、`HARMONYOS_*.md`）不是具体路径，单独归类
PLACEHOLDER_PATTERN = re.compile(r"[*<>{}\[\]]")

# 编号分层（docs/<NN-领域>/…）——文档重排后的唯一留存层
NUMBERED_LAYERS = frozenset({
    "0-index", "01-architecture", "02-api", "03-user-guide", "04-plans", "05-reports",
    "06-bugfix", "08-research", "09-dev-progress", "10-configuration", "11-legacy",
})

# 台账类文档把"被清空的引用"作为**数据**逐条列出（表格里的形态样例），
# 扫描时排除：否则台账每生成一次就把自己举的样例当成新命中点，
# "生成 → 计数变化 → 再生成"永远收敛不了（自引用死循环）。
LEDGER_DOCUMENTS = frozenset({
    "docs/06-bugfix/历史悬空引用登记台账_2026-09-21.md",
    "docs/06-bugfix/文档空链登记台账_2026-09-21.md",
})

VERDICT_REACHABLE = "可达"
VERDICT_MOVED = "迁移可达"
VERDICT_AMBIGUOUS = "同名歧义"
VERDICT_DELETED = "源已删除"
VERDICT_EMPTY = "空标签悬空"
VERDICTS = (VERDICT_REACHABLE, VERDICT_MOVED, VERDICT_AMBIGUOUS, VERDICT_DELETED, VERDICT_EMPTY)


def trackedFiles() -> list:
    """仓库已入库文件（git ls-files；关掉 quotepath 以免中文名被转义）。"""
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    return [line for line in proc.stdout.split("\n") if line.strip()]


def indexByBasename(files: list) -> dict:
    index = {}
    for path in files:
        index.setdefault(path.split("/")[-1], []).append(path)
    return index


def resolveTarget(ref: str, source: Path, byBasename: dict) -> tuple:
    """返回 (判定, 命中路径或候选说明)。"""
    literal = ref.lstrip("/").split("#")[0].strip()
    # 1. 文件自身目录 / 仓库根两处按字面解析（与 Markdown 相对链接语义一致）
    for base in (source.parent, PROJECT_ROOT):
        candidate = base / literal
        if candidate.exists():
            # 字面可达 —— 引用本身没坏，不进台账
            return VERDICT_REACHABLE, displayPath(candidate.resolve())
    # 2. 按「同后缀完整路径」找唯一命中
    basename = literal.split("/")[-1]
    candidates = byBasename.get(basename, [])
    parts = literal.split("/")
    exact = [p for p in candidates if p.split("/")[-len(parts):] == parts]
    if len(exact) == 1:
        return VERDICT_MOVED, exact[0]
    # 3. 全仓唯一同名 → 可达（仅限带目录的引用；裸文件名歧义风险高）
    if len(candidates) == 1 and "/" in literal:
        return VERDICT_MOVED, candidates[0]
    if candidates:
        return VERDICT_AMBIGUOUS, ", ".join(candidates[:3])
    return VERDICT_DELETED, "—"


def emptyCodeSpans(line: str) -> list:
    """返回该行中"被清空的引用"位置（反引号 run 的起始下标）。

    判据：**孤立的反引号 run**——它在整行里找不到同长度的配对 run。
    这条判据同时挡住两类相反的错误：

    - 假阳性：`\`\` `行内码` \`\`` 是"内容里含反引号"的合法写法（CommonMark 用双
      反引号定界），代码审计与规范类文档里大量出现。它的首尾 run 会彼此配对，
      故被正确跳过。若简单地把任意两个反引号读成"空引用"，这些会成批误报——
      假阳性比漏报更坏，它会训练人忽略这道门禁。
    - 假阴性：真正被删空的引用就是一个孤立的 `\`\``，没有任何配对 run，
      必须照样报出来（漏报等于门禁失效）。
    """
    runs = []
    index = 0
    length = len(line)
    while index < length:
        if line[index] != "`":
            index += 1
            continue
        runEnd = index
        while runEnd < length and line[runEnd] == "`":
            runEnd += 1
        runs.append((index, runEnd - index))
        index = runEnd

    paired = set()
    for position, (start, runLength) in enumerate(runs):
        if runLength != 2 or position in paired:
            continue
        for other in range(position + 1, len(runs)):
            if other in paired:
                continue
            if runs[other][1] == runLength:
                paired.add(position)
                paired.add(other)
                break
    return [start for position, (start, runLength) in enumerate(runs)
            if runLength == 2 and position not in paired]


def _isFenceLine(line: str) -> bool:
    """行首（可带引用前缀 `> `）的围栏定界符。

    引用块里嵌的代码围栏（`> ```python`）与顶格围栏同样是**被测代码**；
    不认它会把它读成"被清空的引用"。
    """
    stripped = line.lstrip()
    while stripped.startswith(">"):
        stripped = stripped[1:].lstrip()
    return bool(FENCE_PATTERN.match(stripped))


def displayPath(path: Path) -> str:
    """台账里展示的路径：仓内用相对路径，仓外（如测试临时文件）用绝对路径。"""
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def scanFile(path: Path, byBasename: dict) -> list:
    """扫描单个 Markdown，返回悬空条目（可达的引用不返回）。"""
    text = io.open(path, encoding="utf-8", errors="replace").read()
    relative = displayPath(path)
    found = []
    inFence = False
    for lineNo, line in enumerate(text.splitlines(), 1):
        if _isFenceLine(line):
            inFence = not inFence
            continue
        if inFence:
            continue
        for match in LINK_PATTERN.finditer(line):
            label, target = match.group(1).strip(), match.group(2).strip()
            if not label or not target:
                found.append(_entry(relative, lineNo, match.group(0), VERDICT_EMPTY, "—"))
        for _ in emptyCodeSpans(line):
            found.append(_entry(relative, lineNo, "``", VERDICT_EMPTY, "—"))
        for match in CODE_PATH_PATTERN.finditer(line):
            ref = match.group(1)
            if ref.startswith(("http", "mailto:", "#")):
                continue
            if not ref.endswith(tuple("." + suffix for suffix in PATH_SUFFIXES)):
                continue
            if PLACEHOLDER_PATTERN.search(ref):
                continue
            verdict, hit = resolveTarget(ref, path, byBasename)
            if verdict == VERDICT_REACHABLE:
                continue
            found.append(_entry(relative, lineNo, ref, verdict, hit))
    return found


# ---------------------------------------------------------------------------
# 同名多份（回潮副本）判定
# ---------------------------------------------------------------------------
# 判据（与台账同源，只此一份）：同一个 basename 同时存在于「编号分层」
# （docs/0-index … docs/11-legacy）与「非编号层」（docs/ 根、docs/<旧目录>/）
# 时，后者是**同一篇文档的第二份**。根因是一次目录重排把文档移入编号分层后，
# 另一批次又把旧路径批量还原回来，于是顶层与分层各留一份、同名不同内容。
#
# 排除项是**具体路径**，不是 basename——`README.md` 这类名字各层都会合法持有，
# 按 basename 一刀切会把 `docs/09-dev-progress/README.md`（与 `docs/09-dev-progress/`
# 那份逐字节相同的真副本）也放过。排除项要能逐条说出理由：
#
# - `docs/README.md`：内容自述为 Neutesting 测试框架说明，是仓库 `docs/` 的目录说明，
#   与 `docs/0-index/README.md`（文档总索引）不是同一篇；
# - `docs/INDEX.md`：现行文档体系唯一导航事实源，被 `AGENTS.md`/`CONTRIBUTING.md`
#   与守卫引用；`docs/11-legacy/INDEX.md` 是归档层入口，正文自述为历史归档版；
# - `docs/01-architecture/adr/README.md`、`docs/architecture-model/README.md`：
#   各自目录的索引，从不与别层同名同文。
#
# 这三类都不是"同一篇文档的第二份"，故不参与回潮副本判定。
LAYER_OWNED_PATHS = frozenset({
    "docs/README.md",
    "docs/INDEX.md",
    "docs/01-architecture/adr/README.md",
    "docs/architecture-model/README.md",
})


def numberedLayer(path: str) -> bool:
    """是否位于编号分层（docs/<NN-领域>/…）。"""
    parts = path.split("/")
    return len(parts) > 2 and parts[0] == "docs" and parts[1] in NUMBERED_LAYERS


def residueDuplicates() -> list:
    """返回「非编号层与编号分层同名」的回潮副本。

    每项为 (副本路径, [编号分层候选路径])，按路径排序。
    """
    docs = [path for path in trackedFiles() if path.startswith("docs/")]
    byBasename = {}
    for path in docs:
        byBasename.setdefault(path.split("/")[-1], []).append(path)
    found = []
    for basename, paths in sorted(byBasename.items()):
        canonical = sorted(p for p in paths if numberedLayer(p))
        residue = sorted(p for p in paths if not numberedLayer(p) and p not in LAYER_OWNED_PATHS)
        if canonical and residue:
            found.append((residue, canonical))
    return found


# ---------------------------------------------------------------------------
# 同名歧义裁定（与台账、守卫同源）
# ---------------------------------------------------------------------------
# 裁定口径：**编号分层是文档重排后的留存层**，非编号层（docs/ 根与 docs/<旧目录>/）
# 里的同 basename 文件是重排后又被批量还原回来的**回潮副本**。故每条同名歧义的
# 裁定目标 = 该 basename 在编号分层的唯一命中。
#
# 该口径可由仓库现状直接算出，不依赖人工另写一份对照表——台账与守卫都从这里取，
# 避免"台账一份裁定、守门另一份裁定"的双源。

# 代码同名引用（`sleep.py` / `__init__.py` 这类）无法用"编号分层唯一命中"裁定——
# 同 basename 的模块在代码树里天然多份。这 11 条按归档文档的**上下文**逐条裁定，
# 判据写在这里（唯一一份），台账与守卫都从这里取。
CODE_REFERENCE_RULINGS = {
    ("docs/11-legacy/NEURON_MEME_EVALUATION.md", "104"):
        ("neurova/cognitive_layers/memory_layer/sleep.py", "2.5 节「睡眠整合」行，指记忆层睡眠巩固模块"),
    ("docs/11-legacy/NEURON_MEME_EVALUATION.md", "118"):
        ("neurova/cognitive_layers/memory_layer/storage.py", "3.1 节「文件存储」行，指记忆层 JSON 后端存储"),
    ("docs/11-legacy/TOOL_LAYER_MAP.md", "136"):
        ("tests/unit/execution/test_tool_engine.py", "「单元测试」行指 ToolEngine 单测现行归档位置"),
    ("docs/11-legacy/audit-skeleton-and-spec-compliance.md", "124"):
        ("neurova/cognitive_layers/memory_layer/bayesian_eki/__init__.py", "1.5 节正文即 bayesian_eki 目录"),
    ("docs/11-legacy/audit-skeleton-and-spec-compliance.md", "159"):
        ("neurova/cognitive_layers/memory_layer/bayesian_eki/__init__.py", "同 1.5 节评估段"),
    ("docs/11-legacy/audit-skeleton-and-spec-compliance.md", "162"):
        ("neurova/cognitive_layers/memory_layer/bayesian_eki/__init__.py", "同 1.5 节建议段"),
    ("docs/11-legacy/audit-skeleton-and-spec-compliance.md", "304"):
        ("neurova/cognitive_layers/memory_layer/bayesian_eki/__init__.py", "P3 第 7 项 bayesian_eki 诚实标注"),
    ("docs/11-legacy/最终UI开发方案.md", "277"):
        ("", "前端已无 `api/chat.ts`：对话 API 现由 `NeurUI/src/api/modules/console.ts` 承载"),
    ("docs/11-legacy/最终UI开发方案.md", "278"):
        ("NeurUI/src/api/modules/collaboration.ts", "5.3 节「API 模块」行指 API 模块而非 store"),
    ("docs/11-legacy/源码图谱.md", "1588"):
        ("", "知识层节点列举的 `neurova/knowledge/integration/` 全史未入库"),
    ("docs/11-legacy/源码图谱.md", "1598"):
        ("tests/integration/test_closed_loop.py", "33-测试层节点指端到端闭环测试"),
}

RULING_SETTLED = "已裁定"
RULING_NO_TARGET = "未决·编号分层无候选"
RULING_TARGET_MISSING = "未决·裁定目标缺失"
# 归档文档引用了一个从未入库的路径——裁定为「源已删除」，以显式文本交代去处
RULING_DELETED_SOURCE = "源已删除（已交代去处）"


def adjudicatedRows() -> list:
    """逐条裁定基线里的同名歧义，返回带裁定结果的记录。

    基线的身份是（文件, 行号, 引用）；裁定目标由当前文件树解析。
    """
    if not AMBIGUITY_BASELINE.is_file():
        return []
    byBasename = indexByBasename(trackedFiles())
    rows = []
    for line in io.open(AMBIGUITY_BASELINE, encoding="utf-8").read().splitlines():
        parts = line.split("|")
        if len(parts) != 3:
            continue
        path, lineNo, ref = parts[0], parts[1], parts[2]
        candidates = byBasename.get(ref.split("/")[-1], [])
        ruling = CODE_REFERENCE_RULINGS.get((path, lineNo))
        if ruling is not None:
            target = ruling[0]
            status = RULING_SETTLED if target else RULING_DELETED_SOURCE
        else:
            canonical = sorted(c for c in candidates if numberedLayer(c))
            if len(canonical) == 1:
                target, status = canonical[0], RULING_SETTLED
            elif canonical:
                target, status = "—", RULING_NO_TARGET
            else:
                target, status = "—", RULING_TARGET_MISSING
        rows.append({"file": path, "line": lineNo, "ref": ref,
                     "target": target, "status": status,
                     "candidates": sorted(candidates)})
    return rows


def renderAdjudication(rows: list) -> str:
    """渲染逐条裁定表。

    裁定表与「悬空引用总表」的判定不是一回事：总表的 `同名歧义` 是**检测信号**
    （扫到多个同名候选）；本表是**决定**（该指哪一份，或源已删除 + 去处）。
    代码同名引用（`sleep.py` 等）在总表里永远是歧义形态，但在本表有明确裁定——
    两者并存不是矛盾，是本表存在的意义。
    """
    lines = [
        ADJUDICATION_BEGIN,
        "| 文件 | 行 | 引用 | 候选数 | 裁定目标 | 状态 |",
        "|------|----|------|-------|----------|------|",
    ]
    for row in sorted(rows, key=lambda r: (r["file"], int(r["line"]), r["ref"])):
        state = row["status"]
        target = row["target"]
        rendered = _code(target) if target and target != "—" else "—"
        lines.append(
            f"| `{row['file']}` | {row['line']} | {_code(row['ref'])} "
            f"| {len(row['candidates'])} | {rendered} | {state} |"
        )
    lines.append(ADJUDICATION_END)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 活跃层引用可达性（第三类形态：指向不存在的具体文件）
# ---------------------------------------------------------------------------
# 根因：文档目录重排 `fd7ea92c` / `5f94b93d` 把文档 `git mv` 进编号分层，之后
# `3b5d7e80` 又把旧路径还原回来；`663faa5d` 退役 43 篇文档时只删文件。三次都
# **没有同批改指引用方**，于是在**活跃层**留下了指向不存在文件的引用。
#
# 与已收口的两类形态的分界（判据只此一份，守卫从这里取数）：
#
# - `docs/11-legacy/` 归档层的悬空引用 → 登记台账（`test_legacy_ref_ledger_guard.py`）；
# - 活跃层指向「已退役目录」的引用 → `test_docs_retired_tree_refs_guard.py`；
# - **活跃层指向「不存在的具体文件」的引用 → 本函数**。
#
# 归档层不在本判据内：`05-reports` / `06-bugfix` / `09-dev-progress` 陈述的是**当时**
# 的代码结构与路径，改成今天的形态反而让历史记录与历史事实不符（与台账口径一致）。
# 随仓库分发的第三方文档（`embedding/`、`models/`）不属本仓文档体系，同样排除。

#: 活跃层（当下可读面）：编号分层 + 仍在使用的非编号目录 + 仓库入口文档
ACTIVE_LAYERS = frozenset({
    "docs/0-index/", "docs/01-architecture/", "docs/02-api/", "docs/03-user-guide/",
    "docs/04-plans/", "docs/08-research/", "docs/10-configuration/", "docs/architecture/",
    "docs/architecture-model/", "docs/security/", "docs/specs/", "docs/superpowers/",
})

#: 仓库入口文档（不在 docs/ 子目录，但同属活跃层）
ENTRY_DOCUMENTS = frozenset({
    "README.md", "AGENTS.md", "CONTRIBUTING.md", "SECURITY.md",
    "docs/INDEX.md", "docs/CONTEXT.md", "docs/README.md",
})

#: 历史层：只登记、不就地改写（引用陈述的是当时结构）
HISTORICAL_LAYERS = frozenset({
    "docs/05-reports/", "docs/06-bugfix/", "docs/09-dev-progress/", "docs/11-legacy/",
})

#: 随仓库分发的第三方文档，不属本仓文档体系
VENDORED_PREFIXES = ("embedding/", "models/")

#: HTML 里的本地资源引用（`<img src>` / `<a href>`）——只扫 Markdown 链接会留盲区
HTML_REF_PATTERN = re.compile(
    r"""<(?P<tag>img|a|iframe|link|source)\b[^>]*?\b(?:src|href)\s*=\s*["'](?P<target>[^"']+)["']""",
    re.IGNORECASE,
)

#: 非仓库内路径（外链 / 锚点 / 邮件 / 协议）
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "data:", "javascript:", "file:")


def activeLayerDocuments() -> list:
    """活跃层文档清单（编号分层 + 入口文档 + docs/ 根下的编号文档）。"""
    documents = []
    for path in trackedFiles():
        if not path.endswith(".md") or path.startswith(VENDORED_PREFIXES):
            continue
        if path in ENTRY_DOCUMENTS or path.startswith(tuple(ACTIVE_LAYERS)):
            documents.append(path)
        elif numberedLayer(path) is False and path.startswith("docs/") and path.count("/") == 1:
            # docs/<编号文档>.md：编号分层之外但仍在活跃使用（如 CUA能力台账.md）
            documents.append(path)
    return documents


def _codeSpanRanges(line: str) -> list:
    """成对反引号 run 覆盖的区间——其中的示例语法不是可点击引用。"""
    runs, index, length = [], 0, len(line)
    while index < length:
        if line[index] != "`":
            index += 1
            continue
        runEnd = index
        while runEnd < length and line[runEnd] == "`":
            runEnd += 1
        runs.append((index, runEnd - index))
        index = runEnd
    paired, ranges = set(), []
    for position, (start, runLength) in enumerate(runs):
        if position in paired:
            continue
        for other in range(position + 1, len(runs)):
            if other in paired or runs[other][1] != runLength:
                continue
            paired.add(position)
            paired.add(other)
            ranges.append((start, runs[other][0] + runLength))
            break
    return ranges


def scanDocumentLinks(path: Path, byBasename: dict) -> list:
    """扫描单个文档里的**仓库内**引用，返回不可达条目（可达的引用不返回）。

    覆盖三种书写形态：Markdown 链接 `[文字](目标)`、图片 `![alt](目标)`、
    HTML 的 `<img src>` / `<a href>`。围栏代码块与行内代码里的示例语法不算引用
    （它们是**被测内容**，不是可点击目标）。
    """
    text = io.open(path, encoding="utf-8", errors="replace").read()
    relative = displayPath(path)
    found, inFence = [], False
    for lineNo, line in enumerate(text.splitlines(), 1):
        if _isFenceLine(line):
            inFence = not inFence
            continue
        if inFence:
            continue
        skip = _codeSpanRanges(line)
        candidates = [(m.start(), m.group(1).strip(), m.group(2).strip())
                      for m in LINK_PATTERN.finditer(line)]
        candidates += [(m.start(), m.group("target").strip(), m.group("target").strip())
                       for m in HTML_REF_PATTERN.finditer(line)]
        for position, label, target in sorted(candidates):
            if any(start <= position < stop for start, stop in skip):
                continue
            literal = target.split("#")[0].strip()
            if not literal or literal.startswith(EXTERNAL_PREFIXES):
                continue
            if PLACEHOLDER_PATTERN.search(literal):
                continue
            verdict, hit = resolveTarget(literal, path, byBasename)
            if verdict == VERDICT_REACHABLE:
                continue
            found.append({"file": relative, "line": lineNo, "label": label,
                          "ref": literal, "verdict": verdict, "hit": hit})
    return found


def activeLayerDangling() -> list:
    """活跃层全部不可达引用（按文件、行号排序）。"""
    byBasename = indexByBasename(trackedFiles())
    found = []
    for relative in sorted(activeLayerDocuments()):
        found.extend(scanDocumentLinks(PROJECT_ROOT / relative, byBasename))
    return sorted(found, key=lambda item: (item["file"], item["line"], item["ref"]))


def _entry(file: str, line: int, ref: str, verdict: str, hit: str) -> dict:
    return {"file": file, "line": line, "ref": ref, "verdict": verdict, "hit": hit}


# ---------------------------------------------------------------------------
# 归档层「是否影响当下导航」筛选（Issue #68 下一层）
# ---------------------------------------------------------------------------
# 归档层 1800 余条悬空引用不是同一件事，不能一视同仁：
#
# - 绝大多数只陈述**当时**的路径，读者今天走不到那篇文档，改它等于改写历史事实；
# - 真正会把人带错路的只有两类：**当下走得到**的文档里，**点开就 404** 的可点击引用，
#   以及**专职指路**的文档里失效的指路条目。
#
# 判据两要件（全部成立才入筛，只此一份，台账与守卫同源取数）：
#
# 1. **载体在当下导航图里可达**：从仓库入口文档出发，沿「可解析链接 + 目录链接」
#    做传递闭包（与 `activeLayerDangling` 同一套解析，不另写判据）。走不到的文档，
#    它的失效引用不构成当下导航问题。
# 2. **载体满足二者之一**：
#    - `甲·可点击引用`：Markdown 链接 / 图片 / HTML `src|href`，点开即 404。
#      **硬零**——与活跃层同一条纪律，本类必须修完。
#    - `乙·指路条目`：载体是**导航承载文档**（`INDEX.md` / `README.md` 文件名，
#      或标题含「清单 / 索引 / 图谱 / 单一事实源」）。这类文档存在的意义就是
#      把人指向别处，其中失效的条目即使写成行内码也会把人带错，
#      故不适用「归档层不就地改写」——但整篇级过期不是改路径能解决的，登记 + 立项。
#
# 不入筛的三类（豁免理由可复算，不接受「人工看过了没事」）：
#   - `无当下读者`：载体不在导航图里；
#   - `描述性行内码`：既不可点击、载体也不是导航承载文档——归档正文里的路径陈述；
#   - `占位/模板路径`（`daily_reports/YYYY-MM-DD.md`、`neurova/xxx/yyy.py`）不是真实目标。

#: 导航承载文档的标题特征（文档存在的意义是指路，不是叙事）
NARRATIVE_TITLE_PATTERN = re.compile(r"清单|索引|图谱|单一事实源")
#: 占位/模板形态的具体路径：不是任何真实目标，改指无从谈起
PLACEHOLDER_PATH_PATTERN = re.compile(r"YYYY|MM-DD|\bxxx\b|\byyy\b|<[^>]+>")

IMPACT_FORM_CLICKABLE = "甲·可点击引用"
IMPACT_FORM_POINTER = "乙·指路条目"

DISPOSITION_REPOINT = "改指真实路径"
DISPOSITION_DESTINATION = "改显式文本交代去处"
DISPOSITION_PROJECT = "单独立项（整篇级过期）"

EXEMPT_UNREACHABLE = "无当下读者（不在导航图内）"
EXEMPT_NARRATIVE = "描述性行内码（不可点击且非指路文档）"
EXEMPT_PLACEHOLDER = "占位/模板路径（非真实目标）"


def documentLinksFrom(relative: str) -> list:
    """单篇文档里**仓库内**的引用目标原文（Markdown 链接 + HTML src/href）。

    只取目标字符串，不判可达性——可达性解析统一走 `resolveTarget`，
    避免"导航图一份解析、悬空判定另一份解析"的双源。
    """
    path = PROJECT_ROOT / relative
    if not path.is_file():
        return []
    text = io.open(path, encoding="utf-8", errors="replace").read()
    targets, inFence = [], False
    for line in text.splitlines():
        if _isFenceLine(line):
            inFence = not inFence
            continue
        if inFence:
            continue
        skip = _codeSpanRanges(line)
        matches = [(m.start(), m.group(2).strip()) for m in LINK_PATTERN.finditer(line)]
        matches += [(m.start(), m.group("target").strip()) for m in HTML_REF_PATTERN.finditer(line)]
        for position, target in sorted(matches):
            if any(start <= position < stop for start, stop in skip):
                continue
            targets.append(target)
    return targets


#: 导航起点：仓库入口文档 + `docs/` 目录自述的唯一入口。
#: `docs/0-index/README.md` 正文写明"本索引是 `docs/` 目录的唯一入口"，且被
#: `AGENTS.md` 点名，读者从根目录出发的第一跳就是它——不认它，`docs/` 下
#: 按领域分层的文档全都成了"无人走得到"，筛选会退化成空集（自证见守卫）。
NAVIGATION_ROOTS = ENTRY_DOCUMENTS | frozenset({"docs/0-index/README.md"})


def readerReachableDocuments() -> set:
    """当下导航图里可达的文档（从导航起点做传递闭包）。

    目录链接（`docs/09-dev-progress/module_designs/`）算作可达其下的全部文档——
    读者点进目录就能逐篇打开。起点取自 `NAVIGATION_ROOTS`（单源）。
    """
    files = set(trackedFiles())
    byBasename = indexByBasename(trackedFiles())
    reached = set(NAVIGATION_ROOTS)
    pending = list(NAVIGATION_ROOTS)
    while pending:
        current = pending.pop()
        base = (PROJECT_ROOT / current).parent
        for target in documentLinksFrom(current):
            literal = target.split("#")[0].strip()
            if not literal or literal.startswith(EXTERNAL_PREFIXES):
                continue
            if literal.endswith("/"):
                folder = base / literal
                if not folder.is_dir():
                    continue
                prefix = displayPath(folder.resolve()) + "/"
                for path in files:
                    if path.startswith(prefix) and path.endswith(".md") and path not in reached:
                        reached.add(path)
                        pending.append(path)
                continue
            verdict, hit = resolveTarget(literal, PROJECT_ROOT / current, byBasename)
            if verdict == VERDICT_REACHABLE and hit in files and hit.endswith(".md") and hit not in reached:
                reached.add(hit)
                pending.append(hit)
    return reached


def isNavigationBearing(relative: str) -> bool:
    """载体是否是「专职指路」的文档（INDEX/README 文件名，或标题写明清单/索引/图谱/单一事实源）。"""
    if relative.split("/")[-1] in ("INDEX.md", "README.md"):
        return True
    path = PROJECT_ROOT / relative
    if not path.is_file():
        return False
    for line in io.open(path, encoding="utf-8", errors="replace").read().splitlines():
        heading = re.match(r"^#\s+(.*)$", line.strip())
        if heading:
            return bool(NARRATIVE_TITLE_PATTERN.search(heading.group(1)))
    return False


def archiveDanglingUnion() -> list:
    """归档层全部悬空引用，**两种书写形态取并集**。

    `scanDirectory` 只看行内码与空标签；可点击链接的目标在另一条解析路上
    （`scanDocumentLinks`）。只看其一都会漏——这正是前几轮"洞换个位置"的来路。
    每条带 `form` 标记（`行内码` / `可点击`），供筛选区分处置。
    """
    byBasename = indexByBasename(trackedFiles())
    found = {}
    for layer in sorted(HISTORICAL_LAYERS):
        directory = PROJECT_ROOT / layer.rstrip("/")
        if not directory.is_dir():
            continue
        for item in scanDirectory(directory):
            found[(item["file"], item["line"], item["ref"])] = dict(item, form="行内码")
        for path in sorted(directory.rglob("*.md")):
            relative = displayPath(path)
            if relative in LEDGER_DOCUMENTS:
                continue
            for item in scanDocumentLinks(path, byBasename):
                key = (item["file"], item["line"], item["ref"])
                if key in found:
                    continue
                found[key] = dict(item, form="可点击")
    return sorted(found.values(), key=lambda item: (item["file"], item["line"], item["ref"]))


def navigationImpactRefs() -> list:
    """筛选出**真正影响当下导航**的归档层失效引用，并给出逐条处置。

    不入筛的条目由 `navigationImpactExemptions()` 按理由计数登记——
    筛选不是"眼不见为净"，被豁免的每一条都能说出为什么。
    """
    reached = readerReachableDocuments()
    rows = []
    for item in archiveDanglingUnion():
        if PLACEHOLDER_PATH_PATTERN.search(item["ref"]):
            continue
        if item["file"] not in reached:
            continue
        if item["form"] == "可点击":
            form = IMPACT_FORM_CLICKABLE
            disposition = (DISPOSITION_REPOINT if item["verdict"] == VERDICT_MOVED
                           else DISPOSITION_DESTINATION)
        elif isNavigationBearing(item["file"]):
            form = IMPACT_FORM_POINTER
            disposition = DISPOSITION_PROJECT
        else:
            continue
        rows.append(dict(item, form=form, disposition=disposition))
    return rows


def navigationImpactExemptions() -> dict:
    """被筛掉的条目按理由计数（理由取自同一判据，不另写一套）。"""
    reached = readerReachableDocuments()
    counters = {EXEMPT_UNREACHABLE: 0, EXEMPT_NARRATIVE: 0, EXEMPT_PLACEHOLDER: 0}
    for item in archiveDanglingUnion():
        if PLACEHOLDER_PATH_PATTERN.search(item["ref"]):
            counters[EXEMPT_PLACEHOLDER] += 1
        elif item["file"] not in reached:
            counters[EXEMPT_UNREACHABLE] += 1
        elif item["form"] != "可点击" and not isNavigationBearing(item["file"]):
            counters[EXEMPT_NARRATIVE] += 1
    return counters


#: 入筛指路条目数的棘轮基线（只降不升）
POINTER_ENTRY_BASELINE = PROJECT_ROOT / "tests" / "unit" / "archiveNavPointerBaseline.txt"

NAV_IMPACT_BEGIN = "<!-- NAV-IMPACT:TABLE:BEGIN -->"
NAV_IMPACT_END = "<!-- NAV-IMPACT:TABLE:END -->"
NAV_IMPACT_SUMMARY_BEGIN = "<!-- NAV-IMPACT:SUMMARY:BEGIN -->"
NAV_IMPACT_SUMMARY_END = "<!-- NAV-IMPACT:SUMMARY:END -->"


def renderNavigationImpactSummary(rows: list) -> str:
    """入筛条目总数、形态分布、按载体分布，以及豁免理由计数。"""
    byForm, byFile = {}, {}
    for row in rows:
        byForm[row["form"]] = byForm.get(row["form"], 0) + 1
        byFile[row["file"]] = byFile.get(row["file"], 0) + 1
    counters = navigationImpactExemptions()
    lines = [
        NAV_IMPACT_SUMMARY_BEGIN,
        f"归档层悬空引用共 **{len(archiveDanglingUnion())}** 条，"
        f"其中**影响当下导航 {len(rows)} 条**（"
        + " · ".join(f"{form} {count}" for form, count in sorted(byForm.items()))
        + "）。",
        "",
        "| 载体文档 | 入筛条数 |",
        "|------|------|",
    ]
    for path, count in sorted(byFile.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| `{path}` | {count} |")
    lines.append("")
    lines.append("余下按理由豁免（可复算，非人工判断）：")
    lines.append("")
    lines.append("| 豁免理由 | 条数 |")
    lines.append("|------|------|")
    for reason, count in sorted(counters.items()):
        lines.append(f"| {reason} | {count} |")
    lines.append(NAV_IMPACT_SUMMARY_END)
    return "\n".join(lines)


def renderNavigationImpact(rows: list) -> str:
    """入筛条目逐条台账（载体 / 行号 / 引用 / 形态 / 可达性判定 / 处置）。"""
    lines = [
        NAV_IMPACT_BEGIN,
        "| 载体文档 | 行 | 引用 | 形态 | 可达性判定 | 处置 |",
        "|------|----|------|------|------|------|",
    ]
    for row in sorted(rows, key=lambda r: (r["file"], r["line"], r["ref"])):
        lines.append(
            f"| `{row['file']}` | {row['line']} | {_code(row['ref'])} | {row['form']} "
            f"| {row['verdict']} | {row['disposition']} |"
        )
    lines.append(NAV_IMPACT_END)
    return "\n".join(lines)


def scanDirectory(targetDir: Path) -> list:
    """扫描目录下全部 Markdown，按（文件, 行号, 引用）去重。"""
    byBasename = indexByBasename(trackedFiles())
    entries, seen = [], set()
    for path in sorted(targetDir.rglob("*.md")):
        if displayPath(path) in LEDGER_DOCUMENTS:
            continue
        for item in scanFile(path, byBasename):
            key = (item["file"], item["line"], item["ref"])
            if key in seen:
                continue
            seen.add(key)
            entries.append(item)
    return entries


# 台账机器生成区的边界标记：守卫据此定位并比对，人工说明写在标记之外
TABLE_BEGIN = "<!-- LEDGER:TABLE:BEGIN -->"
TABLE_END = "<!-- LEDGER:TABLE:END -->"
ADJUDICATION_BEGIN = "<!-- ADJUDICATION:TABLE:BEGIN -->"
ADJUDICATION_END = "<!-- ADJUDICATION:TABLE:END -->"

AMBIGUITY_BASELINE = PROJECT_ROOT / "tests" / "unit" / "docsAmbiguityBaseline.txt"

SUMMARY_BEGIN = "<!-- LEDGER:SUMMARY:BEGIN -->"
SUMMARY_END = "<!-- LEDGER:SUMMARY:END -->"


def _cell(value: str) -> str:
    """表格单元格转义：管道符与空值。"""
    text = (value or "").replace("|", "\\|").strip()
    return text if text else "（空）"


def _code(ref: str) -> str:
    """把引用渲染成行内代码；空反引号用占位符避免又把表格打散。"""
    if ref == "``":
        return "空反引号"
    return "`" + ref.replace("`", "'") + "`"


def renderSummary(entries: list) -> str:
    """渲染总数与分布摘要（也是生成物——手写的数字必然漂移）。"""
    byVerdict, byFile = {}, {}
    for item in entries:
        byVerdict[item["verdict"]] = byVerdict.get(item["verdict"], 0) + 1
        byFile[item["file"]] = byFile.get(item["file"], 0) + 1
    lines = [
        SUMMARY_BEGIN,
        f"共 **{len(entries)}** 条。按判定分布："
        + " · ".join(f"**{v} {byVerdict.get(v, 0)}**" for v in VERDICTS if byVerdict.get(v)),
        "",
        "| 文件 | 条数 |",
        "|------|------|",
    ]
    for path, count in sorted(byFile.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| `{path}` | {count} |")
    lines.append(SUMMARY_END)
    return "\n".join(lines)


def renderTable(entries: list) -> str:
    """把扫描结果渲染成台账表格（行按文件、行号排序，保证可复现）。"""
    lines = [
        TABLE_BEGIN,
        "| 文件 | 行 | 引用 | 判定 | 命中 / 候选 |",
        "|------|----|------|------|-------------|",
    ]
    for item in sorted(entries, key=lambda e: (e["file"], e["line"], e["ref"])):
        lines.append(
            f"| `{item['file']}` | {item['line']} | {_code(item['ref'])} "
            f"| {item['verdict']} | {_cell(item['hit'])} |"
        )
    lines.append(TABLE_END)
    return "\n".join(lines)


def main(argv: list) -> int:
    positional = [a for a in argv[1:] if not a.startswith("--")]
    target = Path(positional[0]) if positional else PROJECT_ROOT / "docs" / "11-legacy"
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    entries = scanDirectory(target)
    if "--json" in argv:
        print(json.dumps(entries, ensure_ascii=False, indent=1))
    elif "--markdown" in argv:
        print(renderSummary(entries))
        print()
        print(renderTable(entries))
    else:
        summary = {}
        for item in entries:
            summary[item["verdict"]] = summary.get(item["verdict"], 0) + 1
        print(f"{target.relative_to(PROJECT_ROOT)}: 悬空引用 {len(entries)} 条")
        for verdict in VERDICTS:
            if summary.get(verdict):
                print(f"  {verdict}: {summary[verdict]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
