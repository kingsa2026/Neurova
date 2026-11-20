# -*- coding: utf-8 -*-
"""工具调用账本（对照报告 B4-2 / 实施计划项 2：**先记账再执行、unknown 不重放**）。

解决什么问题：外部写类工具（发邮件/发消息/写版本库/写文件等）在超时、连接断、
5xx 这类**结果不可判定**场景下，调用方（模型）往往会原样重试——第二次执行就是
第二次真实副作用。Linger 的纪律是：动作身份先落账，结果未知时**保留账目、
封锁重放**，同 key 重试返回原结果或结构化拦截，而不是再次执行。

三层结构：
- ``ToolCallJournal``：SQLite 存储层（begin 幂等 / settle 终态 / get_by_key），
  库文件在数据根（``NEUROVA_TOOL_JOURNAL_DB`` 可覆盖），模式对齐
  ``agent_run_store``（RLock + WAL + 迁移链）；
- ``run()`` 编排层：begin → 命中 running/succeeded/failed/unknown 的分流 →
  执行 → settle；unknown 与 replayed 语义在这里实现；
- ``computeKey``：幂等键 = sha256(工具名 + 规范化参数 + 作用域)，
  作用域 = ``<request_user_id>:<session_id>``（键在会话内有效，跨会话不误伤）。

消费方：``ToolExecutor.execute``（tool_executor.py 单管道）——只读能力声明的
工具不记账（零开销），其余工具全部先记账。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "ToolCallJournal",
    "JournalEntry",
    "computeKey",
    "classifyFailure",
    "get_tool_call_journal",
    "reset_tool_call_journal",
]

#: 结果留档上限（超出截断；回放面只需要判定与主要载荷）
_RESULT_JSON_MAX = 64 * 1024
#: running 条目超过该时长仍无终态 → 视为前次执行结果未知（进程崩溃/丢电）
_STALE_RUNNING_SECONDS = 600.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_call_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idem_key TEXT NOT NULL UNIQUE,
    tool_name TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running',
    result_json TEXT,
    error_class TEXT,
    replay_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL DEFAULT 0,
    settled_at REAL
);
CREATE INDEX IF NOT EXISTS idx_tool_call_journal_key
    ON tool_call_journal(idem_key);
"""

# 迁移链（对齐 agent_run_store 的版本化惯例；v1 即全量 schema）
_MIGRATIONS = [_SCHEMA]


@dataclass(frozen=True)
class JournalEntry:
    """一条工具调用账目（不可变快照；status: running/succeeded/failed/unknown）。"""

    id: int
    idem_key: str
    tool_name: str
    scope: str
    status: str
    result_json: Optional[str]
    error_class: Optional[str]
    replay_count: int = 0
    created_at: float = 0.0
    settled_at: Optional[float] = None


def computeKey(tool_name: str, params: Dict[str, Any], scope: str) -> str:
    """幂等键 = sha256(工具名 + 规范化参数 + 作用域)。

    参数规范化：JSON 序列化按键排序（键序无关）；不可序列化值退化为 str()。
    作用域 = ``<request_user_id>:<session_id>``——键在会话内判重，跨会话不误伤。
    """
    try:
        canonical = json.dumps(params or {}, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001 - 不可序列化参数退化为字符串化
        canonical = str(params)
    raw = f"{tool_name}\n{canonical}\n{scope}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def classifyFailure(result: Optional[Dict[str, Any]] = None, exc: Optional[BaseException] = None) -> str:
    """失败分类：结果不可判定（超时/断连/限流/5xx 类）→ ``unknown``，否则 ``failed``。

    unknown 的后果由调用方（run 编排）执行：同 key 重试被封锁，不再产生第二次
    真实副作用。关键词保守列举——拿不准的一律按 failed（可回放、不封锁）。
    """
    text = ""
    if exc is not None:
        text = str(exc)
    elif isinstance(result, dict):
        text = str(result.get("error") or "")
    lowered = text.lower()
    markers = (
        "timeout", "timed out", "connection", "network", "unreachable",
        "rate limit", "overloaded", "temporarily unavailable", "reset by peer",
        "502", "503", "504",
    )
    if any(marker in lowered for marker in markers):
        return "unknown"
    return "failed"


class ToolCallJournal:
    """工具调用账本（每实例一个 SQLite 连接，RLock 串行写，WAL）。"""

    def __init__(self, db_path: Any = None, enabled: Optional[bool] = None):
        from neurova.core.data_root import get_data_root

        self.db_path = str(
            db_path
            or os.environ.get("NEUROVA_TOOL_JOURNAL_DB")
            or (get_data_root() / "tool_call_journal.db")
        )
        self.enabled = (
            enabled if enabled is not None else os.environ.get("NEUROVA_TOOL_JOURNAL", "1") != "0"
        )
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        with self._lock, self._conn:
            for step in _MIGRATIONS:
                self._conn.executescript(step)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── 存储层 ──────────────────────────────────────────────────────

    def begin(self, idem_key: str, tool_name: str, scope: str = "") -> JournalEntry:
        """登记一条 running 账目；同 key 已存在时返回**既有条目**（幂等）。"""
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO tool_call_journal"
                " (idem_key, tool_name, scope, status, created_at)"
                " VALUES (?, ?, ?, 'running', ?)",
                (idem_key, tool_name, scope, now),
            )
            row = self._conn.execute(
                "SELECT * FROM tool_call_journal WHERE idem_key = ?", (idem_key,)
            ).fetchone()
        return self._toEntry(row)

    def settle(
        self,
        entry_id: int,
        status: str,
        result_json: Optional[str] = None,
        error_class: Optional[str] = None,
    ) -> None:
        """收敛终态（succeeded/failed/unknown）；running 不可作为终态。"""
        if status == "running":
            raise ValueError("running 不是终态，不能 settle")
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE tool_call_journal SET status = ?, result_json = ?,"
                " error_class = ?, settled_at = ? WHERE id = ?",
                (status, result_json, error_class, time.time(), entry_id),
            )

    def get_by_key(self, idem_key: str) -> Optional[JournalEntry]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tool_call_journal WHERE idem_key = ?", (idem_key,)
            ).fetchone()
        return self._toEntry(row) if row is not None else None

    def hasUnknown(
        self,
        tool_names: Optional[frozenset] = None,
        scope: Optional[str] = None,
    ) -> bool:
        """是否存在 unknown 终态账目（可按工具名与作用域过滤）——只读判据。

        消费方：``computer_use.lane_mutex`` 的车道互斥——同作用域内某侧上一次
        外部写结果未知时，对侧车道拒绝执行，不在未知状态上叠加副作用。
        scope 传 None 表示不限作用域；传空串只匹配未带作用域的账目。
        """
        if not self.enabled:
            return False
        query = "SELECT 1 FROM tool_call_journal WHERE status = 'unknown'"
        args: list = []
        if tool_names:
            marks = ",".join("?" for _ in tool_names)
            query += f" AND tool_name IN ({marks})"
            args.extend(tool_names)
        if scope is not None:
            query += " AND scope = ?"
            args.append(scope)
        query += " LIMIT 1"
        with self._lock:
            row = self._conn.execute(query, tuple(args)).fetchone()
        return row is not None

    def _toEntry(self, row: sqlite3.Row) -> JournalEntry:
        return JournalEntry(
            id=int(row["id"]),
            idem_key=str(row["idem_key"]),
            tool_name=str(row["tool_name"]),
            scope=str(row["scope"] or ""),
            status=str(row["status"]),
            result_json=row["result_json"],
            error_class=row["error_class"],
            replay_count=int(row["replay_count"] or 0),
            created_at=float(row["created_at"] or 0.0),
            settled_at=row["settled_at"],
        )

    # ── 编排层 ──────────────────────────────────────────────────────

    async def run(
        self,
        idem_key: str,
        tool_name: str,
        scope: str,
        invoke: Callable[[], Any],
        is_success: Callable[[Dict[str, Any]], bool],
    ) -> Dict[str, Any]:
        """先记账再执行的编排入口（键由调用方经 ``computeKey`` 预计算）。

        - 新 key：begin(running) → 执行 → settle(succeeded/failed/unknown)；
        - 命中 succeeded/failed：**回放**原结果（附 ``replayed: true``），不执行；
        - 命中 unknown（含超时未收敛的 stale running）：**封锁重放**，返回
          ``code=tool_result_unknown`` 的结构化拦截，不执行；
        - 账本关闭（``enabled=False``）：直接执行，零拦截。
        """
        if not self.enabled:
            return await invoke()

        entry = self.begin(idem_key, tool_name, scope)

        if entry.status == "unknown" or (
            entry.status == "running" and (time.time() - entry.created_at) > _STALE_RUNNING_SECONDS
        ):
            # 结果未知（或前次执行未收敛即失联）：封锁重放，如实报告
            if entry.status == "running":
                self.settle(entry.id, "unknown", error_class="stale_running")
            return {
                "error": (
                    "工具调用结果未知：此前一次执行未能确认结果，"
                    "为避免重复副作用已拦截本次重复执行"
                ),
                "code": "tool_result_unknown",
                "journal_id": entry.id,
                "tool_name": tool_name,
            }
        if entry.status in ("succeeded", "failed"):
            replay: Dict[str, Any]
            if entry.result_json:
                try:
                    replay = json.loads(entry.result_json)
                except Exception:  # noqa: BLE001 - 留档损坏时退化为错误回放
                    replay = {"error": entry.error_class or "journal_corrupted"}
            else:
                replay = {"error": entry.error_class or "unknown"}
            if isinstance(replay, dict):
                replay["replayed"] = True
                with self._lock, self._conn:
                    self._conn.execute(
                        "UPDATE tool_call_journal SET replay_count = replay_count + 1"
                        " WHERE id = ?",
                        (entry.id,),
                    )
            return replay

        # 新账目：执行并收敛
        try:
            result = await invoke()
        except Exception as exc:  # noqa: BLE001 - 异常也必须收敛账目
            status = classifyFailure(exc=exc)
            self.settle(entry.id, status, error_class=type(exc).__name__)
            raise
        status = "succeeded" if is_success(result) else classifyFailure(result=result)
        try:
            result_json = json.dumps(result, ensure_ascii=False, default=str)[:_RESULT_JSON_MAX]
        except Exception:  # noqa: BLE001 - 不可序列化结果只留摘要
            result_json = json.dumps({"tool_name": tool_name}, ensure_ascii=False)
        self.settle(
            entry.id,
            status,
            result_json=result_json,
            error_class=None if status == "succeeded" else str((result or {}).get("error") or "")[:200],
        )
        return result


# ── 进程级单例（DCL + RLock，仓规） ──────────────────────────────────

_journal_instance: Optional[ToolCallJournal] = None
_journal_lock = threading.RLock()


def get_tool_call_journal() -> ToolCallJournal:
    global _journal_instance
    if _journal_instance is not None:
        return _journal_instance
    with _journal_lock:
        if _journal_instance is None:
            _journal_instance = ToolCallJournal()
        return _journal_instance


def reset_tool_call_journal() -> None:
    """重置单例（测试专用；换库文件的测试先改 env 再 reset）。"""
    global _journal_instance
    with _journal_lock:
        _journal_instance = None


# ── execute() 编排（从 tool_executor.execute 搬入，尺寸棘轮：执行器文件只减不增）──


async def executeWithJournal(executor: Any, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """ToolExecutor.execute 的完整编排（控制工具分支 + 记账 + 单工具管道委托）。

    executor 按鸭子类型取 ``_execute_single_tool`` / ``_result_is_success`` /
    ``_agent``——存在经 ``object.__new__`` 跳过 ``__init__`` 的构造路径
    （如 A6 测试），一律 ``getattr`` 兜底，不假设属性必然存在。
    """
    from neurova.context import tool_search as _ts

    if tool_name in ("tool_search", "tool_describe", "tool_call"):
        if tool_name == "tool_call":
            real_name = str((params or {}).get("name", ""))
            arguments = (params or {}).get("arguments") or {}
            if not real_name:
                return {"error": "tool_call 缺少 name 参数"}
            if real_name in _ts.CONTROL_TOOL_NAMES:
                return {"error": "tool_call 不能调用控制工具自身"}
            catalog_names = {e["name"] for e in _ts.get_active_catalog()}
            if real_name not in catalog_names:
                return {"error": f"工具 {real_name} 不在隐藏目录中（可能为直连工具，直接调用即可）"}
            return await _runJournaledCall(executor, real_name, arguments)
        return _ts.handle_control_tool(tool_name, params)

    return await _runJournaledCall(executor, tool_name, params)


async def _runJournaledCall(executor: Any, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    journal = get_tool_call_journal()
    if not journal.enabled or not _shouldJournal(executor, tool_name):
        return await executor._execute_single_tool(tool_name, params)
    scope = _journalScope(executor)
    key = computeKey(tool_name, params, scope)
    return await journal.run(
        key,
        tool_name,
        scope,
        invoke=lambda: executor._execute_single_tool(tool_name, params),
        is_success=getattr(executor, "_result_is_success", None) or (lambda result: True),
    )


def _shouldJournal(executor: Any, tool_name: str) -> bool:
    """只读能力声明的工具不记账（零开销）；未声明/未知工具按非只读记账。

    能力解析走 `tool_coordinator.resolveToolCapability` 单一入口（内置 + MCP）。
    """
    try:
        from neurova.agent.tool_coordinator import resolveToolCapability

        capability = resolveToolCapability(tool_name)
    except Exception:  # noqa: BLE001 - 能力面故障按保守侧（记账）处置
        return True
    if capability is not None and capability.readOnly:
        return False
    return True


def _journalScope(executor: Any) -> str:
    """账本作用域：<request_user_id>:<session_id>（键在会话内判重，跨会话不误伤）。"""
    agent = getattr(executor, "_agent", None)
    session_id = getattr(agent, "current_session_id", None) or ""
    try:
        from neurova.core.identity_context import get_request_user_id

        user_id = get_request_user_id() or "anonymous"
    except Exception:  # noqa: BLE001 - 身份面故障退化为匿名（账本仍按会话判重）
        user_id = "anonymous"
    return f"{user_id}:{session_id}"
