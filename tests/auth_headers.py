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

`overrideIdentity()` 是本文件第二件事，专治上面那句"只能替换端点实际依赖的那个函数"：
仓内身份入口有**两条策略**（严格头 / 可回退 `?access_token=`），两条都活着是刻意的
（资源标签端点发不出 Authorization 头），但于是每个夹具都得知道自己钉的是哪一个——
钉错了不报错，只是**静默不生效**，表现为"守卫没咬住"（比红更危险，见 `deps.py:16-24`）。
2026-10-08 §6-54 把角色门的取源改成严格门本体后，25 个只钉 `deps` 那份的文件同时露出，
就是这笔账。收口形态：一处 helper 把所有入口一起打上。
"""

from __future__ import annotations

import typing
from typing import Any, Callable, Dict

from neurova.api.auth import create_access_token


def bearerHeaders(sub: str = "probe-user", **claims: Any) -> Dict[str, str]:
    """签发一枚真 token 并包成请求头（`sub` 即租户键 user_id）。"""
    token = create_access_token(data={"sub": sub, **claims})
    return {"Authorization": f"Bearer {token}"}


def _identityEntryPoints() -> typing.List[Callable[..., Any]]:
    """当前仓内**全部**身份入口函数对象。取"运行时现值"而不是抄一份名单——
    入口再加一条时这里自动跟上，不需要哪个夹具记得改自己。"""
    from neurova.api import auth as auth_mod
    from neurova.api import deps as deps_mod

    names = []
    for mod in (auth_mod, deps_mod):
        for attr in ("get_current_user", "get_current_userWithQueryToken",
                     "get_current_user_or_default", "get_optional_user",
                     "get_optional_userWithQueryToken"):
            fn = getattr(mod, attr, None)
            if callable(fn):
                names.append(fn)
    # 去重但保留顺序：deps 那份是 auth 那份的再导出，同一对象只打一次
    seen, ordered = set(), []
    for fn in names:
        if id(fn) not in seen:
            seen.add(id(fn))
            ordered.append(fn)
    return ordered


def _appDependencyCallables(app) -> set:
    """枚举这个 app 的路由图上**真正出现**的依赖函数对象。

    拿不到就返回空集——调用方据此退回"全打"，宁可慢也不漏。
    """
    found = set()
    stack = []
    for route in getattr(app, "routes", []) or []:
        dep = getattr(route, "dependant", None)
        if dep is not None:
            stack.append(dep)
        # 路由级 dependencies（APIRouter(dependencies=[...]) 挂的那一类）
        for d in getattr(route, "dependencies", []) or []:
            stack.append(d)
    while stack:
        node = stack.pop()
        call = getattr(node, "call", None)
        if call is not None:
            found.add(call)
        stack.extend(getattr(node, "dependencies", []) or [])
    return found


def overrideIdentity(app, identity: Any) -> None:
    """把身份替身打在**这个 app 真正依赖的**那些身份入口上。

    为什么"只打用到的"而不是"全打"：`create_app()` 返回的是**缓存实例**
    （`app.py:1320`），夹具往它的 `dependency_overrides` 上写，写的东西会活到下一个
    用例。早先一版 helper 无差别铺满所有入口，于是把这条缓存实例的污染面从 1 个门
    撑到 5 个门，跨文件顺序敏感的用例随之翻红（实测
    `test_consoleRunLedgerReadout.py` 两条在全量批跑里红、单跑绿）。
    现在按路由图取交集：既保住"override 必须打在端点实际依赖的那个对象上"这条
    （§6-54 一次暴露 25 个文件的成因），又不扩大共享实例上的残留面。
    """
    gates = _identityEntryPoints()
    referenced = _appDependencyCallables(app)
    targets = [fn for fn in gates if not referenced or fn in referenced]
    if not targets:
        targets = gates

    if callable(identity):
        # `async def` 的替身必须**原样**登记，让 FastAPI 自己去 await；
        # 拿同步 lambda 包一层会得到"返回协程对象的同步依赖"，FastAPI 不会 await 它，
        # 身份就变成 `<coroutine object>`——实测报 `'coroutine' object has no attribute 'get'`。
        import inspect

        provider: Callable[[], Any] = identity if inspect.iscoroutinefunction(identity) else (
            lambda: identity()
        )
    else:
        snapshot = dict(identity)
        provider = lambda: dict(snapshot)
    app.dependency_overrides.update({fn: provider for fn in targets})
