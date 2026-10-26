# -*- coding: utf-8 -*-
"""C1（P3-12 拍板"跨租户不可读"）：记忆面写类请求必须有**可验证身份**。

现状（2026-10-08 实测，比台账原描述更宽）：`get_current_user_or_default`
（`api/auth.py:636`）挂在 memory 包里 **11 个文件**上（不只 crud+eki），
无凭证时它返回 `_DEFAULT_USER`(:617) 即租户键 `default`——于是**匿名请求可以写**：
POST/PUT/DELETE 一路共 26 个 handler 今天都不需要任何身份就能落进共享 default 桶。
读侧匿名只落 default 曾是 2026-10-06 定的政策，本文件当年**不动**它；
2026-10-26 点单「甲」把它一起撤了（实测匿名可读走 24 行正文，而 `agent_wide=True`
让"只见 default 桶"这句从未被执行），判据随之改见
`testAnonymousReadIsNowRejectedToo`。要修的根因始终是：**回落身份被当成了身份**。

修法取单点：memory 包 11 个子模块全部 `from .base import router` 注册到**同一个
APIRouter**（`memory/base.py:22`），所以门挂在 router 级一处即可覆盖全门面，
不在 26 个 handler 上各补一遍判空（那正是 consumer-side guard 的形态）。

判据三条：
① 路由矩阵（行为）：枚举 app 上 `/api/v1/memory*` 的全部写类路由，无凭证必须 401。
   写"逐条列出路由"而不是"挑几条测"，是为了让**新加的写端点自动落入判据**——
   挑样子会变成"加了端点忘了加门"的温床。
② 反向一格：匿名**读**仍 200 且只见 default 桶（政策不许被顺手收紧，也不许被放宽）。
③ 门的名字只许来自 `auth.py` 里那份清单（结构守卫，防第五道门自己长出来）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests import ast_scan

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
AUTH_PY = REPO_ROOT / "neurova" / "api" / "auth.py"
MEMORY_PKG = REPO_ROOT / "neurova" / "api" / "endpoints" / "memory"

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MEMORY_PREFIX = "/api/v1/memory"

# 路径参数占位符需要一个能过 schema 校验的具体值（门的优先级高于 body 校验，
# 但路径参数属于请求解析的一部分，故仍要给出可转换的值）
_PATH_PARAM_FILL = re.compile(r"\{[^}]+\}")


@pytest.fixture(scope="module")
def appClient():
    """把**生产 memory router 本体**挂进一个 FastAPI 实例，并给它一份真的 app state。

    为什么不用整 app：本批要验的门挂在 `memory/base.py:22` 那个共享 router 上，
    挂本体即可全覆盖，且与 `tests/unit/api/test_governance_llm_retry.py` 同形
    （不是新造装配口径）。用整 app 反而要额外背 lifespan 与默认 Agent 装配。

    为什么必须自己装 state（本批改判加的前置）：原先没有 state 时读端点走的是
    `AGENT_NOT_INITIALIZED`，而 `crud.py` 当年把它**吞成 200 空列表**——于是
    `testAnonymousReadStillSeesOnlyDefaultBucket` 的 200 是假成功给的，"匿名读只看到
    default 桶"这半句从没真被测过（A/B 里它在基线绿、在本树红＝本批摘掉吞异常后才露出来）。
    这里给一个真 `MemoryManager`（落临时隔离库）而不是再造假 manager：作用域注入
    (`base.py:214 set_request_scope`) 与读面归属都得走生产实现才叫验到。
    """
    import tempfile
    import types
    from pathlib import Path

    from fastapi import FastAPI

    from neurova.api import app as appModule
    from neurova.api.endpoints.memory import router as memory_router
    from tests.cognitive_body_store import bodyManager

    app = FastAPI()
    app.include_router(memory_router, prefix="/api/v1/memory")

    root = Path(tempfile.mkdtemp(prefix="memWriteGate-"))
    manager = bodyManager(root, agentId="default")
    manager.remember(content="default 桶里的那条记忆", id="gate_row")
    agent = types.SimpleNamespace(memory_manager=manager, agent_id="default")
    state = types.SimpleNamespace(agents={"default": agent}, get_agent=lambda: agent)
    originalGetAppState = appModule.get_app_state
    appModule.get_app_state = lambda: state
    # raise_server_exceptions=False：本判据要的是"匿名请求能不能通过门"，
    # 不是"handler 里抛什么"——门缺失时后端会 5xx，那同样是"放行匿名"的证据；
    # 让它抛出来只会把红变成异常，归因反而更难。
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        appModule.get_app_state = originalGetAppState
        manager.close()


def _memoryWriteRoutes(appClient):
    """枚举生产 memory router 的写路由（不依赖 FastAPI 的路由表内部形状）。

    FastAPI 0.142.2 起 `include_router` 挂进去的是 `_IncludedRouter`
    （`path`/`methods`/`routes` 全为 None，真表在它自己的 `original_router` 里）。
    与其依赖那个私有形状，不如直接读 `memory.router.routes` 再自己拼挂载前缀——
    反正"挂载前缀 + 路由路径"就是 app 实际对外暴露的那一条。
    """
    from neurova.api.endpoints.memory import router as memory_router

    routes = []
    for route in memory_router.routes:
        methods = set(getattr(route, "methods", None) or ()) & WRITE_METHODS
        path = getattr(route, "path", "")
        if methods and path:
            routes.append((sorted(methods), _PATH_PARAM_FILL.sub("1", MEMORY_PREFIX + path)))
    return routes


def testEveryMemoryWriteRouteRejectsAnonymous(appClient):
    """① 记忆面**每一条**写路由都必须拒匿名（不是"抽查几条绿了"）。"""
    routes = _memoryWriteRoutes(appClient)
    assert routes, "没枚举到任何写路由——判据退化为恒真，先修枚举再谈绿灯"

    offenders = []
    for methods, concrete in routes:
        for method in methods:
            resp = appClient.request(method, concrete)
            if resp.status_code != 401:
                offenders.append(f"{method} {concrete} → {resp.status_code}")

    assert not offenders, (
        f"{len(routes)} 条写路由里 {len(offenders)} 条放行了匿名请求"
        "（无凭证即写进共享 default 桶）：\n  - " + "\n  - ".join(offenders[:8])
    )


def testAnonymousReadIsNowRejectedToo(appClient):
    """② 读侧那一半 2026-10-26 随点单「甲」撤销，本格随之改判（改前提，不是放弱闸）。

    原判据写的是"匿名**读**仍 200 且只见 default 桶"，钉的是 2026-10-06 那条政策。
    撤销依据是两条实测：无凭证 `GET /api/v1/memory?agent_id=default` 返回 24 行正文
    （含他人用户域 9 行），而列表腿传 `agent_wide=True` ⇒ 后半句"只见 default 桶"
    在实现上从来没被执行过；`start_server.py` 默认 `0.0.0.0` 又把它送到同网段。

    另如实记一格：原判据的"只读到 default 桶"那半句**早就是恒真**——它读
    `row.get("user_id") or row.get("neuser_id")`，而 §6-425 之后投影里根本没有这两个键
    （归属身份刻意不上线上），`owner` 恒为 None ⇒ 该循环什么都没咬过。改判成 401 之后
    这半句不再需要，故一并删掉，不留一条不咬人的断言。
    """
    resp = appClient.get(f"{MEMORY_PREFIX}?limit=5")

    assert resp.status_code == 401, (
        f"记忆面读侧仍放行匿名（回落身份在 agent_wide 口径下等于没有身份）：{resp.status_code}"
    )


def _gatesDefinedInAuth():
    tree = ast.parse(AUTH_PY.read_text(encoding="utf-8"))
    return {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("get_current_user")
    }


def testGateNamesComeFromOneDeclaredList():
    """③ 门的名字有唯一清单，且清单里的门都真实存在（防"名字写了、实现没跟上"）。"""
    defined = _gatesDefinedInAuth()
    match = re.search(
        r"^MEMORY_IDENTITY_GATES[^=]*=\s*\(([^)]*)\)",
        AUTH_PY.read_text(encoding="utf-8"),
        re.M,
    )
    assert match, (
        "auth.py 没有 `MEMORY_IDENTITY_GATES` 清单——门的名字散落各处，"
        "第四道第五道门会自己长出来而无人核对（本批实测已存在四道）"
    )
    declared = {tok.strip().strip('"\'') for tok in match.group(1).split(",") if tok.strip()}
    assert declared <= defined, f"清单里声明了不存在的门：{sorted(declared - defined)}"
    assert declared == {"get_current_user", "get_current_user_or_default"}, (
        f"记忆面允许的门不再是两道（{sorted(declared)}）——本批的收口结论要重写"
    )


def testMemoryPackageUsesOnlyDeclaredGates():
    """④ 反向：memory 包用到的门必须都在清单内，**且 import 来源要对**。

    只比函数名会留一个洞：`from neurova.api.deps import get_current_user` 拿到的是
    `get_current_userWithQueryToken`（`deps.py:26` 的再导出），名字在清单内而语义
    不同——这正是本仓"override 打错对象静默不生效"那一族的成因。故按 (来源, 名字)
    二元组判。
    """
    declared = {"get_current_user", "get_current_user_or_default"}
    offenders = []
    # 枚举与解析走 tests/ast_scan 的共享预算（不私有 rglob + ast.parse——
    # 后者把判据成本绑在代码总量上，见 tests/unit/test_ci_ast_scan_budget_guard.py）。
    modules = list(ast_scan.parsedModules(MEMORY_PKG, ".py"))
    # 扫描根＝记忆面那个包，本判据的域就到它为止；这条下限让「根被改窄」露形而不是露出「零 offender」。
    assert len(modules) > 8, (
        f"扫描面现读 {len(modules)} 档（根＝{MEMORY_PKG}）——量级不对＝这条判据根本没在看记忆面端点")
    for path, tree in modules:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.endswith(("api.deps", "api/auth", "api.auth", "neurova.api.deps")):
                continue
            for alias in node.names:
                if not alias.name.startswith("get_current_user"):
                    continue
                src = "deps" if node.module.endswith("api.deps") else "auth"
                if alias.name not in declared:
                    offenders.append(f"{path.name}:{node.lineno} {src}.{alias.name}")
                elif alias.name in declared and src != "auth":
                    offenders.append(
                        f"{path.name}:{node.lineno} 从 {src} 导入 {alias.name}"
                        "（deps 那份是带 query token 的变体，名字相同语义不同）"
                    )
    assert not offenders, "记忆面的身份门不如清单：\n  - " + "\n  - ".join(offenders)
