"""时序事实模块 —— 读写的都是底座那一份权威，不持自己的事实字典。

本模块此前是**第三套事实库**：一个进程内 `_facts` 字典，API 能往里写、
进程一灭就没、检索链从来读不到它（Issue #72 点名的第三条断链）。
时序事实的权威早已是 `knowledge_facts`（012 把对话链那条分支换成它），
所以这里的正确形态是**薄适配**：写经唯一咽喉 `admit()`，读走底座的
`knowledge_facts` 递归/过滤，自己一份都不留。

口径一条都不新造：
- 谓词与实体类型由本体注册表判（越界落 `custom`，与 `graph_bridge` 同一套）；
- 事实身份、冲突判定、严重度全部复用治理层（`KnowledgeConflictJudge`）；
- 时间窗用底座的两列 `valid_from` / `valid_until`，不另立时间索引。
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class TKGModule:
    """时序事实的读写门面：一份权威（底座），零私有存储。"""

    def __init__(self, time_window_hours: float = 24.0, factStore: Any = None) -> None:
        """
        Args:
            time_window_hours: 默认时间窗口（小时），仅影响 `query_recent` 的缺省值
            factStore: 底座事实库句柄；None 时用生产单例
        """
        self._time_window_hours = time_window_hours
        self._lock = threading.RLock()
        self._initialized = False
        self._factStore = factStore

    @property
    def name(self) -> str:
        """模块名称"""
        return "tkg_module"

    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("TKGModule initialized（权威：底座知识库）")
        return True

    def shutdown(self) -> None:
        """关闭模块"""
        self._initialized = False
        logger.info("TKGModule shutdown")

    # ── 权威 ──────────────────────────────────────────────────

    def _store(self) -> Any:
        if self._factStore is not None:
            return self._factStore
        from neurova.knowledge.foundation.knowledge_facts import get_knowledge_fact_store

        self._factStore = get_knowledge_fact_store()
        return self._factStore

    def _agentId(self) -> str:
        """默认域。manager 委托时经 `agentId` 显式传入；缺省用 default。"""
        return getattr(self, "_agent_id", "") or "default"

    def bindAgent(self, agentId: str) -> None:
        """绑定事实域：一个 MemoryManager 实例只服务一个 agent。"""
        self._agent_id = str(agentId or "") or "default"

    # ── 写 ────────────────────────────────────────────────────

    def add_fact(
        self,
        subject: str,
        predicate: str,
        obj: str,
        confidence: Optional[float] = None,
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
        agentId: str = "",
        mediumRef: str = "",
        statementText: str = "",
    ) -> str:
        """写一条时序事实（经唯一咽喉）。返回 fact_id。

        三个必填项一个都不许为空：此前委托层用 `.get(..., "")` 静默兜底，
        于是 API 传了别的字段名时写进去一条空三元组、HTTP 还回 200。
        """
        for name, value in (("subject", subject), ("predicate", predicate), ("obj", obj)):
            if not str(value or "").strip():
                raise ValueError("时序事实缺必填字段 %s（不接受静默写空行）" % name)

        from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate

        domain = str(agentId or self._agentId())
        statement = statementText or "%s %s %s" % (subject, predicate, obj)
        gate = productionAdmissionGate(self._store(), toolVersion="tkg-module")
        receipt = gate.admit(AdmissionRequest(
            agentId=domain,
            subjectLabel=str(subject),
            predicateTermId=str(predicate),
            objectTerm=str(obj),
            content=statement,
            relationKind="entity",
            assertions=[{
                "actorType": "pipeline",
                "actorId": "tkg_module",
                "mediumRef": mediumRef or "tkg:api",
                "statementText": statement,
            }],
            validFrom=valid_from,
            validUntil=valid_until,
            activityKind="admit",
            activityBasis="TKGModule.add_fact（时序事实走咽喉）",
        ))
        return receipt.factId

    # ── 读 ────────────────────────────────────────────────────

    def query_facts(
        self,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        obj: Optional[str] = None,
        time_from: Optional[Any] = None,
        time_until: Optional[Any] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """按主语/谓语/宾语与时间范围取活动事实（时间比的是 `valid_from`/`recorded_at`）。"""
        rows = self._activeRows(subject)
        out: List[Dict[str, Any]] = []
        for fact in rows:
            if predicate and fact["predicate_term_id"] != predicate:
                continue
            if obj and fact["object_term"] != obj:
                continue
            moment = str(fact.get("valid_from") or fact.get("recorded_at") or "")
            if time_from is not None and _epoch(moment) < float(time_from):
                continue
            if time_until is not None and _epoch(moment) > float(time_until):
                continue
            out.append(self._asFactDict(fact))
        out.sort(key=lambda f: (str(f.get("timestamp") or ""), str(f.get("fact_id") or "")),
                 reverse=True)
        return out[:max(int(limit), 1)]

    def detect_conflicts(self, subject: str, predicate: str, obj: str) -> List[Dict[str, Any]]:
        """与这个说法矛盾的活动事实。判定只有一处实现：治理层的 `KnowledgeConflictJudge`。

        回的是**底座事实行**（`fact_id` / `object_term` / `confidence` 都是权威的列），
        与"事实级判定只有一处实现"是同一条纪律：形状若另立一套，读的人还是要去猜。
        """
        from neurova.knowledge.foundation.conflict_judge import KnowledgeConflictJudge

        store = self._store()
        judge = KnowledgeConflictJudge(store)
        contested = {
            member
            for conflict in judge.detect(subjectLabel=subject, predicateTermId=predicate)
            for member in conflict["member_fact_ids"]
        }
        return [
            store._hydrate(fact) for fact in store.candidateFactsForConflict(subject, predicate)
            if fact["fact_id"] in contested and fact["object_term"] != obj
        ]

    def get_entities(self, limit: int = 100) -> List[str]:
        """"有哪些实体"= 出现过的**主体名**，不含客体字面量。

        旧实现把主语与宾语都塞进实体索引，于是属性值（`2.0`、`SQLite`）也被算成实体——
        读数虚高，且与"实体数"这个词在别处的口径不一致。
        """
        labels: List[str] = []
        for fact in self._allActiveRows():
            label = self._labelOf(fact["subject_key"])
            if label and label not in labels:
                labels.append(label)
        return labels[:max(int(limit), 1)]

    def _predicates(self) -> List[str]:
        """谓词清单（`get_stats.relations` 用）。"""
        seen: List[str] = []
        for fact in self._allActiveRows():
            predicate = str(fact["predicate_term_id"])
            if predicate not in seen:
                seen.append(predicate)
        return seen

    def get_stats(self) -> Dict[str, Any]:
        """读数全部来自权威，键名与前端 `TKGStats` 契约一致（一份形状，不做两套）。

        私有字典那份"总数"与检索面讲的不是同一件事，报它只会让读数与事实分家。
        """
        rows = self._allActiveRows()
        stamps = sorted(str(f.get("recorded_at") or "") for f in rows if f.get("recorded_at"))
        return {
            "total_facts": len(rows),
            "entities": len(self.get_entities(limit=10 ** 6)),
            "relations": len(self._predicates()),
            "time_range": {"earliest": stamps[0] if stamps else "",
                           "latest": stamps[-1] if stamps else ""},
            # 以下三项是权威侧的生命周期读数，前端暂未展示但读面/巡检要用
            "invalidated_facts": self._retractedCount(),
            "agents_count": len({str(f.get("agent_id") or "") for f in rows}),
            "time_window_hours": self._time_window_hours,
        }

    # ── 内部 ──────────────────────────────────────────────────

    def _allActiveRows(self) -> List[Dict[str, Any]]:
        return [f for f in self._store().searchableFacts() if f["record_kind"] == "triple"]

    def _retractedCount(self) -> int:
        store = self._store()
        with store._lock:
            return int(store._conn.execute(
                "SELECT COUNT(*) FROM knowledge_facts WHERE status = 'retracted'").fetchone()[0])

    def _activeRows(self, subject: Optional[str]) -> List[Dict[str, Any]]:
        if not subject:
            return self._allActiveRows()
        keys = self._entityKeys(subject)
        return [f for f in self._allActiveRows() if f["subject_key"] in keys]

    def _entityKeys(self, entity: str) -> set:
        """实体名 → 主体键：本域优先，本域没有才跨域找同名主体。

        主体身份是 (agent, label) 维内唯一，所以"本域查得到"与"别域同名"是两件事；
        先本域再回退，既不会跨域串读，也不会让不带域名的查询恒空。
        """
        store = self._store()
        from neurova.knowledge.foundation.knowledge_facts import normalizeLabel

        normalized = normalizeLabel(str(entity or ""))
        keys = {s["subject_key"] for s in store.listSubjects(self._agentId())
                if s["normalized_label"] == normalized}
        if keys:
            return keys
        with store._lock:
            rows = store._conn.execute(
                "SELECT subject_key FROM knowledge_subjects WHERE normalized_label = ?",
                (normalized,)).fetchall()
        return {r["subject_key"] for r in rows}

    def _labelOf(self, subjectKey: str) -> str:
        row = self._store().subjectFor(subjectKey) or {}
        return str(row.get("canonical_label") or "")

    def _asFactDict(self, fact: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """检索/接口契约形状与旧模块逐字相同——换的是数据源，不是形状。"""
        if not fact:
            return None
        return {
            "fact_id": fact["fact_id"],
            "subject": self._labelOf(fact["subject_key"]),
            "predicate": fact["predicate_term_id"],
            "object": fact["object_term"],
            "confidence": fact.get("confidence"),
            "created_at": _epoch(str(fact.get("recorded_at") or "")),
            "valid_from": fact.get("valid_from"),
            "valid_until": fact.get("valid_until"),
            "status": fact.get("status"),
            "agent_id": fact.get("agent_id"),
            "record_kind": fact.get("record_kind"),
            "evidence_state": fact.get("evidence_state"),
        }


def _epoch(isoText: str) -> float:
    """ISO 串 → 秒级时间戳（旧接口的 `created_at` 是 float，形状不能变）。"""
    import datetime

    if not isoText:
        return 0.0
    try:
        moment = datetime.datetime.fromisoformat(str(isoText).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment.timestamp()
