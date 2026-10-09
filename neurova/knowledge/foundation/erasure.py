"""条目擦除喉（批次 K2 / 断点 N2）：让一个条目的正文在权威库里取不回来。

擦除为什么是独立的喉，而不是 `retract` 的另一种写法：`retract` 是"这条说法不再成立，
但账上永远读得到"（`knowledge_facts.py` 的 `retract` 原话"可撤销不可遗忘"）；擦除是
"这段话不得再被任何人读到"。两者混用必然一头错——拿 retract 冒充删除，正文留在库里，
换个读面就回来（正是本批要灭的病）；拿删除冒充撤回，历史说法蒸发，溯源面指着空气。

链的取舍（2026-10-09 拍板）：**擦正文、留链与哈希**。
`digest_chain._DIGEST_FIELDS` 吃 `statement_hash` 不吃 `statement_text`，所以把正文置空
不动任何一跳的摘要；硬删断言行会让 `seq` 出空洞、`ActivityDigestChain.verify` 判
"链被削过"，`/foundation/integrity` 从此常红——合规删除不该以毁掉审计面为代价。
代价如实说清：仍持有哈希的人可以比对"是不是同一条说法"，但取不回正文。
标记落在新列 `erased_at`（v13）：一条断言"曾是链上跳"与"现在还在主张"是两件事，
所以 `assertions()` 的口径不动（溯源要看得见曾经主张过谁），置信度聚合改读
`liveAssertions()`——让已擦除的条目继续算一个独立来源，等于用一条不存在的说法替
活着的说法抬轿。

事实行的去留按**主张集合**判，不按"谁先写"：同内容折回同一行
（`ux_fact_agent_content`），若仍有别的条目在主张它，行留着、只擦本条目那一条的正文；
全属本条目才删行。派生结论顺 `knowledge_derivation_edges` 求闭包一起走——推导器不填
`sourceTurnId`（`rule_engine._admitDerivedFact`），按 `medium_ref` 找必漏它。
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from neurova.core.logger import get_logger

logger = get_logger(__name__)

STATE_ERASED = "erased"
STATE_REDACTED = "redacted"
STATE_ABSENT = "absent"
STATE_UNAVAILABLE = "unavailable"
STATE_FAILED = "failed"
# 前一面已经失败时，后面的面**不执行**而不是顺手做完：条目行是唯一还能把这件事
# 再跑一遍的把手，副本没清成就删条目，留下的是一片没人能再认领、也没人能再擦的残局。
STATE_NOT_ATTEMPTED = "not_attempted"

# 派生闭包的跳数上限：与多跳走查同源的那条纪律（`graph_walk._MAX_HOPS_CEILING`）
# 不是一个量级的东西，这里防的是规则环导致的无界展开，不是深度不足。
_MAX_CLOSURE_HOPS = 32

# 活动信封里保留的键：只留身份与指针，不留任何从条目正文派生的文本。
# 新增要留的键必须在这里显式表态——"默认全留 + 删几个"会随 inputs_json 的字段增长
# 静默漏出新副本。
_ENVELOPE_KEEP_KEYS = ("agent_id", "source_turn_id", "knowledge_id", "predicate_term_id")

# 能算"独立来源"的 medium 前缀：`rule:` 是推导器自陈的来路，不是第二个主张者。
_CLAIM_PREFIXES = ("entry:", "legacy:", "import:")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _face(state: str, count: int = 0, **extra: Any) -> Dict[str, Any]:
    """一栏回执。`state` 只许取那五个值——端点靠它判"删净"还是"删漏"。"""
    body: Dict[str, Any] = {"state": state, "count": int(count)}
    body.update(extra)
    return body


def _marks(items: Sequence[str]) -> str:
    return ",".join("?" * len(items))


class EntryErasure:
    """权威库侧的擦除动作。条目层与投影/向量两面由 `repository` 编排（它才有那些句柄）。"""

    def __init__(self, store: Any) -> None:
        self._store = store

    def eraseEntry(self, knowledgeId: str, reason: str = "") -> Dict[str, Dict[str, Any]]:
        """擦掉一个条目在权威库里留下的正文，逐面回状态。"""
        if not knowledgeId:
            raise ValueError("擦除必须点名 knowledge_id，空串等于要擦掉整个库")
        refs = tuple("%s%s" % (p, knowledgeId)
                     for p in ("entry:", "legacy:", "import:")) + (knowledgeId,)
        faces: Dict[str, Dict[str, Any]] = {}
        with self._store._lock, self._store._conn:
            conn = self._store._conn
            seed = self._entryFacts(conn, refs, knowledgeId)
            if not seed:
                faces.update({
                    "facts": _face(STATE_ABSENT),
                    "assertions": _face(STATE_ABSENT),
                    "derivations": _face(STATE_ABSENT),
                    "conflicts": _face(STATE_ABSENT),
                    "subjects": _face(STATE_ABSENT),
                    "activities": _face(STATE_ABSENT),
                })
                return faces

            deleted = self._closeOverDerivation(conn, seed, refs)
            touchedSubjects = {
                r["subject_key"] for r in conn.execute(
                    "SELECT DISTINCT subject_key FROM knowledge_facts"
                    " WHERE fact_id IN (%s)" % _marks(deleted), deleted)}

            faces["assertions"] = self._redactAssertions(conn, refs, deleted)
            faces["facts"] = self._deleteFacts(conn, deleted, seed)
            faces["derivations"] = self._dropDerivationEdges(conn, deleted)
            faces["conflicts"] = self._pruneConflicts(conn, deleted)
            faces["subjects"] = self._dropOrphanSubjects(conn, touchedSubjects)
            faces["activities"] = self._redactActivities(conn, refs)
            self._regradeSurvivors(conn, seed, deleted)

        logger.info("条目擦除 %s（%s）：%s", knowledgeId, reason or "未注明理由",
                    {k: v["state"] for k, v in faces.items()})
        return faces

    # ── 取集合 ────────────────────────────────────────────────

    def _entryFacts(self, conn, refs: Sequence[str], knowledgeId: str) -> List[str]:
        """本条目直接留下的事实行：溯源列、客体列、断言介质三条都认。

        三条都要认，因为历史上落法不一致——回填与叙述投影写 `source_turn_id`，
        抽取写 `object_term`，只认一条就会有一批行删不掉（真库实测 390/401 带
        `entry:` 溯源，其余正是要靠客体与介质键兜住的那些）。
        """
        turnMarks, kidMarks = _marks(refs[:-1]), _marks((knowledgeId,))
        rows = conn.execute(
            "SELECT DISTINCT fact_id FROM ("
            "  SELECT fact_id FROM knowledge_facts"
            "   WHERE source_turn_id IN (%s) OR object_term IN (%s)"
            "  UNION SELECT fact_id FROM knowledge_assertions WHERE medium_ref IN (%s)"
            ")" % (turnMarks, kidMarks, turnMarks),
            (*refs[:-1], knowledgeId, *refs[:-1]))
        return [r["fact_id"] for r in rows.fetchall()]

    def _closeOverDerivation(self, conn, seed: Sequence[str],
                             refs: Sequence[str]) -> List[str]:
        """从"确实该删"的种子出发求派生闭包；仍有他人在主张的行不进闭包。"""
        doomed: Set[str] = {f for f in seed if not self._hasOtherClaimant(conn, f, refs)}
        frontier, hops, visited = set(doomed), 0, set(doomed)
        while frontier and hops < _MAX_CLOSURE_HOPS:
            fm = _marks(tuple(frontier))
            nxt = {r["derived_fact_id"] for r in conn.execute(
                "SELECT derived_fact_id FROM knowledge_derivation_edges"
                " WHERE premise_fact_id IN (%s)" % fm, tuple(frontier))} - visited
            doomed |= nxt
            visited |= nxt
            frontier, hops = nxt, hops + 1
        if frontier and hops >= _MAX_CLOSURE_HOPS:
            # 静默截断等于让一部分副本活下来，这里宁可少删也不假装删净。
            raise RuntimeError(
                "派生闭包超过 %d 跳仍未收敛——擦除中止，不留「部分删净」的假回执"
                % _MAX_CLOSURE_HOPS)
        return sorted(doomed)

    def _hasOtherClaimant(self, conn, factId: str, refs: Sequence[str]) -> bool:
        rows = conn.execute(
            "SELECT medium_ref FROM knowledge_assertions WHERE fact_id = ?", (factId,)).fetchall()
        return any(str(r["medium_ref"] or "").startswith(_CLAIM_PREFIXES)
                   and r["medium_ref"] not in refs for r in rows)

    # ── 各面动作 ──────────────────────────────────────────────

    def _redactAssertions(self, conn, refs: Sequence[str], deleted: Sequence[str]) -> Dict[str, Any]:
        """正文置空 + 打擦除标记；行、`seq`、`digest`、`statement_hash` 一律不动。"""
        orParts = ["medium_ref IN (%s)" % _marks(refs)]
        params: List[Any] = list(refs)
        if deleted:
            orParts.append("fact_id IN (%s)" % _marks(deleted))
            params += deleted
        rows = conn.execute(
            "SELECT assertion_id FROM knowledge_assertions"
            " WHERE erased_at = '' AND (%s)" % " OR ".join(orParts), params).fetchall()
        ids = [r["assertion_id"] for r in rows]
        if not ids:
            return _face(STATE_ABSENT)
        conn.executemany(
            "UPDATE knowledge_assertions SET statement_text = '', erased_at = ?"
            " WHERE assertion_id = ?", [(_now(), i) for i in ids])
        return _face(STATE_REDACTED, len(ids))

    def _deleteFacts(self, conn, deleted: Sequence[str], seed: Sequence[str]) -> Dict[str, Any]:
        if not deleted:
            return _face(STATE_ABSENT)
        cur = conn.execute(
            "DELETE FROM knowledge_facts WHERE fact_id IN (%s)" % _marks(deleted), deleted)
        retained = [f for f in seed if f not in set(deleted)]
        return _face(STATE_ERASED, int(cur.rowcount), retained=retained)

    def _dropDerivationEdges(self, conn, deleted: Sequence[str]) -> Dict[str, Any]:
        if not deleted:
            return _face(STATE_ABSENT)
        dm = _marks(deleted)
        cur = conn.execute(
            "DELETE FROM knowledge_derivation_edges"
            " WHERE derived_fact_id IN (%s) OR premise_fact_id IN (%s)" % (dm, dm),
            (*deleted, *deleted))
        return _face(STATE_ERASED, int(cur.rowcount))

    def _pruneConflicts(self, conn, deleted: Sequence[str]) -> Dict[str, Any]:
        """冲突账里不许挂着已不存在的成员：`conflictMembers` 会把它读成查无此行的空洞。"""
        rows = conn.execute(
            "SELECT conflict_id, member_fact_ids_json, winner_fact_id"
            " FROM knowledge_conflicts").fetchall()
        gone = set(deleted)
        pruned = dropped = 0
        for row in rows:
            members = [m for m in json.loads(row["member_fact_ids_json"] or "[]")
                       if m not in gone]
            if len(members) == len(json.loads(row["member_fact_ids_json"] or "[]")):
                continue
            if not members:
                conn.execute("DELETE FROM knowledge_conflicts WHERE conflict_id = ?",
                             (row["conflict_id"],))
                dropped += 1
                continue
            winner = row["winner_fact_id"] if row["winner_fact_id"] not in gone else None
            conn.execute(
                "UPDATE knowledge_conflicts SET member_fact_ids_json = ?, winner_fact_id = ?"
                " WHERE conflict_id = ?", (json.dumps(members), winner, row["conflict_id"]))
            pruned += 1
        for row in conn.execute(
                "SELECT fact_id, contradicted_by_json FROM knowledge_facts"
                " WHERE contradicted_by_json <> '[]'").fetchall():
            marked = json.loads(row["contradicted_by_json"] or "[]")
            kept = [m for m in marked if m not in gone]
            if len(kept) != len(marked):
                conn.execute("UPDATE knowledge_facts SET contradicted_by_json = ?"
                             " WHERE fact_id = ?", (json.dumps(kept), row["fact_id"]))
                pruned += 1
        if not (pruned or dropped):
            return _face(STATE_ABSENT)
        return _face(STATE_ERASED, pruned + dropped, rows_dropped=dropped)

    def _dropOrphanSubjects(self, conn, touched: Set[str]) -> Dict[str, Any]:
        """只清这次被碰过的主体；`merged_into` 非空的是合并史锚，不是孤儿。"""
        if not touched:
            return _face(STATE_ABSENT)
        tm = _marks(tuple(touched))
        rows = conn.execute(
            "SELECT subject_key FROM knowledge_subjects"
            " WHERE subject_key IN (%s) AND merged_into IS NULL"
            "   AND subject_key NOT IN (SELECT subject_key FROM knowledge_facts)" % tm,
            tuple(touched)).fetchall()
        keys = [r["subject_key"] for r in rows]
        if not keys:
            return _face(STATE_ABSENT)
        conn.execute(
            "DELETE FROM knowledge_subjects WHERE subject_key IN (%s)" % _marks(keys), keys)
        return _face(STATE_ERASED, len(keys))

    def _redactActivities(self, conn, refs: Sequence[str]) -> Dict[str, Any]:
        """活动信封：实测 import 那批把归一化正文整段写进了 `inputs_json`。

        链不吃活动行（摘要只串断言），所以这里可以直接改写而不动 `verify_chain`。
        """
        orParts: List[str] = []
        params: List[Any] = []
        for ref in refs:
            orParts += ["inputs_json LIKE ?", "outputs_json LIKE ?"]
            params += ["%%%s%%" % ref, "%%%s%%" % ref]
        orParts.append("activity_id IN (SELECT activity_id FROM knowledge_assertions"
                       " WHERE medium_ref IN (%s))" % _marks(refs))
        params += list(refs)
        rows = conn.execute(
            "SELECT activity_id, inputs_json FROM knowledge_activities"
            " WHERE (%s)" % " OR ".join(orParts), params).fetchall()
        if not rows:
            return _face(STATE_ABSENT)
        redacted = 0
        for row in rows:
            payload = self._scrubEnvelope(row["inputs_json"])
            if payload is None:
                continue
            conn.execute("UPDATE knowledge_activities SET inputs_json = ?"
                         " WHERE activity_id = ?", (payload, row["activity_id"]))
            redacted += 1
        if not redacted:
            return _face(STATE_ABSENT)
        return _face(STATE_REDACTED, redacted)

    def _scrubEnvelope(self, raw: Optional[str]) -> Optional[str]:
        """留下身份与指针，丢掉从条目正文派生的文本；解不开就整坨换成红线标记。"""
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return json.dumps({"redacted": True}, ensure_ascii=False)
        if not isinstance(data, dict):
            return json.dumps({"redacted": True}, ensure_ascii=False)
        kept = {k: data[k] for k in _ENVELOPE_KEEP_KEYS if k in data}
        if not kept and all(str(v) == "" for v in data.values()):
            return None
        kept["redacted"] = True
        if json.dumps(kept, ensure_ascii=False) == raw:
            return None
        return json.dumps(kept, ensure_ascii=False)

    def _regradeSurvivors(self, conn, seed: Sequence[str], deleted: Sequence[str]) -> None:
        """留下来的行重新算置信度：本条目的断言已不再是主张，不该继续计入来源数。"""
        gone = set(deleted)
        for factId in [f for f in seed if f not in gone]:
            self._store._refreshConfidence(factId)


def eraseEntryInAuthority(store: Any, knowledgeId: str,
                          reason: str = "") -> Dict[str, Dict[str, Any]]:
    """单点入口：底座库的擦除只此一条路，别在下游各写一套 DELETE。"""
    return EntryErasure(store).eraseEntry(knowledgeId, reason=reason)


def isComplete(receipt: Dict[str, Any]) -> bool:
    """回执齐面且无 failed 才算删净——端点据此决定回 200 还是把失败点名。"""
    faces: Iterable[Dict[str, Any]] = (receipt.get("faces") or {}).values()
    return all(f.get("state") != STATE_FAILED for f in faces)
