"""/metrics 端点暴露策略（P2-7）

背景（Issue #57）：`/metrics` 列在 `api/global_auth.py` 的 `PUBLIC_EXACT_PATHS`
里 → 全局鉴权中间件放行，加上后端监听 0.0.0.0，抓取面在网络上是**完全敞开**的
（无鉴权、无限流、无来源限制）。公开确实是运维抓取（Prometheus scrape）的需求，
但"公开"不该等于"谁来都给"。

三档策略（`NEUROVA_METRICS_ACCESS`）：

- ``public``（默认）: 保持现状语义 —— 任何来源可抓。这是**向后兼容的默认值**：
  e2e 冒烟、CI、既有抓取配置都不受本次改动影响。
- ``local``: 仅回环来源（127.0.0.0/8、::1）可抓，其余 403。适合"后端监听 0.0.0.0
  但抓取只在同机/同 Pod"的部署。
- ``token``: 需 `Authorization: Bearer <token>` 或 `X-Metrics-Token`，
  token 取 `NEUROVA_METRICS_TOKEN`。选它就必须配 token，否则视为未配置。

**fail-closed 的边界**：token 模式未配 token 时拒绝全部（而不是放行全部）——
安全开关配错了应当"抓不到"而不是"全敞开"。local 模式取不到 client IP 时同样
拒绝（无法证明来源即不信任）。

默认值刻意选 public：本 PR 的定位是"把选择权交出来 + 把选择写进文档/测试"，
而不是替部署方改行为（突然 403 会打断所有人的抓取）。
"""

from __future__ import annotations

import ipaddress
import os
from typing import Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

MODE_PUBLIC = "public"
MODE_LOCAL = "local"
MODE_TOKEN = "token"
_VALID_MODES = (MODE_PUBLIC, MODE_LOCAL, MODE_TOKEN)

LOOPBACK_NETS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)


def get_metrics_access_mode() -> str:
    """读取 /metrics 暴露模式（每请求读取，便于测试与热切换）。

    未设置 → public（向后兼容）；非法值 → public 并告警（不因拼错把抓取打断，
    但必须留痕——静默兜底会让"我以为配成了 token"永远查不出来）。
    """
    raw = (os.environ.get("NEUROVA_METRICS_ACCESS") or "").strip().lower()
    if not raw:
        return MODE_PUBLIC
    if raw in _VALID_MODES:
        return raw
    logger.warning(
        "NEUROVA_METRICS_ACCESS 取值非法 %r（合法: %s），按 %s 处理",
        raw, "/".join(_VALID_MODES), MODE_PUBLIC,
    )
    return MODE_PUBLIC


def get_metrics_token() -> str:
    """抓取令牌（token 模式用）。"""
    return (os.environ.get("NEUROVA_METRICS_TOKEN") or "").strip()


def _is_loopback(host: Optional[str]) -> bool:
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        # IPv6 字面量去掉 zone id（fe80::1%eth0）后重试
        try:
            addr = ipaddress.ip_address(host.split("%", 1)[0])
        except ValueError:
            return host in ("localhost",)
    return any(addr in net for net in LOOPBACK_NETS)


def check_metrics_access(
    client_host: Optional[str], headers: dict, mode: Optional[str] = None
) -> tuple[bool, str]:
    """判定是否放行抓取。

    返回 (allowed, reason)；reason 只进日志/测试，不返回给调用方
    （避免向匿名抓取者泄漏策略细节）。
    """
    effective = (mode or get_metrics_access_mode()).lower()

    if effective == MODE_PUBLIC:
        return True, "public"

    if effective == MODE_LOCAL:
        if _is_loopback(client_host):
            return True, "loopback"
        return False, "source not loopback"

    if effective == MODE_TOKEN:
        expected = get_metrics_token()
        if not expected:
            # fail-closed：开关选了 token 却没配 token，拒绝而非放行
            return False, "token mode without NEUROVA_METRICS_TOKEN"
        provided = _extract_token(headers)
        if provided and _constant_time_eq(provided, expected):
            return True, "token"
        return False, "token mismatch"

    return True, "unknown-mode-fallback-public"


def _extract_token(headers: dict) -> str:
    """从 ASGI headers 或普通 dict 中取 token（大小写不敏感）。"""
    lowered = {}
    for key, value in (headers or {}).items():
        try:
            k = key.decode("latin-1") if isinstance(key, bytes) else str(key)
            v = value.decode("latin-1") if isinstance(value, bytes) else str(value)
        except Exception:  # noqa: BLE001
            continue
        lowered[k.lower()] = v

    direct = lowered.get("x-metrics-token", "")
    if direct:
        return direct.strip()

    authorization = lowered.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _constant_time_eq(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
