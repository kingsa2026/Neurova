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
import re
from pathlib import Path
from typing import Iterable, Iterator, List, NamedTuple, Tuple

#: 仓根：与 `tests/repo_paths.py` 同口径（`__file__` 定位，禁写死开发机路径）
REPO_ROOT = Path(__file__).resolve().parents[1]

#: 生产代码根：判据若只谈「生产侧」，就不该把 tests/ 一起 parse
PRODUCTION_ROOT = REPO_ROOT / "neurova"


#: 剪枝目录名：第三方安装产物与构建/缓存目录。判据扫的是**本仓代码**，把这些算进
#: 扫描面不仅烧时间，还让"绿灯"取决于本机装了什么（实测本仓根下 `.venv`/`node_modules`
#: 贡献 32711 个 .py，全量读文本 49.68s，越过 pyproject 全局 `timeout = 30`，
#: 导致 `tests/unit/cognitive_layers/` 整目录在开发机上不可跑）。
#: 只列第三方/产物目录，**不含任何仓内源码目录**——排除第三方不等于砍窄仓内面。
_PRUNED_DIR_NAMES = frozenset({
    ".venv", "venv", "env", "node_modules", "site-packages", "dist-packages",
    ".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", "htmlcov", "coverage", "build", "dist",
})


#: ── 扫描面的两个"清单"入口（§6-234，与 `filesUnder` 并列的第三种取数口）───────────────
#:
#: 判据要回答"仓里有哪些文件"时，历史上只有两条路：`filesUnder()`（**工作树**遍历）与
#: 各判据自己抄一份 `git ls-files`。后者在收口前的 HEAD 树里实测被抄了 **13 处／9 档**
#: （按 AST 调用点数，同档本文件判据现量），而每份自抄都各自决定
#: "怎么解码、查不查退出码、按不按空白切"——本仓路径含中文，这几处正是出错的地方：
#: `test_temperature_single_source.py` 那档**不查退出码**，git 一失败就读到空清单，
#: 于是"没人 import 退役模块"当场假绿；`test_committed_tree_dependencies.py` 按空白切，
#: 实测把 181 条非 ASCII 跟踪档读成带引号的八进制串（这些档因此压根不在扫描面里），
#: 带空格的路径同形会断。收口到这一处，出错只可能错在一个地方。
#:
#: 两条路面区别（本仓两次 A/B 误报的根因，务必按用途选）：
#:   * **工作树面**（`filesUnder`）＝"不许新增"型守卫用——当场咬住还没提交的档；
#:   * **已跟踪面**（本函数族）＝"存量比对"型守卫用——并发会话正在半写的在途档不该
#:     被算成本仓的存量红，也不该被算成"我引入了新命中"。
def _gitLsFiles(*args: str) -> List[str]:
    """`git ls-files` 的唯一出口：NUL 分隔、显式 utf-8 解、退出码非 0 **就抛**。

    抛而不是回空清单：回空清单会让"扫了个空"读成"仓里干净"，那是最坏的一种假绿
    （自抄的那 13 处里就有一处不查退出码）。
    """
    import subprocess

    proc = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", *args, "-z"],
                          capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "git ls-files 失败（退出码 %d），扫描面不可信：%s"
            % (proc.returncode, proc.stderr.decode("utf-8", "replace")[:200]))
    return [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p]


def trackedPaths(*pathspecs: str) -> List[str]:
    """**已跟踪**文件清单（仓内相对路径，正斜杠）。给"存量比对"型判据用作扫描面。"""
    return sorted(_gitLsFiles(*pathspecs))


def trackedPyPaths(*pathspecs: str) -> List[str]:
    """已跟踪的 `.py` 清单；不传 pathspec 时按全仓 `*.py` 取。"""
    specs = pathspecs or ("*.py",)
    return sorted(p for p in _gitLsFiles(*specs) if p.endswith(".py"))


def untrackedNotIgnoredPaths() -> List[str]:
    """未跟踪**且未被 `.gitignore` 豁免**的清单（= 别人/自己正在写、还没提交的在途档）。

    与 `trackedPaths()` 合成"证据面"＝"这文件要么在版本控制里，要么是有意放在树上的"；
    被忽略的散件（`.tmp_*.py` 那族）不算——它们到不了 CI，也到不了别人的机器。
    """
    return _gitLsFiles("--others", "--exclude-standard")


#: ── 受保护子集清单的唯一读法（§6-332 登记的那条边界的正面）────────────────────────
#: 这份清单是 CI 的**唯一执行面**，"哪些档在子集内"这个问题在仓内只该有一处读法。
#: 收口前按 AST 现量：**29 档各自抄了一份**（`io.open` 24 处／`read_text` 8 处／`read` 6 处），
#: 每份各自决定怎么剥 `#` 注释、要不要去空行、返回 list 还是 set；其中 6 档还把它**当扫描面**
#: 逐条拼路径动手——那种用法下清单被截短或路径写错时，循环少跑几圈而判据照样绿（§6-332）。
#: 与上面 `_gitLsFiles` 那一族同一条理由：读法分叉时，出错可以出现在任何一份抄本里，
#: 而判据的读数只反映其中一份。
#:
#: `root` 形参只为**合成控制格**保留（面自证棘轮要在临时目录里造一份假清单验探测器咬不咬）；
#: 生产判据一律不传，向仓根要那份清单。
def protectedSubsetEntries(root: Path = None) -> List[str]:
    """`scripts/ci/protected_tests.txt` 的条目（剥 `#` 注释与空行，顺序保持清单原序）。"""
    base = Path(root) if root is not None else REPO_ROOT
    path = base / "scripts" / "ci" / "protected_tests.txt"
    if not path.is_file():
        # 回空清单＝"扫了个空"读成"清单干净"，与本模块 `_gitLsFiles` 那条同形，响亮失败
        raise AssertionError(f"受保护子集清单不存在：{path}（判据的扫描面不可信）")
    with path.open(encoding="utf-8") as handle:
        return [line.split("#", 1)[0].strip() for line in handle.read().splitlines()
                if line.split("#", 1)[0].strip()]


def rawManifestLines(path: Path) -> List[str]:
    """清单的**原始行**读数：只丢空行与整行注释，行内 `#` 与其后文字一律保留，不去重、不排序。

    为什么已经有 `protectedSubsetEntries()` 还要这一条：夜间档那一格比的正是
    "脚本自己那份 reader 有没有去重／排序／吞行"，**如果对照尺和被量的尺是同一条归一化读法，
    它归一化了什么就永远看不见**（同形即自证，251/252 那一族）。所以这条刻意不同源。

    但它仍只此一处——各档再各自手抄一遍 `read_text().splitlines()` 就是 §6-332 收掉的那个病。
    与 `protectedSubsetEntries(root)` 的区别只有一处：那个把行内注释也剥掉，这个不剥。
    """
    text = Path(path).read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")]


def filesUnder(root: Path, suffix: str = ".py") -> List[Path]:
    """`root` 子树下的源码文件清单（原地剪掉第三方/产物目录，路径排序稳定）。

    用 `os.walk` 而不是 `rglob` 后过滤：`rglob` 会**先进目录再筛**，实测剪枝前
    光是遍历 11376 个目录就要 1.82s，而真正被扫的仓内文件只有约 3200 个。
    """
    import os

    found: List[Path] = []
    for dirPath, dirNames, fileNames in os.walk(root):
        dirNames[:] = [d for d in dirNames if d not in _PRUNED_DIR_NAMES]
        base = Path(dirPath)
        for name in fileNames:
            if name.endswith(suffix):
                found.append(base / name)
    return sorted(found)


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


def transientTrees(root: Path, suffix: str = ".py",
                   hints: Tuple[str, ...] = ()) -> Iterator[Tuple[Path, ast.AST]]:
    """**一次性**产出 `(路径, 语法树)`：不留常驻树，也**不让调用方自己枚举/解析**。

    与 `transientNodes` 同一族（同样吃文本预筛、同样不进 `_cachedParse`），
    区别是交出**树**而不是节点表：判据要按"模块层语句"这类结构位置读它，或者
    同一棵树要读好几件事（走两遍 `ast.walk`）时，走这个入口只解析一遍 —— 而
    自己 `filesUnder` + `ast.parse` 的写法既把成本绑在代码总量上，也让同一份文本
    被反复编译（受保护子集实测：一次全仓取证解析三遍同一批 `.py`，30s 墙钟超时）。

    什么时候**不**用它：会跨判据重复扫的（走 `parsedModules` / `nodeScan`），
    预算实现自身（走 `sourceRefsUnder`）。
    """
    for ref in sourceRefsUnder(root, suffix, hints):
        try:
            yield ref.path, ast.parse(ref.code)
        except SyntaxError:
            continue


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


def importersOfModule(root: Path, moduleName: str, suffix: str = ".py") -> List[Tuple[str, int, str]]:
    """`root` 子树里**经导入通道取 `moduleName`** 的位置 `(相对路径, 行号, 取法)`。四种取法都认：

      `import a.b.c` / `import a.b.c as p`、`from a.b.c import X`、
      相对形 `from .c import X`（按发起文件位置解析成绝对名）、
      父包取名形 `from a.b import c`（`node.module` 是父包，取的是子模块名）——
      这一类含相对写法 `from . import c`（`node.module` 是 None），别当成前一类的缺席。

    **预筛词取末段名 `c`，不取全名 `a.b.c`**——这是"判据成本"与"判据口径"同时成立的关键：
    相对形与父包形的源码里根本不含包前缀，按全名预筛会把它们在**读文本这一关**就滤出扫描面，
    于是"还在导入"被读成零引用——「取法窄于意图」那条老账在预筛这一关的复现。

    为什么收在本模块而不是各判据自己写：`tests/` 里曾有 17 处各写一份 `_importedNames`，
    每一处都要独立决定"相对形认不认、父包形认不认、预筛取哪个词"——同一个问题十七个口径，
    正是教义第 6 条点名的形态。误报面只有一处并已界定：`from a.b import c`（或其相对写法
    `from . import c`）里 `c` 若恰是**符号名**而非子模块名，会被算进取法；两侧名字要同时
    相等才撞上，故宁可计入也不漏。

    返回的是 `(相对路径, 行号, 取法)`，取法只用于报错文本点名，不参与裁决。
    """
    parts = moduleName.split(".")
    base = parts[-1]
    hits: List[Tuple[str, int, str]] = []
    for path, node in transientNodes(root, suffix, textHints(base)):
        rel = _relOrAbs(path)
        form = importFormForModule(rel, node, moduleName)
        if form:
            hits.append((rel, node.lineno, form))
    return hits


def importFormForModule(relPath: str, node: ast.AST, moduleName: str) -> str:
    """这个 import 节点取的是不是 `moduleName`？是则返回取法名，否则空串。**四种取法都认**。

    拆成这个纯函数是为了**可证伪**：整棵树得在仓内才解得出相对形（`resolveImportModule` 按
    发起文件的仓内相对路径算包名），而"四种形都认"这句话必须能用合成样本逐条验证——
    往仓里种临时文件会污染别的常驻判据，所以把判定与枚举分开：枚举归 `importersOfModule`，
    判定归这里。

    「父包取名形」这一标签**含两种写法**，别把它们当成一种：
      `from pkg.sub import leaf`（绝对，`node.module` 就是父包）
      `from . import leaf`（相对，`node.module` 是 None，父包只能由发起文件位置解出）
    两者都算取了这个子模块，故共用一个标签；拆成两个标签会让八个消费方的"四种取法都认"
    集体过期。写法各有一例钉在 `test_detectorOwnsAllFourImportForms` 里。
    """
    parts = moduleName.split(".")
    base, parent = parts[-1], ".".join(parts[:-1])
    if isinstance(node, ast.Import):
        return "import 全名" if any(a.name == moduleName for a in node.names) else ""
    if not isinstance(node, ast.ImportFrom):
        return ""
    resolved = resolveImportModule(relPath, node)
    if resolved == moduleName:
        return "相对形" if node.level else "from 全名"
    if parent and resolved == parent and any(a.name == base for a in node.names):
        return "父包取名形"
    return ""


def _relOrAbs(path: Path) -> str:
    """仓内给相对路径；仓外（探测器的合成夹具）给绝对路径。

    为什么要容下仓外：`importersOfModule` 要能在 `tmp_path` 里被**合成源码**验证
    （"四种取法都认"这句话没有合成样本就是不可证伪的），而往仓里种临时文件会污染别的常驻判据。
    """
    try:
        return relativeToRepo(path)
    except ValueError:
        return path.as_posix()


def importsOf(scan: Iterable[Tuple[Path, ast.AST]], moduleName: str) -> List[Tuple[Path, int]]:
    """扫描结果里 `import <moduleName>` / `from <moduleName> import ...` 的命中点。

    判据是「代码里有引用」，不是「文本里提过」——注释与字符串不算，故走 AST。
    `scan` 可以是 `nodeScan()` 的惰性迭代器（推荐），也可以是已物化的序列。

    **本函数只认"取的就是那个模块"这一种形**：看不见相对形（`node.module` 不含包前缀）
    也看不见父包取名形（`from a.b import c`）。要"谁还在导入它"的完整答案，用
    `importersOfModule(root, moduleName)`——它自己管末段名预筛，不会在文本这一关漏。
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


def resolveImportModule(relPath: str, node: ast.ImportFrom) -> str:
    """把 `from .x import a` / `from ..x import a` 解析成**绝对模块名**；解不出返回空串。

    为什么收进共享源：只按 `node.module` 文本相等比较的口径看不见相对导入，于是
    『这个门面名字没人经门面取用』会被读成假死。§6-212 那批的档案实测这形会误判
    `neurova.api.endpoints.memory.router`（4 个集成测试写的正是这种取法）与
    `neurova.cognitive.Memory`（判据按 `import pkg as p` + `p.X` 的属性形在用）。
    """
    if node.level == 0:
        return node.module or ""
    parts = relPath.split("/")[:-1]
    drop = node.level - 1
    if drop > len(parts):
        return ""
    base = ".".join(parts[:len(parts) - drop] if drop else parts)
    if node.module:
        base = f"{base}.{node.module}" if base else node.module
    return base


def namesTakenFrom(scan: Iterable[Tuple[Path, ast.AST]],
                   moduleName: str) -> List[Tuple[str, Path, int]]:
    """扫描结果里 `from <moduleName> import a`／`… import a as b` 的**原名**取点。

    记的是 `alias.name`（源模块必须提供的那个名字），不是本地别名——按别名记账会把
    活着的门面名字读成零消费者。`scan` 用 `nodeScan(hints=...)` 的惰性迭代即可。
    """
    hits: List[Tuple[str, Path, int]] = []
    for path, node in scan:
        if not isinstance(node, ast.ImportFrom):
            continue
        if resolveImportModule(relativeToRepo(path), node) != moduleName:
            continue
        for alias in node.names:
            hits.append((alias.name, path, node.lineno))
    return hits


def _walkNodes(tree: ast.AST) -> List[ast.AST]:
    """整棵树的节点清单（`ast.walk` 的同义实现）。

    给出这个入口，是为了让"同一棵树要分几趟过"的调用方**只付一次下潜**：
    本仓实测一遍 `ast.walk` 走 413 万节点要 2.86s，两趟就是白付一趟。
    `ast.walk` 本身是一次 BFS 生成器，产出序是「父先于子、同级按字段序」。这里用
    显式栈做 DFS 等价实现，`reversed(list(ast.iter_child_nodes(...)))` 只为把同级的
    产出序摆回字段序 —— **顺序会改读数**：属性链的归属判据是"该文件 import 过那个前缀"，
    先撞见 `x.y` 还是先撞见 `import x`，结果就是记不记这一条（实测本仓
    `neurova/auth/qclaw_binding_model.py` 恰好两者都不按书写序，顺序一错读数就变）。
    等价性由 `tests/unit/test_ci_ast_scan_budget_guard.py` 与 `takenPerModule` 的对拍钉住。
    """
    nodes: List[ast.AST] = []
    stack = [tree]
    while stack:
        node = stack.pop()
        nodes.append(node)
        stack.extend(reversed(list(ast.iter_child_nodes(node))))
    return nodes


def takenPerModule(root: Path, suffix: str = ".py") -> dict:
    """一次遍历，按**被取用的绝对模块名**归集"谁从它取了什么名"。

    四种取法都记（少一种就会把活着的门面名字读成『没人取用』——§6-212 那批就是这么发现的）：
      `from M import X [as Y]`（记**原名** X）、相对形按发起文件位置解析成绝对名、
      `import M` / `import M as p` 之后的 `M.X` 与 `p.X` 属性读法。
    返回 `{模块名: {名字: [(仓内相对路径, 行号), ...]}}`。"包自己绑的那几条 `from . import x`
    算不算它的消费者"是裁决不是取数 ⇒ 由调用方按路径滤掉本包 `__init__.py`。

    为什么单开一个整表入口而不是逐包调 `namesTakenFrom`：后者一次调用要把整棵子树走一遍，
    五个包就五遍；这张表一遍扫完全部归属，且沿用 `transientTree` 一族的**不留常驻语法树**口径。
    属性链的归属按"该文件确实 import 过那个前缀"判定（不是拿全表前缀去凑），
    否则同一棵文件里 `a.b` 与另一文件里的 `a.b.c` 会互相串味。
    """
    out: dict = {}
    for ref in sourceRefsUnder(root, suffix):
        try:
            tree = ast.parse(ref.code)
        except SyntaxError:
            continue
        rel = relativeToRepo(ref.path)
        # 下潜**只付一次**：节点先收进一份清单，再在这份清单上分两趟过（import 面 → 属性面）。
        #
        # 为什么不能合成一趟：属性链的归属判据是"该文件确实 import 过那个前缀"，而
        # `ast.walk` 的产出序列由**树形**决定，不由书写顺序：本仓
        # `neurova/auth/qclaw_binding_model.py` 顶层 `try:` 里的
        # `import cryptography.hazmat.primitives.kdf.pbkdf2` 就排在函数体里的
        # `cryptography.fernet.Fernet(...)` **之后**。合成一趟会静默改写读数（实测：
        # `cryptography.fernet::fernet` 凭空多一条、`…kdf.pbkdf2` 整条消失），而这张表是
        # 仓内多处判据的事实源，读数必须逐条不变。
        # 省下的是**下潜**那一遍（本机 2.86s / 413 万节点），不是语义：清单化后两趟
        # 都只做线性过表（各 0.3s 量级）。
        nodes = _walkNodes(tree)
        imported = set()                      # 该文件里真被 import 过的绝对模块名
        aliasTo = {}                          # 本地名 → 绝对模块名
        for node in nodes:
            if isinstance(node, ast.ImportFrom):
                mod = resolveImportModule(rel, node)
                if not mod:
                    continue
                imported.add(mod)
                bucket = out.setdefault(mod, {})
                for a in node.names:
                    if a.name == "*":
                        continue
                    imported.add(f"{mod}.{a.name}")
                    bucket.setdefault(a.name, []).append((rel, node.lineno))
            elif isinstance(node, ast.Import):
                for a in node.names:
                    imported.add(a.name)
                    aliasTo[(a.asname or a.name).split(".")[0]] = a.name
        for node in nodes:
            if not isinstance(node, ast.Attribute):
                continue
            base = node.value
            target = aliasTo[base.id] if isinstance(base, ast.Name) and base.id in aliasTo else None
            if target:
                out.setdefault(target, {}).setdefault(node.attr, []).append((rel, node.lineno))
            d = dottedChain(node)
            if not d:
                continue
            parts = d.split(".")
            for i in range(1, len(parts)):
                prefix = ".".join(parts[:i])
                if prefix in imported:
                    out.setdefault(prefix, {}).setdefault(parts[i], []).append((rel, node.lineno))
    return out


def dottedChain(node: ast.AST):
    """把 `a.b.c` 这类纯属性链解成点号串；解不出返回 None。"""
    parts, cur = [], node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return ".".join(reversed(parts))


#: 词法层的 def/class 头名（`shadowedTopLevelNames` 的预筛，**充分条件**，见该函数docstring）。
#: 行首允许缩进是**故意的宽收**：类内方法名也算进来只会多解析几个文件，
#: 而少收一种形就会把真命中滤出扫描面——预筛的错只许朝"多付钱"那一侧偏。
DEF_OR_CLASS_HEADER = re.compile(r"^[ \t]*(?:async[ \t]+def|def|class)[ \t]+(\w+)", re.M)


class TopLevelNameDup(NamedTuple):
    """一份「模块级同名被定义多次」的档案：路径／名字／各份行号／剥掉说明行后是否同体。"""

    rel: str
    name: str
    linenos: List[int]
    sameIgnoringDocstring: bool


def _lexicalHeaderDup(code: str) -> bool:
    """词法闸：这份源码**有没有可能**藏着模块级重名定义。"""
    if "\\\n" in code:
        # 反斜杠续行能把 `def` 与头名拆到两行，词法层看不见名字——这种文件一律放行解析。
        return True
    names = DEF_OR_CLASS_HEADER.findall(code)
    return len(names) != len(set(names))


def _shapeSignature(node: ast.AST) -> Tuple[Tuple[str, ...], str]:
    """节点的可比形状：装饰器 + 剥掉首条 docstring 后的函数/类体语法图。

    为什么要剥 docstring：报错文本得说清「两份是差在说明文字，还是差在断言」——
    前者是同一件事写了两遍（编辑哪一份才生效这件事答不出来），后者才可能藏着真分叉。
    装饰器进签名，否则 `@x` 与裸定义会被判成同体。
    """
    body = list(getattr(node, "body", []))
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    deco = tuple(ast.dump(d) for d in getattr(node, "decorator_list", []))
    return deco, ast.dump(ast.Module(body=body, type_ignores=[]))


def shadowedTopLevelNames(root: Path, suffix: str = ".py",
                          stats: dict = None) -> List[TopLevelNameDup]:
    """`root` 子树里**同一个模块级名字被定义两次以上**的落点，按 `(路径, 名字)` 排序。

    为什么要给它做格子（不是"下次编代码注意点"）：第二次定义会**静默遮住**第一份——
    模块命名空间里只剩后一份，于是
      * 被遮住的那份若是 `Test*` 类，它名下每一条用例**连收集都不发生**
        （读代码的人看见两份共 6 格，实际在跑 3 格；`--collect-only` 只报一个 Class 节点）；
      * 若第一份里恰好放着某个模块级常量的**唯一消费点**，那份常量从此是第二份表示——
        改它既不报错也不生效。
    判据**不看体是否相同**：同体也是遮蔽（"编辑哪一份才生效"本身就答不出来），
    体只是写进报错文本供分流处置。

    口径与边界（写在这里，别让下一轮重新猜）：
      * 只看 `tree.body` 的 `FunctionDef`／`AsyncFunctionDef`／`ClassDef`；被 `if`／`try`
        包一层的同名定义（`if TYPE_CHECKING:`、平台分支这类**合法**条件定义）不在面内；
      * 类体内的同名方法不在面内（合法写法极多，且与本条要防的"遮蔽"不同根）；
      * 预筛是**充分条件**：真命中必然让某个 def/class 头名在词法层重复出现；
        行续写那一形由 `\\\n` 兜底整档放行。

    `stats` 传入一个字典即回填**这次扫描自己的面**（`filesSeen`／`parsedAfterGate`）。
    为什么由取数口给而不是调用方另数一遍：判据要钉的是"这条格扫的面是不是整仓"，
    而另开一条取数路去证它，等于假设两次扫的是同一棵树——面读数必须与被它裁决的那次扫描同源。
    """
    hits: List[TopLevelNameDup] = []
    seen = gated = 0
    for ref in sourceRefsUnder(root, suffix):
        seen += 1
        if not _lexicalHeaderDup(ref.code):
            continue
        gated += 1
        try:
            tree = ast.parse(ref.code)
        except (SyntaxError, ValueError):
            continue
        byName: dict = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                byName.setdefault(node.name, []).append(node)
        for name, nodes in byName.items():
            if len(nodes) < 2:
                continue
            first = _shapeSignature(nodes[0])
            hits.append(TopLevelNameDup(
                _relOrAbs(ref.path), name, [n.lineno for n in nodes],
                all(_shapeSignature(n) == first for n in nodes[1:])))
    if stats is not None:
        stats.update(filesSeen=seen, parsedAfterGate=gated)
    return sorted(hits, key=lambda h: (h.rel, h.name))
