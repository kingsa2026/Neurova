# -*- coding: utf-8 -*-
"""AgentRun 持久化状态机。

按 Neurova 单进程+SQLite
形态裁剪（同 `channels/channel_ingress_queue.py` 的已验证模式，报告结论
"渠道入站队列已经懂这套，只是从未推广"）：

  - intake：请求先落库（queued）再执行——"先提交事实再投递执行"不变量；
  - claim_next：同 session 至多一个 running，由**部分唯一索引**在库层强制
；队头 FIFO 晋升；
  - heartbeat/finish：owner 栅栏，陈旧 owner 无法续租或写终态；
  - request_cancel：持久取消意图（cancel_requested 列）——stop 端点先落库
    再走 in-process task_tracker，Redis 信号层的等价物是"进程内取消即时、
    DB 意图跨重启可见"；
  - reconcile_at_startup：上一进程遗留 running → failed(process_died)、
    queued → cancelled(server_restart)。单进程模型（app.py workers=1）下
    启动时存在 running 行即证明其 owner 进程已死——这是"重启丢在途"的
    根治第一步：run 事实不再随内存消失，幽灵行不再永驻。

  - park / takeForResume：**parked 是非终态**，专门给"让位闸等不到额度"的回合。
    它与上面两条相反，是**故意活过重启**的——重启后收敛只能把它原样留着，
    人工点"续跑"时由唯一回合入口拿载荷重跑（`api/endpoints/console.py`）。

边界（如实，勿超读）：本模块**不自动**跨重启续跑——parked 行等着，但没人替它
执行；执行仍只在有人（会话属主或管理员）打续跑端点时发生（单进程形态下不引入
后台轮询，那会造出一条无人管的执行路径）。SSE 重放缓冲仍是内存有界结构。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.db_migration import migrate as apply_migrations, register_migration
from neurova.core.logger import get_logger
from neurova.core.data_root import get_data_root

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_runs (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT '',
    message_digest TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    owner TEXT NOT NULL DEFAULT '',
    lease_expires_at REAL NOT NULL DEFAULT 0,
    heartbeat_at REAL NOT NULL DEFAULT 0,
    attempt INTEGER NOT NULL DEFAULT 0,
    error_type TEXT,
    created_at REAL NOT NULL DEFAULT 0,
    started_at REAL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_session_status
    ON agent_runs(session_id, status, seq);
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_runs_one_running
    ON agent_runs(session_id) WHERE status = 'running';
"""
register_migration(1, _SCHEMA, domain="agent_runs")


def _migrateToV2(conn: sqlite3.Connection) -> None:
    """v2：给 `parked`（挂起等人工续跑）补它需要的两列。

    - `park_reason`：为什么挂起。人要点"续跑"，得先看得见卡在哪。
    - `resume_payload`：待跑回合的请求载荷。这条**不是**消息的第二份真相——
      用户原文要到 `ChatPipeline._step_save_session` 才落进会话，而挂起发生在
      那之前，此刻除了这里没有任何地方存着这一轮，不落就等于"续跑"无从谈起。
      写终态即清空（见 `finish`），不让原文在库里长期滞留。
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_runs)")}
    for name, decl in (("park_reason", "TEXT"), ("resume_payload", "TEXT")):
        if name not in columns:
            conn.execute(f"ALTER TABLE agent_runs ADD COLUMN {name} {decl}")


register_migration(2, _migrateToV2, domain="agent_runs")

TERMINAL_STATUSES = ("completed", "failed", "cancelled")

# 挂起态：非终态。它的存在意义就是"活过进程、等人点续跑"，因此
# `reconcile_at_startup` 不收敛它，且 park 时松开 owner 栅栏、退出单活槽。
PARKED_STATUS = "parked"
NON_TERMINAL_STATUSES = ("queued", "running", PARKED_STATUS)

# 进程 identity：owner 栅栏的比较基准
OWNER_IDENTITY = f"p{os.getpid()}-{uuid.uuid4().hex[:8]}"

def defaultDbPath() -> Path:
    """默认库落点：数据根下的绝对路径（原值 `Path("data")` 随 CWD 漂移）。"""
    return get_data_root() / "agent_runs.db"


def _default_db_path() -> str:
    return str(os.environ.get("NEUROVA_RUN_STORE_DB") or defaultDbPath())


class AgentRunStore:
    """run 台账（每实例一个 SQLite 连接，threading.Lock 串行写，WAL）。"""

    def __init__(self, db_path: Any = None, lease_seconds: float = 90.0):
        self.db_path = str(db_path or _default_db_path())
        self.lease_seconds = float(lease_seconds)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        with self._lock, self._conn:
            apply_migrations(self._conn, "agent_runs")
        # 进程启动语义：store 每进程恰好构造一次（单例 + app.py workers=1），
        # init 时仍为 running 的行必来自已死的前进程 → 收敛不留幽灵。
        self.reconcile_at_startup()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # 写入侧
    # ------------------------------------------------------------------

    def intake(
        self, session_id: str, user_id: str = "", agent_id: str = "", message: str = ""
    ) -> str:
        """请求落库（queued）。返回 run_id。message 只存摘要（正文真相在会话）。"""
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO agent_runs (run_id, session_id, user_id, agent_id,"
                " message_digest, status, created_at) VALUES (?,?,?,?,?,'queued',?)",
                (run_id, session_id, user_id, agent_id, (message or "")[:200], now),
            )
        return run_id

    def claim_next(self, session_id: str, owner: Optional[str] = None) -> Optional[str]:
        """把该 session 的 FIFO 队头 queued 晋升 running；已有活跃 run 返回 None。

        单进程内由 _lock 串行；跨进程防重由部分唯一索引兜底（晋升撞约束
        即 IntegrityError → 本进程无赢家资格，回退 None）。
        """
        owner = owner or OWNER_IDENTITY
        now = time.time()
        with self._lock:
            try:
                with self._conn:
                    row = self._conn.execute(
                        "SELECT run_id FROM agent_runs WHERE session_id=? AND status='queued'"
                        " ORDER BY seq LIMIT 1",
                        (session_id,),
                    ).fetchone()
                    if not row:
                        return None
                    run_id = row[0]
                    cur = self._conn.execute(
                        "UPDATE agent_runs SET status='running', owner=?, attempt=attempt+1,"
                        " started_at=?, heartbeat_at=?, lease_expires_at=?"
                        " WHERE run_id=? AND status='queued'"
                        " AND NOT EXISTS (SELECT 1 FROM agent_runs WHERE session_id=?"
                        "   AND status='running')",
                        (owner, now, now, now + self.lease_seconds, run_id, session_id),
                    )
                    return run_id if cur.rowcount == 1 else None
            except sqlite3.IntegrityError:
                # 部分唯一索引赢家是别的 owner（多进程/重放），本次不夺权
                logger.warning("claim_next 让位部分唯一索引: session=%s owner=%s", session_id, owner)
                return None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def heartbeat(self, run_id: str, owner: str) -> bool:
        """续租——仅当前且未过期 owner 可续。"""
        now = time.time()
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE agent_runs SET heartbeat_at=?, lease_expires_at=?"
                " WHERE run_id=? AND owner=? AND status='running' AND lease_expires_at >= ?",
                (now, now + self.lease_seconds, run_id, owner, now),
            )
            return cur.rowcount == 1

    def finish(
        self,
        run_id: str,
        owner: str,
        status: str,
        error_type: Optional[str] = None,
    ) -> bool:
        """写终态——owner 栅栏；status 必须是终态枚举。"""
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"finish 需要终态，收到 {status!r}（合法: {TERMINAL_STATUSES}）")
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE agent_runs SET status=?, error_type=?, finished_at=?,"
                " resume_payload=NULL"
                " WHERE run_id=? AND owner=? AND status='running'",
                (status, error_type, time.time(), run_id, owner),
            )
            return cur.rowcount == 1

    def request_cancel(self, session_id: str) -> Optional[str]:
        """持久取消意图：running 行优先返回；同 session 全部 queued 行一并
        打标（P1-#8 排队中可停——等待方在晋升轮询中消费该意图自行收尾）。

        parked 行**直接落终态**：它按定义没有执行体，只打一个意图标记就会留下
        一条"用户已叫停、却永远还挂在等人续跑"的行——既读不懂也清不掉。

        重放幂等：已打标行重复打标无害，返回值恒为本 session 最老的活跃/
        排队/挂起行（无则 None，调用方保持旧语义）。
        """
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT run_id, status FROM agent_runs"
                " WHERE session_id=? AND status IN ('running','queued',?)"
                " ORDER BY seq",
                (session_id, PARKED_STATUS),
            ).fetchall()
            if not rows:
                return None
            self._conn.execute(
                "UPDATE agent_runs SET cancel_requested=1"
                " WHERE session_id=? AND status IN ('running','queued')",
                (session_id,),
            )
            self._conn.execute(
                "UPDATE agent_runs SET status='cancelled', error_type=?,"
                " finished_at=?, resume_payload=NULL, owner='', lease_expires_at=0"
                " WHERE session_id=? AND status=?",
                ("user_stopped_while_parked", time.time(), session_id, PARKED_STATUS),
            )
            return rows[0]["run_id"]

    def abandon(self, run_id: str, reason: str = "client_abandoned") -> bool:
        """等待方离开：仅未晋升（queued）的行可弃——正在跑的绝不在此误杀。"""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE agent_runs SET status='cancelled', error_type=?, finished_at=?"
                " WHERE run_id=? AND status='queued'",
                (reason, time.time(), run_id),
            )
            return cur.rowcount == 1

    def park(
        self,
        run_id: str,
        owner: str,
        parkReason: str,
        payload: Any = None,
    ) -> bool:
        """running → parked（挂起等人工续跑）。

        owner 栅栏保留在 WHERE 上（只有当前执行者能挂起自己那一轮），但写完后
        **松开 owner 并清零租约**：留着 owner 就仍占着同 session 单活槽，
        `claim_next` 的 `NOT EXISTS (… 'running')` 会把整个会话永久挡住——
        连"续跑"都发不出去；租约继续跑也会被 `reconcile_stale` 误杀成 failed。
        """
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE agent_runs SET status=?, park_reason=?, resume_payload=?,"
                " owner='', lease_expires_at=0, heartbeat_at=0"
                " WHERE run_id=? AND owner=? AND status='running'",
                (
                    PARKED_STATUS,
                    parkReason,
                    json.dumps(payload if payload is not None else {}, ensure_ascii=False),
                    run_id,
                    owner,
                ),
            )
            return cur.rowcount == 1

    def takeForResume(self, run_id: str) -> Optional[Dict[str, Any]]:
        """把 parked 行交还给回合入口（翻回 queued），返回**翻转前**的行。

        载荷列在换手时即清空：调用方拿到了它，库里就不该再留第二份原文；
        若这一轮再次挂起，`park` 会重新写入当时的载荷。

        非 parked 一律 None：running 被取走＝同一轮双执行；终态行已跑过。
        `seq` 不变，所以它仍排在会话队列最前——这一轮本来就先提交。
        """
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM agent_runs WHERE run_id=? AND status=?",
                (run_id, PARKED_STATUS),
            ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                "UPDATE agent_runs SET status='queued', cancel_requested=0,"
                " resume_payload=NULL"
                " WHERE run_id=? AND status=?",
                (run_id, PARKED_STATUS),
            )
        return dict(row)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM agent_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

    def active_run(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM agent_runs WHERE session_id=? AND status='running' LIMIT 1",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def cancel_requested(self, run_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT cancel_requested FROM agent_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return bool(row and row[0])

    def queued_position(self, run_id: str) -> int:
        """该 run 在同 session 队列中的相对位次（0=下一个执行）。非 queued 态返回 0。"""
        with self._lock:
            own = self._conn.execute(
                "SELECT seq, status FROM agent_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if not own or own[1] != "queued":
                return 0
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM agent_runs WHERE session_id=("
                " SELECT session_id FROM agent_runs WHERE run_id=?) AND status='queued'"
                " AND seq < ?",
                (run_id, own[0]),
            ).fetchone()
        return int(cur[0])

    def list_runs(self, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agent_runs WHERE session_id=? ORDER BY seq DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> Dict[str, int]:
        with self._lock:
            # parked 必须单列：把它折进 terminal 就等于把"等人续跑"读成"已结束"
            counts = {s: 0 for s in ("running", "queued", PARKED_STATUS, "terminal")}
            for status, n in self._conn.execute(
                "SELECT status, COUNT(*) FROM agent_runs GROUP BY status"
            ).fetchall():
                counts[status if status in counts else "terminal"] += int(n)
        return counts

    # ------------------------------------------------------------------
    # 收敛
    # ------------------------------------------------------------------

    def reconcile_at_startup(self) -> List[Dict[str, Any]]:
        """启动收敛：单进程模型（app.py workers=1）下，启动时仍为 running
        的行必然来自已死进程 → failed(process_died)；遗留 queued →
        cancelled(server_restart)（其等待方 SSE 连接已随进程消失）。

        parked **原样留着**：它是"等人"而不是"在跑"，把它收敛掉就等于一次重启
        之后人工再也没东西可续——这条能力的全部意义正是活过进程。数量必须打进
        日志：否则运维只看得到"什么都没发生"，而库里挂着 N 条待办。
        """
        now = time.time()
        with self._lock, self._conn:
            dead = self._conn.execute(
                "SELECT run_id, session_id FROM agent_runs WHERE status='running'"
            ).fetchall()
            queued = self._conn.execute(
                "SELECT run_id, session_id FROM agent_runs WHERE status='queued'"
            ).fetchall()
            parked = self._conn.execute(
                "SELECT COUNT(*) FROM agent_runs WHERE status=?", (PARKED_STATUS,)
            ).fetchone()[0]
            self._conn.execute(
                "UPDATE agent_runs SET status='failed', error_type='process_died',"
                " finished_at=? WHERE status='running'",
                (now,),
            )
            self._conn.execute(
                "UPDATE agent_runs SET status='cancelled', error_type='server_restart',"
                " finished_at=? WHERE status='queued'",
                (now,),
            )
        if parked:
            logger.warning(
                "AgentRun 启动对账：%d 条 parked 原样保留（等人工续跑，不自动执行）", int(parked)
            )
        if dead or queued:
            logger.warning(
                "AgentRun 启动收敛: %d running→failed(process_died), %d queued→cancelled(server_restart)",
                len(dead),
                len(queued),
            )
        return [
            {"run_id": r, "session_id": s, "status": "failed", "error_type": "process_died"}
            for r, s in dead
        ] + [
            {"run_id": r, "session_id": s, "status": "cancelled", "error_type": "server_restart"}
            for r, s in queued
        ]

    def reconcile_stale(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """租约过期收敛（进程内可周期调用）：仅 lease 已过期的 running →
        failed(process_died)。心跳停止但进程未重启的场景兜底。"""
        now = now if now is not None else time.time()
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT run_id, session_id FROM agent_runs"
                " WHERE status='running' AND lease_expires_at < ?",
                (now,),
            ).fetchall()
            if rows:
                self._conn.execute(
                    "UPDATE agent_runs SET status='failed', error_type='process_died',"
                    " finished_at=? WHERE status='running' AND lease_expires_at < ?",
                    (now, now),
                )
        return [{"run_id": r, "session_id": s} for r, s in rows]


# ── 单例工厂（全项目 get_*/reset_* 惯例）────────────────────────────
_store: Optional[AgentRunStore] = None
_store_lock = threading.Lock()


def get_agent_run_store() -> AgentRunStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = AgentRunStore()
        return _store


def reset_agent_run_store() -> None:
    global _store
    with _store_lock:
        if _store is not None:
            try:
                _store.close()
            except Exception:  # noqa: BLE001 - 释放失败不阻断重置
                pass
            _store = None


def run_gate_enabled() -> bool:
    """特性开关（默认 on）：run 台账故障永不阻断聊天——接线层全部
    fail-open（对位 channel_ingress enqueue 的 fail-open + 类型区分先例）。"""
    return (os.environ.get("NEUROVA_RUN_GATE") or "on").strip().lower() != "off"
