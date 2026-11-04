"""/metrics 端点暴露策略（P2-7）

背景（Issue #57）：`/metrics` 列在 `api/global_auth.py` 的 `PUBLIC_EXACT_PATHS`
里 → 全局鉴权中间件放行，加上后端监听 0.0.0.0，抓取面在网络上是**完全敞开**的
（无鉴权、无限流、无来源限制）。公开确实是运维抓取（Prometheus scrape）的需求，
但"公开"不该等于"谁来都给"。

三档策略（`NEUROVA_METRICS_ACCESS`）：

- ``local``（默认）: 仅回环来源（127.0.0.0/8、::1）可抓，其余 403。
  跨 Pod Prometheus 抓取需显式设 ``public`` 或 ``token``。
- ``public``: 任何来源可抓（旧默认，现需显式选择）。
- ``token``: 需 `Authorization: Bearer <token>` 或 `X-Metrics-Token`，
  token 取 `NEUROVA_METRICS_TOKEN`。选它就必须配 token，否则视为未配置。

**fail-closed 的边界**：token 模式未配 token 时拒绝全部（而不是放行全部）——
安全开关配错了应当"抓不到"而不是"全敞开"。local 模式取不到 client IP 时同样
拒绝（无法证明来源即不信任）。

默认值取 local（审计 2026-11-04 P2-1）：此前默认 public，容器绑 0.0.0.0 时
指标面匿名可读。默认只信回环，跨机抓取必须成为一次显式配置。
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


HEALTH_ACCESS_ENV = "NEUROVA_HEALTH_ACCESS"
HEALTH_TOKEN_ENV = "NEUROVA_HEALTH_TOKEN"


def _modeFromEnv(env_name: str, default: str = MODE_LOCAL) -> str:
    """读三档策略；未设置用默认，非法值告警后回落默认（不因拼错把门拆掉）。"""
    raw = (os.environ.get(env_name) or "").strip().lower()
    if not raw:
        return default
    if raw in _VALID_MODES:
        return raw
    logger.warning(
        "%s 取值非法 %r（合法: %s），按 %s 处理",
        env_name, raw, "/".join(_VALID_MODES), default,
    )
    return default


def get_metrics_access_mode() -> str:
    """读取 /metrics 暴露模式（每请求读取，便于测试与热切换）。"""
    return _modeFromEnv("NEUROVA_METRICS_ACCESS")


def get_metrics_token() -> str:
    """抓取令牌（token 模式用）。"""
    return (os.environ.get("NEUROVA_METRICS_TOKEN") or "").strip()


def get_health_access_mode() -> str:
    """读取 /health/detailed 暴露模式（与 metrics 同三档，默认 local）。"""
    return _modeFromEnv(HEALTH_ACCESS_ENV)


def get_health_token() -> str:
    return (os.environ.get(HEALTH_TOKEN_ENV) or "").strip()


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


def _check_access(
    client_host: Optional[str], headers: dict, effective: str,
    expected_token: str, token_header: str,
) -> tuple[bool, str]:
    if effective == MODE_PUBLIC:
        return True, "public"

    if effective == MODE_LOCAL:
        if _is_loopback(client_host):
            return True, "loopback"
        return False, "source not loopback"

    if effective == MODE_TOKEN:
        if not expected_token:
            # fail-closed：开关选了 token 却没配 token，拒绝而非放行
            return False, "token mode without configured token"
        provided = _extract_token(headers, token_header)
        if provided and _constant_time_eq(provided, expected_token):
            return True, "token"
        return False, "token mismatch"

    return False, "unknown-mode"


def check_metrics_access(
    client_host: Optional[str], headers: dict, mode: Optional[str] = None
) -> tuple[bool, str]:
    """判定是否放行抓取；reason 只进日志/测试，不返回给调用方。"""
    effective = (mode or get_metrics_access_mode()).lower()
    return _check_access(client_host, headers, effective, get_metrics_token(), "x-metrics-token")


def check_health_access(
    client_host: Optional[str], headers: dict, mode: Optional[str] = None
) -> tuple[bool, str]:
    """判定是否放行 /health/detailed；默认 local，跨机访问需显式 public/token。"""
    effective = (mode or get_health_access_mode()).lower()
    return _check_access(client_host, headers, effective, get_health_token(), "x-health-token")


def _extract_token(headers: dict, token_header: str = "x-metrics-token") -> str:
    """从 ASGI headers 或普通 dict 中取 token（大小写不敏感）。"""
    lowered = {}
    for key, value in (headers or {}).items():
        try:
            k = key.decode("latin-1") if isinstance(key, bytes) else str(key)
            v = value.decode("latin-1") if isinstance(value, bytes) else str(value)
        except Exception:  # noqa: BLE001
            continue
        lowered[k.lower()] = v

    direct = lowered.get(token_header, "")
    if direct:
        return direct.strip()

    authorization = lowered.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _constant_time_eq(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
