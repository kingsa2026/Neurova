"""Rete v2 求值档（U5）：AlphaNode / BetaNode / TerminalNode 三段网络。

与 full_replay / rete 共用同一规则表、同一推导账本、同一咽喉写入契约——本模块只替换
「匹配」这一段：AlphaNode 预编译谓词与变元位置，BetaNode 做绑定一致性合并，
TerminalNode 触发结论写入。三条单点纪律（不新造平行体系）：

- body 形状直接用 `ForwardChainingEngine._hydrate` 的产物，不重新解析 body_json；
- 否定判定复用 `_negatedHolds` / `_negatedConstHolds`（分层语义不在此重复实现）；
- 结论落库只走 `_admitDerivedFact`（咽喉单点），本模块零 SQL 写入。

绑定值域：主体位置绑 subject_key（"key" 域），客体位置绑 object_term（"term" 域）。
relay 链的中项在上一原子是客体、在下一原子是主体，一致性合并经 knowledge_subjects
的 (agent_id, normalized_label → subject_key) 桥接——与 `_fireRule` 的 SQL JOIN
逐字同义：客体没登记成主体就接不上、逐跳要求同 agent、conjunction/inverse 形状
另带租户过滤（relay 与既有 SQL 一样只按 agent 圈域）。

激活去重：TerminalNode 按（规则, 绑定规范形）记已点火集合；同一 fireAll 跨轮复用
同一个网络，因此同绑定即使被后续轮次的 delta 重新匹配到，也不再触发第二次咽喉。
同一头绑定的多条前提路径按 `_fireRule` 的 GROUP BY 语义合并前提后一次写入。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _sqlLowerTrim(text: str) -> str:
    """SQLite `lower(trim(x))` 的逐字镜像：trim 只去空格、lower 只折 ASCII 大写。

    主体桥接的键必须与 `_fireRule` 里 `lower(trim(a.object_term))` 的取值域一致；
    Python 的 str.lower 对非 ASCII 也折行，会与 SQLite 产生分叉，这里显式按
    SQLite 语义实现。
    """
    stripped = str(text or "").strip(" ")
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in stripped)


class AlphaNode:
    """单原子预编译：谓词钉死 + 变元位置钉死（条件类原子的客体是常量）。"""

    __slots__ = ("atomIndex", "predicate", "subjectVar", "objectVar", "objectConst")

    def __init__(self, atomIndex: int, atom: Dict[str, str]) -> None:
        self.atomIndex = atomIndex
        self.predicate = str(atom.get("predicate") or "")
        self.subjectVar = str(atom.get("subject") or "")
        self.objectVar = str(atom.get("object") or "")
        self.objectConst = str(atom.get("objectConst") or "")

    def bind(self, fact: Dict[str, Any]) -> Optional[Tuple[Tuple[str, str, str], ...]]:
        """事实 → 本原子的变元绑定（(变元, 域, 值) 三元组）；常量客体不合即 None。"""
        if self.objectConst:
            if fact["object_term"] != self.objectConst:
                return None
            return ((self.subjectVar, "key", fact["subject_key"]),)
        return ((self.subjectVar, "key", fact["subject_key"]),
                (self.objectVar, "term", fact["object_term"]))


class _Token:
    """β 内存里的 token：变元绑定 + 沿途事实（按原子序，作前提血缘）＋ 主体域。"""

    __slots__ = ("bindings", "agentId", "facts")

    def __init__(self, bindings: Dict[str, Tuple[str, str]],
                 agentId: str, facts: Tuple[Dict[str, Any], ...]) -> None:
        self.bindings = bindings
        self.agentId = agentId
        self.facts = facts

    def canonicalKey(self) -> Tuple:
        """绑定规范形（激活去重的键）：已绑定变元首次绑定的 (域, 值) 排序元组。"""
        return tuple(sorted(self.bindings.items()))


class BetaNode:
    """绑定一致性合并：左内存 token × 右 alpha 原子。

    一致性判据与 `_fireRule` / `_fireConjunction` 的 SQL 逐字同义：
    - 接续变元（relay 链＝上一原子客体即下一原子主体；conjunction＝共享 head 主语）
      按主体键直查 alpha 索引；term 域的值先过主体桥接，没登记成主体的客体接不上；
    - 事实的 agent 必须与左 token 一致（SQL 的 `b.agent_id = a.agent_id`）；
    - conjunction/inverse 形状另加租户过滤（SQL 的 tenant_id 谓词；relay 无此过滤）。
    已绑定变元不重复改写（首次绑定为准），token 规范形因此确定。
    """

    __slots__ = ("alpha", "tenantScoped")

    def __init__(self, alpha: AlphaNode, tenantScoped: bool) -> None:
        self.alpha = alpha
        self.tenantScoped = tenantScoped

    def merge(self, token: _Token, index: "_AlphaIndex", tenantId: str) -> List[_Token]:
        alpha = self.alpha
        expectedKeys = index.expectedSubjectKeys(token, alpha.subjectVar)
        candidates = (index.byPredicate(alpha.predicate) if expectedKeys is None
                      else index.bySubject(alpha.predicate, expectedKeys))
        out: List[_Token] = []
        for fact in candidates:
            if fact["agent_id"] != token.agentId:
                continue
            if self.tenantScoped and fact["tenant_id"] != tenantId:
                continue
            bind = alpha.bind(fact)
            if bind is None:
                continue
            merged = dict(token.bindings)
            for var, domain, value in bind:
                if var not in merged:
                    merged[var] = (domain, value)
            out.append(_Token(merged, token.agentId, token.facts + (fact,)))
        return out


class TerminalNode:
    """终端节点：满绑定触发结论写入——只经 `engine._admitDerivedFact` 咽喉，不直插 SQL。

    头部分配与 `_fireRule` / `_fireConjunction` / `_fireInverse` 逐字同义：
    - relay：head 主语取首原子主体键、head 客体取末原子客体词形；
    - conjunction：head 客体 = headObjectConst；
    - inverse：head 主语 = 前提客体词形、head 客体 = 前提主体的规范标签、subjectKey 留空。
    主体的规范标签查不到（SQL 的 INNER JOIN 落空）时该激活不产结论——与既有求值器
    同一取舍。激活去重的集合挂在节点上，随网络跨轮复用。
    """

    def __init__(self, rule: Dict[str, Any], shape: str, negated: List[Dict[str, str]],
                 engine: Any) -> None:
        self._rule = rule
        self._shape = shape
        self._negated = negated
        self._engine = engine
        self._fired: set = set()

    def fire(self, tokens: List[_Token], index: "_AlphaIndex",
             agentId: Optional[str], tenantId: str) -> List[str]:
        groups: Dict[Tuple, List[str]] = {}
        for token in tokens:
            key = (self._rule["rule_id"], token.canonicalKey())
            if key in self._fired:
                continue
            self._fired.add(key)
            assignment = self._headAssignment(token, index)
            if assignment is None:
                continue
            groupKey, premises = assignment
            bucket = groups.setdefault(groupKey, [])
            for premiseId in premises:
                if premiseId not in bucket:
                    bucket.append(premiseId)
        written: List[str] = []
        for groupKey, premises in groups.items():
            label, predicate, objectTerm, subjectKey, negSubject, negObject = groupKey
            if self._negationHolds(agentId, tenantId, subjectKey, negSubject, negObject):
                continue
            factId = self._engine._admitDerivedFact(
                self._rule, agentId, label, predicate, objectTerm, subjectKey,
                premises, tenantId=tenantId)
            if factId:
                written.append(factId)
        return written

    def _headAssignment(self, token: _Token,
                        index: "_AlphaIndex") -> Optional[Tuple[Tuple, List[str]]]:
        head = self._rule["head_predicate"]
        facts = token.facts
        premises: List[str] = []
        for fact in facts:
            if fact["fact_id"] not in premises:
                premises.append(fact["fact_id"])
        if self._shape == "inverse":
            atom = facts[0]
            xKey = atom["subject_key"]
            xLabel = index.labelOf(xKey)
            if xLabel is None:
                return None
            yLabel = atom["object_term"]
            return ((yLabel, head, xLabel, "", xKey, yLabel), premises)
        subjectKey = facts[0]["subject_key"]
        label = index.labelOf(subjectKey)
        if label is None:
            return None
        if self._shape == "conjunction":
            objectTerm = str(self._rule.get("head_object_const") or "")
            return ((label, head, objectTerm, subjectKey, subjectKey, ""), premises)
        objectTerm = facts[-1]["object_term"]
        return ((label, head, objectTerm, subjectKey, subjectKey, objectTerm), premises)

    def _negationHolds(self, agentId: Optional[str], tenantId: str,
                       subjectKey: str, negSubject: str, negObject: str) -> bool:
        if not self._negated:
            return False
        if self._shape == "conjunction":
            return self._engine._negatedConstHolds(agentId, self._negated, subjectKey,
                                                   tenantId=tenantId)
        return self._engine._negatedHolds(agentId, self._negated, negSubject, negObject)


class _AlphaIndex:
    """一轮求值的事实快照（alpha 存储）：谓词索引、(谓词, 主体键) 索引、主体桥接与规范标签。

    事实圈域与 `_fireRule` 一致：status='active' 且 record_kind='triple'，agentId 给了
    就按 agent 圈；租户不过滤在快照层（relay 的 SQL 也没有租户谓词），conjunction/
    inverse 的租户过滤由 BetaNode 按 shape 施加。主体桥接/规范标签镜像既有 SQL 的两次
    knowledge_subjects JOIN：桥接只取 active 行、标签不过滤状态。
    """

    def __init__(self, engine: Any, agentId: Optional[str],
                 rules: List[Dict[str, Any]]) -> None:
        predicates = sorted({str(atom["predicate"]) for rule in rules
                             for atom in rule["body"]
                             if atom.get("kind") == "atom" and atom.get("predicate")})
        sql = ("SELECT fact_id, agent_id, tenant_id, subject_key, predicate_term_id,"
               " object_term FROM knowledge_facts"
               " WHERE status = 'active' AND record_kind = 'triple'")
        params: List[Any] = []
        if agentId:
            sql += " AND agent_id = ?"
            params.append(agentId)
        if predicates:
            sql += " AND predicate_term_id IN (%s)" % ",".join("?" * len(predicates))
            params.extend(predicates)
        store = engine._store
        with store._lock:
            rows = store._conn.execute(sql, params).fetchall()
        self._byPredicate: Dict[str, List[Dict[str, Any]]] = {}
        self._bySubject: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for row in rows:
            fact = dict(row)
            self._byPredicate.setdefault(fact["predicate_term_id"], []).append(fact)
            self._bySubject.setdefault(
                (fact["predicate_term_id"], fact["subject_key"]), []).append(fact)
        self._labels: Dict[str, str] = {}
        self._bridge: Dict[Tuple[str, str], List[str]] = {}
        with store._lock:
            subjectRows = store._conn.execute(
                "SELECT subject_key, agent_id, canonical_label, normalized_label, status"
                " FROM knowledge_subjects").fetchall()
        for row in subjectRows:
            self._labels[row["subject_key"]] = row["canonical_label"]
            if row["status"] == "active":
                self._bridge.setdefault(
                    (row["agent_id"], row["normalized_label"]), []).append(row["subject_key"])

    def byPredicate(self, predicate: str) -> List[Dict[str, Any]]:
        return self._byPredicate.get(predicate, [])

    def bySubject(self, predicate: str, subjectKeys: List[str]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for key in subjectKeys:
            out.extend(self._bySubject.get((predicate, key), []))
        return out

    def expectedSubjectKeys(self, token: _Token, subjectVar: str) -> Optional[List[str]]:
        """接续变元的主体键候选：key 域直用；term 域过桥（未登记主体的客体接不上）。

        变元未绑定时返回 None（不设限）——有效形状下接续变元必已绑定，这里只是
        与 SQL 语义对齐的兜底。
        """
        bound = token.bindings.get(subjectVar)
        if bound is None:
            return None
        domain, value = bound
        if domain == "key":
            return [value]
        return self._bridge.get((token.agentId, _sqlLowerTrim(value)), [])

    def labelOf(self, subjectKey: str) -> Optional[str]:
        return self._labels.get(subjectKey)


class _CompiledRule:
    """一条规则的编译产物：alpha 链 + 逐跳 BetaNode + 终端节点。"""

    __slots__ = ("rule", "alphas", "betas", "terminal", "tenantScoped")

    def __init__(self, rule: Dict[str, Any], alphas: List[AlphaNode],
                 betas: List[BetaNode], terminal: TerminalNode,
                 tenantScoped: bool) -> None:
        self.rule = rule
        self.alphas = alphas
        self.betas = betas
        self.terminal = terminal
        self.tenantScoped = tenantScoped

    def match(self, index: _AlphaIndex, tenantId: str) -> List[_Token]:
        first = self.alphas[0]
        tokens: List[_Token] = []
        for fact in index.byPredicate(first.predicate):
            if self.tenantScoped and fact["tenant_id"] != tenantId:
                continue
            bind = first.bind(fact)
            if bind is None:
                continue
            tokens.append(_Token({var: (domain, value) for var, domain, value in bind},
                                 fact["agent_id"], (fact,)))
        for beta in self.betas:
            if not tokens:
                break
            nxt: List[_Token] = []
            for token in tokens:
                nxt.extend(beta.merge(token, index, tenantId))
            tokens = nxt
        return tokens


class ReteNetwork:
    """一次 fireAll 的 Rete 网络：编译全部启用规则，逐轮匹配并经咽喉写结论。

    由 `ForwardChainingEngine.fireAll` 在 rete_network 档构建并跨轮复用——
    TerminalNode 的激活去重集合因此覆盖整个 fireAll。每轮重建 alpha 快照：
    上一轮写入的事实这一轮可见（与 semi-naive 的 delta 推进同拍收敛）。
    """

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self._compiled: Dict[Tuple[str, str], _CompiledRule] = {}

    def runRound(self, agentId: Optional[str], tenantId: str,
                 deltaPredicates: Optional[set] = None) -> List[str]:
        tenant = str(tenantId or "default")
        rules = sorted(self._engine.rules(includeDisabled=False, tenantId=tenant),
                       key=lambda r: (r["stratification_level"], r["rule_id"]))
        if deltaPredicates is not None:
            rules = [r for r in rules if set(r["depends_on"]) & deltaPredicates]
        if not rules:
            return []
        index = _AlphaIndex(self._engine, agentId, rules)
        produced: List[str] = []
        for rule in rules:
            compiled = self._compile(rule)
            tokens = compiled.match(index, tenant)
            if not tokens:
                continue
            produced.extend(compiled.terminal.fire(tokens, index, agentId, tenant))
        return produced

    def _compile(self, rule: Dict[str, Any]) -> _CompiledRule:
        key = (rule["rule_id"], str(rule.get("updated_at") or ""))
        cached = self._compiled.get(key)
        if cached is not None:
            return cached
        shape = str(rule.get("shape") or "relay")
        positive = [a for a in rule["body"] if a.get("kind") == "atom"]
        negated = [a for a in rule["body"] if a.get("kind") == "not"]
        alphas = [AlphaNode(i, atom) for i, atom in enumerate(positive)]
        betas = [BetaNode(alpha, tenantScoped=shape in ("conjunction", "inverse"))
                 for alpha in alphas[1:]]
        terminal = TerminalNode(rule, shape, negated, self._engine)
        compiled = _CompiledRule(rule, alphas, betas, terminal,
                                 tenantScoped=shape in ("conjunction", "inverse"))
        self._compiled[key] = compiled
        return compiled
