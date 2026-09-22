# -*- coding: utf-8 -*-
"""仓内 AST 扫描的唯一入口（跨用例复用的解析预算）。

根因（Issue #148，构建 `cnb-2p6-1k347lfg1` 实测）：受保护子集里有若干个
「单源/收口点」判据，判据内容是「仓库里不得出现第二处实现」，实现方式却是
**把全仓每个 `.py` 都 `ast.parse` 一遍再 `ast.walk` 一遍**。实测解析成本
≈ 1.4 ms/文件（本机 1000 文件 ≈ 1.4s、2000 文件 ≈ 2.9s），词法遍历再叠 1.5 倍。

于是判据把**代码总量**编码成了**时间上界**：单个用例 4–6s，与另外 170 个
受保护文件共享机器时撞 `pytest-timeout` 的 30s 默认墙钟（本次构建即
`Failed: Timeout (>30.0s) from pytest-timeout`）。单跑绿、全套红——正是
`AGENTS.md` 修复教义第 2 条点名的「判据与机器速度捆绑」形态：
判据本身与代码行数、与机器快慢都无关，墙钟上界不会因为它变松而更成立。

处置分两层，**都在本模块里收口**，不在各守卫里各写一套：

1. **解析按前缀择优**：`moduleSourcesUnder()` / `filesUnder()` 只列目标子树；
2. **同进程内复用**：`parsedModules()` / `walkedModules()` 以「文件路径 + mtime +
   大小」为键整进程缓存解析结果与词法节点，同一批受保护用例里的 N 个守卫共用
   一次解析。缓存键含 mtime 与 size，改文件即失效——不做「一次解析永久有效」
   这种会静默漏报的缓存。

口径只写一份：任何新增的跨文件 AST 判据都走本模块，不自己 `ast.parse`
（`AGENTS.md` 修复教义第 6 条：不新造平行体系）。
"""

from __future__ import annotations

import ast
import functools
from pathlib import Path
from typing import Iterable, Iterator, List, NamedTuple, Tuple

#: 仓根：与 `tests/repo_paths.py` 同口径（`__file__` 定位，禁写死开发机路径）
REPO_ROOT = Path(__file__).resolve().parents[1]

#: 生产代码根：判据若只谈「生产侧」，就不该把 tests/ 一起 parse
PRODUCTION_ROOT = REPO_ROOT / "neurova"


def filesUnder(root: Path, suffix: str = ".py") -> List[Path]:
    """`root` 子树下的源码文件清单（跳过字节码缓存目录，路径排序稳定）。"""
    return sorted(
        path for path in root.rglob("*" + suffix)
        if "__pycache__" not in path.parts
    )


#: 文本预筛词表：`attributePrefilter` 的默认词。判据若只找 `X.attest(...)`，
#: 连 `attest` 三个字都没出现的文件不可能命中，无需 parse。
def textHints(*names: str) -> Tuple[str, ...]:
    """把谓词名转成文本预筛词（`attest` → `attest`；`record_metric` → `record_metric`）。"""
    return tuple(names)


def _cacheKey(path: Path) -> Tuple[str, int, int]:
    """缓存键 = 路径 + mtime(ns) + 大小：文件一改即失效，不留下会漏报的陈旧缓存。"""
    stat = path.stat()
    return (str(path), stat.st_mtime_ns, stat.st_size)


class SourceRef(NamedTuple):
    """一次读取的源码：路径 + 内容戳 + 文本。

    解析与遍历的缓存键都取自它，故「同一份内容只编译一次」；
    戳含 mtime 与 size，改文件必然失效——不做「一次解析永久有效」这种会在
    同一进程里静默漏报的缓存。
    """

    path: Path
    stamp: Tuple[str, int, int]
    code: str


def sourceRefsUnder(root: Path, suffix: str = ".py",
                    hints: Tuple[str, ...] = ()) -> List[SourceRef]:
    """`root` 子树下的源码引用清单：文件系统只读一遍，交给解析/遍历缓存。

    `hints` 是**文本预筛**：只要给定，就只保留文本里含任一 hint 的文件。
    这不是放宽判据（`sourceRefsUnder` 的键仍是全量清单），而是**判据的充分条件**：
    谓词是 `X.<name>(...)`，连 `<name>` 三个字都没出现的文件不可能命中。
    实测 `neurova/` 1014 文件里含 `attest` 的只有 4 个——预筛把「解析量」从
    **代码总量**变成**命中面**，判据与文件数彻底脱钩（0.06s vs 6.5s）。
    """
    refs = [SourceRef(path, _cacheKey(path),
                      path.read_text(encoding="utf-8", errors="replace"))
            for path in filesUnder(root, suffix)]
    if not hints:
        return refs
    return [ref for ref in refs if any(hint in ref.code for hint in hints)]


@functools.lru_cache(maxsize=None)
def _cachedCode(stamp: Tuple[str, int, int]) -> str:
    """按内容戳缓存文件文本：同进程里 N 个跨文件判据只读盘一次。"""
    return Path(stamp[0]).read_text(encoding="utf-8", errors="replace")


def sourceCode(path: Path) -> str:
    """单文件源码文本（走同一份内容戳缓存；改文件即失效）。"""
    return _cachedCode(_cacheKey(path))


@functools.lru_cache(maxsize=None)
def _cachedParse(stamp: Tuple[str, int, int], code: str) -> ast.AST:
    """按**代码文本**缓存语法树；`compile()` 是这条链上唯一的大头。"""
    return ast.parse(code)


def parsedModules(root: Path, suffix: str = ".py") -> List[Tuple[Path, ast.AST]]:
    """`(路径, 语法树)` 清单，整进程复用（同一份文本只编译一次）。"""
    return [(ref.path, _cachedParse(ref.stamp, ref.code))
            for ref in sourceRefsUnder(root, suffix)]


def walkedModules(root: Path, suffix: str = ".py",
                  hints: Tuple[str, ...] = ()) -> Iterator[Tuple[Path, ast.AST]]:
    """逐节点产出 `(路径, 节点)`（含 Module 本身；命中缓存时零解析）。"""
    for ref in sourceRefsUnder(root, suffix, hints):
        for node in _cachedNodes(ref):
            yield ref.path, node


@functools.lru_cache(maxsize=None)
def _cachedNodes(ref: SourceRef) -> Tuple[ast.AST, ...]:
    """整棵树的节点元组，按源码引用整进程复用。

    词法遍历按文件整进程缓存（`_cachedNodes` 之上是 `_cachedScan`，命中时连
    `tuple()` 都不重建）：`ast.walk` 的 deque + `iter_child_nodes` 在 1000 文件
    量级上与 `compile()` 同量级（实测 4.3s vs 5.1s），只缓存解析不缓存遍历
    等于把这笔账留着。
    """
    return tuple(ast.walk(_cachedParse(ref.stamp, ref.code)))


def nodeScan(root: Path, suffix: str = ".py",
             hints: Tuple[str, ...] = ()) -> Iterator[Tuple[Path, ast.AST]]:
    """**惰性**产出 `(路径, 节点)`：调用方直接 `for` 遍历，不物化全量元组。

    为什么不返回元组：150 万节点的元组**即便全部命中缓存**，重建也要 2s
    （`tuple()` + 解的 150 万个 `(path, node)` 对）。返回迭代器则逐文件取
    `_cachedNodes`（按文件缓存的节点元组），命中时近零成本。

    传入 `hints` 即启**文本预筛**（见 `sourceRefsUnder`）：判据是 `X.<name>`
    形态时，连 `<name>` 都没出现的文件不可能命中，解析量从「代码总量」降到
    「命中面」（实测 0.06s vs 6.5s）。
    """
    return walkedModules(root, suffix, hints)


def callNodes(root: Path, attribute: str, suffix: str = ".py",
              hints: Tuple[str, ...] = ()) -> Iterator[Tuple[Path, ast.AST]]:
    """子树里 `X.<attribute>(...)` 的**节点** `(路径, 节点)`（带文本预筛）。

    与 `callSites` 同一份取数，只是把节点本体一并交出——判据要看实参时用它
    （例如「`record_metric(RSIMetrics.X)` 的 X 有哪些」）。
    """
    for ref in sourceRefsUnder(root, suffix, hints or textHints(attribute)):
        for node in _cachedNodes(ref):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == attribute):
                yield ref.path, node


def classDefsIn(root: Path, className: str, suffix: str = ".py") -> List[Tuple[Path, int]]:
    """子树里 `class <className>` 的定义点 `(路径, 行号)`（带文本预筛）。

    只认**顶层** `tree.body`：嵌套类同名不算「另一份实现」，但缩进写法的
    顶层类定义也是顶层节点，故拓扑不受影响。
    """
    hits: List[Tuple[Path, int]] = []
    needle = f"class {className}"
    for ref in sourceRefsUnder(root, suffix, (needle,)):
        for node in _cachedParse(ref.stamp, ref.code).body:
            if isinstance(node, ast.ClassDef) and node.name == className:
                hits.append((ref.path, node.lineno))
    return hits


def callSites(root: Path, attribute: str, suffix: str = ".py") -> List[Tuple[Path, int]]:
    """`root` 子树里 `X.<attribute>(...)` 的命中点 `(路径, 行号)`（带文本预筛）。

    这是「某调用点有几处」这类判据的**推荐入口**：预筛 + 逐文件解析后即时走查，
    不物化全量节点元组（实测 0.06s vs 6.5s）。
    """
    hits: List[Tuple[Path, int]] = []
    for ref in sourceRefsUnder(root, suffix, textHints(attribute)):
        for node in _cachedNodes(ref):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == attribute):
                hits.append((ref.path, node.lineno))
    return hits


def callsTo(scan: Iterable[Tuple[Path, ast.AST]], attribute: str) -> List[Tuple[Path, int]]:
    """扫描结果里 `X.<attribute>(...)` 的命中点 `(路径, 行号)`（已物化的 scan）。"""
    return [
        (path, node.lineno) for path, node in scan
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == attribute
    ]


def importsOf(scan: Iterable[Tuple[Path, ast.AST]], moduleName: str) -> List[Tuple[Path, int]]:
    """扫描结果里 `import moduleName` / `from moduleName import ...` 的命中点。

    判据是「代码里有引用」，不是「文本里提过」——注释与字符串不算，故走 AST。
    `scan` 可以是 `nodeScan()` 的惰性迭代器（推荐），也可以是已物化的序列。
    """
    hits: List[Tuple[Path, int]] = []
    for path, node in scan:
        if isinstance(node, ast.ImportFrom) and (node.module or "") == moduleName:
            hits.append((path, node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == moduleName:
                    hits.append((path, node.lineno))
    return hits


def relativeToRepo(path: Path) -> str:
    """仓内相对路径（统一正斜杠，报错信息跨平台一致）。"""
    return path.relative_to(REPO_ROOT).as_posix()
