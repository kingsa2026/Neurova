"""企业微信 access_token 单源（gettoken URL/提前失效/失效码）。

自建应用回调面（wecom.py）与微信客服面（wechat_auth.py）各自持有 HTTP
执行（aiohttp 异步 / requests 同步），但 token 的 URL 构造、响应解析、
提前失效秒数与"哪些 errcode 视为 token 失效"必须只有一份定义——
两处各写一遍就会在其中一处放宽（教义第 6 条）。
"""
from __future__ import annotations

import time
from typing import Any, Dict, Tuple

WECOM_API_BASE = "https://qyapi.weixin.qq.com"
WECOM_TOKEN_URL = f"{WECOM_API_BASE}/cgi-bin/gettoken"

#: token 实际有效期 7200s；提前 300s 判失效，给刷新留安全窗口
TOKEN_EARLY_EXPIRY_SECONDS = 300

#: 官方"access_token 无效/已过期"错误码——命中即强制刷新并重试一次
INVALID_TOKEN_ERRCODES = frozenset({40014, 42001})


def buildTokenUrl(corpid: str, corpsecret: str) -> str:
    return f"{WECOM_TOKEN_URL}?corpid={corpid}&corpsecret={corpsecret}"


def parseTokenPayload(payload: Dict[str, Any]) -> Tuple[str, float]:
    """解析 gettoken 响应 → (access_token, 失效时刻 epoch)。

    errcode 非 0 或缺 access_token 抛 ValueError（调用方按认证失败记账）。
    """
    if payload.get("errcode") not in (None, 0):
        raise ValueError(f"WeCom token refresh failed: {payload}")
    token = str(payload.get("access_token") or "")
    if not token:
        raise ValueError("WeCom token refresh failed: empty access_token")
    expireIn = int(payload.get("expires_in") or 7200)
    return token, time.time() + expireIn - TOKEN_EARLY_EXPIRY_SECONDS
