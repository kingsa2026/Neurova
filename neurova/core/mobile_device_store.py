# -*- coding: utf-8 -*-
"""已配对设备的**在册权威**（设计方案 §4.8／§4.9／§10.2）。

这条库存在的理由是三个实测现状（2026-10-24 复核）：

1. `mobile_websocket` 的 token 分支只验 HMAC 签名与时效，**不查设备是否还在册**——
   `revoke_pairing` 删得掉记录，却拦不住设备随后重连，旧凭证在剩余窗口内照样连得上。
   「只写不读」的断点（AGENTS §2）在这里的表现是一个**安全动作不生效**。
2. 在册设备原先是模块级 dict，进程重启即清空：升级一次，用户配好的设备全部失联，
   而面板只会说「还没有已配对的设备」。
3. 原先「离线且配对超 24h 就删」会静默删除用户自己配的设备（§4.9 已裁：改长期在册，
   30 天无活动只给提醒位）。

状态口径（字面量）在 `neurova/tunnel/protocol.py`；本模块只放**持久化与投影**。
`online` 是活连接叠加出来的读数，进程重启后必然是 0 条——这正是它的语义，不落库。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.data_root import get_data_root
from neurova.core.db_migration import migrate as applyMigrations, register_migration
from neurova.core.logger import get_logger
from neurova.tunnel import protocol

logger = get_logger(__name__)

DOMAIN = "mobile_devices"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mobile_devices (
    pairing_id  TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    device_name  TEXT NOT NULL DEFAULT '',
    device_type  TEXT NOT NULL DEFAULT 'mobile',
    device_id    TEXT NOT NULL DEFAULT '',
    state        TEXT NOT NULL DEFAULT 'paired',
    token_epoch  INTEGER NOT NULL DEFAULT 0,
    paired_at    REAL NOT NULL DEFAULT 0,
    last_active  REAL NOT NULL DEFAULT 0,
    revoked_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_mobile_devices_user ON mobile_devices(user_id, state);
"""
register_migration(1, _SCHEMA, domain=DOMAIN)


def _migrateToV2(conn: sqlite3.Connection) -> None:
    """v2：设备身份的**验证材料**（§4.7 分层：接入凭证可续签，靠的是这一列）。

    存的是设备长期密钥的 SHA-256，不存明文：续签口要判"来的是不是这台设备"，
    而库被读走时不该顺手拿到可用的凭据。`challenge` 只是与这张 ticket 绑定的随机数，
    不构成公钥认证——本仓没在这里假装做了 E2E（设计方案 §4.5 把它排到 S3）。
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(mobile_devices)")}
    if "secret_hash" not in columns:
        conn.execute("ALTER TABLE mobile_devices ADD COLUMN secret_hash TEXT NOT NULL DEFAULT ''")


register_migration(2, _migrateToV2, domain=DOMAIN)


def defaultDbPath() -> Path:
    """默认库落点：数据根下的绝对路径（相对路径随 CWD 漂移，本仓已收口过一轮）。"""
    return get_data_root() / "mobile_devices.db"


def dbPathForNewStore() -> str:
    """新库实例的路径解析（env 优先，缺省落数据根）。单点，别处不再拼。"""
    return str(os.environ.get("NEUROVA_MOBILE_DEVICES_DB") or defaultDbPath())


def refuseSharedRootInTests(dbPath: str) -> None:
    """跑测期间不许把在册库落在**会话级数据根**——那是所有用例共用的一份库。

    为什么钉在构造处而不是夹具里：夹具的隔离靠"谁先拆"，实测读数是一条用例在自己的
    call 阶段拿到 `NEUROVA_MOBILE_DEVICES_DB=<unset>`、库回退到 `neurovaDataRoot-*`，
    于是前一档写的 `pair-c` 出现在后一档的设备列表里（表现成"设备数 2 ≠ 1"，
    而肇事者与受害者不是同一条用例，根因隔了好几拍）。落在构造处 ⇒ 红在**肇事那一拍**、
    带路径与用例名，谁都不用再猜。

    只认 env 这一条唯一解析入口，不设例外名单：真要在共享根上开库的（生产启动）
    本来就不在 pytest 里，`PYTEST_CURRENT_TEST` 不在时这条判定整体不成立。
    """
    currentTest = os.environ.get("PYTEST_CURRENT_TEST")
    if not currentTest:
        return
    root = Path(str(get_data_root())).resolve()
    resolved = Path(str(dbPath)).resolve()
    if root != resolved.parent and root not in resolved.parents:
        return
    raise AssertionError(
        "本条用例让在册设备库落在会话级共享数据根：" + str(resolved)
        + " | 用例：" + currentTest.split("::")[0]
        + " | 隔离只有一条通道：monkeypatch.setenv('NEUROVA_MOBILE_DEVICES_DB', "
          "str(tmp_path / 'mobile_devices.db')) 并 mp.resetDeviceRegistry()"
        + "（判定钉在构造处，红应落在肇事那一拍，而不是三拍之后的受害者读数）"
    )


def _hashSecret(deviceSecret: str) -> str:
    """设备长期密钥的落库形态：只存 SHA-256 摘要。

    明文一旦入库，"读出数据库"就等于"拿到全部设备的续签能力"——而这台库和会话记录、
    记忆体在同一个数据根下。摘要比对不需要明文（`verifyDeviceSecret` 比的是摘要）。
    """
    return hashlib.sha256(deviceSecret.encode("utf-8")).hexdigest()


class MobileDeviceStore:
    """在册设备库（每实例一条连接，`threading.RLock` 串行写，WAL——AGENTS §3）。"""

    def __init__(self, dbPath: Any = None) -> None:
        self.dbPath = str(dbPath or dbPathForNewStore())
        refuseSharedRootInTests(self.dbPath)
        Path(self.dbPath).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.dbPath, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        with self._lock, self._conn:
            applyMigrations(self._conn, DOMAIN)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001 - 关闭失败不该掩盖别的东西
                logger.warning("mobile 在册库关闭失败 path=%s", self.dbPath, exc_info=True)

    # ------------------------------------------------------------------ 写侧

    def register(self, *, pairingId: str, userId: str, deviceName: str,
                 deviceType: str = "mobile", deviceId: str = "",
                 deviceSecret: str = "") -> Dict[str, Any]:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO mobile_devices"
                " (pairing_id, user_id, device_name, device_type, device_id,"
                "  state, token_epoch, paired_at, last_active, revoked_at, secret_hash)"
                " VALUES (?,?,?,?,?,?,?,?,?,NULL,?)",
                (pairingId, userId, deviceName, deviceType, deviceId, "paired", 0, now, now,
                 _hashSecret(deviceSecret)),
            )
        return self.get(pairingId) or {}

    def verifyDeviceSecret(self, pairingId: str, deviceSecret: str) -> bool:
        """设备身份核验（续签用）。

        用 `hmac.compare_digest` 比哈希，不比明文——明文压根不入库（§4.7）。
        """
        row = self.get(pairingId)
        if not row or not deviceSecret:
            return False
        stored = row.get("secret_hash") or ""
        if not stored:
            return False
        return hmac.compare_digest(str(stored), _hashSecret(deviceSecret))

    def recordActivity(self, pairingId: str, at: Optional[float] = None) -> None:
        """唯一的活动时间写口（生产在消息循环里调；判据也经它推旧时间戳）。

        刻意**不**提供「测试专用」的第二条写口：夹具与生产走同一个入口，
        否则判据读的是影子路径，生产改了这个入口也测不出（形态 403）。
        """
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE mobile_devices SET last_active = ? WHERE pairing_id = ?",
                (at if at is not None else time.time(), pairingId),
            )

    def revoke(self, pairingId: str) -> Optional[int]:
        """解除 = 置 revoked **＋** 递增 token_epoch（后者才是"关掉之后再也连不上"那半）。

        返回新 epoch；设备不在册时返回 None——调用方不得把 None 读成"成功"。
        """
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT token_epoch FROM mobile_devices WHERE pairing_id = ?",
                (pairingId,),
            ).fetchone()
            if row is None:
                return None
            epoch = int(row["token_epoch"]) + 1
            self._conn.execute(
                "UPDATE mobile_devices SET state = 'revoked', token_epoch = ?, revoked_at = ?"
                " WHERE pairing_id = ?",
                (epoch, time.time(), pairingId),
            )
        return epoch

    # ------------------------------------------------------------------ 读侧

    def get(self, pairingId: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM mobile_devices WHERE pairing_id = ?", (pairingId,)
            ).fetchone()
        return dict(row) if row else None

    def isAdmissible(self, pairingId: str, epoch: Any = None) -> bool:
        """建连放行判定：**这台设备现在还在册吗**。

        `epoch` 给了就比较（凭证里带的那份必须等于在册那份）；
        不给就只判在册——撤销的效力由 epoch 那一半负责，两半都在这一处读。
        """
        row = self.get(pairingId)
        if row is None or row["state"] == "revoked":
            return False
        if epoch is not None and str(epoch) != str(row["token_epoch"]):
            return False
        return True

    def epochOf(self, pairingId: str) -> Optional[int]:
        row = self.get(pairingId)
        return None if row is None else int(row["token_epoch"])

    def listForUser(self, userId: str, livePairingIds: Optional[Any] = None,
                    now: Optional[float] = None) -> List[Dict[str, Any]]:
        """回该属主的在册设备，投影成面板要读的形状（状态投影也只在这一处）。"""
        live = set(livePairingIds or ())
        stamp = now if now is not None else time.time()
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM mobile_devices WHERE user_id = ? AND state != 'revoked'"
                " ORDER BY paired_at ASC",
                (userId,),
            ).fetchall()
        return [self.project(dict(r), isLive=r["pairing_id"] in live, now=stamp) for r in rows]

    @staticmethod
    def project(row: Dict[str, Any], *, isLive: bool, now: float) -> Dict[str, Any]:
        """把持久态叠加活连接，投成 M1b 的字面量状态（单一投影处，端点/前端不再各自拼）。"""
        lastActivity = float(row.get("last_active") or row.get("paired_at") or 0)
        idleSeconds = max(0.0, now - lastActivity)
        dormantDays = protocol.DEVICE_DORMANT_AFTER_DAYS
        if isLive:
            state = "online"
        elif idleSeconds >= dormantDays * 86400:
            state = "dormant"
        elif float(row.get("last_active") or 0) > 0 and row.get("state") == "paired":
            state = "offline"
        else:
            state = row.get("state") or "paired"
        return {
            "pairing_id": row["pairing_id"],
            "user_id": row["user_id"],
            "device_name": row["device_name"],
            "device_type": row["device_type"],
            "device_id": row["device_id"] or None,
            "paired_at": row["paired_at"],
            "last_active": lastActivity or None,
            "is_online": bool(isLive),
            "state": state,
            "dormant": state == "dormant",
            "token_epoch": int(row["token_epoch"]),
        }
