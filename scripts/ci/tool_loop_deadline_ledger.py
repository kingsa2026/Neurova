#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具/loop 域「死线」判据取数、阈值可达性轴与台账对账（T-01，Issue #175）。

## 为什么复用上下文域的形态，而不是另立一套

Issue #175 的前置是本仓已在上下文域（B6-1）趟通一条可机器验证的死线处置闭环——
**两轴分离**：判据类由 `classify()` 机器算、台账照抄且不一致即报红；处置是人对该条的
决定，依据不得留空。本模块把同一条形态复用到工具/loop 域，故：

- 判据词汇（`absent` / `no_consumer` / `self_loop` / `consumed`）与判据规则**不重写**：
  符号级取数直接走 `scripts/ci/context_deadline_ledger.py`（同仓唯一事实源），
  本模块只在它覆盖不到的两种形态上补取数（见下），四个判据类的规则文本逐字相同
  （由 `tests/unit/tools/test_tool_loop_deadline_ledger.py` 机器比对）。
- 台账格式在上下文域四列之上**加两列**（种类 / 阈值可达性）与**一列计数**（引用点数），
  见「为什么本域要多一轴」。

## 本域比上下文域多出来的两种形态（这是取数为什么要扩展）

Issue #175 点名的符号里有两类是上下文域的取数模型看不见的：

1. **函数内局部量**（`MAX_TOOL_CALL_ROUNDS` = chat_pipeline.py:2443、
   `ctx_snapshot` = :2451）。它们不是类/函数/属性，`ast.Attribute` 口径下取数为零，
   会被误判成 `absent`（「符号不存在」）。故新增**局部绑定取数**：按 `ast.Name` 的
   Store/Load 计写入与读取，并**限定在首次写入所在的函数作用域内**——否则全仓
   同名局部会互相串台（同名变量的读取被算成消费）。
2. **字典字符串键**（`tool_choice` = openai_loop.py:281）。它从不作为属性出现，
   只在 `request_params["tool_choice"]` 这类下标里。故新增**键取数**：
   写入 = 下标赋值；读取 = 下标取值与 `get(...)`；**移除型访问（`pop` / `del`）
   记为 write 而不是 read**——移除一个键证明有人动过它，但不证明有人消费它的值
   （与上下文域「孤立 `import` 不算消费」同一条收窄精神，机械可验、不引推理）。

## 为什么本域要多一轴「阈值可达性」（Issue #175 的三选一裁定）

`IterationGate` 是本片唯一的设计争议点：它被构造（`openai_loop.py:101` / `:136`）、
被 `GateRunner` 每轮 `check()`，AST 判据给出 `consumed`——但它在**任意合法配置下都
不可能出声**：

    硬顶   self._max_tool_rounds = get_effective_limits()['max_loop_rounds'] // 2
    门控   IterationGate(max_rounds = get_effective_limits()['max_loop_rounds'])

同一个配置键取两个尺度。`classify()` 的四个值回答的是「**AST 事实能直接证明的直接
可达性**」——这门控确实可达；「阈值在值域上够不到」是**值比较**事实，把两件事塞进
同一个轴，四值分支就不再能由 `referenceSites()` 的事实直接验算，且两个域的判据类
将不再可比。故本片裁定：**不加第五态**（判据类仍是四值，与上下文域同词汇、可比），
**给台账加第二判据轴「阈值可达性」**，且该轴**同样由机器算**（人填的只有处置与依据）：

    not_a_threshold ― 不是阈值型门控（`check()` 里没有对 `self.<阈值参数>` 的比较）
    unbound         ― 阈值型，但生产侧找不到该阈值参数的配置键绑定来源
    single_source   ― 阈值型，且该配置键在生产侧只有一个尺度（阈值可达，可出声）
    shadowed        ― 阈值型，且存在**同配置键的更小尺度守卫**（floor-div d≥2），
                      使门控阈值在合法配置域内不可达

`shadowed` 的机器证据三条，缺一条都不成立（由 `thresholdAxis()` 复算）：
① 门控构造处直接绑定配置键（尺度 1）；② 生产侧存在 `…[<同键>] // d`（d≥2）的赋值
且该量参与比较；③ 配置键的**合法下界**（单源 `security/agent_limits_settings.py`
的 `MIN_ROUNDS` / `MAX_ROUNDS`，经 AST 读取，不 import）满足 `下界 // d < 下界`。
三条都成立才能判 `shadowed`——T-04（轮次预算单源）把尺度收口成一份后，②会消失，
轴值必须跟着改，否则 `reconcile()` 的 `threshold_conflict` 报红。这就是
写入→读取→反馈→再写入的闭环（协作红线：不留断点）。

轴值只发表「可达性」，**站点次序的细节写在依据里**：`IterationGate` 在非流式路径上
守卫（`:377`）先于门控（`:394`），在流式路径上门控（`:671`）先于守卫（`:711`），
故 `n=2`（合法域下界）时流式路径的门控**确有可能**出声——本模块把站点次序作为事实
输出（`shadow_orders`），由台账依据逐条论证，不由机器猜。

## 判据为什么不绑墙钟

唯一解析入口是 `tests/ast_scan.py`（按前缀择优 + 文本预筛 + 整进程复用），
本模块不做 `rglob + ast.parse`（同类形态由
`tests/unit/test_ci_ast_scan_budget_guard.py` 常驻拦截）。

用法：
    python scripts/ci/tool_loop_deadline_ledger.py           # 人类可读
    python scripts/ci/tool_loop_deadline_ledger.py --json    # 机器可读
"""

from __future__ import annotations

import argparse
import ast
import functools
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import ast_scan  # noqa: E402
from scripts.ci import context_deadline_ledger as symbolLedger  # noqa: E402

#: 扫描根：**只有生产根**。`NeurUI/src-tauri/{resources,target/*}/backend/neurova/`
#: 下是整套字节偏移的运行时副本（`ToolExecutor` 在副本 `:235`、正典 `:236`），
#: 不带生产根约束的扫描会把副本算成消费点——Issue #175 前置警告 2。
SCAN_ROOTS = (ast_scan.PRODUCTION_ROOT,)
PRODUCTION_ROOT = ast_scan.PRODUCTION_ROOT

#: 判据词汇与规则单源在上下文域模块（`AGENTS.md` 第 6 条：不新造平行体系）。
JUDGE_ABSENT = symbolLedger.JUDGE_ABSENT
JUDGE_NO_CONSUMER = symbolLedger.JUDGE_NO_CONSUMER
JUDGE_SELF_LOOP = symbolLedger.JUDGE_SELF_LOOP
JUDGE_CONSUMED = symbolLedger.JUDGE_CONSUMED
JUDGE_CLASSES = symbolLedger.JUDGE_CLASSES
JUDGE_LABELS = symbolLedger.JUDGE_LABELS

RULE_ABSENT = "1 · 无定义、无赋值"
RULE_NO_CONSUMER = "2 · 有定义/赋值，零消费点"
RULE_SELF_LOOP = "3 · 消费点全在自己定义文件内"
RULE_CONSUMED = "4 · 存在跨文件消费点"

DISPOSAL_PENDING = symbolLedger.DISPOSAL_PENDING
DISPOSAL_WIRED = symbolLedger.DISPOSAL_WIRED
DISPOSAL_RETIRED = symbolLedger.DISPOSAL_RETIRED
DISPOSAL_MERGED = symbolLedger.DISPOSAL_MERGED
DISPOSALS = symbolLedger.DISPOSALS

THRESHOLD_NOT_APPLICABLE = "not_a_threshold"
THRESHOLD_UNBOUND = "unbound"
THRESHOLD_SINGLE_SOURCE = "single_source"
THRESHOLD_SCALED_UNREACHABLE = "scaled_unreachable"
THRESHOLD_SCALED_SPARSE = "scaled_sparse"
THRESHOLD_CLASSES = (
    THRESHOLD_NOT_APPLICABLE,
    THRESHOLD_UNBOUND,
    THRESHOLD_SINGLE_SOURCE,
    THRESHOLD_SCALED_UNREACHABLE,
    THRESHOLD_SCALED_SPARSE,
)

THRESHOLD_LABELS = {
    THRESHOLD_NOT_APPLICABLE: "非阈值型门控",
    THRESHOLD_UNBOUND: "阈值参数无配置来源",
    THRESHOLD_SINGLE_SOURCE: "单一份尺度（阈值可达）",
    THRESHOLD_SCALED_UNREACHABLE: "被更小尺度守卫遮蔽（合法域内不可达）",
    THRESHOLD_SCALED_SPARSE: "被更小尺度守卫遮蔽（合法域内稀疏可达）",
}

#: 符号种类（机器算）：决定取数口径，也决定判据怎么读。
KIND_SYMBOL = "symbol"
KIND_BINDING = "binding"
KIND_KEY = "key"
KINDS = (KIND_SYMBOL, KIND_BINDING, KIND_KEY)

KIND_LABELS = {
    KIND_SYMBOL: "模块级符号",
    KIND_BINDING: "函数内局部量",
    KIND_KEY: "字典字符串键",
}

#: 台账文件：`符号 | 种类 | 判据类 | 阈值可达性 | 引用点数 | 处置 | 依据`。
LEDGER_PATH = Path(__file__).resolve().parent / "toolLoopDeadlines.txt"

#: 登记符号全集：`(符号, 种类, 出处)`。前 17 条是 Issue #175 点名集，
#: 末 3 条是「放大视角」按同一根因 grep 出来的同类命中点（零消费、同域）。
AUDIT_SYMBOLS: Tuple[Tuple[str, str, str], ...] = (
    ("UnifiedToolRegistry", KIND_SYMBOL, "tool_layers/unified_registry.py:50（§类/模块）"),
    ("ToolExecutionLogger", KIND_SYMBOL, "tool_layers/tool_logger.py:76"),
    ("ToolSchemaConverter", KIND_SYMBOL, "tool_layers/openai_schema.py:128"),
    ("ToolCallParser", KIND_SYMBOL, "tool_layers/openai_schema.py:285"),
    ("ToolSchema", KIND_SYMBOL, "tool_layers/schemas.py:140（与 api/endpoints/tool_schema.py:32 同名）"),
    ("ToolParameter", KIND_SYMBOL, "tool_layers/schemas.py:96（与 execution_engine/tool_engine.py:33 同名）"),
    ("ToolSource", KIND_SYMBOL, "tool_layers/schemas.py:36"),
    ("ToolExecutionPipeline", KIND_SYMBOL, "agent/tool_pipeline.py:202"),
    ("CostTrackingMixin", KIND_SYMBOL, "llm/cost_tracking_middleware.py:27"),
    ("CLIToolExecutor", KIND_SYMBOL, "tool_layers/cli_tool.py:22"),
    ("IterationGate", KIND_SYMBOL, "agent/gates.py:59（阈值型门控）"),
    ("TokenBudgetGate", KIND_SYMBOL, "agent/gates.py:78（阈值型门控·反向控制）"),
    ("notify_tool_result", KIND_SYMBOL, "agent/tool_pipeline.py:460（反向控制·符号级）"),
    ("get_pipeline_observers", KIND_SYMBOL, "agent/tool_pipeline.py:443（反向控制·符号级）"),
    ("GoalGate", KIND_SYMBOL, "agent/gates.py:149（阈值型门控·G2 目标验收链）"),
    ("set_turn_goal", KIND_SYMBOL, "core/turn_context.py（G2 目标写入面）"),
    ("get_turn_goal", KIND_SYMBOL, "core/turn_context.py（G2 目标读取面）"),
    ("goal_max_continuations", KIND_KEY, "security/agent_limits_settings.py（G2 续跑预算）"),
    ("goal_verification_enabled", KIND_KEY, "security/agent_limits_settings.py（G2 成本闸）"),
    ("reset_pipeline_observers", KIND_SYMBOL, "agent/tool_pipeline.py:453（放大视角补登）"),
    ("ToolExecutionResult", KIND_SYMBOL, "tool_layers/schemas.py:291（放大视角补登）"),
    ("tool_choice", KIND_KEY, "agent/loops/openai_loop.py:281（只写不读）"),
    ("MAX_TOOL_CALL_ROUNDS", KIND_BINDING, "agent/chat_pipeline.py:2443（写后无读）"),
    ("ctx_snapshot", KIND_BINDING, "agent/chat_pipeline.py:2451"),
    ("max_parallel_tools", KIND_KEY, "security/agent_limits_settings.py（工具批次并行上限）"),
    # G4 工具取消/超时处置（Issue #288）：会话进程回收的接线。
    # 登记前实测判据类为 `no_consumer`（实现完整、生产侧零调用），接线后机器算
    # 为 `consumed`——这一行就是「写了却无人读」那条断点的闭环证据。
    ("kill_all", KIND_SYMBOL, "execution_engine/shell_sessions.py（G4 会话进程回收）"),
)

#: 反向控制：已知生产可达，必须报 `consumed`，且台账处置**永远**是「待处置」。
#: 前两条同时钉住前置警告 1（符号级而非文件级）：它们与 `ToolExecutionPipeline`
#: 同处 `agent/tool_pipeline.py`，按文件判「死」会连带砍断熔断器的观测接线。
REACHABLE_CONTROLS = ("notify_tool_result", "get_pipeline_observers", "TokenBudgetGate")

#: 移除型访问：证明有人动过这个键，不证明有人消费它的值。
_REMOVAL_METHODS = ("pop", "del")

#: 配置键绑定的表达式形态：`<...>[<键>]`（取数只认常量字符串键）。
_SUBSCRIPT_KEY = re.compile(r"\[['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\]")

SETTINGS_FILE = PRODUCTION_ROOT / "security" / "agent_limits_settings.py"


class RefSite(NamedTuple):
    """一个引用点：生产根相对路径 + 行号 + 形态（`def` / `call` / `import` / `read` / `write`）
    + **接收者/作用域**（事实，不是判定）。

    `receiver` 只对 `binding` / `key` 两种取数口径有值：局部量填承载它的函数名，
    字符串键填被下标的表达式（`request_params` / `kwargs` …）。它**不参与**判据类
    的机器判定（接收者归属需要类型推断，静态近似必然误判——上下文域已实测
    `dedup` 与 `clear` 两面反例），只为台账依据提供可核对的事实：
    「唯一一处 `read` 落在另一个接收者上」这件事必须能被读出来，而不是靠人复述。
    """

    path: str
    line: int
    form: str
    receiver: str = ""


def inProductionScope(rel: str) -> bool:
    """该相对路径是否落在**生产根**内（判据限径的唯一谓词）。

    `NeurUI/src-tauri/**/backend/neurova/` 下是运行时副本，`tests/`、`scripts/`、
    `docs/` 是判据自身与文档——它们都不构成「生产消费点」。
    """
    normalized = rel.replace("\\", "/").lstrip("./")
    return normalized == "neurova" or normalized.startswith("neurova/")


def _kindOf(symbol: str) -> str:
    for name, kind, _origin in AUDIT_SYMBOLS:
        if name == symbol:
            return kind
    raise KeyError(f"未登记符号：{symbol}")


def _iterCalls(node: ast.AST) -> List[ast.Call]:
    return [sub for sub in ast.walk(node) if isinstance(sub, ast.Call)]


@functools.lru_cache(maxsize=None)
def _parsed(rel: str) -> ast.AST:
    """按生产根相对路径取语法树（内容戳缓存，改文件即失效）。"""
    return ast_scan._cachedParse(
        ast_scan._cacheKey(REPO_ROOT / rel),
        ast_scan.sourceCode(REPO_ROOT / rel),
    )


# ── 取数：符号级（复用上下文域单源） ─────────────────────────────────────


def _symbolSites(symbol: str) -> List[RefSite]:
    return [
        RefSite(site.path, site.line, site.form)
        for site in symbolLedger.referenceSites(symbol)
    ]


# ── 取数：函数内局部绑定 ────────────────────────────────────────────────


@functools.lru_cache(maxsize=None)
def _bindingScopes(name: str) -> Tuple[Tuple[str, ast.AST], ...]:
    """写入 `name` 的**最内层**函数作用域：`((相对路径, 函数节点), ...)`。

    不限作用域就会串台：全仓同名的另一个局部量（或参数）的读取会被算成本处的消费。
    故只保留「自身含 Store，且不包含另一个候选作用域」的最内层函数。
    """
    candidates: List[Tuple[str, ast.AST]] = []
    for ref in ast_scan.sourceRefsUnder(PRODUCTION_ROOT, hints=(name,)):
        rel = ast_scan.relativeToRepo(ref.path)
        for node in ast.walk(_parsed(rel)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            has_store = any(
                isinstance(sub, ast.Name) and sub.id == name and isinstance(sub.ctx, ast.Store)
                for sub in ast.walk(node)
            )
            if has_store:
                candidates.append((rel, node))
    innermost = [
        (rel, func) for rel, func in candidates
        if not any(
            other is not func
            and other.lineno >= func.lineno
            and (other.end_lineno or other.lineno) <= (func.end_lineno or func.lineno)
            for _orel, other in candidates
        )
    ]
    return tuple(sorted(innermost, key=lambda item: (item[0], item[1].lineno)))


@functools.lru_cache(maxsize=None)
def _bindingSites(name: str) -> Tuple[RefSite, ...]:
    """局部量的写入/读取点（限定在写入它的最内层函数作用域内，接收者=函数名）。"""
    sites: List[RefSite] = []
    for rel, func in _bindingScopes(name):
        for node in ast.walk(func):
            if isinstance(node, ast.arg) and node.arg == name:
                sites.append(RefSite(rel, node.lineno, "def", func.name))
            elif isinstance(node, ast.Name) and node.id == name:
                form = "write" if isinstance(node.ctx, (ast.Store, ast.Del)) else "read"
                sites.append(RefSite(rel, node.lineno, form, func.name))
    return tuple(sorted(set(sites)))


# ── 取数：字典字符串键 ─────────────────────────────────────────────────


@functools.lru_cache(maxsize=None)
def _keySites(key: str) -> Tuple[RefSite, ...]:
    """字符串键的写入/读取点（接收者=被下标的表达式）。

    `X[key] = …` 记 write；`X[key]` 记 read；`X.get(key)` / `key in X` 记 read；
    `X.pop(key)` / `del X[key]` 记 **write**（移除型访问证明有人动过它，不证明有人
    消费它的值）。接收者一并报出——`kwargs.get("tool_choice")` 与
    `request_params["tool_choice"] = …` 是**两个不同的字典**，只报「有一处 read」
    会把「从调用方 kwargs 取值写出」误读成「有人在消费写出的那个键」。
    """
    sites: List[RefSite] = []
    for ref in ast_scan.sourceRefsUnder(PRODUCTION_ROOT, hints=(key,)):
        rel = ast_scan.relativeToRepo(ref.path)
        for node in ast.walk(_parsed(rel)):
            if isinstance(node, ast.Subscript) and _constantKey(node.slice) == key:
                receiver = ast.unparse(node.value)
                removed = isinstance(node.ctx, (ast.Del, ast.Store))
                sites.append(RefSite(rel, node.lineno,
                                     "write" if removed else "read", receiver))
            elif isinstance(node, ast.Call):
                func = node.func
                receiver = ast.unparse(func.value) if isinstance(func, ast.Attribute) else ""
                if (isinstance(func, ast.Attribute) and func.attr in _REMOVAL_METHODS
                        and node.args and _constantKey(node.args[0]) == key):
                    sites.append(RefSite(rel, node.lineno, "write", receiver))
                elif (isinstance(func, ast.Attribute) and func.attr == "get"
                        and node.args and _constantKey(node.args[0]) == key):
                    sites.append(RefSite(rel, node.lineno, "read", receiver))
            elif isinstance(node, ast.Compare) and any(
                isinstance(op, (ast.In, ast.NotIn)) for op in node.ops
            ) and any(_constantKey(comp) == key for comp in [node.left, *node.comparators]):
                sites.append(RefSite(rel, node.lineno, "read",
                                     ast.unparse(node.left)))
    return tuple(sorted(set(sites)))


def _constantKey(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


# ── 判据类：机器算（四值，与上下文域同词汇同规则） ──────────────────────


@functools.lru_cache(maxsize=None)
def referenceSites(symbol: str) -> Tuple[RefSite, ...]:
    """生产侧对 `symbol` 的全部引用点（按种类分派取数口径）。"""
    kind = _kindOf(symbol)
    if kind == KIND_SYMBOL:
        sites = _symbolSites(symbol)
    elif kind == KIND_BINDING:
        sites = _bindingSites(symbol)
    else:
        sites = _keySites(symbol)
    return tuple(site for site in sites if inProductionScope(site.path))


def _judgeFromSites(sites: Tuple[RefSite, ...]) -> Tuple[str, Dict[str, object]]:
    """四个判据类的规则（与上下文域 `classify()` 逐字同规则、同词汇）。"""
    defs = [s for s in sites if s.form == "def"]
    writes = [s for s in sites if s.form == "write"]
    real_use_files = {s.path for s in sites if s.form in ("call", "read")}
    consumers = [
        s for s in sites
        if s.form in ("call", "read")
        or (s.form == "import" and s.path in real_use_files)
    ]
    detail: Dict[str, object] = {
        "def_files": sorted({s.path for s in defs}),
        "write_files": sorted({s.path for s in writes}),
        "consumer_files": sorted({s.path for s in consumers}),
        "write_receivers": sorted({s.receiver for s in writes if s.receiver}),
        "consumer_receivers": sorted({s.receiver for s in consumers if s.receiver}),
    }
    if not defs and not writes:
        detail["rule"] = RULE_ABSENT
        return JUDGE_ABSENT, detail
    if not consumers:
        detail["rule"] = RULE_NO_CONSUMER
        return JUDGE_NO_CONSUMER, detail
    home = {s.path for s in defs} | {s.path for s in writes}
    external = sorted({s.path for s in consumers} - home)
    if external:
        detail["rule"] = RULE_CONSUMED
        return JUDGE_CONSUMED, detail
    detail["rule"] = RULE_SELF_LOOP
    return JUDGE_SELF_LOOP, detail


def classify(symbol: str) -> Tuple[str, Dict[str, object]]:
    """按写死的四值规则给出判据类；返回 `(判据类, 判定过程)`。

    种类为 `binding` / `key` 的符号走本模块的 `_judgeFromSites`；种类为 `symbol`
    的直接复用上下文域模块的 `classify()`（同仓唯一事实源，不重写规则）。
    未登记符号（判据自证时喂合成事实用）按本模块规则就地复算，不走种类分派——
    不抛错，否则规则本身不可被合成输入复算。
    """
    if symbol not in {name for name, _kind, _origin in AUDIT_SYMBOLS}:
        return _judgeFromSites(referenceSites(symbol))
    if _kindOf(symbol) == KIND_SYMBOL:
        judge, detail = symbolLedger.classify(symbol)
        detail = dict(detail)
        detail["consumer_count"] = len([
            site for site in referenceSites(symbol) if site.form in ("call", "read")
        ])
        return judge, detail
    return _judgeFromSites(referenceSites(symbol))


# ── 第二轴：阈值可达性（机器算，四个值） ─────────────────────────────────


def _thresholdParams(classNode: ast.ClassDef) -> Tuple[str, ...]:
    """`check()` 里与 `self.<参数>` 比较的阈值参数名（没有则该符号不是阈值型）。"""
    params: List[str] = []
    for method in classNode.body:
        if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if method.name != "check":
            continue
        for node in ast.walk(method):
            if not isinstance(node, ast.Compare):
                continue
            for side in [node.left, *node.comparators]:
                if (isinstance(side, ast.Attribute) and isinstance(side.value, ast.Name)
                        and side.value.id == "self"):
                    params.append(side.attr)
    return tuple(sorted(set(params)))


def _classNode(symbol: str) -> Optional[Tuple[str, ast.ClassDef]]:
    for site in referenceSites(symbol):
        if site.form != "def":
            continue
        for node in ast.walk(_parsed(site.path)):
            if isinstance(node, ast.ClassDef) and node.name == symbol:
                return site.path, node
    return None


def _ctorBindings(symbol: str) -> Tuple[Dict[str, object], ...]:
    """生产侧构造该门控时，阈值参数的绑定表达式（含从哪个配置键取）。"""
    bindings: List[Dict[str, object]] = []
    for ref in ast_scan.sourceRefsUnder(PRODUCTION_ROOT, hints=(symbol,)):
        rel = ast_scan.relativeToRepo(ref.path)
        for node in ast.walk(_parsed(rel)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name != symbol:
                continue
            for keyword in node.keywords:
                expr = ast.unparse(keyword.value)
                found = _SUBSCRIPT_KEY.search(expr)
                if found:
                    bindings.append({
                        "param": keyword.arg or "",
                        "expr": expr,
                        "config_key": found.group(1),
                        "file": rel,
                        "line": node.lineno,
                    })
    return tuple(bindings)


def _enclosingFunction(rel: str, lineno: int) -> Tuple[str, int]:
    """含该行的最内层函数：`(函数名, 函数起始行)`（站点次序按**函数**分组比较）。"""
    best: Tuple[str, int] = ("", 0)
    for node in ast.walk(_parsed(rel)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = node.end_lineno or node.lineno
        if node.lineno <= lineno <= end and node.lineno >= best[1]:
            best = (node.name, node.lineno)
    return best


def _orderPairs(rel: str, guardLines: List[int], gateLines: List[int]) -> List[Dict[str, object]]:
    """同一函数内「守卫比较」与「门控调用」的先后（`guard_first` / `gate_first`）。

    这是本片能够**机器证明**「门控是否可能出声」的唯一事实：同一轮内守卫先于门控，
    则门控在该路径上永远吃不到阈值（守卫已把计数截断）；门控先于守卫，则门控可以在
    本轮的计数上判定。按函数分组比较，而不是全文件取最小行号——流式与非流式是两条
    独立路径，全文件取最小会把 `_predict_stream` 的 `gate_first` 掩成 `guard_first`。
    """
    pairs: List[Dict[str, object]] = []
    groups: Dict[Tuple[str, int], Dict[str, List[int]]] = {}
    for key, lines in (("guard", guardLines), ("gate", gateLines)):
        for line in lines:
            name, start = _enclosingFunction(rel, line)
            groups.setdefault((name, start), {"guard": [], "gate": []})[key].append(line)
    for (name, start), bucket in sorted(groups.items(), key=lambda item: item[0][1]):
        if not bucket["guard"] or not bucket["gate"]:
            continue
        pairs.append({
            "file": rel,
            "function": name,
            "guard_lines": sorted(bucket["guard"]),
            "gate_lines": sorted(bucket["gate"]),
            "order": "guard_first" if min(bucket["guard"]) < min(bucket["gate"]) else "gate_first",
        })
    return pairs


def _scalingWitnesses(configKey: str) -> Tuple[Dict[str, object], ...]:
    """同配置键的**更小尺度**守卫：`…[<configKey>] // d`（d≥2）的赋值点及用量。"""
    witnesses: List[Dict[str, object]] = []
    pattern = re.compile(r"\[['\"]" + re.escape(configKey) + r"['\"]\]\s*//\s*(\d+)")
    for ref in ast_scan.sourceRefsUnder(PRODUCTION_ROOT, hints=(configKey,)):
        rel = ast_scan.relativeToRepo(ref.path)
        for node in ast.walk(_parsed(rel)):
            if not isinstance(node, ast.Assign):
                continue
            divisor = pattern.search(ast.unparse(node.value))
            if not divisor or int(divisor.group(1)) < 2:
                continue
            targets = [ast.unparse(target) for target in node.targets]
            aliases = _aliasesOf(rel, targets)
            witnesses.append({
                "file": rel,
                "line": node.lineno,
                "targets": targets,
                "divisor": int(divisor.group(1)),
                "guard_lines": _guardLines(rel, targets, aliases),
                "gate_lines": _gateCallLines(rel),
            })
    return tuple(witnesses)


def _aliasesOf(rel: str, targets: List[str]) -> List[str]:
    """被赋值量派生的局部别名（`_max_rounds = getattr(self, "_max_tool_rounds", None) or 10`）。"""
    aliases: List[str] = []
    for node in ast.walk(_parsed(rel)):
        if not isinstance(node, ast.Assign):
            continue
        text = ast.unparse(node.value)
        if not any(target.split(".")[-1] in text for target in targets):
            continue
        aliases += [ast.unparse(target) for target in node.targets
                    if isinstance(target, ast.Name)]
    return aliases


def _guardLines(rel: str, targets: List[str], aliases: List[str]) -> List[int]:
    """该量的比较点（守卫），含经别名间接比较的位置。"""
    needles = [target.split(".")[-1] for target in targets] + aliases
    lines: List[int] = []
    for node in ast.walk(_parsed(rel)):
        if not isinstance(node, ast.Compare):
            continue
        text = ast.unparse(node)
        if any(needle and needle in text for needle in needles):
            lines.append(node.lineno)
    return sorted(set(lines))


def _gateCallLines(rel: str) -> List[int]:
    """该文件里 `GateRunner.on_round_end(...)` 的调用点（门控真正发声的位置）。"""
    return sorted({
        node.lineno for node in ast.walk(_parsed(rel))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "on_round_end"
    })


@functools.lru_cache(maxsize=None)
def settingsBounds() -> Dict[str, int]:
    """配置键的合法下/上界：单源 `security/agent_limits_settings.py`，经 AST 读取。

    不 import 生产模块（判据保持纯 AST 事实，也不引入运行期耦合）。
    """
    rel = ast_scan.relativeToRepo(SETTINGS_FILE)
    bounds: Dict[str, int] = {}
    for node in ast.walk(_parsed(rel)):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                if target.id.startswith("MIN_") or target.id.startswith("MAX_"):
                    bounds[target.id] = int(node.value.value)
    return bounds


def _reachableConfigs(lower: int, upper: int, divisor: int,
                      countsEveryIteration: bool = True) -> List[int]:
    """合法配置域内**门控能吃到阈值**的那些配置值（分片枚举，域是闭区间）。

    计数每轮自增时，被 `// divisor` 的守卫截断前，计数最多能到 `n // divisor + 1`
    （`n // divisor` 轮通过守卫后还要再走一轮才触顶）。门控在 `n` 这个配置上能出声
    当且仅当 `n // divisor + 1 >= n`。这里如实枚举有限域（`MIN_ROUNDS..MAX_ROUNDS`，
    2..200），而不是给一个「恒不成立」的断言——实测该式在小 n 上成立。

    `divisor < 2` 不构成遮蔽（没有更小尺度），此时合法域内全部配置都可达；
    计数不在每轮自增时该式不适用，交回调用方按站点次序判定。
    """
    if not countsEveryIteration:
        return []
    if divisor < 2:
        return list(range(lower, upper + 1))
    return [value for value in range(lower, upper + 1)
            if value // divisor + 1 >= value]


def thresholdAxis(symbol: str) -> Tuple[str, Dict[str, object]]:
    """第二轴的机器判定：`(轴值, 判定过程)`。

    轴值只回答「阈值在**值域**上够不够得到」，取数三条：① 门控构造处直接绑定的配置键；
    ② 生产侧是否存在 `…[同键] // d`（d≥2）的更小尺度守卫；③ 合法配置域内是否存在
    使门控吃到阈值的配置值。站点次序（同一轮内守卫先还是门控先）一并作为事实输出，
    因为它是 `scaled_unreachable` 与 `scaled_sparse` 的唯一分界。
    """
    if symbol not in {name for name, _kind, _origin in AUDIT_SYMBOLS}:
        return THRESHOLD_NOT_APPLICABLE, {"reason": "未登记符号，无阈值参数"}
    if _kindOf(symbol) != KIND_SYMBOL:
        return THRESHOLD_NOT_APPLICABLE, {"reason": "非模块级符号，无阈值参数"}
    found = _classNode(symbol)
    if found is None:
        return THRESHOLD_NOT_APPLICABLE, {"reason": "生产侧无类定义"}
    path, classNode = found
    params = _thresholdParams(classNode)
    if not params:
        return THRESHOLD_NOT_APPLICABLE, {"reason": "check() 无阈值比较", "file": path}
    bindings = _ctorBindings(symbol)
    bound = [item for item in bindings if item["param"] in params]
    if not bound:
        return THRESHOLD_UNBOUND, {
            "reason": "阈值参数在生产侧无配置键绑定来源",
            "params": list(params),
            "bindings": list(bindings),
        }
    configKey = str(bound[0]["config_key"])
    witnesses = _scalingWitnesses(configKey)
    if not witnesses:
        return THRESHOLD_SINGLE_SOURCE, {
            "reason": "该配置键在生产侧只有一个尺度",
            "params": list(params),
            "config_key": configKey,
            "binding": bound[0],
        }
    bounds = settingsBounds()
    lower = int(bounds.get("MIN_ROUNDS", 0))
    upper = int(bounds.get("MAX_ROUNDS", 0))
    divisor = int(witnesses[0]["divisor"])
    orders = [
        pair for witness in witnesses
        for pair in _orderPairs(str(witness["file"]),
                                list(witness["guard_lines"]), list(witness["gate_lines"]))
    ]
    reachable = _reachableConfigs(lower, upper, divisor)
    # 守卫在**每条路径**上都先于门控 ⇒ 门控连一轮阈值都吃不到（与值域无关）。
    allGuardFirst = bool(orders) and all(pair["order"] == "guard_first" for pair in orders)
    detail: Dict[str, object] = {
        "params": list(params),
        "config_key": configKey,
        "binding": bound[0],
        "witnesses": list(witnesses),
        "settings_bounds": bounds,
        "orders": orders,
        "legal_configs": {"lower": lower, "upper": upper, "divisor": divisor},
        "reachable_configs": reachable,
    }
    if allGuardFirst or not reachable:
        detail["reason"] = "被更小尺度守卫遮蔽，合法配置域内门控吃不到阈值"
        return THRESHOLD_SCALED_UNREACHABLE, detail
    detail["reason"] = "被更小尺度守卫遮蔽，合法配置域内仅少数配置能让门控出声"
    return THRESHOLD_SCALED_SPARSE, detail


# ── 事实层与台账对账 ────────────────────────────────────────────────────


@functools.lru_cache(maxsize=None)
def facts() -> Tuple[Dict[str, object], ...]:
    """全部登记符号的取数结果（事实层：引用点、判据类、第二轴）。"""
    rows: List[Dict[str, object]] = []
    for symbol, kind, origin in AUDIT_SYMBOLS:
        sites = referenceSites(symbol)
        judge, detail = classify(symbol)
        axis, axisDetail = thresholdAxis(symbol)
        rows.append({
            "symbol": symbol,
            "kind": kind,
            "origin": origin,
            "sites": [site._asdict() for site in sites],
            "site_count": len(sites),
            "consumer_count": len([s for s in sites if s.form in ("call", "read")]),
            "consumer_forms": sorted({s.form for s in sites if s.form in ("call", "read")}),
            "judge": judge,
            "judge_label": JUDGE_LABELS[judge],
            "classify": detail,
            "threshold_axis": axis,
            "threshold_detail": axisDetail,
        })
    return tuple(rows)


def readLedger() -> Dict[str, Dict[str, str]]:
    """读台账：`{符号: {kind, judge, threshold, count, disposal, basis}}`。"""
    entries: Dict[str, Dict[str, str]] = {}
    for raw in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 7:
            raise ValueError(
                "台账行不是「符号 | 种类 | 判据类 | 阈值可达性 | 引用点数 | 处置 | 依据」七列: "
                f"{raw!r}"
            )
        entries[parts[0]] = {
            "kind": parts[1],
            "judge": parts[2],
            "threshold": parts[3],
            "count": parts[4],
            "disposal": parts[5],
            "basis": "|".join(parts[6:]).strip(),
        }
    return entries


def reconcile() -> Dict[str, List[Dict[str, object]]]:
    """台账与实测对账：判据类、第二轴、引用点数、种类、依据、反向控制。"""
    rows = facts()
    ledger = readLedger()
    problems: Dict[str, List[Dict[str, object]]] = {
        "missing": [], "not_registered": [], "unknown_judge": [],
        "unknown_disposal": [], "unknown_kind": [], "unknown_threshold": [],
        "empty_basis": [], "judge_conflict": [], "threshold_conflict": [],
        "count_conflict": [], "kind_conflict": [], "pending_controls": [],
    }
    for row in rows:
        symbol = str(row["symbol"])
        entry = ledger.get(symbol)
        if entry is None:
            problems["not_registered"].append({"symbol": symbol, "origin": row["origin"]})
            continue
        if entry["judge"] not in JUDGE_CLASSES:
            problems["unknown_judge"].append({"symbol": symbol, "judge": entry["judge"]})
        elif entry["judge"] != row["judge"]:
            problems["judge_conflict"].append({
                "symbol": symbol, "ledger": entry["judge"], "computed": row["judge"],
                "rule": row["classify"]["rule"],
            })
        if entry["kind"] not in KINDS:
            problems["unknown_kind"].append({"symbol": symbol, "kind": entry["kind"]})
        elif entry["kind"] != row["kind"]:
            problems["kind_conflict"].append({
                "symbol": symbol, "ledger": entry["kind"], "computed": row["kind"],
            })
        if entry["threshold"] not in THRESHOLD_CLASSES:
            problems["unknown_threshold"].append(
                {"symbol": symbol, "threshold": entry["threshold"]})
        elif entry["threshold"] != row["threshold_axis"]:
            problems["threshold_conflict"].append({
                "symbol": symbol, "ledger": entry["threshold"],
                "computed": row["threshold_axis"],
                "reason": row["threshold_detail"].get("reason"),
            })
        if not entry["count"].isdigit() or int(entry["count"]) != row["site_count"]:
            problems["count_conflict"].append({
                "symbol": symbol, "ledger": entry["count"], "measured": row["site_count"],
            })
        if entry["disposal"] not in DISPOSALS:
            problems["unknown_disposal"].append(
                {"symbol": symbol, "disposal": entry["disposal"]})
        if not entry["basis"]:
            problems["empty_basis"].append({"symbol": symbol})
        if symbol in REACHABLE_CONTROLS and entry["disposal"] != DISPOSAL_PENDING:
            problems["pending_controls"].append(
                {"symbol": symbol, "disposal": entry["disposal"]})
    registered = {str(row["symbol"]) for row in rows}
    for symbol in ledger:
        if symbol not in registered:
            problems["missing"].append({"symbol": symbol})
    return problems


def disposalConflicts() -> List[Dict[str, object]]:
    """处置与判据的咬合判据（纯函数，可喂合成输入自证）。

    声明「已删除 / 收口第二份」⇒ 实测判据类必须是 `absent`；
    声明「已接线」⇒ 必须是 `consumed`。写「已删除」而符号还在 = 处置是口号。
    """
    factsBySymbol = {str(row["symbol"]): row for row in facts()}
    conflicts: List[Dict[str, object]] = []
    for symbol, entry in readLedger().items():
        row = factsBySymbol.get(symbol)
        if row is None:
            continue
        judge = str(row["judge"])
        disposal = entry["disposal"]
        if disposal in (DISPOSAL_RETIRED, DISPOSAL_MERGED) and judge != JUDGE_ABSENT:
            conflicts.append({
                "symbol": symbol, "disposal": disposal, "judge": judge,
                "expected": JUDGE_ABSENT,
            })
        elif disposal == DISPOSAL_WIRED and judge != JUDGE_CONSUMED:
            conflicts.append({
                "symbol": symbol, "disposal": disposal, "judge": judge,
                "expected": JUDGE_CONSUMED,
            })
    return conflicts


def main() -> int:
    parser = argparse.ArgumentParser(description="工具/loop 域死线判据取数与台账对账")
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

    print("工具/loop 域死线判据取数与台账对账（T-01）")
    print(f"  登记符号 {len(rows)} | 台账条目 {len(ledger)}")
    for row in rows:
        symbol = str(row["symbol"])
        entry = ledger.get(symbol, {})
        print(f"  {symbol:28s} {row['kind']:8s} 判据:{row['judge']:11s}"
              f" 阈值:{row['threshold_axis']:15s}"
              f" 引用 {row['site_count']:2d}（消费 {row['consumer_count']}）"
              f" {entry.get('disposal', '未登记')}")
    if any(problems.values()):
        print("\n对账问题：")
        for key, items in problems.items():
            if items:
                print(f"  {key}: {items}")
        return 1

    print(f"\n反向控制项（必须为 {JUDGE_CONSUMED} 且处置为「{DISPOSAL_PENDING}」）："
          f"{', '.join(REACHABLE_CONTROLS)}")
    print("一致性 OK：判据类/第二轴/引用点数与台账一致、枚举合法、依据非空。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
