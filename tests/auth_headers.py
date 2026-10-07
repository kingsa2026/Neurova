# -*- coding: utf-8 -*-
"""测试面共用的 Bearer 凭证 helper。

存在的理由是一条本仓反复踩过的口径：**不要在端点判据里"绕过身份门"**。
`dependency_overrides` 只能替换端点实际依赖的那个函数（同名两份的历史见
`api/deps.py:16` 的注释），而且它把"凭证链是否走得通"这一整段跳过了——
2026-10-08 记忆面写操作收口（P3-12）后，写请求必须带凭证，override 身份
已不足以满足那道门。这里的 helper 签的是**生产同一个函数**产出的真 JWT，
所以测试覆盖到的那条链和用户在浏览器里走的那条是同一条。

用法：`TestClient(app, headers=bearerHeaders("u1"))`——挂在 client 上，
该夹具内所有请求自动带证；要模拟"匿名"就别传。
"""

from __future__ import annotations

from typing import Any, Dict

from neurova.api.auth import create_access_token


def bearerHeaders(sub: str = "probe-user", **claims: Any) -> Dict[str, str]:
    """签发一枚真 token 并包成请求头（`sub` 即租户键 user_id）。"""
    token = create_access_token(data={"sub": sub, **claims})
    return {"Authorization": f"Bearer {token}"}
