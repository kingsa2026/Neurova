"""guest agent HTTP 客户端（宿主侧 remote 后端调用来宾守护进程）"""

from __future__ import annotations

import threading
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
        ownerId: 领用该来宾桌面的属主身份（W1a 端点登记用；空=调用链无可信
            身份，登记跳过、不臆造属主）
        tenantId: 属主租户段（调用链经租户单源解析所得；空时登记面回落 default）
    """

    def __init__(self, base_url: str, token: Optional[str] = None, timeout: float = 30.0,
                 ownerId: str = "", tenantId: str = ""):
        self._base_url = base_url.rstrip("/")
        self._ownerId = str(ownerId or "").strip()
        self._tenantId = str(tenantId or "").strip()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.Client(base_url=self._base_url, timeout=timeout, headers=headers)
        self._registered = False
        self._registerLock = threading.Lock()

    def health(self) -> bool:
        try:
            ok = bool(self._client.get("/health").json().get("ok"))
        except Exception:  # noqa: BLE001
            return False
        if ok:
            self._registerOnce()
        return ok

    def action(self, kind: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """执行一个来宾桌面动作，返回结构化结果（含 error 时为失败）。"""
        try:
            r = self._client.post("/action", json={"kind": kind, "params": params or {}})
            r.raise_for_status()
            out = r.json()
        except Exception as e:  # noqa: BLE001
            logger.warning("guest agent 调用失败 %s: %s", kind, e)
            return {"error": f"guest agent 不可达: {e}"}
        if not out.get("error"):
            # 首个动作成功处登记（此刻连接已被证实可用）
            self._registerOnce()
        return out

    def _registerOnce(self) -> None:
        """W1a：guest 端点登记（每客户端至多一次、fail-soft）。

        首次 health 成功或首个动作成功时向统一端点注册表登记 kind=guest；
        token 是引用不落明文——connectionRef 只存 base_url。无可信属主身份
        时跳过（不臆造租户/属主）；登记失败仅告警，绝不阻断来宾动作链路。
        """
        if self._registered:
            return
        with self._registerLock:
            if self._registered:
                return
            if not self._ownerId:
                logger.debug("guest 端点登记跳过：调用链无可信属主身份 (base_url=%s)",
                             self._base_url)
                self._registered = True  # 无身份是定局，不逐动作重试
                return
            try:
                from neurova.remote_exec.registry import (
                    KIND_GUEST,
                    RemoteEndpoint,
                    getRemoteEndpointRegistry,
                )

                registered = getRemoteEndpointRegistry().registerEndpoint(RemoteEndpoint(
                    endpointId="",
                    kind=KIND_GUEST,
                    name=f"guest:{self._base_url}",
                    ownerId=self._ownerId,
                    tenantId=self._tenantId or "default",
                    capabilities={"desktop": True},
                    connectionRef=self._base_url,
                    health="online",
                ))
                self._registered = True
                logger.info("guest 端点已登记: %s (endpoint=%s owner=%s tenant=%s)",
                            registered.name, registered.endpointId,
                            registered.ownerId, registered.tenantId)
            except Exception as exc:  # noqa: BLE001 - 登记失败不阻断来宾链路
                logger.warning("guest 端点登记失败（不阻断原链路）: %s", exc)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass
