"""受限 AST 表达式求值器（specs/2026-11-12 §4 W2）。

函数层的语言面：算术 `+ - * / %`、比较 `> >= < <= == !=`、布尔 `and/or/not`、
常量、绑定变量、聚合 `sum/count/avg/min/max(selector)`；selector＝
`facts(predicate, qualifierFilter?, asOf?)` 事实集选择器。

**禁止**（登记时编译即拒，不求值不执行）：属性访问、下标、调用白名单外名字、
import、lambda、推导式、字典、if 表达式、f-string。求值是纯 AST 解释——
模块内不出现 `eval`/`exec`（守卫测试逐字钉住）。

D1（§16 已裁）：selector 取**全租户**事实集，行数超 `SELECTOR_ROW_CAP`
显式拒（`SelectorCapError`），不静默截断。聚合消费事实 object_term 的
量值（quantity.parseQuantity 单源解析，W1 产物）；qualifierFilter 值以
`$名字` 引用 input_bindings。
"""

from __future__ import annotations

import ast
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set, Tuple

#: selector 取数上限（D1：超限显式拒，不静默截断）
SELECTOR_ROW_CAP = 5000
#: 表达式 AST 深度上限
MAX_EXPR_DEPTH = 20
#: 表达式 AST 节点数上限
MAX_EXPR_NODES = 200

_ALLOWED_AGGREGATES = ("sum", "count", "avg", "min", "max")
_ALLOWED_SELECTOR_KWARGS = ("qualifierfilter", "asof")

_ALLOWED_NODES: Tuple[type, ...] = (
    ast.Expression, ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
    ast.UnaryOp, ast.USub, ast.UAdd, ast.Not, ast.BoolOp, ast.And, ast.Or,
    ast.Compare, ast.Gt, ast.GtE, ast.Lt, ast.LtE, ast.Eq, ast.NotEq,
    ast.Constant, ast.Name, ast.Load, ast.Call, ast.keyword,
    # Dict 仅限 selector 的 qualifierFilter 字面量（键须字符串常量、值须常量/绑定名，
    # 结构约束在 _collectNames 里逐键验）——出现在别处照样拒。
    ast.Dict,
)


class FunctionCompileError(ValueError):
    """登记期编译拒绝（未知符号/越界节点/超深度超尺寸）。"""


class SelectorCapError(ValueError):
    """selector 命中行数超上限——显式拒（D1），绝不静默截断。"""


class SelectorAmbiguityError(ValueError):
    """谓词声明了多个数值限定键，selector 无法确定聚合哪个——显式拒，不猜。"""


class SelectorResult(NamedTuple):
    """selector 取数产物：可聚合数值、贡献前提的事实 id（溯源）、命中事实数。

    `count` 聚合读 `matchedCount`（事实集语义）；sum/avg/min/max 读 `values`
    （量值语义，object_term 经 quantity.parseQuantity 单源解析）。"""
    values: List[float]
    factIds: List[str]
    matchedCount: int


def _checkNode(node: ast.AST, depth: int, counter: List[int]) -> None:
    """编译期白名单巡检：节点类型/深度/尺寸/名字与调用形状。"""
    counter[0] += 1
    if counter[0] > MAX_EXPR_NODES:
        raise FunctionCompileError("表达式节点数超上限 %d" % MAX_EXPR_NODES)
    if depth > MAX_EXPR_DEPTH:
        raise FunctionCompileError("表达式深度超上限 %d" % MAX_EXPR_DEPTH)
    if not isinstance(node, _ALLOWED_NODES):
        raise FunctionCompileError(
            "表达式含白名单外节点 %s（禁止属性访问/下标/lambda/推导式/import 等）"
            % type(node).__name__)
    for child in ast.iter_child_nodes(node):
        _checkNode(child, depth + 1, counter)


def _collectNames(node: ast.AST, names: Set[str], selectorPredicates: List[str]) -> None:
    """收集自由名字与 selector 谓词（编译期静态依赖）。"""
    if isinstance(node, ast.Name):
        names.add(node.id)
    if isinstance(node, ast.Dict):
        # qualifierFilter 字面量：键须字符串常量，值须常量或绑定名
        for keyNode in node.keys:
            if not isinstance(keyNode, ast.Constant) or not isinstance(keyNode.value, str):
                raise FunctionCompileError("qualifierFilter 键须字符串字面量")
        for valueNode in node.values:
            if isinstance(valueNode, ast.Constant):
                continue
            if isinstance(valueNode, ast.Name):
                names.add(valueNode.id)
                continue
            raise FunctionCompileError("qualifierFilter 值须字面量或绑定名")
        return
    if isinstance(node, ast.Call):
        func = node.func
        if not isinstance(func, ast.Name):
            raise FunctionCompileError("调用目标须是名字（禁止属性调用）")
        names.add(func.id)  # 全部调用名进名字闭包——白名单外（__import__/open…）编译即拒
        if func.id != "facts":
            for arg in node.args:
                _collectNames(arg, names, selectorPredicates)
            for kw in node.keywords:
                _collectNames(kw.value, names, selectorPredicates)
            return
        if not node.args or not isinstance(node.args[0], ast.Constant) \
                or not isinstance(node.args[0].value, str):
            raise FunctionCompileError(
                "selector 谓词须是字符串字面量（静态可提依赖，不接受拼接）")
        selectorPredicates.append(node.args[0].value)
        # 位置形：facts(pred, {filter}?, "asOf"?)；关键字形：qualifierFilter=/asOf=
        if len(node.args) > 3:
            raise FunctionCompileError("selector 至多三个参数（predicate/qualifierFilter/asOf）")
        for arg in node.args[1:]:
            _collectNames(arg, names, selectorPredicates)
        for kw in node.keywords:
            if kw.arg is None or kw.arg.casefold() not in _ALLOWED_SELECTOR_KWARGS:
                raise FunctionCompileError("selector 关键字只接受 qualifierFilter/asOf")
            _collectNames(kw.value, names, selectorPredicates)
        return
    for child in ast.iter_child_nodes(node):
        _collectNames(child, names, selectorPredicates)


class CompiledFunction:
    """编译产物：AST＋静态依赖。求值走本类的解释器，零 eval/exec。"""

    def __init__(self, exprText: str, tree: ast.Expression,
                 selectorPredicates: List[str], freeNames: Set[str]) -> None:
        self.exprText = exprText
        self._tree = tree
        self.selectorPredicates = selectorPredicates
        self.freeNames = freeNames


def compileFunction(exprText: str, allowedNames: Tuple[str, ...] = (),
                    allowedPredicates: Tuple[str, ...] = ()) -> CompiledFunction:
    """登记期编译：解析→白名单巡检→名字闭包→selector 谓词在册校验→Dict 位置检查。

    `allowedNames` 是 input_bindings 声明的变量名（外层注册面传入）；出现
    闭包外自由名即拒（调用名一律进闭包——`__import__`/`open` 等编译即拒）。
    `allowedPredicates` 是注册表在册谓词闭集（B-10 纪律），selector 引用表外
    谓词即拒。Dict 仅允许作为 facts selector 的 qualifierFilter 字面量出现，
    表达式其他位置出现即拒。
    """
    text = str(exprText or "").strip()
    if not text:
        raise FunctionCompileError("表达式为空")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise FunctionCompileError("表达式语法错误：%s" % exc) from exc
    counter = [0]
    _checkNode(tree, 0, counter)
    names: Set[str] = set()
    selectorPredicates: List[str] = []
    _collectNames(tree, names, selectorPredicates)
    unknown = sorted(n for n in names
                     if n not in allowedNames and n not in _ALLOWED_AGGREGATES
                     and n != "facts")
    if unknown:
        raise FunctionCompileError("表达式含未知符号 %r（绑定变量须在 input_bindings 声明）"
                                   % unknown)
    missing = [p for p in selectorPredicates
               if allowedPredicates and p not in allowedPredicates]
    if missing:
        raise FunctionCompileError(
            "selector 引用的谓词 %r 不在注册表（B-10：谓词清单取注册表）" % missing)
    # Dict 位置白名单：只有 facts 调用的 qualifierFilter 关键字下允许 Dict 字面量
    allowedDictIds = {id(d) for d in _selectorFilterDicts(tree)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and id(node) not in allowedDictIds:
            raise FunctionCompileError(
                "Dict 字面量仅限 selector 的 qualifierFilter（表达式其余位置禁止字典）")
    return CompiledFunction(text, tree, selectorPredicates, names)


def _selectorFilterDicts(tree: ast.AST) -> List[ast.Dict]:
    """收集 facts 调用 qualifierFilter 的 Dict 节点（位置白名单的正集；位置形＋关键字形）。"""
    out: List[ast.Dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "facts":
            for arg in node.args[1:]:
                if isinstance(arg, ast.Dict):
                    out.append(arg)
            for kw in node.keywords:
                if kw.arg is not None and kw.arg.casefold() == "qualifierfilter" \
                        and isinstance(kw.value, ast.Dict):
                    out.append(kw.value)
    return out


def makeSelectorRunner(store: Any, agentId: str, tenantId: str = "default",
                       asOfDefault: str = "",
                       ) -> Callable[[Dict[str, Any], Dict[str, Any]], "SelectorResult"]:
    """selector 求值器工厂：`facts(predicate, qualifierFilter?, asOf?)` → SelectorResult。

    - **数值源**：谓词在注册表声明了唯一数值限定键（quantity.numericQualifierKeys
      单点判据）→ 取该键 canonical 值（W1 写入口归一产物）；声明多个数值键 →
      SelectorAmbiguityError 显式拒（不猜用哪个）；未声明 → 回退
      quantity.parseQuantity(object_term)。不可解析的行不进 values（聚合只吃
      数值），但计入 matchedCount 与 factIds。
    - qualifierFilter 键支持 `subject_key` 精确过滤与 qualifier JSON 键包含；
      值 `$名字` 引用 bindings。
    - 行数超 SELECTOR_ROW_CAP 显式拒（D1）。查询走 factsBitemporal（W0-1 判据
      继承：非法 asOf 同样显式 ValueError）。
    """
    import json as _json

    numericKeysCache: Dict[str, List[str]] = {}

    def _numericKeysFor(predicate: str) -> List[str]:
        if predicate not in numericKeysCache:
            try:
                from neurova.knowledge.ontology.quantity import numericQualifierKeys
                from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

                term = OntologyTermRegistry(store).term(predicate, tenantId=tenantId)
                numericKeysCache[predicate] = numericQualifierKeys(term)
            except Exception:  # noqa: BLE001 - 术语面故障按未声明处理（回退 object_term）
                numericKeysCache[predicate] = []
        return numericKeysCache[predicate]

    def run(selector: Dict[str, Any], bindings: Dict[str, Any]) -> "SelectorResult":
        from neurova.knowledge.foundation.knowledge_facts import get_knowledge_fact_store

        predicate = str(selector.get("predicate") or "")
        qualifierFilter = selector.get("qualifierFilter") or {}
        asOf = str(selector.get("asOf") or asOfDefault or "")
        factStore = store if store is not None else get_knowledge_fact_store()
        with factStore._lock:
            total = factStore._conn.execute(
                "SELECT COUNT(*) AS n FROM knowledge_facts"
                " WHERE agent_id = ? AND tenant_id = ? AND predicate_term_id = ?"
                " AND status = 'active' AND record_kind = 'triple'",
                (agentId, tenantId, predicate)).fetchone()["n"]
        if int(total) > SELECTOR_ROW_CAP:
            raise SelectorCapError(
                "selector %r 命中 %d 行超上限 %d（D1：显式拒不截断）"
                % (predicate, int(total), SELECTOR_ROW_CAP))
        facts = factStore.factsBitemporal(
            agentId, tenantId=tenantId, predicate=predicate, asOf=asOf)
        values: List[float] = []
        factIds: List[str] = []
        from neurova.knowledge.ontology.quantity import parseQuantity

        numericKeys = _numericKeysFor(predicate)
        if len(numericKeys) > 1:
            raise SelectorAmbiguityError(
                "谓词 %r 声明了多个数值限定键 %r，selector 无法确定聚合哪个"
                % (predicate, numericKeys))
        numericKey = numericKeys[0] if numericKeys else ""
        for fact in facts:
            if not _matchFilter(fact, qualifierFilter, bindings):
                continue
            factIds.append(str(fact.get("fact_id") or ""))
            value: Optional[float] = None
            qualifier = fact.get("qualifier") or {}
            if numericKey and isinstance(qualifier, dict):
                stored = qualifier.get(numericKey)
                if isinstance(stored, dict) and isinstance(stored.get("value"), (int, float)):
                    value = float(stored["value"])  # W1 写入口归一的 canonical 量值
            if value is None:
                parsed = parseQuantity(fact.get("object_term"))
                if parsed is not None:
                    value = float(parsed["value"]) * float(parsed.get("multiplier", 1.0))
            if value is not None:
                values.append(value)
        return SelectorResult(values=values, factIds=factIds,
                              matchedCount=len(factIds))

    def _matchFilter(fact: Dict[str, Any], qualifierFilter: Dict[str, Any],
                     bindings: Dict[str, Any]) -> bool:
        for key, expectedRaw in (qualifierFilter or {}).items():
            expected = expectedRaw
            if isinstance(expectedRaw, str) and expectedRaw.startswith("$"):
                expected = bindings.get(expectedRaw[1:])
            if expected is None:
                return False
            if key == "subject_key":
                # 绑定值语义是主体规范标签（input_bindings 主语变元）：
                # 按规范标签解析出 subject_key 再比对（大小写/空白不敏感）。
                wanted = _resolveSubjectKey(str(expected))
                if str(fact.get("subject_key") or "") != wanted:
                    return False
                continue
            qualifier = fact.get("qualifier") or {}
            actual = qualifier
            try:
                actual = _json.loads(qualifier) if isinstance(qualifier, str) else qualifier
            except Exception:  # noqa: BLE001 - qualifier 非法即不过滤
                actual = {}
            stored = (actual or {}).get(key)
            if isinstance(stored, dict) and "value" in stored:
                stored = stored.get("value")
            if stored is None or str(stored) != str(expected):
                return False
        return True

    def _resolveSubjectKey(expected: str) -> str:
        """先按 subject_key 精确匹配，再按规范标签解析（绑定值语义是规范标签）。"""
        with store._lock:
            row = store._conn.execute(
                "SELECT subject_key FROM knowledge_subjects"
                " WHERE agent_id = ? AND tenant_id = ? AND subject_key = ?"
                " AND status = 'active'",
                (agentId, tenantId, expected)).fetchone()
            if row is None:
                row = store._conn.execute(
                    "SELECT subject_key FROM knowledge_subjects"
                    " WHERE agent_id = ? AND tenant_id = ? AND normalized_label = ?"
                    " AND status = 'active'",
                    (agentId, tenantId, expected.strip().casefold())).fetchone()
        return str(row["subject_key"]) if row is not None else "\x00no-such-subject"

    return run


def evaluateFunction(compiled: CompiledFunction, bindings: Dict[str, Any],
                     selectorRunner: Callable[[Dict[str, Any], Dict[str, Any]], List[float]],
                     ) -> Optional[float]:
    """纯 AST 解释求值：返回数值或 None（空集 avg/min/max 诚实 None）。

    顶层是聚合调用时直接聚合（facts selector 只能被聚合消费）。"""
    body = compiled._tree.body
    if isinstance(body, ast.Call) and isinstance(body.func, ast.Name) \
            and body.func.id in _ALLOWED_AGGREGATES:
        return _evalAggregate(body, dict(bindings or {}), selectorRunner)
    return _evalNode(body, dict(bindings or {}), selectorRunner)


def _evalNode(node: ast.AST, bindings: Dict[str, Any],
              selectorRunner: Callable) -> Optional[float]:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise FunctionCompileError("仅数值常量可参与计算：%r" % (node.value,))
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id in bindings:
            value = bindings[node.id]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise FunctionCompileError("绑定变量 %s 不是数值" % node.id)
            return float(value)
        raise FunctionCompileError("求值期未知符号 %s" % node.id)
    if isinstance(node, ast.UnaryOp):
        value = _evalNode(node.operand, bindings, selectorRunner)
        if value is None:
            return None
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.Not):
            return 0.0 if value else 1.0
        raise FunctionCompileError("白名单外一元运算 %s" % type(node.op).__name__)
    if isinstance(node, ast.BinOp):
        left = _evalNode(node.left, bindings, selectorRunner)
        right = _evalNode(node.right, bindings, selectorRunner)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise FunctionCompileError("除零：表达式在当前输入下无定义")
            return left / right
        if isinstance(node.op, ast.Mod):
            if right == 0:
                raise FunctionCompileError("模零：表达式在当前输入下无定义")
            return left % right
        raise FunctionCompileError("白名单外运算 %s" % type(node.op).__name__)
    if isinstance(node, ast.BoolOp):
        results = [_evalNode(v, bindings, selectorRunner) for v in node.values]
        if any(r is None for r in results):
            return None
        if isinstance(node.op, ast.And):
            return 1.0 if all(r != 0 for r in results) else 0.0
        return 1.0 if any(r != 0 for r in results) else 0.0
    if isinstance(node, ast.Compare):
        left = _evalNode(node.left, bindings, selectorRunner)
        rest = [_evalNode(c, bindings, selectorRunner) for c in node.comparators]
        if left is None or any(r is None for r in rest):
            return None
        current = left
        for op, right in zip(node.ops, rest):
            ok = _compareOp(op, current, right)
            if not ok:
                return 0.0
            current = right
        return 1.0
    if isinstance(node, ast.Call):
        func = node.func
        if not isinstance(func, ast.Name):
            raise FunctionCompileError("白名单外调用（仅聚合内允许 facts selector）")
        if func.id in _ALLOWED_AGGREGATES:
            return _evalAggregate(node, bindings, selectorRunner)
        if func.id == "facts":
            raise FunctionCompileError("裸 facts selector 不产生数值（仅聚合可消费）")
        raise FunctionCompileError("白名单外调用 %s" % func.id)
    raise FunctionCompileError("求值期白名单外节点 %s" % type(node).__name__)


def _filterDictOf(dictNode: ast.Dict) -> Dict[str, Any]:
    """qualifierFilter 字典字面量 → 求值期过滤字典（值 `$名字` 表示绑定引用）。"""
    filterOut: Dict[str, Any] = {}
    for kNode, vNode in zip(dictNode.keys, dictNode.values):
        if not isinstance(kNode, ast.Constant) or not isinstance(kNode.value, str):
            raise FunctionCompileError("qualifierFilter 键须字符串字面量")
        if isinstance(vNode, ast.Constant):
            filterOut[kNode.value] = vNode.value
        elif isinstance(vNode, ast.Name):
            filterOut[kNode.value] = "$" + vNode.id
        else:
            raise FunctionCompileError("qualifierFilter 值须字面量或绑定名")
    return filterOut


def _compareOp(op: ast.AST, left: float, right: float) -> bool:
    if isinstance(op, ast.Gt):
        return left > right
    if isinstance(op, ast.GtE):
        return left >= right
    if isinstance(op, ast.Lt):
        return left < right
    if isinstance(op, ast.LtE):
        return left <= right
    if isinstance(op, ast.Eq):
        return left == right
    if isinstance(op, ast.NotEq):
        return left != right
    raise FunctionCompileError("白名单外比较 %s" % type(op).__name__)


def _evalAggregate(node: ast.Call, bindings: Dict[str, Any],
                   selectorRunner: Callable) -> Optional[float]:
    name = node.func.id
    if not node.args:
        raise FunctionCompileError("聚合缺 selector 参数")
    selectorArg = node.args[0]
    if not isinstance(selectorArg, ast.Call) or not isinstance(selectorArg.func, ast.Name) \
            or selectorArg.func.id != "facts":
        raise FunctionCompileError("聚合参数必须是 facts(...) selector")
    selector: Dict[str, Any] = {"predicate": selectorArg.args[0].value}
    # 位置形：facts(pred, {filter}?, "asOf"?)；关键字形：qualifierFilter=/asOf=
    for arg in selectorArg.args[1:]:
        if isinstance(arg, ast.Dict):
            selector["qualifierFilter"] = _filterDictOf(arg)
        elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            selector["asOf"] = arg.value
        else:
            raise FunctionCompileError("selector 位置参数须 qualifierFilter 字典或 asOf 字符串")
    for kw in selectorArg.keywords:
        key = kw.arg.casefold()
        if isinstance(kw.value, ast.Constant):
            selector["asOf" if key == "asof" else "qualifierFilter"] = kw.value.value
        elif isinstance(kw.value, ast.Dict):
            selector["qualifierFilter"] = _filterDictOf(kw.value)
        else:
            raise FunctionCompileError("selector 关键字值须字面量或 qualifierFilter 字典")
    result = selectorRunner(selector, bindings)
    values = result.values
    if name == "count":
        return float(result.matchedCount)
    if name == "sum":
        return float(sum(values))
    if not values:
        return None
    if name == "avg":
        return float(sum(values) / len(values))
    if name == "min":
        return float(min(values))
    return float(max(values))
