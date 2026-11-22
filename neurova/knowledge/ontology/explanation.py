"""解释生成器（升级卡 U13）：把推导账本与证明树投影成统一解释结构。

两本账（`derivation_ledger`）只记"这条结论由哪条规则、从哪几条前提来"；
本模块把它们投影成人能读的解释：嵌套 steps 树 + 中文模板文本。纯只读——
不写任何表、不建第二账本；数据全部来自账本与事实表的现成行。

与溯因（`abduction.explainGoal`）分工不同：溯因是对着目标三元组向前搜
"可能怎么成立"的假设树；本模块是对着已落库的 factId 沿推导边回溯
"实际怎么来的"的投影。一个产假设，一个读账本，不互为第二实现。
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Set

#: 解释展开深度上限（环境变量可调；环不靠它兜底——环有专门剪枝并记入 missing）
DEFAULT_EXPLAIN_DEPTH = 32

_DEPTH_ENV = "NEUROVA_ONTOLOGY_EXPLAIN_DEPTH"

# 规则变元是单个大写字母（登记处 `_VAR` 同一口径）；小写或常量不是变元
_VAR = re.compile(r"^[A-Z]$")


def _resolveDepthLimit(maxDepth: Optional[int]) -> int:
    """深度上限：显式入参优先，其次环境变量，最后缺省 32。解析失败显式报错。"""
    if maxDepth is not None:
        return int(maxDepth)
    raw = str(os.environ.get(_DEPTH_ENV) or "").strip()
    if not raw:
        return DEFAULT_EXPLAIN_DEPTH
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValueError("环境变量 %s 必须是整数，收到 %r" % (_DEPTH_ENV, raw))


def _ledgerOf(store: Any) -> Any:
    ledger = getattr(store, "_derivationLedger", None)
    if ledger is None:
        raise ValueError("store 未挂推导账本（_derivationLedger），无法解释推导")
    return ledger


def _normalTriple(raw: Any) -> Dict[str, str]:
    raw = raw if isinstance(raw, dict) else {}
    return {"subject": str(raw.get("subject") or ""),
            "predicate": str(raw.get("predicate") or ""),
            "object": str(raw.get("object") or "")}


def _subjectLabel(store: Any, fact: Dict[str, Any]) -> str:
    subject = store.subjectFor(fact.get("subject_key") or "") or {}
    label = str(subject.get("canonical_label") or "").strip()
    return label or str(fact.get("subject_key") or "")


def _tripleOf(store: Any, fact: Dict[str, Any]) -> Dict[str, str]:
    """事实行 → {subject, predicate, object}；主语取人读标签，缺省回 key。"""
    return {"subject": _subjectLabel(store, fact),
            "predicate": str(fact.get("predicate_term_id") or ""),
            "object": str(fact.get("object_term") or "")}


def _loadRule(store: Any, ruleId: str, tenantId: str) -> Optional[Dict[str, Any]]:
    """规则行单源读取：复用规则引擎的 hydrate，不另写第二套 body 解析。

    函数来源的边（rule_id 形如 `function:…`）在规则表里查不到 → None，
    调用方按"无绑定"投影，不猜。
    """
    from .rule_engine import ForwardChainingEngine

    return ForwardChainingEngine(store).rule(ruleId, tenantId=tenantId)


def _rebuildBinding(store: Any, rule: Optional[Dict[str, Any]],
                    premiseTriples: List[Dict[str, str]],
                    derivedTriple: Dict[str, str]) -> Dict[str, str]:
    """从规则正文与前提三元组重构变元绑定（账本只记前提 id，不记绑定）。

    原子与前提做一致性匹配（同一变元在各原子取值必须相同），小回溯即可——
    正文最多 2 个正原子。匹配不上就少绑，不编造。
    """
    binding: Dict[str, str] = {}
    if not rule:
        return binding
    atoms = [a for a in (rule.get("body") or []) if a.get("kind") == "atom"]

    def assign(index: int, current: Dict[str, str]) -> bool:
        if index == len(atoms):
            binding.update(current)
            return True
        atom = atoms[index]
        for triple in premiseTriples:
            if triple.get("predicate") != str(atom.get("predicate") or ""):
                continue
            nxt = dict(current)
            consistent = True
            for var, value in ((str(atom.get("subject") or ""), triple.get("subject", "")),
                               (str(atom.get("object") or ""), triple.get("object", ""))):
                if var and _VAR.match(var):
                    if nxt.get(var, value) != value:
                        consistent = False
                        break
                    nxt[var] = value
            if consistent and assign(index + 1, nxt):
                return True
        return False

    assign(0, {})
    headVar = str(rule.get("head_subject_var") or "")
    if headVar and _VAR.match(headVar):
        binding.setdefault(headVar, derivedTriple.get("subject", ""))
    return binding


def _factStep(factId: str, triple: Optional[Dict[str, str]]) -> Dict[str, Any]:
    return {"kind": "fact", "ref": factId, "triple": triple,
            "premiseIds": [], "steps": []}


def _expandFact(store: Any, ledger: Any, tenantId: str, factId: str,
                depth: int, limit: int, path: Set[str],
                missing: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把一条事实展开成 step 列表（同一结论被多条规则各推一次时并列多步）。

    无推导边 → 断言事实（单 fact step）；有边 → 每条规则一个 rule step，
    前提各自递归。成环（前提回到当前链上）与超深（depth >= limit）都剪枝，
    并把命中点以 reason=cycle / depth 记入 missing——截断要显式，不静默。
    """
    fact = store.fact(factId)
    if fact is None:
        missing.append({"ref": factId, "reason": "unknown_fact"})
        return [_factStep(factId, None)]
    triple = _tripleOf(store, fact)
    edges = ledger.premisesOf(factId)
    if not edges:
        return [_factStep(factId, triple)]
    if factId in path:
        missing.append({"ref": factId, "reason": "cycle"})
        return [_factStep(factId, triple)]
    if depth >= limit:
        missing.append({"ref": factId, "reason": "depth"})
        return [_factStep(factId, triple)]

    path.add(factId)
    try:
        groups: Dict[Any, List[str]] = {}
        for edge in edges:
            key = (str(edge["rule_id"]), str(edge.get("rule_version") or "v1"))
            groups.setdefault(key, []).append(str(edge["premise_fact_id"]))
        steps: List[Dict[str, Any]] = []
        for (ruleId, ruleVersion), premiseIds in sorted(groups.items()):
            rule = _loadRule(store, ruleId, tenantId)
            premiseTriples: List[Dict[str, str]] = []
            childSteps: List[Dict[str, Any]] = []
            for premiseId in premiseIds:
                childSteps.extend(_expandFact(store, ledger, tenantId, premiseId,
                                              depth + 1, limit, path, missing))
                premiseFact = store.fact(premiseId)
                if premiseFact:
                    premiseTriples.append(_tripleOf(store, premiseFact))
            steps.append({
                "kind": "rule", "ref": ruleId, "ruleVersion": ruleVersion,
                "binding": _rebuildBinding(store, rule, premiseTriples, triple),
                "premiseIds": premiseIds, "triple": triple, "steps": childSteps,
            })
        return steps
    finally:
        path.discard(factId)


def _tripleText(triple: Optional[Dict[str, str]]) -> str:
    if not triple:
        return "（未知三元组）"
    return "%s %s %s" % (triple.get("subject", ""), triple.get("predicate", ""),
                         triple.get("object", ""))


def _renderStep(step: Dict[str, Any]) -> str:
    """中文模板：结论 <s> <p> <o> 由规则 <ruleId> 从前提 <…> 推出；
    前提自身的推导用「；其中」逐级衔接；断言事实落在「事实」语义上。"""
    children = step.get("steps") or []
    if step.get("kind") == "fact":
        return "事实 %s" % _tripleText(step.get("triple"))
    premiseText = "、".join(_tripleText(child.get("triple")) for child in children)
    text = "结论 %s 由规则 %s 从前提 %s 推出" % (
        _tripleText(step.get("triple")), step.get("ref", ""), premiseText)
    deeper = [_renderStep(child) for child in children if child.get("kind") == "rule"]
    if deeper:
        text += "；其中 " + "；".join(deeper)
    return text


def explainDerivation(store: Any, factId: str, *, tenantId: str = "default",
                      maxDepth: Optional[int] = None) -> Dict[str, Any]:
    """沿推导账本回溯一条事实怎么来的，投影成 {conclusion, steps, missing, text}。

    断言事实（无推导边）→ 单 fact step；派生事实 → 每次规则点火一个 rule step
    （ref=规则 id，premiseIds 与账本记录逐条一致），前提再各自展开。深度上限
    `NEUROVA_ONTOLOGY_EXPLAIN_DEPTH`（默认 32）；成环剪枝记入 missing
    （reason=cycle），超深截断记 reason=depth。纯只读投影，不写任何表。
    """
    ledger = _ledgerOf(store)
    limit = _resolveDepthLimit(maxDepth)
    key = str(factId or "")
    fact = store.fact(key)
    if fact is None:
        raise ValueError("事实 %r 不存在，无法解释推导" % (key,))
    missing: List[Dict[str, Any]] = []
    steps = _expandFact(store, ledger, str(tenantId or "default"), key,
                        0, limit, set(), missing)
    return {"conclusion": _tripleOf(store, fact), "steps": steps,
            "missing": missing,
            "text": "；".join(_renderStep(step) for step in steps)}


def _projectProofStep(step: Dict[str, Any]) -> Dict[str, Any]:
    """反向链证明树的一步 → 统一 step 形态（鸭子类型，兼容 sub/steps 两种子键）。"""
    kind = str(step.get("kind") or "fact")
    children = step.get("sub") if step.get("sub") is not None else step.get("steps")
    out: Dict[str, Any] = {
        "kind": kind,
        "ref": str(step.get("ref") or ""),
        "triple": _normalTriple(step.get("goal") if step.get("goal") is not None
                                else step.get("triple")),
        "premiseIds": [str(p) for p in (step.get("premiseIds") or [])],
        "steps": [_projectProofStep(child) for child in (children or [])
                  if isinstance(child, dict)],
    }
    if kind == "rule":
        out["binding"] = dict(step.get("binding") or {})
    return out


def explainProof(proofTree: Any) -> Dict[str, Any]:
    """把反向链证明树（普通 dict：goal / steps[{kind, ref, binding, sub}] / missing）
    投影成与 `explainDerivation` 同构的 {conclusion, steps, missing, text}。

    只做形态投影，不 import 反向链模块、不回查库——树里给什么就投影什么。
    """
    tree = proofTree if isinstance(proofTree, dict) else {}
    steps = [_projectProofStep(step) for step in (tree.get("steps") or [])
             if isinstance(step, dict)]
    missing = [dict(entry) for entry in (tree.get("missing") or [])
               if isinstance(entry, dict)]
    return {"conclusion": _normalTriple(tree.get("goal")), "steps": steps,
            "missing": missing,
            "text": "；".join(_renderStep(step) for step in steps)}
