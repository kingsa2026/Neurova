# -*- coding: utf-8 -*-
"""A3 effect outbox：崩溃安全的副作用投递**意图层**（SQLite 持久）。

与 B1 ``delegated_delivery``（内存投递账本）的分工：账本是投递的**活体状态机**
（pending→claimed→acknowledged|disposed + 父闲补投），进程崩溃即丢失；本模块是
**持久意图层**——投递前先落一条意图（intent），投递成功后销账（delivered）。
进程崩溃时内存账本与邮箱都丢了，outbox 里的意图仍在：启动对账（``reconcile``）
对每条 pending 意图重新投递。**不做第二套投递状态机**——只有 intent/delivered
两态 + 启动对账；重投的去重安全网是邮箱的 messageId 幂等（宁重不丢，不重复生效）。

组合点在 ``swarm.pushParentMail``（邮箱唯一写点）：outbox 记意图（持久）→
邮箱投递 → 账本记状态（内存）。outbox 故障 fail-open（debug 留痕），不阻断
投递主流程；销账失败留待下次对账重投。

schema 经 ``db_migration.register_migration`` 登记（domain=mail_outbox），
库文件按 command_receipt 先例落 ``get_data_root()/mail_outbox.db``：user_version
按域推进、已应用版本自动跳过、库版本高于代码已知版本时按防降级语义拒绝。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from neurova.core.db_migration import migrate as _applyDomainMigrations
from neurova.core.db_migration import register_migration

MAIL_OUTBOX_DB_DOMAIN = "mail_outbox"

_MAIL_OUTBOX_SCHEMA_VERSION = 1

_MAIL_OUTBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS mail_outbox (
    intent_id TEXT PRIMARY KEY,
    pairing_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_ts REAL NOT NULL,
    delivered_ts REAL
);
CREATE INDEX IF NOT EXISTS idx_mail_outbox_pairing_status
    ON mail_outbox(pairing_key, status);
CREATE INDEX IF NOT EXISTS idx_mail_outbox_status_created
    ON mail_outbox(status, created_ts);
CREATE INDEX IF NOT EXISTS idx_mail_outbox_status_delivered
    ON mail_outbox(status, delivered_ts);
"""

# 模块级登记（与 core/command_receipt.py、agent/swarm_event_store.py 同范式）：
# import 即入登记表可审计；register_migration 对同版本重复注册幂等忽略，
# ensureMailOutboxStore 内再注册一次亦安全。
register_migration(
    _MAIL_OUTBOX_SCHEMA_VERSION, _MAIL_OUTBOX_SCHEMA, domain=MAIL_OUTBOX_DB_DOMAIN
)

#: 两态词值（本模块唯一出处）：intent=待投递；delivered=已投递销账
OUTBOX_INTENT = "intent"
OUTBOX_DELIVERED = "delivered"

_INSERT_INTENT_SQL = (
    "INSERT INTO mail_outbox "
    "(intent_id, pairing_key, payload_json, status, created_ts, delivered_ts) "
    "VALUES (?, ?, ?, ?, ?, NULL)"
)

_INTENT_COLUMNS = "intent_id, pairing_key, payload_json, status, created_ts, delivered_ts"


class MailOutboxError(Exception):
    """effect outbox 基础异常（入参校验等本域错误，诚实上抛不静默）。"""


def ensureMailOutboxStore(conn) -> None:
    """注册并应用 mail_outbox 迁移（幂等；防降级遵循 db_migration 语义）。"""
    register_migration(
        _MAIL_OUTBOX_SCHEMA_VERSION, _MAIL_OUTBOX_SCHEMA, domain=MAIL_OUTBOX_DB_DOMAIN
    )
    _applyDomainMigrations(conn, domain=MAIL_OUTBOX_DB_DOMAIN)


class MailOutbox:
    """持久投递意图库（SQLite；RLock 串行化短临界区，AGENTS.md §3）。

    每实例一条连接（check_same_thread=False）；``:memory:`` 供测试内嵌。
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # 落点遵循 command_receipt 先例：get_data_root() 派生，每域一库
            from neurova.core.data_root import get_data_root

            db_path = get_data_root() / "mail_outbox.db"
        self._path = str(db_path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        ensureMailOutboxStore(self._conn)

    def close(self) -> None:
        """关闭连接（测试与停机路径用；之后的调用不再受支持）。"""
        with self._lock:
            self._conn.close()

    # ── 对外契约 ────────────────────────────────────────────────

    def recordIntent(self, intentId: str, pairingKey: str, payload: Any) -> Dict[str, Any]:
        """登记投递意图（intentId=幂等键，如同 B1 的 messageId）。

        同 intentId 幂等：返回既有意图快照、首写为准（不覆盖不改状态）。
        payload 以 JSON 落库（ensure_ascii=False，中文原样可往返）；不可
        序列化时 TypeError 诚实上抛（调用方 fail-open 自行留痕）。
        """
        iid = str(intentId or "").strip()
        pkey = str(pairingKey or "").strip()
        if not iid or not pkey:
            raise MailOutboxError("recordIntent 需要 intentId 与 pairingKey")
        payloadJson = json.dumps(payload if payload is not None else {}, ensure_ascii=False)
        with self._lock:
            existing = self._getLocked(iid)
            if existing is not None:
                return existing
            self._conn.execute(
                _INSERT_INTENT_SQL, (iid, pkey, payloadJson, OUTBOX_INTENT, time.time())
            )
            self._conn.commit()
            return self._getLocked(iid)

    def markDelivered(self, intentId: str) -> bool:
        """intent→delivered 销账。幂等（已销账重复调用返回 True）；
        未知/空 id 诚实返回 False。"""
        iid = str(intentId or "").strip()
        if not iid:
            return False
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM mail_outbox WHERE intent_id = ?", (iid,)
            ).fetchone()
            if row is None:
                return False
            if row[0] == OUTBOX_DELIVERED:
                return True
            self._conn.execute(
                "UPDATE mail_outbox SET status = ?, delivered_ts = ? WHERE intent_id = ?",
                (OUTBOX_DELIVERED, time.time(), iid),
            )
            self._conn.commit()
            return True

    def pendingIntents(self, pairingKey: Optional[str] = None) -> List[Dict[str, Any]]:
        """待投递意图快照（落单序）；带 pairingKey 时按会话/配对维度过滤。"""
        with self._lock:
            if pairingKey is None:
                rows = self._conn.execute(
                    f"SELECT {_INTENT_COLUMNS} FROM mail_outbox "
                    "WHERE status = ? ORDER BY created_ts, intent_id",
                    (OUTBOX_INTENT,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    f"SELECT {_INTENT_COLUMNS} FROM mail_outbox "
                    "WHERE status = ? AND pairing_key = ? ORDER BY created_ts, intent_id",
                    (OUTBOX_INTENT, str(pairingKey)),
                ).fetchall()
            return [self._rowToIntent(row) for row in rows]

    def getIntent(self, intentId: str) -> Optional[Dict[str, Any]]:
        """按 intentId 取意图快照（任意状态）；不存在返回 None。"""
        iid = str(intentId or "").strip()
        if not iid:
            return None
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_INTENT_COLUMNS} FROM mail_outbox WHERE intent_id = ?", (iid,)
            ).fetchone()
            return self._rowToIntent(row) if row is not None else None

    def snapshot(self) -> List[Dict[str, Any]]:
        """全量意图快照（含已销账；落单序）——运维读数与测试判据用。"""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_INTENT_COLUMNS} FROM mail_outbox ORDER BY created_ts, intent_id"
            ).fetchall()
            return [self._rowToIntent(row) for row in rows]

    def deleteDelivered(self, before_ts: Optional[float] = None) -> int:
        """清理已投递意图（防无界增长）。before_ts 为 epoch 秒：只删
        delivered_ts 早于它的行；None=清全部已投递。返回删除行数。
        未投递（intent）行任何情况下都不删。"""
        with self._lock:
            if before_ts is None:
                cursor = self._conn.execute(
                    "DELETE FROM mail_outbox WHERE status = ?", (OUTBOX_DELIVERED,)
                )
            else:
                cursor = self._conn.execute(
                    "DELETE FROM mail_outbox WHERE status = ? "
                    "AND delivered_ts IS NOT NULL AND delivered_ts < ?",
                    (OUTBOX_DELIVERED, float(before_ts)),
                )
            self._conn.commit()
            return int(cursor.rowcount)

    def reconcile(self, deliver_fn: Callable[[Dict[str, Any]], bool]) -> Dict[str, Any]:
        """启动对账：对每条 pending 意图调用 deliver_fn 重放投递。

        deliver_fn(intent) 返回 True → markDelivered 销账；返回 False 或抛
        异常 → 意图保持 pending（宁重不丢，留待下次对账），单条失败不拖垮
        整体。去重安全网在邮箱的 messageId 幂等：崩溃前已入箱的意图重投同
        messageId 只补销账、不重复生效。返回 {attempted, delivered, failed}。
        """
        if deliver_fn is None:
            raise MailOutboxError("reconcile 需要 deliver_fn")
        attempted = 0
        delivered = 0
        failed = 0
        for intent in self.pendingIntents():  # 逐条快照，锁不跨投递持有
            attempted += 1
            ok = False
            try:
                ok = bool(deliver_fn(intent))
                if ok:
                    ok = bool(self.markDelivered(intent["intent_id"]))
            except Exception:  # noqa: BLE001 - 单条失败保持 pending，不拖垮整体
                ok = False
            if ok:
                delivered += 1
            else:
                failed += 1
        return {"attempted": attempted, "delivered": delivered, "failed": failed}

    # ── 内部工具（持锁调用）──────────────────────────────────────
    @staticmethod
    def _rowToIntent(row: tuple) -> Dict[str, Any]:
        try:
            payload = json.loads(row[2]) if row[2] else {}
        except (TypeError, ValueError):
            payload = {}
        return {
            "intent_id": row[0],
            "pairing_key": row[1],
            "payload": payload,
            "status": row[3],
            "created_ts": row[4],
            "delivered_ts": row[5],
        }

    def _getLocked(self, intentId: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            f"SELECT {_INTENT_COLUMNS} FROM mail_outbox WHERE intent_id = ?", (intentId,)
        ).fetchone()
        return self._rowToIntent(row) if row is not None else None


# ── 进程级单例（DCL + RLock，AGENTS.md §3）────────────────────────

_OUTBOX: Optional[MailOutbox] = None
_OUTBOX_LOCK = threading.RLock()


def getMailOutbox() -> MailOutbox:
    """进程级 outbox 单例（DCL+RLock）。库文件落 get_data_root()/mail_outbox.db。"""
    global _OUTBOX
    if _OUTBOX is not None:
        return _OUTBOX
    with _OUTBOX_LOCK:
        if _OUTBOX is None:
            _OUTBOX = MailOutbox()
    return _OUTBOX


def resetMailOutbox() -> None:
    """测试用：关闭并清空进程级单例（下一个 getMailOutbox 重建）。"""
    global _OUTBOX
    with _OUTBOX_LOCK:
        if _OUTBOX is not None:
            try:
                _OUTBOX.close()
            except Exception:  # noqa: BLE001 - 测试清场不因连接已关闭而失败
                pass
        _OUTBOX = None
