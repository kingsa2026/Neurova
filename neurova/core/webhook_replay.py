# -*- coding: utf-8 -*-
"""Webhook 重放去重账本（CORE-09）。

入站 Webhook 的 HMAC + 时效校验只回答「这份请求确实由密钥持有者在窗口内发出」，
回答不了「这份请求是否已经处理过」——窗口（默认 300s）内原样重放会再次触发
工作流。本模块提供**原子领取**：

- 重放键由**签名覆盖物**派生：trigger_id + 规范化时间戳 + payload 的 SHA-256。
  任一项被改动签名即失效，因此攻击者无法通过换 nonce/事件 ID 绕过；
- 领取走 SQLite `INSERT OR IGNORE`（主键 `(trigger_id, replay_key)`），
  并发同帧只有一个请求领取成功；
- 过期行按 TTL（2× 验签时效）在领取时顺手回收，账本不无界增长。

持久化的意义：进程重启不重置去重窗口，重启前发出的请求同样不能被重放。
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from neurova.core.data_root import get_data_root
from neurova.core.logger import get_logger

logger = get_logger(__name__)

REPLAY_DB_NAME = "webhook_replay.db"
# 2 × webhook_security 默认验签时效（300s）：超窗口的签名本就验不过，行可回收。
REPLAY_TTL_S = 900.0


class ReplayStoreUnavailable(RuntimeError):
    """去重账本不可读写——按显式 503 暴露，不在入口静默放行。"""


def replayDbPath() -> Path:
    """去重账本落点：数据根下绝对路径（测试与部署经 NEUROVA_DATA_DIR 注入）。"""
    return get_data_root() / REPLAY_DB_NAME


def computeReplayKey(trigger_id: str, timestamp: str, payload: bytes) -> str:
    """由签名覆盖物派生重放键（trigger_id + 时间戳 + 原始 payload）。"""
    digest = hashlib.sha256()
    digest.update(str(trigger_id).encode("utf-8"))
    digest.update(b"\x00")
    digest.update(str(timestamp).encode("utf-8"))
    digest.update(b"\x00")
    digest.update(payload)
    return digest.hexdigest()


def claimReplayKey(
    trigger_id: str, replay_key: str, *, now_s: float | None = None, ttl_s: float = REPLAY_TTL_S
) -> bool:
    """原子领取重放键：True＝首次（可派发），False＝已处理过（重放）。"""
    from neurova.core.database import short_transaction

    now = time.time() if now_s is None else float(now_s)
    try:
        with short_transaction(str(replayDbPath())) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS webhook_replay_keys ("
                " trigger_id TEXT NOT NULL,"
                " replay_key TEXT NOT NULL,"
                " created_at REAL NOT NULL,"
                " PRIMARY KEY (trigger_id, replay_key))"
            )
            conn.execute(
                "DELETE FROM webhook_replay_keys WHERE created_at < ?", (now - ttl_s,)
            )
            cur = conn.execute(
                "INSERT OR IGNORE INTO webhook_replay_keys"
                " (trigger_id, replay_key, created_at) VALUES (?, ?, ?)",
                (trigger_id, replay_key, now),
            )
            return cur.rowcount > 0
    except Exception as e:  # noqa: BLE001 - 账本故障必须显式暴露，不静默放行
        logger.error("webhook 重放去重账本不可用: %s", e)
        raise ReplayStoreUnavailable(str(e)) from e


def releaseReplayKey(trigger_id: str, replay_key: str) -> None:
    """释放领取（派发失败时调用，允许发送方合法重试同一签名请求）。"""
    from neurova.core.database import short_transaction

    try:
        with short_transaction(str(replayDbPath())) as conn:
            conn.execute(
                "DELETE FROM webhook_replay_keys WHERE trigger_id = ? AND replay_key = ?",
                (trigger_id, replay_key),
            )
    except Exception as e:  # noqa: BLE001 - 释放失败只留痕；原派发异常仍是主异常
        logger.warning("webhook 重放键释放失败（%s/%s）: %s", trigger_id, replay_key[:12], e)