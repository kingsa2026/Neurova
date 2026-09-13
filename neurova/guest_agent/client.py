"""guest agent HTTP 客户端（宿主侧 remote 后端调用来宾守护进程）"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class GuestAgentClient:
    """到来宾 neurova-guest-agent 的同步 HTTP 客户端（宿主在 to_thread 中调用）。

    Args:
        base_url: 如 http://127.0.0.1:8765
        token: 双向鉴权 token（None=不带）
        timeout: 秒
    """

    def __init__(self, base_url: str, token: Optional[str] = None, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.Client(base_url=self._base_url, timeout=timeout, headers=headers)

    def health(self) -> bool:
        try:
            return bool(self._client.get("/health").json().get("ok"))
        except Exception:  # noqa: BLE001
            return False

    def action(self, kind: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """执行一个来宾桌面动作，返回结构化结果（含 error 时为失败）。"""
        try:
            r = self._client.post("/action", json={"kind": kind, "params": params or {}})
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            logger.warning("guest agent 调用失败 %s: %s", kind, e)
            return {"error": f"guest agent 不可达: {e}"}

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass
