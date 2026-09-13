"""RDP 直连会话提供者（CUA Phase 3 扩展 RS-4，用户授权的既有机器）

把用户已授权、且已安装 neurova-guest-agent 的远程机器当作会话后端——**不造池、
不 spawn**：agent 动作走该机器的 guest agent（控制面 HTTP），RDP 凭据只用于人工
查看/接管。凭据走现有凭据分桶（platform="rdp"：host/port/token）。

fail-closed：无授权端点即拒（不凭空连机器）。destroy 是 no-op——绝不关停用户真机。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from neurova.core.logger import get_logger
from neurova.computer_use.session_pool import DesktopSession, SessionProvider

logger = get_logger(__name__)

_RDP_PLATFORM = "rdp"


class RdpDirectProvider(SessionProvider):
    """既有远程机器（预装 guest agent）的直连提供者。

    Args:
        endpoint_resolver: user_id → {host, port, token} 解析器；默认从凭据分桶读。
    """

    def __init__(self, endpoint_resolver: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None):
        self._resolve = endpoint_resolver or self._resolve_from_credentials

    @staticmethod
    def _resolve_from_credentials(user_id: str) -> Optional[Dict[str, Any]]:
        try:
            from neurova.web_reach.credentials import get_credential_store

            creds = get_credential_store().platform_credentials(user_id, _RDP_PLATFORM) or {}
            if creds.get("host"):
                return {
                    "host": creds["host"],
                    "port": int(creds.get("port") or 8765),
                    "token": creds.get("token") or "",
                }
        except Exception as e:  # noqa: BLE001
            logger.debug("RDP 凭据解析失败（user=%s）: %s", user_id, e)
        return None

    def create(self, user_id: str) -> DesktopSession:
        ep = self._resolve(user_id)
        if not ep or not ep.get("host"):
            raise RuntimeError(f"用户 {user_id} 未授权 RDP 直连桌面端点")
        host = str(ep["host"])
        port = int(ep.get("port") or 8765)
        token = str(ep.get("token") or "")
        logger.info("RDP 直连会话: %s → %s:%s", user_id, host, port)
        return DesktopSession(
            session_id=f"rdp-{user_id}-{host}",
            base_url=f"http://{host}:{port}",
            token=token,
            user_id=user_id,
        )

    def destroy(self, session: DesktopSession) -> None:
        # 绝不关停/改动用户既有机器——仅释放本侧引用
        logger.debug("RDP 直连会话归还（不触碰远端）: %s", session.session_id)
