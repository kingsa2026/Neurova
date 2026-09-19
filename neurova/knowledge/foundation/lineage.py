"""溯源账本（工单 005，设计文档 §4.2 溯源层、G01）。

一条事实要能回答"谁、何时、经哪条管线、依据什么原始陈述进来"。
本模块只做校验与编排，落库由 `KnowledgeFactStore` 负责（DB 所有权不外溢）。
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

ACTIVITY_KINDS: tuple = (
    "normalize", "extract", "resolve", "adjudicate", "import", "derive", "retract",
)
ACTOR_TYPES: tuple = ("agent", "user", "pipeline", "importer")

_REQUIRED_ASSERTION_FIELDS = ("actorType", "actorId", "statementText")


class KnowledgeLineageLedger:
    def __init__(self, store: Any, toolVersion: str = "") -> None:
        self._store = store
        self._toolVersion = toolVersion

    # ── 活动 ──────────────────────────────────────────────────

    def openActivity(
        self, kind: str, inputs: Optional[Dict[str, Any]] = None, basis: str = ""
    ) -> str:
        if kind not in ACTIVITY_KINDS:
            raise ValueError(
                "未知 activity_kind: %r（有效值: %s）" % (kind, " / ".join(ACTIVITY_KINDS))
            )
        return self._store.insertActivity(
            kind, inputs=inputs, basis=basis, toolVersion=self._toolVersion,
        )

    def closeActivity(self, activityId: str, outputs: Optional[Dict[str, Any]] = None) -> None:
        self._store.finishActivity(activityId, outputs=outputs)

    # ── 断言 ──────────────────────────────────────────────────

    def attach(
        self, factId: str, assertions: List[Dict[str, Any]],
        activityId: Optional[str] = None,
    ) -> int:
        """挂断言，返回实际新增条数。校验前置：匿名断言一律不进。"""
        if not assertions:
            raise ValueError(
                "事实 %s 没有任何断言：缺 actorType / actorId / statementText 的来源声明，"
                "不允许写匿名知识" % factId
            )
        attached = 0
        for assertion in assertions:
            self._validate(assertion)
            statementText = str(assertion["statementText"])
            statementHash = hashlib.sha256(statementText.encode("utf-8")).hexdigest()[:16]
            if self._store.insertAssertion(
                factId,
                actorType=str(assertion["actorType"]),
                actorId=str(assertion["actorId"]),
                mediumRef=str(assertion.get("mediumRef") or ""),
                statementText=statementText,
                statementHash=statementHash,
                activityId=assertion.get("activityId") or activityId,
                weight=float(assertion.get("weight", 1.0)),
            ):
                attached += 1
        self._syncAssertionCount(factId)
        return attached

    @staticmethod
    def _validate(assertion: Dict[str, Any]) -> None:
        for name in _REQUIRED_ASSERTION_FIELDS:
            if not str(assertion.get(name, "") or "").strip():
                raise ValueError("断言缺必填字段: %s" % name)
        if str(assertion["actorType"]) not in ACTOR_TYPES:
            raise ValueError(
                "未知 actor_type: %r（有效值: %s）" % (assertion["actorType"], " / ".join(ACTOR_TYPES))
            )

    def _syncAssertionCount(self, factId: str) -> None:
        """计数以断言行实况为准，不靠增量累加——避免多写路径把计数跑偏。"""
        self._store.setAssertionCount(factId, len(self._store.assertions(factId)))

    def assertionsFor(self, factId: str) -> List[Dict[str, Any]]:
        return self._store.assertions(factId)

    def traceLineage(self, factId: str) -> List[Dict[str, Any]]:
        rows = self._store.lineageRows(factId)
        return [
            {
                "assertion_id": row["assertion_id"],
                "fact_id": row["fact_id"],
                "actor_type": row["actor_type"],
                "actor_id": row["actor_id"],
                "medium_ref": row["medium_ref"],
                "statement_text": row["statement_text"],
                "asserted_at": row["asserted_at"],
                "verification_state": row["verification_state"],
                "activity_id": row["activity_id"],
                "activity_kind": row.get("activity_kind"),
                "activity_basis": row.get("activity_basis"),
                "activity_inputs": row.get("activity_inputs") or {},
            }
            for row in rows
        ]
