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

处置分三层，**都在本模块里收口**，不在各守卫里各写一套：

1. **解析按前缀择优**：`moduleSourcesUnder()` / `filesUnder()` 只列目标子树；
2. **同进程内复用**：`parsedModules()` / `walkedModules()` 以「文件路径 + mtime +
   大小」为键整进程缓存解析结果与词法节点，同一批受保护用例里的 N 个守卫共用
   一次解析。缓存键含 mtime 与 size，改文件即失效——不做「一次解析永久有效」
   这种会静默漏报的缓存。
3. **常驻图按步长退役**（Issue #197 登记后本轮实证）：第 2 层的缓存是
   `maxsize=None`，保留下来的每棵树都还留在 gen2 的扫描面里，于是 gen2 每扫一遍
   都要走完整棵常驻图——**成本随代码总量涨**，与本文件开头的根因同形，只是账单
   记在 GC 上（实测 1787 个测试文件全量解析后单次 gen2 1030ms vs 不留 0.78ms）。
   `RETIRE_STEP` 控制退役步长：常驻树每新增这么多棵就把整棵图移出扫描分代
   （读侧 `retireStats()` 给出 `retires` / `pending` / `frozen`）。**保留量不变**（跨用例仍只编译一次），变的只是
   扫描面——故不得改用 LRU 限制保留量：被淘汰的树要在下一条判据里重新解析，
   实测 miss 从 1586 涨到 4790，反而更慢。

口径只写一份：任何新增的跨文件 AST 判据都走本模块，不自己 `ast.parse`
（`AGENTS.md` 修复教义第 6 条：不新造平行体系）。

本模块对外有**两条**入口，按「这棵树会不会被重复扫」选：

- **会重复扫** → 保留型（`parsedModules` / `nodeScan` / `callSites` …），同进程内复用；
- **只扫一次** → 一次性（`transientTree` / `transientNodes`），不留常驻树 ——
  保留的收益此时不存在，成本（常驻对象图让 gen2 GC 按图大小收费）却照付。
"""

from __future__ import annotations

import ast
import functools
import gc
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


@functools.lru_cache(maxsize=None)
def _cachedCode(stamp: Tuple[str, int, int]) -> str:
    """按内容戳缓存文件文本：同进程里 N 个跨文件判据只读盘一次。"""
    return Path(stamp[0]).read_text(encoding="utf-8", errors="replace")


def sourceRefsUnder(root: Path, suffix: str = ".py",
                    hints: Tuple[str, ...] = ()) -> List[SourceRef]:
    """`root` 子树下的源码引用清单：文件系统只读一遍，交给解析/遍历缓存。

    `hints` 是**文本预筛**：只要给定，就只保留文本里含任一 hint 的文件。
    这不是放宽判据（`sourceRefsUnder` 的键仍是全量清单），而是**判据的充分条件**：
    谓词是 `X.<name>(...)`，连 `<name>` 三个字都没出现的文件不可能命中。
    实测 `neurova/` 1014 文件里含 `attest` 的只有 4 个——预筛把「解析量」从
    **代码总量**变成**命中面**，判据与文件数彻底脱钩（0.06s vs 6.5s）。

    文本读取也走 `_cachedCode()`：预筛**必须先有文本**，而此前本函数对生产根下
    每个文件（实测 1007 个）都裸读一遍，调用方每符号各来一次 —— 实测 20140 次
    读盘 / 2.6s 里读盘占 0.67s（`cnb-2p6-1k347lfg1` 的同形账：判据与文件数挂钩）。
    改后同一进程里同一文件只读一次，口径不变（仍是全量清单 + hints 过滤）。
    """
    refs = [SourceRef(path, _cacheKey(path), _cachedCode(_cacheKey(path)))
            for path in filesUnder(root, suffix)]
    if not hints:
        return refs
    return [ref for ref in refs if any(hint in ref.code for hint in hints)]


def sourceCode(path: Path) -> str:
    """单文件源码文本（走同一份内容戳缓存；改文件即失效）。"""
    return _cachedCode(_cacheKey(path))


#: 常驻语法树的**退役步长**：常驻树每新增这么多棵，就把已保留的语法图整体移出
#: GC 的扫描分代（`gc.freeze()`）。0 = 关闭退役（仅供反向锁判据使用）。
#:
#: 为什么必须有退役（Issue #197 登记后本轮实证）：本缓存是 `maxsize=None`——
#: 跨用例复用要求「同一份源码只编译一次」，但**保留下来的每棵树都还留在 gen2 的
#: 扫描面里**，于是 gen2 每扫一遍都要走完整棵常驻图，成本随代码总量涨。这与
#: Issue #148 同根，只是账单记在 GC 上而不是 `ast.parse` 上。实测（本机，
#: 1787 个 `test_*.py` 全量解析后）：
#:
#: | 保留策略 | 建缓存 | 单次 gen2 | 常驻对象 |
#: |---|---|---|---|
#: | 不保留 | 1.10s | 0.78ms | 1.2 万 |
#: | 全部保留（改前） | 4.51s | **1030.43ms** | 267 万 |
#: | 全部保留 + 退役（改后） | 1.07s | **1.9ms** | 267 万 |
#:
#: 受保护子集整会话读数（同一批文件、同机同顺序）：gen2 合计 7.4s → 1.4s。
#: 退役本身是链表拼接（实测 1792 次退役合计 0.6ms），代价可忽略；**保留量不变**
#: （两种策略的 RSS 相同：退役只改变扫描面，不改变保留对象）。
#:
#: 退役的**代价与边界**（如实登记，不做无痕处理）：`gc.freeze()` 是进程级操作，
#: 冻结的是**当时全部**被跟踪对象。故冻结前先 `gc.collect()`——冻结之后不可达
#: 对象永远不会再被回收（实测：冻结前已不可达的环，`gc.collect()` 恒返回 0，
#: 解冻后才回收），不先回收就等于把当时的垃圾冻成永久垃圾。残留边界：**冻结时
#: 还活着、之后才变成垃圾**的对象本轮不会再被回收；测试进程生命周期内可接受，
#: 但不得据此假定冻结不改变可达性。
RETIRE_STEP = 8

#: 退役账：写侧在 `_retireResidentGraphIfDue`，读侧为
#: `tests/unit/test_ci_ast_scan_budget_guard.py::TestResidentGraphIsRetiredFromTheScannedGenerations`
#: （判据按它反证「退役真发生了」），不留只写不读的断点。
#:
#: `parsesSinceRetire` 记的是**自上次退役以来新增的常驻树数**，不与 `currsize` 挂钩。
#: 为什么不按「常驻树总数」推游标：那个量**可以被外部拉回 0**（受保护子集里就有
#: 用例显式 `_cachedParse.cache_clear()` 自证缓存语义），而游标是高水位——清空之后
#: 它还停在高位，于是接下来几百次解析一棵也不退役，扫描面重新无界，判据退化成
#: 「取决于前面跑过哪些用例」（判据与运行环境捆绑，正是本文件开头点名的形态）。
#: 靶点是新增量，故与清缓存解耦。
_RETIRE_LEDGER = {"retires": 0, "parsesSinceRetire": 0}


def retireStats() -> dict:
    """退役读数（唯一读取口）。

    `retires` 已发生的退役次数（判据按它反证「退役真发生了」）；
    `pending` 距下次退役还差的新增数量（判据按它反证「退役后已复位」）；
    `frozen` 当前被移出扫描分代的对象数。

    只给这三个：`步长` 就是模块常量 `RETIRE_STEP`、`常驻树数` 就是两条缓存的
    `cache_info().currsize`，搬进来只是第二份定义，且没有人读它（教义第 6 条：
    只写不读的字段是断点）。
    """
    return {
        "retires": _RETIRE_LEDGER["retires"],
        "pending": _RETIRE_LEDGER["parsesSinceRetire"],
        "frozen": gc.get_freeze_count(),
    }


def resetRetireLedger() -> None:
    """把退役账复位到初值（**账的形态只在本模块定义一处**）。

    给出这个复位点，是为了让判据能构造「刚开工」的进程状态而不必手抄
    `_RETIRE_LEDGER` 的键名——手抄私有字段就是第二份定义，键改名时静默错位
    （实测形态：判据 monkeypatch 一份旧键名，生产侧改名后判据以 `KeyError` 收场，
    报错点名的却不是真因）。
    """
    _RETIRE_LEDGER["retires"] = 0
    _RETIRE_LEDGER["parsesSinceRetire"] = 0


def _retireResidentGraphIfDue(pendingEntries: int) -> None:
    """常驻图增长到步长就把整棵图移出 GC 的扫描分代。

    判据的靶点是**扫描面**（gen2 要走的对象数），不是保留量——保留量由
    「跨用例只编译一次」决定，不该为了 GC 去动它（实测按 LRU 限制保留量反而更慢：
    被淘汰的树在下一条判据里要重新解析，miss 从 1586 涨到 4790）。

    触发量是**自上次退役以来的新增解析数**（`parsesSinceRetire`），不是常驻树总数：
    后者可被 `cache_clear()` 拉回 0，而游标是高水位——清空后它停在高位，退役停摆。

    `pendingEntries`：本次调用后才会写进缓存的条数。`functools.lru_cache` 是在被包
    函数**返回之后**才写缓存的（实测：函数体内 `cache_info().currsize` 不含本条），
    故不计入这个增量，退役就会整整滞后一棵树。命中路径传 `0`，零额外开销。
    """
    if RETIRE_STEP <= 0:
        return
    _RETIRE_LEDGER["parsesSinceRetire"] += pendingEntries
    if _RETIRE_LEDGER["parsesSinceRetire"] < RETIRE_STEP:
        return
    gc.collect()
    gc.freeze()
    _RETIRE_LEDGER["retires"] += 1
    _RETIRE_LEDGER["parsesSinceRetire"] = 0


@functools.lru_cache(maxsize=None)
def _cachedParse(stamp: Tuple[str, int, int], code: str) -> ast.AST:
    """按**代码文本**缓存语法树；`compile()` 是这条链上唯一的大头。

    每次未命中都会按 `RETIRE_STEP` 检查退役（命中路径零额外开销）。
    """
    tree = ast.parse(code)
    _retireResidentGraphIfDue(pendingEntries=1)
    return tree


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


def transientTree(path: Path) -> ast.AST:
    """**一次性**解析单文件：返回语法树但**不留常驻缓存**。

    为什么要单开一个入口而不是复用 `_cachedParse`：保留这份收益（跨判据复用）
    只在**重复扫描**同一棵树时成立，而成本（常驻对象图让 gen2 GC 按图大小收费）
    是**每次扫描都付**。实测本机 2985 个 `.py`：空进程 gen2 1.0ms、只留文本 1.1ms、
    留全部语法树 **2243ms**（532 万对象）；真会话里 12 个消费方同进程跑，gen2 合计
    8.5s、单次峰值 1.26s、进程末存活 143 万 ast 节点。

    典型适用面是**一次性全仓判据**（只为「仓库里有没有出现某个形状」跑一遍，
    不存在第二次命中）。这类判据走保留型入口**更慢**：实测同一个一次性全仓扫描
    私有解析 2.59s / gen2 0.7ms，走保留型 5.74s / gen2 892ms。

    绑小 `maxsize` 不是解法 —— 淘汰引发重复解析，省下的 GC 被解析吃掉（实测
    三连扫 1200 文件：`None` 5.86s / 1024 档 20.83s / 256 档 22.72s / 不保留 7.42s）。
    故保留型入口与一次性入口**并存且各有适用面**，由消费方按「会不会重复扫」
    自行选择，口径仍只在本模块一处。
    """
    return ast.parse(sourceCode(path))


def transientNodes(root: Path, suffix: str = ".py",
                   hints: Tuple[str, ...] = ()) -> Iterator[Tuple[Path, ast.AST]]:
    """**一次性**逐节点产出 `(路径, 节点)`，不留常驻语法树。

    与 `nodeScan` 同形（同样吃文本预筛、同样惰性），区别只在**不留常驻树**：
    每条 `(路径, 节点)` 用完即可回收。文本缓存 `_cachedCode` 保留 —— 它便宜
    （实测只留文本 gen2 1.1ms vs 只留语法树 2243ms），且判据常对同一棵树多次预筛。
    """
    for ref in sourceRefsUnder(root, suffix, hints):
        try:
            tree = ast.parse(ref.code)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            yield ref.path, node


@functools.lru_cache(maxsize=None)
def _cachedNodes(ref: SourceRef) -> Tuple[ast.AST, ...]:
    """整棵树的节点元组，按源码引用整进程复用。

    词法遍历按文件整进程缓存（`_cachedNodes` 之上是 `_cachedScan`，命中时连
    `tuple()` 都不重建）：`ast.walk` 的 deque + `iter_child_nodes` 在 1000 文件
    量级上与 `compile()` 同量级（实测 4.3s vs 5.1s），只缓存解析不缓存遍历
    等于把这笔账留着。
    """
    tuple_ = tuple(ast.walk(_cachedParse(ref.stamp, ref.code)))
    _retireResidentGraphIfDue(pendingEntries=1)
    return tuple_


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


@functools.lru_cache(maxsize=None)
def relativeToRepo(path: Path) -> str:
    """仓内相对路径（统一正斜杠，报错信息跨平台一致）。

    按**路径**记忆化：这是纯函数，且调用方常在**逐节点**循环里取它（实测
    `context_deadline_ledger._rawNodes` 一度逐节点调 25 万次 `Path.relative_to`
    ≈ 2.2s，占该取数整体一半以上）。缓存键是路径本身，同一路径只算一次；
    Path 不可变，故不存在陈旧读数面。

    收口点放在**共享源**而不是各消费方：任何一个消费方漏配，它就会退回按节点
    计算（消费方自己的镜像缓存层正是「consumer-only guard」的形态）。
    """
    return path.relative_to(REPO_ROOT).as_posix()
