"""条目 ↔ 治理层的投影账本（工单 019b-2）。

只做一件事：把"`self._items` 现在长什么样"投影成治理层的现状——
缺的 admit、正文改了的开新行并取代旧行、没人认领的 retract。

**取代归冲突裁决，不归账本**：admit() 内部已经会对同一 (主体, 谓词) 上的新旧说法判
duplicate/contradicts 并按 policy_basis 取代旧行；账本若再补一次 supersede，同一对行
就被裁决两遍，第二遍必然撞上"取代只发生在 active 事实上"。账本只做裁决做不到的那件事——
按全集算认领关系（claims），把没有任何活条目认领的行 retract：**共享的事实不会被误撤**。

断言口径沿用 `reconcile._assertionFor`：同一条目的合成规则与对账/回填完全一致，
不然后面又要问"三个写入器为什么各数出一套"。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from neurova.core.content_identity import normalized_key
from neurova.core.logger import get_logger

from .admission import AdmissionRequest, productionAdmissionGate
from .reconcile import _assertionFor

logger = get_logger(__name__)


def _identity(item: Dict[str, Any]) -> Tuple[str, str]:
    kid = str(item.get("knowledge_id", "") or "")
    return kid, normalized_key(item.get("content") or "")


def _subjectLabel(item: Dict[str, Any], kid: str) -> str:
    return str(item.get("title", "") or "").strip() or ("untitled-" + kid)


class EntryLedger:
    def __init__(self, store: Any, gate: Any = None) -> None:
        self._store = store
        self._gate = gate or productionAdmissionGate(store, toolVersion="entry-ledger")

    # ── 投影 ──────────────────────────────────────────────────

    def syncFromEntries(self, itemsByAgent: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """把治理层对齐到条目集合。返回本轮动作与每条目的当前置信度。"""
        claims: set = set()
        confidences: Dict[str, Optional[float]] = {}
        admitted = 0

        for agentId, items in itemsByAgent.items():
            for item in items:
                kid, key = _identity(item)
                if not kid or not key:
                    continue  # 无内容身份的条目不参与去重与取代（004 口径）
                held = self._store.activeNarrativeFact(agentId, kid, key)
                if held:
                    claims.add(held["fact_id"])
                    confidences[kid] = held.get("confidence")
                    continue
                receipt = self._gate.admit(
                    AdmissionRequest(
                        agentId=agentId, subjectLabel=_subjectLabel(item, kid),
                        recordKind="narrative", objectTerm=kid,
                        content=str(item.get("content") or ""),
                        assertions=[_assertionFor(agentId, item)],
                        sourceTurnId="entry:%s" % kid,
                    ),
                    allowPendingSegments=True,
                )
                admitted += 1
                claims.add(receipt.factId)
                confidences[kid] = self._confidenceOf(receipt.factId)

        retracted = self._retractUnclaimed(claims)
        return {"admitted": admitted, "retracted": retracted, "confidences": confidences}

    def verifyProjection(self, itemsByAgent: Dict[str, List[Dict[str, Any]]]) -> List[str]:
        """条目在、治理行不在 ⇒ 分叉清单。只报不改——补投的语义还没定（见工单注记）。"""
        drift: List[str] = []
        for agentId, items in itemsByAgent.items():
            for item in items:
                kid, key = _identity(item)
                if not kid:
                    drift.append("%s/<无 knowledge_id> 条目缺身份，无法投影" % agentId)
                    continue
                if not key:
                    continue  # 无内容身份本就不进治理层，不算分叉
                if self._store.activeNarrativeFact(agentId, kid, key) is None:
                    drift.append("%s/%s 缺 active 治理行" % (agentId, kid))
        return drift

    # ── 内部 ──────────────────────────────────────────────────

    def _confidenceOf(self, factId: str) -> Optional[float]:
        fact = self._store.fact(factId)
        return fact.get("confidence") if fact else None

    def _retractUnclaimed(self, claims: Iterable[str]) -> int:
        claimed = set(claims)
        retracted = 0
        for fact in self._store.activeNarrativeFacts():
            if fact["fact_id"] in claimed:
                continue
            self._store.retract(fact["fact_id"], reason="条目已删除或正文被改写")
            retracted += 1
        return retracted
