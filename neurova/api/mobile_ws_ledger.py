# -*- coding: utf-8 -*-
"""移动端远程驾驶 WS 的可靠性账本（实施计划项 1：连接 epoch + 事件账本重放 + 指令记账）。

解决什么问题：手机经 `/v1/mobile/ws` 远程驾驶 PC 端 Agent 时，移动网络不可靠——
指令可能没到服务端、结果帧可能没回到手机、重连后两端状态可能不一致。本模块提供
三件套（对齐 Linger Computer Daemon 的纪律）：

1. **连接 epoch**：每条连接建立时发号递增 epoch（按设备计数），帧内携带——
   客户端据此识别"这是新连接"，旧连接的流任务被收尸后不可能冒充新连接续写。
2. **事件账本**：出站帧先落账（设备级单调 seq）再发送，帧内注入 ``seq``；
   客户端断线重连后发 ``sync_resume {last_seq}``，服务端按游标补发缺失帧
   （带 ``replay: true``），实现"断网 30s 内的遥控指令与结果帧不丢、不重"。
3. **指令记账**：入站遥控指令携带客户端生成的 ``command_id``，服务端先记账再
   执行——同 ``command_id`` 的重复发送回放原终态（``replayed: true``），不再
   产生第二次真实执行。

存储：SQLite 落数据根（``NEUROVA_MOBILE_WS_LEDGER_DB`` 可覆盖），RLock 串行写
+ WAL + 版本化迁移（对齐 ``agent_run_store`` 惯例）；事件按设备保留最近 500 帧。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from neurova.api.connection_runtime import SubscriptionScope
from neurova.api.connection_runtime import inScope as _frameInScope
from neurova.api.connection_runtime import parseSubscriptionScope as _parseScope
from neurova.api.subscription_resume import ResumeDecision
from neurova.api.subscription_resume import resolveResume as _resolveResumeDecision
from neurova.core.db_migration import migrate as applyMigrations, register_migration
from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 本库的 schema 版本域（域隔离：不与 agent_runs/memory 等共用版本链）
LEDGER_DB_DOMAIN = "mobile_ws"

__all__ = [
    "MobileWsLedger",
    "LedgerWs",
    "getMobileWsLedger",
    "resetMobileWsLedger",
]

#: 结果留档上限（与工具账本同量级；回放面只需要终态帧）
_RESULT_JSON_MAX = 64 * 1024

#: 每设备保留的最近事件帧数（重放窗口；超出即老化删除）
_EVENTS_RETAIN_PER_DEVICE = 500
#: 单次 sync_resume 最多补发的帧数（客户端游标更远时分次拉）
_REPLAY_LIMIT = 500


def _replayVisible(frame: Any, effectiveScope: Any) -> bool:
    """补发可见性（B7 修正）：``device:*`` 帧是**设备自身账本帧**（按 pairing_id
    寻址，离线入队的 execute/回执都走这里），不参与会话订阅过滤——否则
    session 订阅下的设备永远补拉不到自己的遥控帧；其余帧维持订阅范围
    fail-closed 过滤（范围外/解析失败一律不下发）。"""
    if isinstance(frame, dict) and str(frame.get("type") or "").startswith("device:"):
        return True
    return effectiveScope is None or _frameInScope(frame, effectiveScope)


@dataclass(frozen=True)
class WsCommandEntry:
    """一条入站遥控指令的账目快照（status: running/settled）。

    身份是 ``(pairing_id, command_id)`` 复合主键——command_id 由各设备自行
    生成（常见就是 cmd-1、cmd-2 递增），不带设备限定的全局去重会把两台
    手机的同名指令误判成重复（第二个事实源）。
    """

    command_id: str
    pairing_id: str
    cmd_type: str
    status: str
    terminal_json: Optional[str]
    created_at: float
    settled_at: Optional[float]


_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS mobile_ws_epochs (
    pairing_id TEXT PRIMARY KEY,
    epoch INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mobile_ws_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    pairing_id TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    frame_type TEXT NOT NULL DEFAULT '',
    frame_json TEXT NOT NULL,
    created_at REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_mobile_ws_events_pairing_seq
    ON mobile_ws_events(pairing_id, seq);
CREATE TABLE IF NOT EXISTS mobile_ws_commands (
    pairing_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    cmd_type TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running',
    terminal_json TEXT,
    created_at REAL NOT NULL DEFAULT 0,
    settled_at REAL,
    PRIMARY KEY (pairing_id, command_id)
);
"""


def _migrateCommandsToCompositePk(conn: sqlite3.Connection) -> None:
    """v1→v2：指令表主键从单列 ``command_id`` 升为 ``(pairing_id, command_id)``。

    command_id 由各设备自行生成（cmd-1 递增是常态），按单列全局去重会把
    第二台设备的同名指令误判成重放。已按旧形建过的持久库（IF NOT EXISTS
    不会改既有表）在此重建：建新表→全量拷贝→换名。
    """
    info = conn.execute("PRAGMA table_info(mobile_ws_commands)").fetchall()
    if not info:
        return  # 全新库：v1 已按复合主键建表
    pkCols = [r[1] for r in sorted((r for r in info if r[5]), key=lambda r: r[5])]
    if pkCols == ["pairing_id", "command_id"]:
        return  # 已是目标形
    conn.execute("""
        CREATE TABLE mobile_ws_commands_v2 (
            pairing_id TEXT NOT NULL,
            command_id TEXT NOT NULL,
            cmd_type TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'running',
            terminal_json TEXT,
            created_at REAL NOT NULL DEFAULT 0,
            settled_at REAL,
            PRIMARY KEY (pairing_id, command_id)
        )
    """)
    conn.execute("""
        INSERT OR IGNORE INTO mobile_ws_commands_v2
            (pairing_id, command_id, cmd_type, payload_json, status,
             terminal_json, created_at, settled_at)
        SELECT pairing_id, command_id, cmd_type, payload_json, status,
               terminal_json, created_at, settled_at
        FROM mobile_ws_commands
    """)
    conn.execute("DROP TABLE mobile_ws_commands")
    conn.execute("ALTER TABLE mobile_ws_commands_v2 RENAME TO mobile_ws_commands")


# 版本化迁移（对齐 agent_run_store 的域隔离惯例；不写"仅 IF NOT EXISTS"的裸演进）
register_migration(1, _SCHEMA_V1, domain=LEDGER_DB_DOMAIN)
register_migration(2, _migrateCommandsToCompositePk, domain=LEDGER_DB_DOMAIN)


class MobileWsLedger:
    """移动 WS 可靠性账本（每实例一个 SQLite 连接，RLock 串行写，WAL）。"""

    def __init__(self, db_path: Any = None):
        from neurova.core.data_root import get_data_root

        self.db_path = str(
            db_path
            or os.environ.get("NEUROVA_MOBILE_WS_LEDGER_DB")
            or (get_data_root() / "mobile_ws_ledger.db")
        )
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # 订阅范围登记（按需订阅，G4 单源）：pairing_id → SubscriptionScope。
        # 连接级内存态：断线重连由客户端重新订阅（不落库，不跨进程）。
        self._subscriptions: Dict[str, SubscriptionScope] = {}
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        with self._lock:
            applyMigrations(self._conn, domain=LEDGER_DB_DOMAIN)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── 连接 epoch ──────────────────────────────────────────────────

    def currentEpoch(self, pairing_id: str) -> int:
        """当前（最近一次连接发放的）epoch，只读**不发号**；无记录返回 0。

        离线入队（设备桥 B7）用它落账：帧挂在设备最近一次连接的 epoch 上，
        重连后 sync_resume 按 seq 补拉即可拿到，不需要预先发新 epoch。
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT epoch FROM mobile_ws_epochs WHERE pairing_id = ?",
                (pairing_id,),
            ).fetchone()
        return int(row["epoch"]) if row is not None else 0

    def nextEpoch(self, pairing_id: str) -> int:
        """按设备发号递增的连接 epoch（每条 WS 连接建立时取一次）。"""
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO mobile_ws_epochs (pairing_id, epoch, updated_at)"
                " VALUES (?, 1, ?) ON CONFLICT(pairing_id) DO UPDATE SET"
                " epoch = epoch + 1, updated_at = ?",
                (pairing_id, now, now),
            )
            row = self._conn.execute(
                "SELECT epoch FROM mobile_ws_epochs WHERE pairing_id = ?", (pairing_id,)
            ).fetchone()
        return int(row["epoch"])

    # ── 事件账本 ────────────────────────────────────────────────────

    def appendEvent(self, pairing_id: str, epoch: int, frame: Dict[str, Any]) -> int:
        """出站帧落账，返回设备级单调递增的 seq（先落账、后发送）。"""
        now = time.time()
        frame_type = str(frame.get("type") or "")
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT INTO mobile_ws_events (pairing_id, epoch, frame_type, frame_json, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (pairing_id, epoch, frame_type,
                 json.dumps(frame, ensure_ascii=False, default=str), now),
            )
            seq = int(cursor.lastrowid)
            # 老化：每设备只留最近 _EVENTS_RETAIN_PER_DEVICE 帧
            self._conn.execute(
                "DELETE FROM mobile_ws_events WHERE pairing_id = ? AND seq <="
                " (SELECT MAX(seq) - ? FROM mobile_ws_events WHERE pairing_id = ?)",
                (pairing_id, _EVENTS_RETAIN_PER_DEVICE, pairing_id),
            )
        return seq

    def lastSeq(self, pairing_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(seq) AS max_seq FROM mobile_ws_events WHERE pairing_id = ?",
                (pairing_id,),
            ).fetchone()
        return int(row["max_seq"] or 0) if row is not None else 0

    def oldestSeq(self, pairing_id: str) -> int:
        """该设备仍留存的最早 seq（保留窗口下界；空账本 0）。

        保留窗口老化按设备删前缀：窗口内更早的帧已不可回放。续传决策据此判
        "游标过旧"。注意全局 seq 跨设备交错，本下界是**设备级**的。
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT MIN(seq) AS min_seq FROM mobile_ws_events WHERE pairing_id = ?",
                (pairing_id,),
            ).fetchone()
        minSeq = row["min_seq"] if row is not None else None
        return int(minSeq) if minSeq is not None else 0

    def resolveResume(
        self, pairing_id: str, last_seq: Optional[int], *, budget=None
    ) -> ResumeDecision:
        """断线重连续传决策（D3 单源语义在本账本的落点，见
        ``neurova/api/subscription_resume.py``）。

        ``min_available_seq`` 取本设备留存窗口下界 ``oldestSeq()``：游标早于
        "下界-1" 即 ``(cursor, head]`` 区间内已有帧被老化删除，增量必不完整 →
        snapshot（与全局事件库 ``replayThrough`` 的 pruned_through 降级语义同构）。
        ``budget`` 为可选的 ``ReplayByteBudget``（预算耗尽 → snapshot）。
        """
        return _resolveResumeDecision(
            last_seq,
            self.lastSeq(pairing_id),
            min_available_seq=self.oldestSeq(pairing_id),
            budget=budget,
        )

    # ── 订阅范围（按需订阅，G4 单源接线） ────────────────────────────

    def subscribe(self, pairing_id: str, scope: str, scope_key: str = "") -> SubscriptionScope:
        """登记该设备当前连接的订阅范围（"看一个线程不付全部线程的账"）。

        解析校验走 ``connection_runtime.parseSubscriptionScope`` 单源；非法范围
        抛 ``ValueError``（fail-closed，不带病登记）。登记后 :meth:`replaySince`
        只下发落在范围内的帧；未登记时不过滤（与改前行为一致——范围过滤只做
        加法，``pairing_id`` 归属校验恒在，不放宽）。
        """
        parsed = _parseScope(scope, scope_key)
        with self._lock:
            self._subscriptions[pairing_id] = parsed
        return parsed

    def subscriptionOf(self, pairing_id: str) -> Optional[SubscriptionScope]:
        """读该设备已登记的订阅范围（未登记返回 None）。"""
        with self._lock:
            return self._subscriptions.get(pairing_id)

    def unsubscribe(self, pairing_id: str) -> None:
        """清除订阅登记（连接关闭 / 客户端要求全量重同步时调用）。"""
        with self._lock:
            self._subscriptions.pop(pairing_id, None)

    def replaySince(
        self,
        pairing_id: str,
        last_seq: int,
        limit: int = _REPLAY_LIMIT,
        scope: Optional[Union[SubscriptionScope, Tuple[str, str]]] = None,
    ) -> List[Dict[str, Any]]:
        """按游标补发：返回该设备 ``seq > last_seq`` 的账本帧（升序，带 seq）。

        ``scope``：订阅范围过滤（G4 按需订阅）。可传
        :class:`~neurova.api.connection_runtime.SubscriptionScope` 或
        ``(scope, scope_key)`` 元组；缺省回落到 :meth:`subscribe` 登记的该设备
        订阅，未登记则不过滤（行为与改前一致）。过滤经
        ``connection_runtime.inScope``：范围外帧与**解析失败（缺/空/错型
        session_id、thread_id）的帧一律扣下不下发**（fail-closed）。
        """
        if scope is None:
            effectiveScope = self.subscriptionOf(pairing_id)
        elif isinstance(scope, SubscriptionScope):
            effectiveScope = scope
        else:
            effectiveScope = _parseScope(scope[0], scope[1] if len(scope) > 1 else "")
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, frame_json FROM mobile_ws_events"
                " WHERE pairing_id = ? AND seq > ? ORDER BY seq ASC LIMIT ?",
                (pairing_id, int(last_seq), int(limit)),
            ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            try:
                frame = json.loads(row["frame_json"])
            except Exception:  # noqa: BLE001 - 留档损坏的帧跳过（不阻断后续补发）
                continue
            if not _replayVisible(frame, effectiveScope):
                continue
            out.append({"seq": int(row["seq"]), "frame": frame})
        return out

    # ── 指令记账 ────────────────────────────────────────────────────

    def beginCommand(
        self, command_id: str, pairing_id: str, cmd_type: str, payload: Dict[str, Any]
    ) -> Tuple[WsCommandEntry, Optional[Dict[str, Any]]]:
        """指令先记账：新指令登记 running 并返回 ``(entry, None)``。

        同 ``command_id`` 已存在时**不执行**：已收敛的回放原终态帧
        （附 ``replayed: true``）；仍在 running 的回结构化冲突
        （``command_already_running``）。返回 ``(entry, prior_frame)``。
        """
        now = time.time()
        payload_json = json.dumps(payload or {}, ensure_ascii=False, default=str)[:_RESULT_JSON_MAX]
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO mobile_ws_commands"
                " (command_id, pairing_id, cmd_type, payload_json, status, created_at)"
                " VALUES (?, ?, ?, ?, 'running', ?)",
                (command_id, pairing_id, cmd_type, payload_json, now),
            )
            inserted = cursor.rowcount == 1
            row = self._conn.execute(
                "SELECT * FROM mobile_ws_commands WHERE pairing_id = ? AND command_id = ?",
                (pairing_id, command_id),
            ).fetchone()
        entry = self._toEntry(row)
        if inserted:
            # 新指令：已登记 running，调用方继续执行
            return entry, None
        if entry.status == "running":
            # 命中**他连接仍在跑**的同 id 指令：结构化冲突，不重复执行
            return entry, {
                "type": "error",
                "code": "command_already_running",
                "message": "同 command_id 的指令仍在执行中，已拦截本次重复发送",
            }
        # 已收敛：回放原终态帧（附 replayed，客户端据此知道不是新执行）
        terminal: Dict[str, Any]
        if entry.terminal_json:
            try:
                terminal = json.loads(entry.terminal_json)
            except Exception:  # noqa: BLE001 - 留档损坏退化为通用回放帧
                terminal = {"type": "error", "code": "journal_corrupted"}
        else:
            terminal = {"type": "error", "code": "journal_corrupted"}
        terminal["replayed"] = True
        return entry, terminal

    def settleCommand(self, command_id: str, pairing_id: str, terminal_frame: Dict[str, Any]) -> None:
        """指令终态收敛：把客户端可读的终态帧留档（供同 id 重放）。"""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE mobile_ws_commands SET status = 'settled', terminal_json = ?,"
                " settled_at = ? WHERE pairing_id = ? AND command_id = ?",
                (json.dumps(terminal_frame, ensure_ascii=False, default=str)[:_RESULT_JSON_MAX],
                 time.time(), pairing_id, command_id),
            )

    def settleRunningCommand(self, command_id: str, pairing_id: str,
                             terminal_frame: Dict[str, Any]) -> bool:
        """仅当命令仍在 ``running`` 时收敛（设备桥 B7 回执闭环），返回是否收敛。

        离线入队命令的回执到达时没有在等 future，靠本方法落终态；已收敛
        （如在线超时先行终态）或未知命令不动——迟到回执不得改写既有终态。
        """
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE mobile_ws_commands SET status = 'settled', terminal_json = ?,"
                " settled_at = ? WHERE pairing_id = ? AND command_id = ?"
                " AND status = 'running'",
                (json.dumps(terminal_frame, ensure_ascii=False, default=str)[:_RESULT_JSON_MAX],
                 time.time(), pairing_id, command_id),
            )
            return cursor.rowcount == 1

    def runningCommands(self, pairing_id: str) -> List[Dict[str, Any]]:
        """该设备仍在 ``running`` 的遥控命令 payload，按入队时间升序（B7）。

        离线入队的命令以此为准在设备回连时**重投递**（新 seq、同 command_id，
        端上按 command_id 去重）；已收敛的命令不在 running 集里，天然不重发。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM mobile_ws_commands WHERE pairing_id = ?"
                " AND status = 'running' AND cmd_type = 'device:execute'"
                " ORDER BY created_at ASC",
                (pairing_id,),
            ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            try:
                out.append(json.loads(row["payload_json"]))
            except Exception:  # noqa: BLE001 - 留档损坏的命令跳过（不阻断其余重投递）
                continue
        return out

    def _toEntry(self, row: sqlite3.Row) -> WsCommandEntry:
        return WsCommandEntry(
            command_id=str(row["command_id"]),
            pairing_id=str(row["pairing_id"] or ""),
            cmd_type=str(row["cmd_type"] or ""),
            status=str(row["status"]),
            terminal_json=row["terminal_json"],
            created_at=float(row["created_at"] or 0.0),
            settled_at=row["settled_at"],
        )


class LedgerWs:
    """账本化 WS 发送器：出站帧先落账（设备级单调 seq）再发送，帧内注入 seq/epoch。

    只代理 ``send_json``；接收侧仍用原始 websocket。``pong`` 这类连接级心跳
    不落账（无状态语义），直接透传。
    """

    #: 终态帧类型：出现即代表一条遥控指令的执行有了可回放的结果
    _TERMINAL_TYPES = ("chat:done", "chat:error", "chat:cancelled")
    #: 连接级心跳不落账
    _UNJOURNALED_TYPES = ("pong",)

    def __init__(self, ws: Any, ledger: MobileWsLedger, pairing_id: str, epoch: int):
        self._ws = ws
        self._ledger = ledger
        self._pairing_id = pairing_id
        self._epoch = epoch
        self._last_terminal: Optional[Dict[str, Any]] = None
        self._last_error: Optional[Dict[str, Any]] = None

    def markCommandStart(self) -> None:
        """新指令开始执行：清空本连接的回合结局暂存（防上一回合/旁路帧串账）。"""
        self._last_terminal = None
        self._last_error = None

    async def send_json(self, frame: Dict[str, Any]) -> None:
        frame_type = str(frame.get("type") or "")
        if frame_type in self._UNJOURNALED_TYPES:
            await self._ws.send_json(frame)
            return
        seq = self._ledger.appendEvent(self._pairing_id, self._epoch, frame)
        payload = dict(frame)
        payload["seq"] = seq
        payload["epoch"] = self._epoch
        if frame_type in self._TERMINAL_TYPES:
            self._last_terminal = payload
        elif frame_type == "error":
            self._last_error = payload
        await self._ws.send_json(payload)

    def commandOutcomeFrame(self) -> Optional[Dict[str, Any]]:
        """本条指令的结局帧：终态帧优先；只有 error 帧的失败回合也照实收敛
        （否则失败指令永远停在 running，同 id 重试只会得到 already_running）。"""
        return self._last_terminal if self._last_terminal is not None else self._last_error

    def lastSeq(self) -> int:
        return self._ledger.lastSeq(self._pairing_id)

    def commandPriorFrame(self, command_id: str, cmd_type: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """指令记账：新指令返回 None；重复指令返回应答帧（原终态回放/运行中冲突）。"""
        _, prior = self._ledger.beginCommand(command_id, self._pairing_id, cmd_type, payload)
        return prior

    def settleCommand(self, command_id: str, terminal_frame: Dict[str, Any]) -> None:
        self._ledger.settleCommand(command_id, self._pairing_id, terminal_frame)

    def __getattr__(self, name: str):
        """其余属性透传原始 websocket（receive 等不经账本）。"""
        return getattr(self._ws, name)


# 进程级单例（DCL + RLock，仓规）
_ledger_instance: Optional[MobileWsLedger] = None
_ledger_lock = threading.RLock()


def getMobileWsLedger() -> MobileWsLedger:
    global _ledger_instance
    if _ledger_instance is not None:
        return _ledger_instance
    with _ledger_lock:
        if _ledger_instance is None:
            _ledger_instance = MobileWsLedger()
        return _ledger_instance


def resetMobileWsLedger() -> None:
    """重置单例（测试专用；换库文件的测试先改 env 再 reset）。"""
    global _ledger_instance
    with _ledger_lock:
        _ledger_instance = None
