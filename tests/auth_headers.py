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


def bearerHeaders(sub: str = "probe-user", **claims: Any) -> Dict[str, str]:
    """对齐本轮密钥，再签一枚真 token 并包成请求头（`sub` 即租户键 user_id）。

    **这一句 `pinJwtSecret()` 是本仓唯一的身份取数不变式**：签发侧与验签门必须读同一把
    密钥的"当时值"。此前 `bearerHeaders` 只签不对齐，于是任何在 import 期签头的档都会在
    别人对齐之后变成「刚签的令牌被自己拒」（现算 6 档 11 处模块级签头、合跑 26 条红、
    另有单档单跑即红 2 条，红形同为 401 —— 见
    `docs/04-plans/记忆面测试密钥作用域工单_2026-10-27.md`）。幂等 ⇒ 已对齐时零开销。

    这里同时退役了 `signedBearerHeaders`：对齐塞进签名口之后，它就是本函数的第二个名字，
    而第二个名字等于第二个事实源（教义第 6/7 条）。
    """
    # 走模块对象调用，不用模块级再导出的那个函数对象："这一轮是哪把密钥"的答案只有
    # `auth.currentJwtSecretKey()` 一处，判据要断也断这一处（不再各读各的副本）。
    from neurova.api import auth as auth_mod

    pinJwtSecret()
    token = auth_mod.create_access_token(data={"sub": sub, **claims})
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
    # 路由级身份门：`requireIdentityForMemoryFace` 这类门不是 `get_current_user*` 命名，
    # 但它在记忆面上是**唯一**真正生效的那道（2026-10-26 点单甲，读写一律要凭证）。
    # 名单是白名单式的手抄，靠命名前缀猜门漏了它，于是记忆面整族 401——
    # 而"整族 401"看起来像"鉴权更严"，很容易被当成环境噪声放过去。
    # 取法：`auth.py` 自己那份闭集（`MEMORY_IDENTITY_GATES`）一处声明，这里只读不抄。
    for fn in getattr(auth_mod, "MEMORY_IDENTITY_GATES", ()):
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

    `include_router` 之后，FastAPI 0.141 起把挂进来的路由器收成一条
    `_IncludedRouter`（`path`/`methods`/`routes` 全为 None，真表在被挂路由器自己的
    `.routes` 上，必要时再往下还有一层）。只看顶层 `app.routes` 会漏掉**整个被挂路由器**
    的依赖——本函数曾因此在记忆面上返回空集，`overrideIdentity` 退回"全打"，
    而记忆面真正的门是路由级的 `requireIdentityForMemoryFace`，它恰好不在全打名单里，
    于是整族 401。

    拿不到就返回空集——调用方据此退回"全打"，宁可慢也不漏。
    """
    found = set()
    stack = list(getattr(app, "routes", []) or [])
    visited = set()
    while stack:
        node = stack.pop()
        if id(node) in visited:
            continue
        visited.add(id(node))
        call = getattr(node, "call", None)
        if call is not None:
            found.add(call)
        stack.extend(getattr(node, "dependencies", []) or [])
        # `_IncludedRouter`：真表在被挂路由器自己的 `.routes` 上（可能还有一层嵌套）
        inner = getattr(node, "original_router", None)
        if inner is not None:
            stack.extend(getattr(inner, "routes", []) or [])
        for sub in getattr(node, "routes", None) or ():
            stack.append(sub)
        dep = getattr(node, "dependant", None)
        if dep is not None:
            stack.extend(getattr(dep, "dependencies", []) or [])
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


#: ── 本轮签名密钥的唯一事实源 ────────────────────────────────────────────────
#: 生产侧 `neurova/api/auth.py:175` 把密钥烘在模块全局，签发（`create_access_token`）
#: 与验签（`verify_access_token` 与各身份门）都读**自己模块字典**里的那一份。
#: 于是只要进程里出现过第二份 auth 模块字典（`deps` 再导出的身份门、夹具重载、
#: 别的档改了全局），两侧就各持一把密钥 —— 形态恰好是"本档刚签发的令牌被自己拒"：
#: `401 Invalid or expired token`，而单跑与邻档合跑都绿。
#:
#: 判据侧的处置不许是"每个档各自把密钥抄一遍"（那是第二份、第三份事实源，
#: 台面上谁先跑谁说了算），也不许给生产加兜底（教义第 1 条：症状挪走，故障还在）。
#: 收成这一处：**这一轮用的是哪把密钥**，由这里回答一次；令牌在用例内现签。
#:
#: 为什么认"函数对象的 `__globals__`"而不是逐个模块名：门是函数对象，它读的是
#: 自己被定义时绑定的那份模块字典。改 `auth.JWT_SECRET_KEY` 对一份已经分叉出去的
#: 字典无效 —— 那正是本仓反复踩红的那个缺口。
#:
#: 可达性边界（不假装能管别人）：已经**导出的名字**（`from neurova.api.auth import
#: JWT_SECRET_KEY`）拿到的是那一刻的字符串，这里改不到它；本仓判据面没有这种写法，
#: 将来有了它自己会红，不会被静默放过。
_TEST_SECRET = "test_secret_key_shared_by_the_identity_gates_0123456789"

#: 身份门名册：`auth` 与 `deps` 两侧的同名对象都要打（`deps` 那份是再导出，
#: 同一对象只打一次 —— 但名字表要保持宽，将来多一条入口时这里自动跟上）。
_GATE_NAMES = ("strictIdentityGate", "get_current_user", "get_current_userWithQueryToken",
               "get_optional_user", "get_optional_userWithQueryToken",
               "get_current_user_or_default", "verify_access_token")


def _signingGates() -> list:
    """当前仓内**全部**读密钥的入口函数对象（运行时现值，不抄名单）。"""
    from neurova.api import auth as auth_mod
    from neurova.api import deps as deps_mod

    found, seen = [], set()
    for module in (auth_mod, deps_mod):
        for name in _GATE_NAMES:
            fn = getattr(module, name, None)
            if callable(fn) and id(fn) not in seen:
                seen.add(id(fn))
                found.append(fn)
    return found


def pinJwtSecret(secret: str = _TEST_SECRET) -> str:
    """把本轮密钥对齐到 `secret`，返回它。

    对齐的落点是**环境变量 `NEUROVA_JWT_SECRET`**，不是模块全局：生产侧的签发与验签
    都走唯一取用口 `auth.currentJwtSecretKey()`（运行时读环境变量）。原先这里逐个改写
    `auth.JWT_SECRET_KEY` 与各身份门 `__globals__` 里的同名全局，那是在测试里替生产
    补一个它本该有的前提——取用口上线后，改全局对签发/验签**一个字都不生效**，
    反而会读出一把谁都不用的"第三把密钥"（实测 10 格 `InvalidSignatureError`）。

    幂等：已经是这一把时什么都不做。返回值的用途是链式取用；
    但**不要在导入期烘一枚令牌** —— 令牌属于"这一轮"，不属于"这个进程"。
    """
    import os

    from neurova.api import auth as auth_mod

    if auth_mod.currentJwtSecretKey() != secret:
        os.environ["NEUROVA_JWT_SECRET"] = secret
    return secret

