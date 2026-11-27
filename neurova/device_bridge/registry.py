# -*- coding: utf-8 -*-
"""在线设备连接登记（设备桥的"哪台手机现在连着、能做什么"单一事实源）。

生命周期：``mobile_websocket`` 建连（鉴权 + 账本包装完成）后 :meth:`register`，
连接 finally 里 :meth:`unregister`；``device:hello`` 到达后 :meth:`updateHello`
刷新能力快照与运行态。离线判定只认这里的在册行——**不回读** ``mobile_devices``
表（那是长期在册权威，online 是活连接叠加出的读数，两件事不合并）。

线程模型：登记/查询可能来自 WS 事件循环，也可能来自工具执行协程——统一
``threading.RLock`` 串行（对齐仓内 SQLite/单例纪律）。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "DeviceConnection",
    "DeviceConnectionRegistry",
    "getDeviceBridgeRegistry",
    "resetDeviceBridgeRegistry",
]


@dataclass
class DeviceConnection:
    """一条在线设备连接的活状态（不落库；断线即消失）。"""

    pairing_id: str
    user_id: str
    #: LedgerWs（出站帧先落账再发）。鸭子类型：只需 send_json/settleCommand/
    #: commandPriorFrame 三个成员，测试可替身。
    ledger_ws: Any
    connected_at: float = field(default_factory=time.time)
    platform: str = ""
    protocol_version: int = 0
    capabilities: frozenset = frozenset()
    app_state: str = ""

    def claims(self, action: str) -> bool:
        return action in self.capabilities


class DeviceConnectionRegistry:
    """pairing_id → 在线连接。键控与账本/在册库同源（pairing_id）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._connections: Dict[str, DeviceConnection] = {}

    def register(self, pairingId: str, userId: str, ledgerWs: Any) -> DeviceConnection:
        """登记一条在线连接（同 pairing 重连即 newest-wins 顶替）。"""
        conn = DeviceConnection(pairing_id=pairingId, user_id=userId, ledger_ws=ledgerWs)
        with self._lock:
            self._connections[pairingId] = conn
        logger.info("device bridge register: %s (user=%s)", pairingId, userId)
        return conn

    def unregister(self, pairingId: str, *, expected: Any = None) -> None:
        with self._lock:
            current = self._connections.get(pairingId)
            if current is None or (expected is not None and current.ledger_ws is not expected):
                return
            self._connections.pop(pairingId, None)

    def updateHello(self, pairingId: str, *, platform: str = "",
                    capabilities: Optional[List[str]] = None,
                    appState: str = "", protocolVersion: int = 0) -> bool:
        """刷新能力快照（WS 层已做词表校验；未登记的连接返回 False）。"""
        with self._lock:
            conn = self._connections.get(pairingId)
            if conn is None:
                return False
            conn.platform = platform
            conn.protocol_version = int(protocolVersion)
            conn.capabilities = frozenset(str(c) for c in (capabilities or []))
            conn.app_state = appState
        return True

    def get(self, pairingId: str) -> Optional[DeviceConnection]:
        with self._lock:
            return self._connections.get(pairingId)

    def onlineForUser(self, userId: str) -> List[DeviceConnection]:
        """该用户的全部在线连接（注册表是 online 的唯一判定处）。"""
        with self._lock:
            conns = [c for c in self._connections.values() if c.user_id == userId]
        conns.sort(key=lambda c: c.connected_at)
        return conns

    def onlineCount(self) -> int:
        with self._lock:
            return len(self._connections)


# 进程级单例（DCL + RLock，仓规）
_registry_instance: Optional[DeviceConnectionRegistry] = None
_registry_lock = threading.RLock()


def getDeviceBridgeRegistry() -> DeviceConnectionRegistry:
    global _registry_instance
    if _registry_instance is not None:
        return _registry_instance
    with _registry_lock:
        if _registry_instance is None:
            _registry_instance = DeviceConnectionRegistry()
        return _registry_instance


def resetDeviceBridgeRegistry() -> None:
    """重置单例（测试专用；生产进程内连接登记随连接生命周期增减，不重置）。"""
    global _registry_instance
    with _registry_lock:
        _registry_instance = None
