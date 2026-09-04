"""Provider 账单后台适配器（P1-13，OpenClaw provider-usage 启发）

各 provider 后台的账单/配额 API 差异大（鉴权头/路径/响应结构），
本模块按 base_url host 匹配内置适配；无适配的 host 记入 errors 跳过。

纪律：
- 只采集 ProviderConfig.usage_collection=True 且带 api_key 的 provider（默认关）；
- 采集是统计副路径：任何网络/解析失败进 errors，绝不抛给调用方；
- 凭证只在内存中使用（api_key 直接作为 Bearer 发往该 provider 自己的后台，
  不落日志、不进 raw JSON——raw 只存账单响应）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# host → fetch 工厂。fetch(provider) -> Dict 快照（plan/quota_remaining/
# currency/balance/window_days/trend...），结构不强制（raw JSON 全保留）。
_BUILTIN_ADAPTERS: Dict[str, Callable[[Any], Dict[str, Any]]] = {}


def _register_builtin(host: str):
    def deco(fn):
        _BUILTIN_ADAPTERS[host] = fn
        return fn

    return deco


@_register_builtin("api.deepseek.com")
def _fetch_deepseek(pc) -> Dict[str, Any]:
    """DeepSeek 后台余额：GET /user/balance（Bearer api_key）"""
    import httpx

    resp = httpx.get(
        "https://api.deepseek.com/user/balance",
        headers={"Authorization": f"Bearer {pc.api_key}"},
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    info = (data.get("balance_infos") or [{}])[0]
    return {
        "plan": "pay_as_you_go",
        "balance": info.get("total_balance"),
        "currency": info.get("currency"),
        "window_days": 30,
    }


@_register_builtin("api.siliconflow.cn")
def _fetch_siliconflow(pc) -> Dict[str, Any]:
    """硅基流动后台：GET /v1/user/info（Bearer api_key）"""
    import httpx

    resp = httpx.get(
        "https://api.siliconflow.cn/v1/user/info",
        headers={"Authorization": f"Bearer {pc.api_key}"},
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    return {
        "plan": data.get("status") or "unknown",
        "balance": data.get("balance"),
        "currency": "CNY",
        "window_days": 30,
    }


@_register_builtin("openrouter.ai")
def _fetch_openrouter(pc) -> Dict[str, Any]:
    """OpenRouter：GET /api/v1/key（Bearer api_key）"""
    import httpx

    resp = httpx.get(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {pc.api_key}"},
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    return {
        "plan": "credits",
        "quota_remaining": data.get("limit_remaining"),
        "currency": "USD",
        "window_days": 30,
    }


def _fetch_for_provider(pc) -> Callable[[], Dict[str, Any]]:
    """按 host 匹配内置适配，返回 fetch 函数；无适配抛 LookupError"""
    host = urlparse((pc.base_url or "").strip()).netloc.lower()
    factory = _BUILTIN_ADAPTERS.get(host)
    if factory is None:
        raise LookupError(f"provider {pc.id} 的 host 无内置账单适配: {host or '空'}")
    return lambda: factory(pc)


def sync_provider_usage(providers: List[Any]) -> Dict[str, Any]:
    """同步一轮 provider 账单快照（显式开启的才采）。

    Args:
        providers: ProviderConfig 列表（调用方决定 scope）

    Returns:
        {"snapshots": [...], "errors": [...]} —— 与采集器实例解耦，
        快照已落 SQLite，errors 含 provider_id/error/ts。
    """
    from neurova.core.provider_usage import (
        ProviderUsageCollector,
        install_provider_usage_collector,
    )

    collector = ProviderUsageCollector.get_installed() or install_provider_usage_collector()

    snapshots: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for pc in providers or []:
        # 默认关语义: 显式开启 + 有凭证才采集
        if not getattr(pc, "usage_collection", False):
            continue
        if not getattr(pc, "api_key", None):
            continue
        try:
            fetch = _fetch_for_provider(pc)
            collector.register_provider(pc.id, fetch)
        except LookupError as e:
            errors.append(
                {"provider_id": pc.id, "error": str(e), "ts": datetime.now().isoformat(timespec="seconds")}
            )
            continue

    collector.collect_all()
    snapshots = collector.get_collected_usage()
    return {"snapshots": snapshots, "errors": errors + collector.get_errors()}
