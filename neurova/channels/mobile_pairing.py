# -*- coding: utf-8 -*-
"""channels/mobile_pairing.py -- 统一到 api/endpoints/mobile_pairing.py

原始独立实现已合并到 neurova.api.endpoints.mobile_pairing。
此处保留数据类供 tests/test_mobile_pairing.py 使用，
MobilePairingManager 改为 re-export 以消除双实现。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class PairingStatus(str, Enum):
    """配对状态"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass
class PairingSession:
    """配对会话"""
    code: str
    pairing_id: str
    user_id: str
    agent_id: str
    device_name: str = ""
    device_type: str = "mobile"
    status: PairingStatus = PairingStatus.PENDING
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    confirmed_at: Optional[float] = None
    ws_token: Optional[str] = None
    qr_data: str = ""

    def __post_init__(self):
        if self.expires_at == 0.0:
            self.expires_at = time.time() + 300

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def is_valid(self) -> bool:
        return self.status == PairingStatus.CONFIRMED and not self.is_expired()


@dataclass
class PairingResult:
    """配对结果"""
    success: bool
    session: Optional[PairingSession] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Re-export MobilePairingManager from api/endpoints (统一实现)
# ---------------------------------------------------------------------------

try:
    from neurova.api.endpoints.mobile_pairing import MobileConnectionManager as MobilePairingManager  # noqa: F401
except ImportError:
    # Fallback: 如果 api/endpoints/mobile_pairing 不可用，提供最小占位
    class MobilePairingManager:  # type: ignore[no-redef]
        def __init__(self, **kwargs):
            self._pairing_sessions: Dict[str, PairingSession] = {}

        def generate_pairing_code(self, user_id: str, agent_id: str, **kwargs) -> PairingSession:
            code = "".join([str(int(time.time() * 1000 + i) % 10) for i in range(6)])
            session = PairingSession(
                code=code,
                pairing_id=f"pair-{uuid.uuid4().hex[:12]}",
                user_id=user_id,
                agent_id=agent_id,
            )
            self._sessions[code] = session
            return session


def get_mobile_pairing_manager(**kwargs) -> MobilePairingManager:
    return MobilePairingManager(**kwargs)


def reset_mobile_pairing_manager():
    pass
