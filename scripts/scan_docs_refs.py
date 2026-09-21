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


def _entry(file: str, line: int, ref: str, verdict: str, hit: str) -> dict:
    return {"file": file, "line": line, "ref": ref, "verdict": verdict, "hit": hit}


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
