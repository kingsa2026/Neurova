"""
移动设备配对系统

功能:
1. 生成配对码 + 二维码 — 手机扫码配对
2. 确认配对 — 设备端使用配对码完成认证
3. WS Token 颁发 — 配对成功后生成 WebSocket 连接凭证
4. 用户隔离 — 所有配对数据按 user_id 隔离
5. 配对码过期 — 默认 5 分钟 TTL
6. 配对管理 — 列表/撤销

使用方式:
    manager = get_mobile_pairing_manager()
    code = manager.generate_pairing_code(user_id="user123")
    result = manager.confirm_pairing(code, device_info={"platform": "ios"})
"""

import hashlib
import hmac
from neurova.core.logger import get_logger
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)

# 配对码有效期（秒）
PAIRING_CODE_TTL = 300  # 5 分钟


class PairingStatus(str, Enum):
    """配对状态"""

    PENDING = "pending"  # 等待确认
    CONFIRMED = "confirmed"  # 已确认
    EXPIRED = "expired"  # 已过期
    REVOKED = "revoked"  # 已撤销


@dataclass
class PairingSession:
    """配对会话"""

    code: str  # 6位数字配对码
    user_id: str  # 用户ID
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0  # 过期时间戳
    status: PairingStatus = PairingStatus.PENDING
    device_info: Dict[str, Any] = field(default_factory=dict)
    ws_token: Optional[str] = None  # WebSocket Token
    pairing_id: str = ""  # 配对ID

    def __post_init__(self):
        if not self.expires_at:
            self.expires_at = self.created_at + PAIRING_CODE_TTL
        if not self.pairing_id:
            self.pairing_id = secrets.token_hex(8)

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def is_valid(self) -> bool:
        return self.status == PairingStatus.PENDING and not self.is_expired

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pairing_id": self.pairing_id,
            "code": self.code,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "status": self.status.value,
            "device_info": self.device_info,
            "ws_token": self.ws_token,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PairingSession":
        return cls(
            code=data["code"],
            user_id=data["user_id"],
            created_at=data.get("created_at", 0.0),
            expires_at=data.get("expires_at", 0.0),
            status=PairingStatus(data.get("status", "pending")),
            device_info=data.get("device_info", {}),
            ws_token=data.get("ws_token"),
            pairing_id=data.get("pairing_id", ""),
        )


@dataclass
class PairingResult:
    """配对结果"""

    success: bool
    pairing_session: Optional[PairingSession] = None
    error_message: str = ""
    ws_token: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "pairing_session": self.pairing_session.to_dict() if self.pairing_session else None,
            "error_message": self.error_message,
            "ws_token": self.ws_token,
        }


class MobilePairingManager:
    """
    移动设备配对管理器

    管理配对码生成、确认、撤销和 WS Token 颁发。
    所有操作按 user_id 隔离。
    """

    def __init__(self, secret_key: str = ""):
        self._secret_key = secret_key or secrets.token_hex(32)
        self._sessions: Dict[str, PairingSession] = {}  # code -> session
        self._user_sessions: Dict[str, List[str]] = {}  # user_id -> [code]
        self._ws_tokens: Dict[str, PairingSession] = {}  # ws_token -> session

    def generate_pairing_code(self, user_id: str) -> PairingSession:
        """
        生成配对码

        参数:
            user_id: 用户ID

        返回:
            PairingSession: 配对会话
        """
        code = self._generate_unique_code()
        session = PairingSession(
            code=code,
            user_id=user_id,
        )

        # 存储会话
        self._sessions[code] = session
        if user_id not in self._user_sessions:
            self._user_sessions[user_id] = []
        self._user_sessions[user_id].append(code)

        logger.info("Generated pairing code %s for user %s", code, user_id)
        return session

    def confirm_pairing(
        self,
        code: str,
        device_info: Optional[Dict[str, Any]] = None,
    ) -> PairingResult:
        """
        确认配对

        参数:
            code: 配对码
            device_info: 设备信息

        返回:
            PairingResult: 配对结果
        """
        session = self._sessions.get(code)

        if not session:
            return PairingResult(
                success=False,
                error_message="Invalid pairing code",
            )

        if session.is_expired:
            session.status = PairingStatus.EXPIRED
            return PairingResult(
                success=False,
                error_message="Pairing code expired",
            )

        if session.status != PairingStatus.PENDING:
            return PairingResult(
                success=False,
                error_message=f"Pairing code already {session.status.value}",
            )

        # 更新会话
        session.status = PairingStatus.CONFIRMED
        if device_info:
            session.device_info = device_info

        # 颁发 WS Token
        ws_token = self._issue_ws_token(session)
        session.ws_token = ws_token

        logger.info("Pairing confirmed for code %s, user %s", code, session.user_id)
        return PairingResult(
            success=True,
            pairing_session=session,
            ws_token=ws_token,
        )

    def get_pairing_by_code(self, code: str) -> Optional[PairingSession]:
        """根据配对码获取配对会话"""
        return self._sessions.get(code)

    def list_user_pairings(self, user_id: str) -> List[PairingSession]:
        """列出用户的所有配对会话"""
        codes = self._user_sessions.get(user_id, [])
        sessions = []
        for code in codes:
            session = self._sessions.get(code)
            if session:
                sessions.append(session)
        return sessions

    def revoke_pairing(self, user_id: str, pairing_id: str) -> bool:
        """
        撤销配对

        参数:
            user_id: 用户ID（用于权限验证）
            pairing_id: 配对ID

        返回:
            bool: 是否成功撤销
        """
        # 查找用户的配对会话
        codes = self._user_sessions.get(user_id, [])
        for code in codes:
            session = self._sessions.get(code)
            if session and session.pairing_id == pairing_id:
                session.status = PairingStatus.REVOKED
                # 移除 WS Token
                if session.ws_token and session.ws_token in self._ws_tokens:
                    del self._ws_tokens[session.ws_token]
                    session.ws_token = None
                logger.info("Pairing %s revoked for user %s", pairing_id, user_id)
                return True
        return False

    def verify_ws_token(self, token: str) -> Optional[PairingSession]:
        """
        验证 WS Token

        参数:
            token: WebSocket Token

        返回:
            PairingSession: 配对会话，无效返回 None
        """
        session = self._ws_tokens.get(token)
        if not session:
            return None

        # 检查配对状态
        if session.status != PairingStatus.CONFIRMED:
            return None

        return session

    def _generate_unique_code(self) -> str:
        """生成唯一的6位数字配对码"""
        while True:
            code = f"{secrets.randbelow(1000000):06d}"
            if code not in self._sessions:
                return code

    def _issue_ws_token(self, session: PairingSession) -> str:
        """颁发 WebSocket Token"""
        # 使用 HMAC 签名生成 token
        message = f"{session.pairing_id}:{session.user_id}:{time.time()}"
        signature = hmac.new(
            self._secret_key.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()

        token = f"{session.pairing_id}:{signature}"
        self._ws_tokens[token] = session
        return token


# 单例管理
_mobile_pairing_manager: Optional[MobilePairingManager] = None


def get_mobile_pairing_manager(secret_key: str = "") -> MobilePairingManager:
    """获取移动设备配对管理器单例"""
    global _mobile_pairing_manager
    if _mobile_pairing_manager is None:
        _mobile_pairing_manager = MobilePairingManager(secret_key)
    return _mobile_pairing_manager


def reset_mobile_pairing_manager():
    """重置移动设备配对管理器单例（用于测试）"""
    global _mobile_pairing_manager
    _mobile_pairing_manager = None
