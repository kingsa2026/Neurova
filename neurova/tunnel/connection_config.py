"""配对连接方式配置 —— 「手机从哪条路回连」的唯一配置源（档一，2026-11-19 拍板）。

面板三选一背后的四种模式（字面量单源在此，前端 `pairingStates.ts` 镜像）：

- ``auto``   存量行为：env 的广播地址 / 中继变量照旧生效（存量部署不被悄悄换道）。
- ``direct`` 强制入站地址：忽略 env 广播地址、不配中继——有公网 IP/端口转发或纯内网时用。
- ``custom`` 用户自备反代入口（Cloudflare Tunnel、自建 nginx/Caddy 等）。本仓只
  **接受并探测地址**，不集成第三方隧道二进制（设计方案 §1 已裁的边界内）。
- ``relay``  自建中继：`neurova/relay` 部署在用户自己的服务器上，对外地址来自
  隧道路由 `/t/<routeId>`（设计方案 §3.3）。

持久化在数据根 `tunnel/connection_config.json`（随数据根走，多实例互不串）。
准入令牌是机密：落盘与既有凭证同域，**读口只回掩码**，日志不碰。
"""
from __future__ import annotations

import json
import threading
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlsplit

from neurova.core.logger import get_logger
from neurova.tunnel import protocol

logger = get_logger(__name__)

#: 模式字面量单源。``auto`` 必须排首位——未做选择的数据根就是它（存量行为不变）。
CONNECTION_MODES = ("auto", "direct", "custom", "relay")

_MODE_LABELS = {
    "auto": "auto（跟随环境配置）",
    "direct": "direct（强制入站地址）",
    "custom": "custom（自定义对外地址）",
    "relay": "relay（自建中继）",
}

_LOCK = threading.RLock()


def configFilePath():
    from pathlib import Path

    from neurova.core.data_root import dataPath

    # dataPath() 回 str（agent.py 里只喂了 hashlib）——这里要拼子路径，显式转 Path
    return Path(dataPath("tunnel")) / "connection_config.json"


def _readRaw() -> Dict[str, Any]:
    path = configFilePath()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # noqa: BLE001 - 坏档按"没配过"处理，但要点名
        logger.warning("连接方式配置文件损坏，按未配置处理：%s", e)
        return {}
    return raw if isinstance(raw, dict) else {}


def _writeRaw(raw: Dict[str, Any]) -> None:
    path = configFilePath()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


def _maskToken(token: str) -> str:
    if not token:
        return ""
    return "••••" + token[-4:]


def _validRemoteUrl(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in ("http", "https", "ws", "wss") and bool(parts.netloc)


def getConnectionConfig() -> Dict[str, Any]:
    """读口：令牌只回掩码与在场标记，全文不出门。"""
    with _LOCK:
        raw = _readRaw()
    token = str(raw.get("relay_enrollment_token") or "")
    return {
        "mode": raw.get("mode") or "auto",
        "custom_advertised_url": str(raw.get("custom_advertised_url") or ""),
        "relay_url": str(raw.get("relay_url") or ""),
        "relay_enrollment_token_masked": _maskToken(token),
        "has_relay_enrollment_token": bool(token),
        "updated_at": raw.get("updated_at") or "",
    }


def setConnectionConfig(mode: str, customAdvertisedUrl: Optional[str] = None,
                        relayUrl: Optional[str] = None,
                        relayEnrollmentToken: Optional[str] = None) -> Dict[str, Any]:
    """写配置并校验。``None``＝保持现值（部分更新），显式传 ``""``＝清空。

    校验按**模式**咬合：custom 必须有合法 http(s) 对外地址；relay 必须有
    中继地址与准入令牌。非法即 ValueError，由 API 面映射成 422（fail-fast，
    不静默回落——填错的地址发出去，手机扫了只能失败一次）。
    """
    if mode not in CONNECTION_MODES:
        raise ValueError(f"未知连接方式 mode={mode!r}（须为 {'/'.join(CONNECTION_MODES)}）")

    with _LOCK:
        raw = _readRaw()
        customUrl = raw.get("custom_advertised_url") or "" if customAdvertisedUrl is None \
            else customAdvertisedUrl.strip()
        relay = raw.get("relay_url") or "" if relayUrl is None else relayUrl.strip()
        token = raw.get("relay_enrollment_token") or "" if relayEnrollmentToken is None \
            else relayEnrollmentToken.strip()

        for label, url in (("custom_advertised_url", customUrl), ("relay_url", relay)):
            if url and not _validRemoteUrl(url):
                raise ValueError(f"{label} 必须是 http/https/ws/wss 的完整地址：{url!r}")

        if mode == "custom" and not customUrl:
            raise ValueError("custom 模式必须提供 custom_advertised_url（http/https 对外地址）")
        if mode == "relay":
            if not relay:
                raise ValueError("relay 模式必须提供 relay_url（自建中继地址）")
            if not token:
                raise ValueError("relay 模式必须提供 relay_enrollment_token（准入令牌）")

        from datetime import datetime

        raw.update({
            "mode": mode,
            "custom_advertised_url": customUrl,
            "relay_url": relay,
            "relay_enrollment_token": token,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })
        _writeRaw(raw)
    return getConnectionConfig()


def effectiveAdvertisedBaseUrl() -> str:
    """配对链路实际对外广播的地址（``_wsOrigin`` 的第二优先级来源）。

    - custom → 用户自备地址；
    - direct / relay → 空串（前者走入站，后者的地址来自隧道路由，不广播）；
    - auto → env `NEUROVA_ADVERTISED_BASE_URL`（存量行为）。
    """
    mode = _readRaw().get("mode") or "auto"
    if mode == "custom":
        return str(_readRaw().get("custom_advertised_url") or "")
    if mode in ("direct", "relay"):
        return ""
    from neurova.core import config

    return (config.get("NEUROVA_ADVERTISED_BASE_URL") or "").strip()


def effectiveRelaySettings() -> Tuple[str, str, bool]:
    """出站隧道 agent 的生效三元组 `(relayUrl, enrollmentToken, configured)`。

    relay 模式读持久化值；direct/custom 模式**不配中继**（用户选了别的路，env 里
    配了也不启用——选了哪条路就走哪条路）；auto 回落 env（存量行为：配了 env
    中继的部署不因这次改动丢通道）。
    """
    mode = _readRaw().get("mode") or "auto"
    if mode == "relay":
        raw = _readRaw()
        relayUrl = str(raw.get("relay_url") or "")
        token = str(raw.get("relay_enrollment_token") or "")
        return relayUrl, token, bool(relayUrl and token)
    if mode in ("direct", "custom"):
        return "", "", False
    from neurova.core import config

    relayUrl = (config.get(protocol.RELAY_URL_ENV) or "").strip()
    token = (config.get(protocol.ENROLLMENT_TOKEN_ENV) or "").strip()
    return relayUrl, token, bool(relayUrl and token)


def buildAgentFromSettings():
    """按生效配置造出站 agent（`tunnelStatus().configured` 跟着走）。"""
    from neurova.tunnel.agent import TunnelAgent, stableInstanceId

    relayUrl, token, _configured = effectiveRelaySettings()
    return TunnelAgent(relayUrl=relayUrl, enrollmentToken=token,
                       instanceId=stableInstanceId())


async def applyConnectionConfig() -> Dict[str, Any]:
    """落盘后重建出站 agent 并热替换——面板改完立即生效，不必重启进程。

    旧 agent 先 stop（控制连接/重连任务收尸），新 agent 按 `start()` 的既有
    语义挂到当前事件循环上（disabled 态只置状态、不派任务）。
    """
    from neurova.tunnel.agent import getTunnelAgent, setTunnelAgent

    old = getTunnelAgent()
    if old is not None:
        await old.stop()
    agent = buildAgentFromSettings()
    setTunnelAgent(agent)
    agent.start()
    logger.info("连接方式已更新：mode=%s relay_configured=%s",
                getConnectionConfig()["mode"],
                agent.tunnelStatus()["configured"])
    return getConnectionConfig()
