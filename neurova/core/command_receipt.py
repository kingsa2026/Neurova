# -*- coding: utf-8 -*-
"""命令回执幂等（参照系 ac 借鉴 A3）：command_id → 回执；重试重放结果，不重跑副作用。

swarm 的派活/审批应答/候选合并等写路径此前无命令级幂等：网络重试或 WS 重连
可能重复派活、重复应答。本模块给每条命令落一条回执（command_id → status +
结果），重试按回执重放结果、绝不重跑副作用；拒绝也落回执（防同 ID 反复打穿）。

三态语义：
- running   预留中（他方在途；进程死亡会残留此态——重试方只报冲突，不接管不重跑）
- accepted  已成功（重试按 result_json 重放，fn 不再执行）
- rejected  已拒绝（重试抛 PreviouslyRejectedError，须换 ID 重发）

schema 经 `db_migration.register_migration` 登记（domain=command_receipt），
应用入口复用 `db_migration.migrate`：user_version 按域推进、已应用版本自动跳过、
库版本高于代码已知版本时按防降级语义拒绝（SchemaVersionError）。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Tuple

from neurova.core.db_migration import migrate as _applyDomainMigrations
from neurova.core.db_migration import register_migration

RECEIPT_DB_DOMAIN = "command_receipt"

_RECEIPT_SCHEMA_VERSION = 1

_RECEIPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS command_receipt (
    command_id TEXT PRIMARY KEY,
    command_type TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL
);
"""

# 模块级登记（与 api/auth.py 的 auth_blacklist 域同范式）：import 即入登记表可审计；
# register_migration 对同版本重复注册幂等忽略，ensureReceiptStore 内再注册一次亦安全。
register_migration(_RECEIPT_SCHEMA_VERSION, _RECEIPT_SCHEMA, domain=RECEIPT_DB_DOMAIN)

# SQLite 多线程访问规约：threading.RLock（AGENTS.md §3）。只护"预留/判定/落账"
# 这几段短临界区；fn() 在锁外执行——不同 command_id 之间不因此串行，fn 内再入
# 本模块（同线程）也因 RLock 可重入而不会自锁。
_RECEIPT_LOCK = threading.RLock()

_STATUS_RUNNING = "running"
_STATUS_ACCEPTED = "accepted"
_STATUS_REJECTED = "rejected"

_INSERT_RECEIPT_SQL = (
    "INSERT INTO command_receipt "
    "(command_id, command_type, thread_id, status, result_json, error, created_at) "
    "VALUES (?, ?, ?, ?, NULL, NULL, ?)"
)


class CommandReceiptError(Exception):
    """命令回执机制基础异常。"""


class CommandIdConflictError(CommandReceiptError):
    """同一 command_id 在不同 thread 上复用（调用方 bug，须换 ID）。"""


class PreviouslyRejectedError(CommandReceiptError):
    """该 command_id 曾被拒绝且不可重试（须换 ID 重发）。"""


def ensureReceiptStore(conn) -> None:
    """注册并应用 command_receipt 迁移（幂等；防降级遵循 db_migration 语义）。"""
    register_migration(_RECEIPT_SCHEMA_VERSION, _RECEIPT_SCHEMA, domain=RECEIPT_DB_DOMAIN)
    _applyDomainMigrations(conn, domain=RECEIPT_DB_DOMAIN)


def executeWithReceipt(
    conn,
    *,
    command_id: str,
    command_type: str,
    thread_id: str,
    fn: Callable[[], Any],
) -> Tuple[Any, bool]:
    """幂等执行入口。返回 (result, replayed: bool)。

    - 首次：单事务内 insertIfAbsent 预留回执（status='running'）→ 执行 fn() →
      回执更新为 accepted 并存 result_json → 返回 (result, False)。
    - fn 抛异常 → 回执置 rejected（error 落库）→ 异常原样上抛。
    - 重放：库中已有 accepted 同 ID 回执：thread_id 不一致 → CommandIdConflictError；
      否则从 result_json 反序列化返回 (result, True)，fn 不执行。
      已有 rejected 同 ID：thread_id 校验同上；然后抛 PreviouslyRejectedError
      （原 error 信息带入）。已有 running（他方在途/进程死亡残留）→ 视为冲突：
      thread_id 校验后抛 CommandReceiptError("command in flight or abandoned")
      （不接管，不重跑）。
    - 事务内 insertIfAbsent 竞态：并发同 ID 只有一个提交成功，另一侧按
      重放/冲突路径走。
    """
    with _RECEIPT_LOCK:
        if not _reserveReceipt(conn, command_id, command_type, thread_id):
            # 预留失败＝同 ID 回执已存在（重试或并发竞争）：按重放/冲突路径走
            return _replayOrRaise(conn, command_id, thread_id)
    try:
        result = fn()
    except Exception as exc:
        with _RECEIPT_LOCK:
            _finalizeReceipt(
                conn,
                command_id,
                _STATUS_REJECTED,
                error=f"{type(exc).__name__}: {exc}",
            )
        raise
    with _RECEIPT_LOCK:
        _finalizeReceipt(
            conn,
            command_id,
            _STATUS_ACCEPTED,
            result_json=json.dumps(result, ensure_ascii=False),
        )
    return result, False


async def executeWithReceiptAsync(
    conn,
    *,
    command_id: str,
    command_type: str,
    thread_id: str,
    afn,
) -> Tuple[Any, bool]:
    """异步命令版幂等入口（swarm async 写路径用）：语义同 :func:`executeWithReceipt`。

    ``afn`` 是 async callable。预留/落账仍是同步短临界区（RLock + 单事务）；
    ``afn`` await 期间不持锁——并发同 ID 的第二协程在首者落账前重入会看到
    running 态，按 "in flight" 冲突上报（不接管、不重跑）；首者落账后重入
    则按 result_json 重放。
    """
    with _RECEIPT_LOCK:
        if not _reserveReceipt(conn, command_id, command_type, thread_id):
            return _replayOrRaise(conn, command_id, thread_id)
    try:
        result = await afn()
    except Exception as exc:
        with _RECEIPT_LOCK:
            _finalizeReceipt(
                conn,
                command_id,
                _STATUS_REJECTED,
                error=f"{type(exc).__name__}: {exc}",
            )
        raise
    with _RECEIPT_LOCK:
        _finalizeReceipt(
            conn,
            command_id,
            _STATUS_ACCEPTED,
            result_json=json.dumps(result, ensure_ascii=False),
        )
    return result, False


def _nowIso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reserveReceipt(conn, command_id: str, command_type: str, thread_id: str) -> bool:
    """insertIfAbsent 预留 running 回执（单事务；提交后其他连接即可见）。

    Returns:
        True＝预留成功（本调用方获得执行权）；False＝同 ID 回执已存在。
    Raises:
        sqlite3.IntegrityError: 非 command_id 冲突的完整性错误原样上抛，不误路由。
    """
    try:
        conn.execute(
            _INSERT_RECEIPT_SQL,
            (command_id, command_type, thread_id, _STATUS_RUNNING, _nowIso()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        if "command_receipt.command_id" in str(exc):
            return False
        raise


def _replayOrRaise(conn, command_id: str, thread_id: str) -> Tuple[Any, bool]:
    """按既有回执决定重放或抛错（thread 校验先于一切状态分支）。"""
    row = conn.execute(
        "SELECT status, thread_id, result_json, error "
        "FROM command_receipt WHERE command_id = ?",
        (command_id,),
    ).fetchone()
    if row is None:
        # 预留竞争失败后回执又被删（并发清理）：诚实上报，不猜测重跑
        raise CommandReceiptError(
            f"command receipt vanished after insert conflict: {command_id!r}"
        )
    status, rowThreadId, resultJson, error = row[0], row[1], row[2], row[3]
    if rowThreadId != thread_id:
        raise CommandIdConflictError(
            f"command_id {command_id!r} 已被 thread {rowThreadId!r} 占用，"
            f"不能在 thread {thread_id!r} 上复用（须换 ID）"
        )
    if status == _STATUS_ACCEPTED:
        result = json.loads(resultJson) if resultJson is not None else None
        return result, True
    if status == _STATUS_REJECTED:
        raise PreviouslyRejectedError(
            f"command_id {command_id!r} 曾被拒绝且不可重试（须换 ID 重发）：{error}"
        )
    raise CommandReceiptError(
        f"command in flight or abandoned: {command_id!r} (status={status!r})"
    )


def _finalizeReceipt(
    conn,
    command_id: str,
    status: str,
    result_json: Any = None,
    error: Any = None,
) -> None:
    """执行权所有者落账（accepted/rejected）；只有预留成功者会走到这里。"""
    conn.execute(
        "UPDATE command_receipt SET status = ?, result_json = ?, error = ? "
        "WHERE command_id = ?",
        (status, result_json, error, command_id),
    )
    conn.commit()
