"""注入 write-ahead 账本（P1-6）。

解决窗口：注入内容（信封里的召回/反思/记忆/指引）此前只存在于当轮
ctx.context——进程崩在「模型已见、回复未落盘」之间时，事后无人知道
模型当时看到了什么。本账本在装配出口（orchestrator._finishContext，
先于上游模型调用）把**最终发出去的视图**落盘：write-ahead 语义 =
先落账、后进模型。

- 每会话一个 JSONL：``<data>/injection_ledgers/<session_id>.jsonl``，
  追加即落盘（每行一个注入视图，含 content 原文，字节级留痕）；
- 行结构：``{"seq","ts","kind","chars","hash","meta","content"}``，
  ``hash = sha256(content)`` 供恢复/审计侧完整性核验；
- ``verifyInjections`` 重算哈希比对，接进编排器 get_context_health
  的 injection_ledger 读数槽；
- 写失败诚实降级：返回 None 并记 warning，不阻断上下文构建；
- 体量治理：超过 COMPACTION_THRESHOLD 行时压缩保留最近
  COMPACTION_KEEP 行（每 COMPACTION_CHECK_INTERVAL 次追加检查一次，
  摊薄重写成本）。
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 压缩检查间隔与保留行数（测试可经 monkeypatch 调小）
COMPACTION_CHECK_INTERVAL = 500
COMPACTION_THRESHOLD = 2000
COMPACTION_KEEP = 1000

_LEDGER_LOCKS: Dict[str, threading.RLock] = {}
_LEDGER_LOCKS_GUARD = threading.Lock()


def ledgerPathFor(sessionId: str) -> Path:
    """会话账本文件路径（单会话单文件；sessionId 做文件名安全化）。"""
    from neurova.core.data_root import resolveDataPath

    safe = "".join(c for c in str(sessionId) if c.isalnum() or c in "-_")[:80] or "session"
    return resolveDataPath("injection_ledgers") / f"{safe}.jsonl"


def _lockFor(path: Path) -> threading.RLock:
    key = str(path)
    with _LEDGER_LOCKS_GUARD:
        lock = _LEDGER_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LEDGER_LOCKS[key] = lock
        return lock


def _contentHash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _readRows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            # 半行（崩溃截断）不炸读侧：跳过并由 verify 点名
            continue
    return rows


def recordInjection(sessionId: str, kind: str, content: str,
                    meta: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """追加一条注入视图（write-ahead：先落账、后进模型）。

    Returns:
        落账行（含 seq/hash）；入参不合法或落盘失败时返回 None（不抛，
        记账故障不阻断上下文构建——失败在读数与日志里点名）。
    """
    if not sessionId or content is None or content == "":
        return None
    path = ledgerPathFor(sessionId)
    lock = _lockFor(path)
    try:
        with lock:
            rows = _readRows(path)
            row = {
                "seq": (rows[-1]["seq"] + 1) if rows else 1,
                "ts": time.time(),
                "kind": str(kind or "view"),
                "chars": len(content),
                "hash": _contentHash(content),
                "meta": dict(meta or {}),
                "content": content,
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
            # 体量治理：每 CHECK_INTERVAL 次追加检查一次，达到阈值压缩保留最近 KEEP 行
            if row["seq"] % COMPACTION_CHECK_INTERVAL == 0 and len(rows) + 1 >= COMPACTION_THRESHOLD:
                keep = rows[-(COMPACTION_KEEP - 1):] + [row]
                tmp = path.with_suffix(".jsonl.tmp")
                tmp.write_text(
                    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep),
                    encoding="utf-8",
                )
                tmp.replace(path)
                logger.info("注入账本已压缩：保留最近 %d 行（会话 %s）", len(keep), sessionId)
            return row
    except Exception as e:  # noqa: BLE001 - 账本故障不阻断上下文构建
        logger.warning("注入账本落盘失败（会话 %s）: %s", sessionId, e)
        return None


def readInjections(sessionId: str) -> List[Dict[str, Any]]:
    """读全部账本行（半行/坏行跳过）。"""
    return _readRows(ledgerPathFor(sessionId))


def verifyInjections(sessionId: str) -> Dict[str, Any]:
    """完整性核验：重算每行 sha256 与行内 hash 比对（恢复/审计侧读数）。"""
    rows = _readRows(ledgerPathFor(sessionId))
    broken = [r.get("seq") for r in rows if _contentHash(str(r.get("content", ""))) != r.get("hash")]
    return {
        "rows": len(rows),
        "ok": len(rows) - len(broken),
        "broken": len(broken),
        "last_seq": rows[-1]["seq"] if rows else None,
        "last_error": None,
    }
