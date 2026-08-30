"""移动设备 QR 码扫码配对核心逻辑。

提供 MobilePairingManager 管理配对码生成 / 确认 / 撤销 / 校验：
- 6 位数字配对码，默认 5 分钟过期（可通过 ttl_seconds 调整）
- WS Token HMAC 签名验证（带撤销失效机制）
- 用户隔离（所有操作绑定 user_id）
"""

from __future__ import annotations

import hashlib
import hmac
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

# 默认签名密钥（仅用于本地校验；生产应通过环境变量注入）
_DEFAULT_SECRET = "neurova-mobile-pairing-secret"


class PairingStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass
class PairingSession:
    """一次配对会话（对应一个 6 位配对码）。"""

    code: str
    pairing_id: str
    user_id: str
    agent_id: str
    status: PairingStatus = PairingStatus.PENDING
    expires_at: float = 0.0
    confirmed_at: Optional[float] = None
    ws_token: Optional[str] = None
    device_name: str = "Unknown Device"
    device_type: str = "unknown"
    qr_data: str = ""
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.expires_at:
            self.expires_at = time.time() + 300

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "pairing_id": self.pairing_id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "status": self.status.value if isinstance(self.status, PairingStatus) else self.status,
            "expires_at": self.expires_at,
            "confirmed_at": self.confirmed_at,
            "device_name": self.device_name,
            "device_type": self.device_type,
            "qr_data": self.qr_data,
            "created_at": self.created_at,
        }


@dataclass
class PairingResult:
    """确认配对的返回结果。"""

    success: bool
    pairing_id: Optional[str] = None
    ws_token: Optional[str] = None
    user_id: Optional[str] = None
    error_message: Optional[str] = None


class MobilePairingManager:
    """移动设备配对管理器：生成配对码、确认配对、撤销配对、校验 WS Token。"""

    def __init__(
        self,
        ws_host: str = "localhost",
        ws_port: int = 9527,
        ttl_seconds: float = 300,
        secret_key: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        self.ws_host = ws_host
        self.ws_port = ws_port
        self.ttl_seconds = ttl_seconds
        self._secret = secret_key or _DEFAULT_SECRET
        self._sessions: Dict[str, PairingSession] = {}  # code -> session
        self._by_pairing_id: Dict[str, str] = {}  # pairing_id -> code
        self._revoked_tokens: set = set()

    # ---- 配对码生成 ----

    def generate_pairing_code(self, user_id: str, agent_id: str = "default", **kwargs: Any) -> PairingSession:
        code = self._new_code()
        session = PairingSession(
            code=code,
            pairing_id=f"pair-{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            agent_id=agent_id,
        )
        session.expires_at = time.time() + float(kwargs.get("ttl_seconds", self.ttl_seconds))
        session.qr_data = f"ws://{self.ws_host}:{self.ws_port}/mobile/ws?code={code}"
        self._sessions[code] = session
        self._by_pairing_id[session.pairing_id] = code
        return session

    def _new_code(self) -> str:
        while True:
            code = "".join(random.choices("0123456789", k=6))
            if code not in self._sessions:
                return code

    # ---- 配对确认 ----

    def confirm_pairing(self, code: str, device_info: Optional[dict] = None) -> PairingResult:
        session = self._sessions.get(code)
        if session is None:
            return PairingResult(success=False, error_message="无效的配对码 (code not found)")
        if session.status == PairingStatus.CONFIRMED:
            return PairingResult(success=False, error_message="配对码已被使用 (already confirmed)")
        if session.status == PairingStatus.REVOKED:
            return PairingResult(success=False, error_message="配对码已撤销 (revoked)")
        if session.is_expired():
            session.status = PairingStatus.EXPIRED
            return PairingResult(success=False, error_message="配对码已过期 (code expired)")

        session.status = PairingStatus.CONFIRMED
        session.confirmed_at = time.time()
        if device_info and isinstance(device_info, dict):
            session.device_name = device_info.get("device_name", session.device_name)
            session.device_type = device_info.get("device_type", session.device_type)
        session.ws_token = self._issue_ws_token(session)
        return PairingResult(
            success=True,
            pairing_id=session.pairing_id,
            ws_token=session.ws_token,
            user_id=session.user_id,
        )

    # ---- 查询 ----

    def get_pairing_by_code(self, code: str) -> Optional[PairingSession]:
        return self._sessions.get(code)

    def list_user_pairings(self, user_id: str) -> List[PairingSession]:
        """返回该用户已确认的配对设备列表。"""
        return [
            s for s in self._sessions.values()
            if s.user_id == user_id and s.status == PairingStatus.CONFIRMED
        ]

    # ---- 撤销 ----

    def revoke_pairing(self, pairing_id: str, user_id: str) -> bool:
        code = self._by_pairing_id.get(pairing_id)
        if code is None:
            return False
        session = self._sessions.get(code)
        if session is None or session.user_id != user_id:
            return False
        session.status = PairingStatus.REVOKED
        if session.ws_token:
            self._revoked_tokens.add(session.ws_token)
        return True

    # ---- WS Token ----

    def _issue_ws_token(self, session: PairingSession) -> str:
        message = f"{session.user_id}:{session.pairing_id}:{int(time.time())}"
        signature = hmac.new(self._secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        return f"{message}:{signature}"

    def verify_ws_token(self, token: str) -> Optional[Dict[str, str]]:
        if not token or token in self._revoked_tokens:
            return None
        try:
            user_id, pairing_id, timestamp, signature = token.split(":")
            message = f"{user_id}:{pairing_id}:{timestamp}"
            expected = hmac.new(self._secret.encode(), message.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return None
            code = self._by_pairing_id.get(pairing_id)
            session = self._sessions.get(code) if code else None
            if session is None or session.status != PairingStatus.CONFIRMED:
                return None
            return {
                "user_id": user_id,
                "agent_id": session.agent_id,
                "pairing_id": pairing_id,
            }
        except (ValueError, KeyError, TypeError):
            return None

    # ---- 统计 / 状态 ----

    def get_statistics(self) -> Dict[str, Any]:
        now = time.time()
        return {
            "total": len(self._sessions),
            "pending": sum(1 for s in self._sessions.values() if s.status == PairingStatus.PENDING),
            "confirmed": sum(1 for s in self._sessions.values() if s.status == PairingStatus.CONFIRMED),
            "expired": sum(1 for s in self._sessions.values() if s.status == PairingStatus.EXPIRED),
            "revoked": sum(1 for s in self._sessions.values() if s.status == PairingStatus.REVOKED),
            "active_devices": sum(1 for s in self._sessions.values() if s.status == PairingStatus.CONFIRMED),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "generated_at": now,
        }


# 模块级单例（延迟初始化）
_shared_manager: Optional[MobilePairingManager] = None


def get_mobile_pairing_manager(**kwargs: Any) -> MobilePairingManager:
    """获取（或创建）共享的 MobilePairingManager。"""
    global _shared_manager
    if _shared_manager is None:
        _shared_manager = MobilePairingManager(**kwargs)
    return _shared_manager


def reset_mobile_pairing_manager() -> None:
    """重置共享实例（测试用）。"""
    global _shared_manager
    _shared_manager = None
