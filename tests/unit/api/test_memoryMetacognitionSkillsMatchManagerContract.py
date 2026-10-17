# -*- coding: utf-8 -*-
"""元认知"技能"三面必须与 `MemoryManager` 的真签名对齐（批 79·D6 甲，§6-305 落地）。

改前实状（真 `create_app()` ＋ 真 JWT 实测，不是推断）：

    GET  /api/v1/memory/meta/skills      -> 500 "MemoryManager.meta_get_all_skills() got an
                                             unexpected keyword argument 'category'"
    POST /api/v1/memory/meta/skills/match -> 500 "MemoryManager.meta_match_skills() got an
                                             unexpected keyword argument 'top_k'"
    GET  /api/v1/memory/meta/skills/stats -> 200（对照：这一条一直是对的）

根因是一类，不是一条：端点把**自己声明的查询/请求参数**原样转给 manager，而 manager 那侧的实装
根本不收（`meta_get_all_skills(self)` 无参；`meta_match_skills(self, query)` 只收 query）。
`except Exception` 再把它包成 `APIError.internal` ⇒ 一个**永远 500 的路由**挂在 OpenAPI 上，
对外承诺"支持按分类和状态筛选"却一次都没通过。现有判据为什么没咬到：
`tests/unit/cognitive_layers/memory_layer/test_manager_full_delegation.py:333/339` 只在 **manager 层无参调用**，
端点那条腿没人走过。

取数口径说明（三处坑各避一次）：
- 签名对齐**按运行时 `inspect.signature` 判**，不按名字扫文本——`meta_get_all_skills` 这个名字在
  别处（别的 manager）有收 `category` 的同名实现，按词扫会误判（241／268 同族）；
- 身份用生产签 token 函数 `create_access_token`，不手工塞阈值；
- ④那格**设计成两侧都绿**：它证的是"这套 app 夹具与这三条路由所在的 router 是通的"，
  没有它，①②的红可能被读成装配坏了而不是签名错。
"""
from __future__ import annotations

import ast
import inspect
import io
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MEMORY_ENDPOINT_DIR = REPO_ROOT / "neurova" / "api" / "endpoints" / "memory"

#: 变量名 → 真身类型。端点里 `manager = get_memory_manager(...)` 拿到的就是这个类。
_MANAGER_ATTRS = ("manager", "mem_manager", "memory_manager")


def _headers():
    from neurova.api.auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token({'sub': 'd6-user', 'role': 'admin'})}"}


def _openapiFor(app, path: str):
    spec = app.openapi()
    return spec["paths"].get(path, {})


def test_metaSkillsListEndpointServesTwoHundred():
    """①行为格（本次要转绿）：`GET /memory/meta/skills` 不再必 500。

    改前实测 500，回包点名 `unexpected keyword argument 'category'`。
    """
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app

    with TestClient(create_app()) as client:
        resp = client.get("/api/v1/memory/meta/skills", headers=_headers())
    assert resp.status_code == 200, f"端点仍不自洽：{resp.status_code} {resp.text[:200]}"
    body = resp.json()
    assert body.get("code") == 0, f"回包不是成功码：{str(body)[:200]}"


def test_metaSkillsMatchEndpointServesTwoHundred():
    """②行为格（本次要转绿）：`POST /memory/meta/skills/match` 不再必 500（带不带 top_k 都一样）。

    改前两种请求体都是 500，都点名 `unexpected keyword argument 'top_k'`——因为 `top_k` 有默认值，
    端点**每次**都把它传下去。
    """
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app

    with TestClient(create_app()) as client:
        withTopK = client.post("/api/v1/memory/meta/skills/match",
                               json={"query": "记忆", "top_k": 3}, headers=_headers())
        withoutTopK = client.post("/api/v1/memory/meta/skills/match",
                                  json={"query": "记忆"}, headers=_headers())
    assert withTopK.status_code == 200, f"带 top_k 仍 500：{withTopK.text[:200]}"
    assert withoutTopK.status_code == 200, f"不带 top_k 仍 500：{withoutTopK.text[:200]}"


def test_noEndpointPassesArgumentsTheManagerRefuses():
    """③常驻契约格（本次要转绿）：memory 端点里 `manager.X(...)` 传的关键字，X 的签名必须收。

    这一格是把"同根因全命中点"变成会红的东西（改完不留着下一次又加一个不收的参数）。
    取数按运行时签名：`VAR_KEYWORD`（`**kwargs`）视为可收；方法不存在也算 offender。
    """
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    offenders = []
    for path in sorted(MEMORY_ENDPOINT_DIR.glob("*.py")):
        tree = ast.parse(io.open(path, encoding="utf-8").read())
        for fn in (n for n in tree.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            for call in (c for c in ast.walk(fn) if isinstance(c, ast.Call)):
                f = call.func
                if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                        and f.value.id in _MANAGER_ATTRS):
                    continue
                meth = getattr(MemoryManager, f.attr, None)
                if meth is None:
                    offenders.append((path.name, fn.name, f.attr, "MemoryManager 上没这个方法"))
                    continue
                sig = inspect.signature(meth)
                if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
                    continue
                allowed = set(sig.parameters) - {"self"}
                refused = {kw.arg for kw in call.keywords if kw.arg} - allowed
                if refused:
                    offenders.append((path.name, fn.name, f.attr, sorted(refused)))

    assert not offenders, f"这些端点在往 manager 传它不收的参数（每一次都是 500）：{offenders}"


def test_openapiNoLongerAdvertisesUnhonouredParameters():
    """⑤形状格（本次要转绿）：OpenAPI 不许再广告"做不到的参数"。

    删参数的正确形态是**从签名/模型里拿掉**（路由与请求体都不再广告它），
    而不是留着不消费——留着就是继续对外承诺一件不做的事（教义第 2 条"契约上说说、body 里不做"）。
    """
    from neurova.api.app import create_app

    app = create_app()
    listPath = _openapiFor(app, "/api/v1/memory/meta/skills")
    getOp = listPath.get("get", {})
    advertised = {p.get("name") for p in getOp.get("parameters", [])}
    assert "category" not in advertised and "status" not in advertised, \
        f"列表面仍广告它做不到的筛选参数：{sorted(a for a in advertised if a)}"

    ref = (_openapiFor(app, "/api/v1/memory/meta/skills/match").get("post", {})
           .get("requestBody", {}).get("content", {}).get("application/json", {})
           .get("schema", {}).get("$ref", ""))
    name = ref.rsplit("/", 1)[-1]
    schema = app.openapi().get("components", {}).get("schemas", {}).get(name, {})
    assert "top_k" not in schema.get("properties", {}), \
        f"请求模型 {name} 仍广告 top_k（manager 不收，传了必 500）"


def test_siblingStatsEndpointStillServes():
    """④对照格（设计成两侧都绿）：同一 router 的 `/meta/skills/stats` 今天就是 200。

    它的作用是排除"这三条路都不通＝夹具坏了"这种读法——①②的红必须是签名错，不是装配错。
    这条现在就该绿，不是漏红：它钉的是"同一条 router、同一套鉴权、同一个 manager 取法"可用。
    """
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app

    with TestClient(create_app()) as client:
        resp = client.get("/api/v1/memory/meta/skills/stats", headers=_headers())
    assert resp.status_code == 200, f"对照格也红了——那是装配问题不是签名问题：{resp.text[:200]}"
    assert resp.json().get("code") == 0
