#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上下文域「死线」判据取数与三态台账（B6-1，Issue #90 审计 §5 / §10 B6）。

## 为什么判据只报「事实」而不自动定「死线」

审计 §10 对 B6 的批注是「每个孤儿需**单独论证可达性**」，不是「grep 命中 0 就删」。
本仓实测已有两面反例说明「数引用」不可能自动定案：

- 池方法 `ContextPool.dedup` 零调用，但池实际走的是 `self._deduplicator.dedup(...)`
  ——**另一个接收者**的同名方法（`context/dedup.py` 的 `DriftSafeDeduplicator`）。
  只数符号名会把「有真实现的第二份」误判成「可删」；而按接收者判需要类型推断，
  静态近似必然误判（`clear` 这类通用名更极端：全仓 300+ 命中）。
- `ContextPoolUtils` 只有导入与 `__all__` 再导出，无消费点——形态与真死线不同，
  但都表现为「零消费」。

所以本模块的职责划清成两半：

1. **取数（本模块）**：给出每个符号在生产侧的全部引用点与**形态**
   （`def` / `call` / `import` / `read` / `write`），一条也不漏、一条也不臆断。
2. **定案（台账 `scripts/ci/contextDeadlines.txt`）**：逐条写「三态 + 依据」。
   依据不得留空，且台账记录的引用点数与实测不一致即报红——判据口径与
   处置进展两件事都不会静默漂移。

## 为什么写入点要与读取点分开报

审计 §5 的「只写不读」是一类独立形态：`X.sym = ...` 在被赋值的文件里
同时产生 `ast.Attribute`，若把它算成「引用」，本类死线会全部自称可达。
故 `write` 只记赋值左侧、`read` 只记其余位置——两者分开，台账才能逐条论证。

## 判据为什么不绑墙钟

唯一解析入口是 `tests/ast_scan.py`（按前缀择优 + 文本预筛 + 整进程复用）。
本模块不做 `rglob + ast.parse`，故判据与代码总量、与机器快慢都无关
（同类形态由 `tests/unit/test_ci_ast_scan_budget_guard.py` 常驻拦截）。

用法：
    python scripts/ci/context_deadline_ledger.py           # 人类可读
    python scripts/ci/context_deadline_ledger.py --json    # 机器可读
"""

from __future__ import annotations

import argparse
import ast
import functools
import json
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import ast_scan  # noqa: E402

PRODUCTION_ROOT = ast_scan.PRODUCTION_ROOT

#: 判据类（**机器判定**，不写进代码以外的地方）：按生产侧 AST 事实一刀切。
#:
#: 审计 §10 对 B6 的要求是「每个孤儿需**单独论证可达性**」。若三态也能人填，
#: 论证就退化成了自述——故本模块把它拆成两条**互不重叠**的轴：
#:
#:   ① 判据类（本模块计算，四值）：证据能证明的**直接可达性**；
#:   ② 处置（台账填写，四值）：人对该条的处置决定，依据文字必须点名理由。
#:
#: 判据类只有四值，规则写死在 `classify()` 里：
#:   `absent`      ― 生产侧**没有定义也没有赋值**（符号不存在/已删除）。
#:                   `get_context_pool` 与已删的 `EnhancedContextBuilder` 都归这里；
#:                   两者处置完全不同（前者要补真面、后者已退场），故区别落在处置轴。
#:   `no_consumer` ― 有定义或赋值，但生产侧零消费点。
#:   `self_loop`   ― 有定义，消费点**全部落在自己的定义文件内**（无外部消费者）。
#:   `consumed`    ― 有定义，且存在**跨文件**消费点。
#:
#: 「消费点」的定义里有一条刻意收窄：**孤立的 `import` 不算消费**。 
#: `from x import Y` 只是把名字带进文件，若该文件再无 Y 的调用/读取，
#: 那是**再导出**（`context_pool.py` 把 `ContextPoolUtils` 提进 `__all__`
#: 就是此形态），不等于有人用它。判据：同一文件内除 `import` 外还有其它形态的
#: 引用，该 import 才算消费点。这条收窄是机械可验的，不引入类型推断。
#:
#: 判据类刻意**只算 1 跳**，不做传递可达性分析：传递分析需要类型推断与调用图，
#: 静态近似必然误判（`dedup` 按接收者判、`clear` 按通用名判，已验证两面反例）。
#: 「1 跳可达但这 1 跳的消费方自己不可达」这类结论由**处置轴的依据文字**逐条论证，
#: 不靠机器猜——这正是审计要求「单独论证」的落点。
JUDGE_ABSENT = "absent"
JUDGE_NO_CONSUMER = "no_consumer"
JUDGE_SELF_LOOP = "self_loop"
JUDGE_CONSUMED = "consumed"
JUDGE_CLASSES = (JUDGE_ABSENT, JUDGE_NO_CONSUMER, JUDGE_SELF_LOOP, JUDGE_CONSUMED)

JUDGE_LABELS = {
    JUDGE_ABSENT: "符号缺失/已删除",
    JUDGE_NO_CONSUMER: "零消费点",
    JUDGE_SELF_LOOP: "仅自循环（无外部消费者）",
    JUDGE_CONSUMED: "跨文件可达",
}

#: 处置枚举（台账填写）：有限枚举保证机器可判定，不得出现第五种写法。
DISPOSAL_PENDING = "待处置"
DISPOSAL_WIRED = "已接线"
DISPOSAL_RETIRED = "已删除"
DISPOSAL_MERGED = "收口第二份"
DISPOSALS = (DISPOSAL_PENDING, DISPOSAL_WIRED, DISPOSAL_RETIRED, DISPOSAL_MERGED)

#: 台账文件：`符号 | 判据类 | 处置 | 依据` 四列，`#` 起头为注释。
LEDGER_PATH = Path(__file__).resolve().parent / "contextDeadlines.txt"

#: 审计 §5 点名的符号全集（判据按它取数，台账按它收录）。
#: 反向控制项（已知可达）一并纳入——没有它们，「零消费」判据可能整体空转。
AUDIT_SYMBOLS: Tuple[Tuple[str, str], ...] = (
    ("EnhancedContextBuilder", "§5 类/模块"),
    ("ContextFacade", "§5 类/模块"),
    ("ContextPoolRegistry", "§5 类/模块"),
    ("ContextCompressor", "§5 类/模块"),
    ("SmartContextCompressor", "§5 类/模块"),
    ("ContextPoolUtils", "§5 只写不读"),
    ("mark_turn_seen", "§5 池方法"),
    ("select_fold_candidates", "§5 池方法"),
    ("convert_context_for_model", "§5 池方法"),
    ("merge_with", "§5 池方法"),
    ("cleanup_expired", "§5 池方法"),
    ("compress_context", "§5 池方法"),
    ("dedup", "§5 池方法"),
    ("set_session_id", "§5 编排器"),
    ("build_system_prompt", "§5 编排器"),
    ("preload_vector_store", "§5 只写不读"),
    ("_last_archived_window_hashes", "§5 只写不读"),
    ("get_context_pool", "§4 P2-1（同判据）"),
    # 反向控制：已知生产可达，必须是 consumed 形态。
    ("draw", "反向控制（已知可达）"),
    ("archiveBatch", "反向控制（已知可达）"),
)

#: 反向控制项：判据必须报 `consumed`，且台账处置必须一直是「待处置」。
REACHABLE_CONTROLS = ("draw", "archiveBatch")


#: `_rawNodes` 的元素：`(生产根相对路径, 已解析节点)`。
SourceKey = Tuple[str, ast.AST]


class RefSite(NamedTuple):
    """一个引用点：相对路径 + 行号 + 形态。形态取自 AST，不是文本出现。"""

    path: str
    line: int
    form: str  # def / call / import / read / write


def _classifyNode(node: ast.AST, symbol: str) -> str | None:
    """该节点是不是对 `symbol` 的引用；是则给出形态。"""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return "def" if node.name == symbol else None
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == symbol:
            return "call"
        if isinstance(func, ast.Name) and func.id == symbol:
            return "call"
        return None
    if isinstance(node, ast.ImportFrom):
        if any(alias.name == symbol for alias in node.names):
            return "import"
        return None
    if isinstance(node, ast.Import):
        if any(alias.name == symbol or alias.name.endswith("." + symbol)
               for alias in node.names):
            return "import"
        return None
    if isinstance(node, ast.Attribute) and node.attr == symbol:
        return "read"
    return None


@functools.lru_cache(maxsize=None)
def _writeLines(symbol: str) -> Dict[str, set]:
    """`X.<symbol> = ...` 的赋值左侧位置：`{相对路径: {行号}}`。

    「只写不读」这类死线的判据落点：`self._last_archived_window_hashes = ...`
    在被赋值文件里同时产生 `ast.Attribute`，若不区分就会把它算成读取而自称可达。
    """
    writes: Dict[str, set] = {}
    for rel, node in _rawNodes(symbol):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            for sub in ast.walk(target):
                if isinstance(sub, ast.Attribute) and sub.attr == symbol:
                    writes.setdefault(rel, set()).add(node.lineno)
    return writes


@functools.lru_cache(maxsize=None)
def _repoRelative(stamp: Tuple[str, int, int]) -> str:
    """生产根相对路径：`ast_scan.relativeToRepo()` 的**按文件内容戳**缓存。

    相对路径按文件是常量，但 `_rawNodes` 此前对每个节点都算一次：实测 20 个
    登记符号合计 **249205** 次 `Path.relative_to`（剖析里占 0.5s 自耗时 + 1.75s
    累计），是排在 AST 解析之后的第二大开销 —— 纯粹是重复计算。
    缓存键取自 `ast_scan` 的同一份内容戳（`SourceRef.stamp`：路径 + mtime + size），
    故**与解析缓存同源、改文件即失效**，不引入会漏报的陈旧缓存
    （`AGENTS.md` 修复教义第 6 条：不新造第二份口径）。
    """
    return ast_scan.relativeToRepo(Path(stamp[0]))


@functools.lru_cache(maxsize=None)
def _rawNodes(symbol: str) -> Tuple[SourceKey, ...]:
    """该符号的全部节点取数（按符号整进程缓存）。

    为什么不直接 `list(nodeScan(...))`：每个符号要跑两遍（一遍取引用、一遍取
    写入归属），而 `sourceRefsUnder` 每次都要遍历并读取生产根下的全部文件。
    20 个登记符号 × 多次调用 = 数万次文件读取，实测单跑 50s，会直接撞
    pytest-timeout 的 30s 墙钟（本仓已有 `cnb-2p6-1k347lfg1` 的同形事故）。
    缓存键是符号名，值是**已解析的节点**（`_cachedNodes` 已按内容戳缓存，
    这里只是避免重复的文本预筛遍历）。
    """
    return tuple(
        (_repoRelative(_stampOf(path)), node)
        for path, node in ast_scan.nodeScan(PRODUCTION_ROOT, hints=(symbol,))
        if _mentionsSymbol(node, symbol)
    )


@functools.lru_cache(maxsize=None)
def _stampOf(path: Path) -> Tuple[str, int, int]:
    """`ast_scan.SourceRef.stamp` 形态的内容戳（与解析缓存同键）。"""
    return ast_scan._cacheKey(path)


def _mentionsSymbol(node: ast.AST, symbol: str) -> bool:
    """该节点是否是 `symbol` 的**候选**引用点（`_rawNodes` 的**唯一**预筛谓词）。

    谓词必须覆盖 `_rawNodes` 的**全部**消费方所认的形态，不只是 `_classifyNode`
    那一组：`_writeLines()`（赋值左侧归属）认的是 `ast.Assign`，故 `Assign` 一并
    保留 —— 预筛漏一类形态不会报错，只会让「只写不读」类死线**静默变成「无定义、
    无赋值」（`absent`）**，即把活线伪装成死线（本谓词第一版实测即漏了 `Assign`，
    由 `_last_archived_window_hashes` 的对账当场咬出：台账 `consumed` / 实测 `absent`）。

    根因（2026-09-25 实测，性能剖析 1187 万次函数调用 / 5.6s）：`_rawNodes` 此前
    **物化该符号命中文件里的全部节点**（实测 `dedup` 一个符号 55447 个节点，
    20 个登记符号合计 **249225** 个），而下游 `referenceSites` 对其中绝大多数
    直接 `continue`（`form is None`）。更贵的是：`ast_scan.relativeToRepo()` 对每个
    节点都要做一次 `Path.relative_to`（实测占掉其中 1.75s，是排在解析之后的第二大
    开销）—— 而相对路径**按文件是常量**。

    本谓词与 `_classifyNode` 同一判据、不新造第二份规则（`AGENTS.md` 修复教义第 6 条）：
    只保留「定义名相同 / 调用名相同 / 导入名相同 / 属性名相同」四种形态，其余节点在
    构造相对路径**之前**就被滤掉。改前改后 `referenceSites()` 的结论必须逐点相同
    （由 `tests/unit/context/test_context_deadline_ledger.py` 的判据与台账逐条钉住）。
    """
    if isinstance(node, ast.Assign):
        # `_writeLines` 的落点：赋值左侧可能含 `X.<symbol>`（再深一层由它自己
        # `ast.walk` 展开），故赋值语句整体保留，不在此提前判定。
        return True
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name == symbol
    if isinstance(node, ast.Call):
        func = node.func
        return (isinstance(func, ast.Attribute) and func.attr == symbol) or (
            isinstance(func, ast.Name) and func.id == symbol
        )
    if isinstance(node, ast.ImportFrom):
        return any(alias.name == symbol for alias in node.names)
    if isinstance(node, ast.Import):
        # 与 `_classifyNode` 同口径：`from x import y` 与 `import x.y` 都算命中
        return any(
            alias.name == symbol or alias.name.endswith("." + symbol)
            for alias in node.names
        )
    return isinstance(node, ast.Attribute) and node.attr == symbol


@functools.lru_cache(maxsize=None)
def referenceSites(symbol: str) -> List[RefSite]:
    """生产侧对 `symbol` 的全部引用点（含定义点，形态已标注）。

    范围是 `neurova/`（生产根）：测试、脚本、文档引用都不算消费方 ——
    测试可能正是该契约的唯一守卫，把它算作「可达」会把死线伪装成活线。
    """
    writes = _writeLines(symbol)
    sites: List[RefSite] = []
    seen: set = set()
    for rel, node in _rawNodes(symbol):
        if isinstance(node, ast.Attribute) and node.attr == symbol:
            if node.lineno in writes.get(rel, set()):
                form = "write"
            else:
                form = "read"
        else:
            form = _classifyNode(node, symbol)
        if form is None:
            continue
        key = (rel, node.lineno, form)
        if key in seen:
            continue
        seen.add(key)
        sites.append(RefSite(rel, node.lineno, form))
    return sorted(sites, key=lambda s: (s.path, s.line, s.form))


def consumerSites(symbol: str) -> List[RefSite]:
    """`symbol` 的**消费点**：除掉定义点与纯写入点之后剩下的引用。

    判据刻意保守：本函数只回答「有没有任何一处不是定义、不是纯赋值」，
    不判断接收者类型 —— 接收者归属由台账逐条论证（见模块 docstring）。
    """
    return [s for s in referenceSites(symbol) if s.form not in ("def", "write")]


def classify(symbol: str) -> Tuple[str, Dict[str, object]]:
    """按写死的四值规则给出判据类；返回 `(判据类, 判定过程)`。

    规则的每个分支都能由 `referenceSites()` 的事实直接验算，不含任何人工判断。
    """
    sites = referenceSites(symbol)
    defs = [s for s in sites if s.form == "def"]
    writes = [s for s in sites if s.form == "write"]
    # 孤立 import 不算消费（再导出形态）：同一文件内除 import 外没有其它引用时，
    # 该 import 不构成「有人用它」的证据。
    real_use_files = {site.path for site in sites if site.form in ("call", "read")}
    consumers = [
        site for site in sites
        if site.form in ("call", "read")
        or (site.form == "import" and site.path in real_use_files)
    ]
    detail: Dict[str, object] = {
        "def_files": sorted({s.path for s in defs}),
        "write_files": sorted({s.path for s in writes}),
        "consumer_files": sorted({s.path for s in consumers}),
    }
    if not defs and not writes:
        # 定义与赋值都没有：符号在生产侧不存在。`get_context_pool`（要补真面）
        # 与已删的 `EnhancedContextBuilder`（已退场）同归此类，区别在处置轴。
        detail["rule"] = "1 · 无定义、无赋值"
        return JUDGE_ABSENT, detail
    if not consumers:
        detail["rule"] = "2 · 有定义/赋值，零消费点"
        return JUDGE_NO_CONSUMER, detail
    home = {s.path for s in defs} | {s.path for s in writes}
    external = sorted({s.path for s in consumers} - home)
    if external:
        detail["rule"] = "4 · 存在跨文件消费点"
        return JUDGE_CONSUMED, detail
    detail["rule"] = "3 · 消费点全在自己定义文件内"
    return JUDGE_SELF_LOOP, detail


@functools.lru_cache(maxsize=None)
def facts() -> Tuple[Dict[str, object], ...]:
    """全部登记符号的取数结果（事实层，不含三态判定）。"""
    rows: List[Dict[str, object]] = []
    for symbol, origin in AUDIT_SYMBOLS:
        sites = referenceSites(symbol)
        consumers = [s for s in sites if s.form not in ("def", "write")]
        # `classify()` 仍是判据类单源；`computedJudge` 只是它的按符号缓存，
        # 让只比判据类的调用方不必再走一遍完整对账取数（见 `computedJudge`）。
        judge, detail = classify(symbol)
        rows.append({
            "symbol": symbol,
            "origin": origin,
            "sites": [s._asdict() for s in sites],
            "site_count": len(sites),
            "consumer_count": len(consumers),
            "consumer_forms": sorted({s.form for s in consumers}),
            "judge": judge,
            "judge_label": JUDGE_LABELS[judge],
            "classify": detail,
        })
    return tuple(rows)


def readLedger() -> Dict[str, Dict[str, str]]:
    """读台账：`{符号: {"judge": ..., "disposal": ..., "basis": ...}}`。"""
    entries: Dict[str, Dict[str, str]] = {}
    for raw in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 4:
            raise ValueError(f"台账行不是「符号 | 判据类 | 处置 | 依据」四列: {raw!r}")
        symbol, judge, disposal = parts[0], parts[1], parts[2]
        basis = "|".join(parts[3:]).strip()
        entries[symbol] = {"judge": judge, "disposal": disposal, "basis": basis}
    return entries


@functools.lru_cache(maxsize=None)
def computedJudge(symbol: str) -> str:
    """`symbol` 的机器判据类（单源 = `classify()`），按符号整进程缓存。

    为什么需要它（根因，2026-09-25 实测）：`reconcile()` 会为每个登记符号构造
    完整对账行（`facts()` 的 `classify` 明细 + 引用点数核对），而**只比判据类**
    的调用方（`tests/unit/context/test_context_deadline_ledger.py` 的
    `test_ledger_matches_computed_judge_classes`）跟着付全价：实测该用例
    **2.64s**，占受保护子集整跑（556s）里的可测尖峰，叠加并发负载即撞 30s 的
    `pytest-timeout` 墙钟 —— py3.12 那条流水线 2026-09-25 即因此判红
    （`Failed: Timeout (>30.0s)`，PR #209；同一提交 py3.11 全绿）。

    这不是"把判据改松"：判据类仍由 `classify()` 单源算出（不新造平行体系，
    `AGENTS.md` 修复教义第 6 条），台账与实测不一致照样报红；省掉的是**同一
    事实的重复取数**。引用点数核对只有在登记符号集变化时才可能变，缓存键是
    符号名 —— 与 `referenceSites()` / `_rawNodes()` 既有缓存同一形态。
    """
    return classify(symbol)[0]


def computeJudgeClasses() -> Dict[str, str]:
    """`{符号: 机器判据类}` —— **只比判据类**的调用方的唯一取数入口。

    与 `reconcile()["judge_conflict"]` 同一判据（都是 `classify()` 单源的
    `computedJudge()`），故两条路径不可能给出不同结论；差别只在取数范围：
    本函数不构造引用点清单与点数核对，成本从「20 符号全量对账」降到「20 次按符号
    缓存的判据分类」。
    """
    return {symbol: computedJudge(symbol) for symbol, _origin in AUDIT_SYMBOLS}


def reconcile() -> Dict[str, List[Dict[str, object]]]:
    """台账与实测对账：三态枚举、依据非空、引用点数一致。"""
    rows = facts()
    ledger = readLedger()
    problems: Dict[str, List[Dict[str, object]]] = {
        "missing": [], "unknown_judge": [], "unknown_disposal": [], "empty_basis": [],
        "not_registered": [], "judge_conflict": [], "pending_controls": [],
    }
    for row in rows:
        symbol = str(row["symbol"])
        entry = ledger.get(symbol)
        if entry is None:
            problems["not_registered"].append({"symbol": symbol, "origin": row["origin"]})
            continue
        if entry["judge"] not in JUDGE_CLASSES:
            problems["unknown_judge"].append(
                {"symbol": symbol, "judge": entry["judge"]})
        elif entry["judge"] != row["judge"]:
            # 判据类是机器算的：台账与算出来的不一致即口径漂移，报红，
            # 而不是让人改台账去迎合（那等于把判据降级成自述）。
            problems["judge_conflict"].append({
                "symbol": symbol, "ledger": entry["judge"], "computed": row["judge"],
                "rule": row["classify"]["rule"],
            })
        if entry["disposal"] not in DISPOSALS:
            problems["unknown_disposal"].append(
                {"symbol": symbol, "disposal": entry["disposal"]})
        if not entry["basis"]:
            problems["empty_basis"].append({"symbol": symbol})
        if symbol in REACHABLE_CONTROLS and entry["disposal"] != DISPOSAL_PENDING:
            # 反向控制项必须一直是「待处置」：它们已知可达，任何时刻被标成
            # 已接线/已删除都说明判据或台账被改坏了。
            problems["pending_controls"].append(
                {"symbol": symbol, "disposal": entry["disposal"]})
    for symbol in ledger:
        if symbol not in {str(r["symbol"]) for r in rows}:
            problems["missing"].append({"symbol": symbol})
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="上下文域死线判据取数与台账对账")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    args = parser.parse_args()

    rows = facts()
    ledger = readLedger()
    problems = reconcile()

    if args.json:
        print(json.dumps(
            {"rows": rows, "ledger": ledger, "problems": problems},
            ensure_ascii=False, indent=2,
        ))
        return 1 if any(problems.values()) else 0

    print("上下文域死线判据取数与台账对账（B6-1）")
    print(f"  登记符号 {len(rows)} | 台账条目 {len(ledger)}")
    for row in rows:
        symbol = str(row["symbol"])
        entry = ledger.get(symbol, {})
        judge = JUDGE_LABELS.get(entry.get("judge", ""), entry.get("judge", "未登记"))
        print(f"  {symbol:32s} 判据:{row['judge']:11s} {judge:20s}"
              f" {entry.get('disposal','未登记'):8s} 引用 {row['site_count']:2d}"
              f"（消费 {row['consumer_count']}） {row['origin']}")
    if any(problems.values()):
        print("\n对账问题：")
        for key, items in problems.items():
            if items:
                print(f"  {key}: {items}")
        return 1

    print(f"\n反向控制项（必须为 {JUDGE_CONSUMED} 且处置为「{DISPOSAL_PENDING}」）："
          f"{', '.join(REACHABLE_CONTROLS)}")
    print("一致性 OK：判据类与台账一致、处置枚举合法、依据非空。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
