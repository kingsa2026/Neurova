"""链式校验和（工单 023，G02）：改过任何一条断言，必须被发现并指到位置。

链按**活动**串，不按事实串（设计文档 §3 G02 的修正）：一条事实的多条断言来自不同
管线，把它们编进同一条链等于让并发写入互相排队，而"谁在什么时候说了什么"的
自然分组本来就是这一次活动。

- 链头 `knowledge_lineage_heads`：一条活动一行，记 `last_seq` / `last_digest` /
  滚动 `head_digest`。
- 链上每一跳 = `seq` + `digest`，`digest` 吃进前驱摘要，所以改中间任何一行，
  它自己和其后所有行的摘要一起对不上。
- 链头另算 `head_digest`（对整条链的滚动折叠）：只删尾巴、不改摘要，
  也会让 `last_seq` 与实况、`head_digest` 与折叠结果双双对不上。

要说清本段的边界：SQLite 里没有密钥，拿到写库权限的人可以重算整条链。这里保证的是
**改写必留痕、留痕必指位**，让巡检读数可信，而不是提供防篡改证明。
"""

from __future__ import annotations

import datetime
import hashlib
from typing import Any, Dict, List, Optional

_SCHEMA_V11 = """
ALTER TABLE knowledge_assertions ADD COLUMN seq INTEGER NOT NULL DEFAULT 0;
ALTER TABLE knowledge_assertions ADD COLUMN digest TEXT NOT NULL DEFAULT '';
ALTER TABLE knowledge_assertions ADD COLUMN prev_digest TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS knowledge_lineage_heads (
    head_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL DEFAULT 'activity',
    activity_id TEXT NOT NULL DEFAULT '',
    last_seq INTEGER NOT NULL DEFAULT 0,
    last_digest TEXT NOT NULL DEFAULT '',
    head_digest TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_lineage_head_activity
    ON knowledge_lineage_heads(activity_id) WHERE activity_id <> '';

-- 链按活动顺序读，断言表此前只有按 fact 的索引。
CREATE INDEX IF NOT EXISTS idx_assertion_activity
    ON knowledge_assertions(activity_id, seq);
"""

# 摘要的输入顺序写在这里一次，写侧与校验侧共用同一个打包函数——两处各排各的序，
# 就会出现"写得进去、校验永远红"。
_DIGEST_FIELDS = ("assertion_id", "fact_id", "actor_type", "actor_id", "activity_id",
                  "medium_ref", "statement_hash")

_UNLINKED_FIELD = "digest"   # 判"有没有上链"看这一列，seq 为 0 只是它的副产物


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _headSeed(activityId: str) -> str:
    return _sha("head:%s" % activityId)


def itemDigest(row: Dict[str, Any]) -> str:
    """一跳摘要：前驱 + 序号 + 断言本体（哈希而非正文，正文另有校验）。"""
    packed = "|".join([str(row.get("seq") or 0), str(row.get("prev_digest") or "")]
                      + [str(row.get(name) or "") for name in _DIGEST_FIELDS])
    return _sha(packed)


def foldHead(prevFold: str, digest: str) -> str:
    return _sha("%s>%s" % (prevFold, digest))


class ActivityDigestChain:
    """断言链的记账与巡检。落库全部走底座连接，不另建存储。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._ensureTable()

    def _ensureTable(self) -> None:
        from .foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    # ── 写 ────────────────────────────────────────────────────

    def digestFor(self, row: Dict[str, Any]) -> str:
        """写侧算摘要的唯一入口（与巡检侧同一个 `itemDigest`，不分两套公式）。"""
        return itemDigest(row)

    def nextSlot(self, conn, activityId: Optional[str]) -> Optional[Dict[str, Any]]:
        """取这一跳该用的 (seq, prev_digest)；没有活动就不上链。

        读的是链头，且必须与插入同事务——两个连接各读各的会给出同一个 seq。
        """
        if not activityId:
            return None
        head = conn.execute(
            "SELECT last_seq, last_digest FROM knowledge_lineage_heads WHERE activity_id = ?",
            (activityId,)).fetchone()
        seq = int(head["last_seq"]) + 1 if head else 1
        return {"seq": seq, "prevDigest": (head["last_digest"] if head else "")}

    def commit(self, conn, activityId: str, seq: int, digest: str) -> None:
        """把这一跳接进链头。调用方负责事务，这里只写。"""
        existing = conn.execute(
            "SELECT head_digest FROM knowledge_lineage_heads WHERE activity_id = ?",
            (activityId,)).fetchone()
        fold = foldHead(existing["head_digest"] if existing else _headSeed(activityId), digest)
        conn.execute(
            "INSERT OR REPLACE INTO knowledge_lineage_heads (head_id, scope, activity_id,"
            " last_seq, last_digest, head_digest, updated_at) VALUES (?,?,?,?,?,?,?)",
            ("ldh_%s" % activityId, "activity", activityId, int(seq), digest, fold, _now()),
        )

    def linkAssertion(self, conn, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """给一条刚落库的断言算好链位并写回（relink 用的独立入口）。"""
        activityId = row.get("activity_id")
        slot = self.nextSlot(conn, activityId)
        if slot is None:
            return None
        item = dict(row)
        item["seq"] = slot["seq"]
        item["prev_digest"] = slot["prevDigest"]
        digest = itemDigest(item)
        conn.execute(
            "UPDATE knowledge_assertions SET seq = ?, digest = ?, prev_digest = ?"
            " WHERE assertion_id = ?", (item["seq"], digest, item["prev_digest"],
                                        row["assertion_id"]),
        )
        self.commit(conn, str(activityId), item["seq"], digest)
        return {"seq": item["seq"], "digest": digest}

    def relinkUnlinked(self) -> int:
        """把上链之前写下的断言补上链（按活动、按落库顺序）。

        只处理"整条活动都没上链"的情况：混合态（部分有摘要）说明链被削过，
        那该由巡检报出来，不该被 relink 悄悄重写成一个新的自证。
        重置链头是必须的——沿用旧 head 会把新跳接到一个已经对不上的折叠上。
        """
        linked = 0
        with self._store._lock, self._store._conn:
            conn = self._store._conn
            halfDone = {r["activity_id"] for r in conn.execute(
                "SELECT DISTINCT activity_id FROM knowledge_assertions"
                " WHERE digest <> '' AND activity_id <> ''").fetchall()}
            rows = conn.execute(
                "SELECT * FROM knowledge_assertions"
                " WHERE (digest = '' OR digest IS NULL) AND activity_id IS NOT NULL"
                "  AND activity_id <> ''"
                " ORDER BY activity_id, asserted_at, assertion_id").fetchall()
            done = set()
            for row in rows:
                item = dict(row)
                activityId = item["activity_id"]
                if activityId in halfDone:
                    continue
                if activityId not in done:
                    conn.execute("DELETE FROM knowledge_lineage_heads WHERE activity_id = ?",
                                 (activityId,))
                    done.add(activityId)
                if self.linkAssertion(conn, item) is not None:
                    linked += 1
        return linked

    # ── 读 ────────────────────────────────────────────────────

    def head(self, activityId: str) -> Optional[Dict[str, Any]]:
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT * FROM knowledge_lineage_heads WHERE activity_id = ?",
                (activityId,)).fetchone()
        return dict(row) if row else None

    def heads(self) -> List[Dict[str, Any]]:
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT * FROM knowledge_lineage_heads ORDER BY activity_id").fetchall()
        return [dict(r) for r in rows]

    def items(self, activityId: str) -> List[Dict[str, Any]]:
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT * FROM knowledge_assertions WHERE activity_id = ?"
                " ORDER BY seq, asserted_at, assertion_id", (activityId,)).fetchall()
        return [dict(r) for r in rows]

    def itemDigests(self, activityId: str) -> List[str]:
        return [str(i.get("digest") or "") for i in self.items(activityId)]

    # ── 巡检 ──────────────────────────────────────────────────

    # ── 校验闭环（工单 023 的落点）──────────────────────────

    def attest(self, activityId: Optional[str] = None) -> Dict[str, Any]:
        """逐条裁决并**回写** `verification_state`——只报不改就等于从不闭环。

        一条断言的裁决吃三样：正文与其哈希是否相符、摘要是否与内容相符、
        链位（seq / prev_digest）是否与前一跳接得上。任一样不成立即 `failed`；
        三样都成立才是 `verified`。`unverified` 从此只有一个含义：**还没验过**。

        回写而不是返回一张临时表：读面（血缘视图、巡检端点）读的是库里的列，
        结论不落回那一列，下一个读的人拿到的还是"没人验过"。
        """
        entries = self._gradeAll(activityId)
        with self._store._lock, self._store._conn:
            for entry in entries:
                self._store._conn.execute(
                    "UPDATE knowledge_assertions SET verification_state = ?"
                    " WHERE assertion_id = ?", (entry["state"], entry["assertion_id"]))
        counts = self._store.assertionVerificationCounts()
        failed = counts.get("failed", 0)
        return {"ok": failed == 0, "graded": len(entries), "failed": failed,
                "verified": counts.get("verified", 0), "unverified": counts.get("unverified", 0),
                "verification": counts,
                "failures": [e for e in entries if e["state"] == "failed"][:5]}

    def _gradeAll(self, activityId: Optional[str]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for one in self._activityIds(activityId):
            items = self.items(one)
            prev = ""
            index = 0
            for item in items:
                if not str(item.get(_UNLINKED_FIELD) or ""):
                    # 上链之前的行：这一维没依据，保持 unverified，不假装验过
                    out.append({"assertion_id": item["assertion_id"], "state": "unverified",
                                "reason": "未上链"})
                    continue
                index += 1
                reason = self._breakReason(item, index, prev)
                if reason is None and itemDigest(item) != str(item["digest"]):
                    reason = "摘要与内容不符"
                out.append({"assertion_id": item["assertion_id"],
                            "state": "failed" if reason else "verified",
                            "reason": reason or ""})
                prev = str(item["digest"])
        return out

    def _activityIds(self, activityId: Optional[str]) -> List[str]:
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT DISTINCT activity_id FROM knowledge_assertions"
                " WHERE activity_id IS NOT NULL AND activity_id <> ''"
                + (" AND activity_id = ?" if activityId else "") + " ORDER BY activity_id",
                (activityId,) if activityId else ()).fetchall()
        return [r["activity_id"] for r in rows]

    def verify(self, activityId: Optional[str] = None) -> Dict[str, Any]:
        """重算每条链并与链头对账，返回首个断裂点。

        上链之前的行（`digest` 为空）算 `unlinked` 不算断裂：那是一维没依据，
        不是有人改过数据——把没测过的事报成故障，巡检就没人信了。
        """
        ids = self._activityIds(activityId)
        checked = unlinked = 0
        firstBreak: Optional[Dict[str, Any]] = None
        for one in ids:
            result = self._verifyChain(one)
            checked += result["rows"]
            unlinked += result["unlinked"]
            if firstBreak is None and result["break"]:
                firstBreak = result["break"]
        return {"ok": firstBreak is None, "chains": len(ids), "rows": checked,
                "unlinked": unlinked, "break": firstBreak,
                # 分布一并给出：巡检只报"有没有断"的话，读的人看不到"多少条还没验过"
                "verification": self._store.assertionVerificationCounts()}

    def _verifyChain(self, activityId: str) -> Dict[str, Any]:
        items = self.items(activityId)
        head = self.head(activityId)
        linked = [i for i in items if str(i.get(_UNLINKED_FIELD) or "")]
        out: Dict[str, Any] = {"rows": len(linked), "unlinked": len(items) - len(linked),
                               "break": None}
        fold = _headSeed(activityId)
        prev = ""
        # 序号按"链上的第几跳"数，不按表里的第几行：混进未上链的行时，
        # 拿行号比 seq 会把正常链报成断裂。
        for index, item in enumerate(linked, start=1):
            reason = self._breakReason(item, index, prev)
            if reason:
                out["break"] = self._breakAt(activityId, item, reason)
                return out
            digest = itemDigest(item)
            if digest != str(item["digest"]):
                out["break"] = self._breakAt(activityId, item, "摘要与内容不符",
                                            expected=digest, found=str(item["digest"]))
                return out
            fold = foldHead(fold, digest)
            prev = digest
        if head and (int(head["last_seq"]) != len(linked)
                     or str(head["head_digest"]) != fold):
            reason = ("链头序号与实况不符" if int(head["last_seq"]) != len(linked)
                      else "链头摘要与滚动结果不符")
            out["break"] = self._breakAt(activityId, linked[-1] if linked else {}, reason,
                                         expected=fold, found=str(head["head_digest"]))
        return out

    @staticmethod
    def _breakReason(item: Dict[str, Any], index: int, prev: str) -> Optional[str]:
        if hashlib.sha256(str(item.get("statement_text") or "").encode("utf-8")
                          ).hexdigest()[:16] != str(item.get("statement_hash") or ""):
            return "正文与哈希不符"
        if int(item.get("seq") or 0) != index:
            return "seq 不连续"
        if str(item.get("prev_digest") or "") != prev:
            return "prev 摘要不接链"
        return None

    @staticmethod
    def _breakAt(activityId: str, item: Dict[str, Any], reason: str,
                 expected: str = "", found: str = "") -> Dict[str, Any]:
        return {"activity_id": activityId, "assertion_id": str(item.get("assertion_id") or ""),
                "seq": int(item.get("seq") or 0), "reason": reason,
                "expected": expected, "found": found}
