# -*- coding: utf-8 -*-
"""media router 路由顺序守卫 + 死模型清理锚定（台账 2026-09-11 第七节 ⑤/④）。

⑤ 根因家族（本会话已实锤两处）：字面段路由（/config、/batch-delete）注册在
参数路由 ``GET /{media_id}`` 之后会被其吞掉（404 "Media 'config' not found"）。
本文件两层守卫：

1. 探针首匹配：对每个字面段前缀（list/config/batch-delete/save/download/
   stats/cache，另加 memory/storage-path）用与 Starlette 相同的「注册顺序首匹配」
   语义断言解析到意图路由而非 ``/{media_id}``——未来新字面路由放错位置即红；
2. 结构规则：任何单段字面路由都不得注册在同方法单段参数路由（/{media_id}）之后。

已知值依赖碰撞（不属本守卫范围，登记报告）：GET /{media_id}/metadata 先于
/stats/{agent_id} 注册，故 agent_id 恰为 "metadata" 时 GET /stats/metadata 被
metadata 路由吞——media_id 为 "media-<hex>" 生成不可碰撞，前端无 /stats 消费。

④：MediaListRequest/MediaInfo/MediaStats 三个 Pydantic 模型全仓零引用
（grep py/ts/vue/tests），删除后以「符号不存在 + 路由表逐条不变 + list 响应
形状不变」锚定 import/行为零变化。GET /stats 单段端点按台账 ⑤ 有意不加：
前端无消费（getMediaStats 已移除且有测试锁），加了反而引入字面段。
"""

import asyncio

import pytest
from fastapi.routing import APIRoute

from neurova.api.endpoints import media as media_module


@pytest.fixture()
def store():
    media_module._media_store.clear()
    yield
    media_module._media_store.clear()


def _route_specs(router=None):
    """(path, methods frozenset) 序列，保持注册顺序。"""
    routes = (router or media_module.router).routes
    return [(r.path, frozenset(r.methods or ())) for r in routes if isinstance(r, APIRoute)]


def _first_match(specs, method, concrete_path):
    """复刻 Starlette 匹配语义：按注册顺序取第一个方法+全路径匹配的路由。"""
    import re

    for path, methods in specs:
        if method not in methods:
            continue
        regex = re.sub(r"{[^}]+}", "[^/]+", path)
        if re.fullmatch(regex, concrete_path):
            return path
    return None


def _literal_after_param_offenders(specs):
    """结构规则：单段字面路由注册在同方法单段参数路由之后 → 记违规。"""
    offenders = []
    for i, (path, methods) in enumerate(specs):
        segs = [s for s in path.split("/") if s]
        if len(segs) != 1 or segs[0].startswith("{"):
            continue
        for j in range(i):
            epath, emethods = specs[j]
            esegs = [s for s in epath.split("/") if s]
            if len(esegs) != 1 or not esegs[0].startswith("{"):
                continue
            if methods & emethods:
                offenders.append(f"{sorted(methods)} {path} 注册在参数路由 {epath} 之后（会被吞）")
    return offenders


# ---------------------------------------------------------------------------
# ⑤ 探针首匹配：字面段前缀必须解析到意图路由
# ---------------------------------------------------------------------------

PROBES = [
    # (method, concrete_path, expected_registered_path)
    ("GET", "/list", "/list"),
    ("GET", "/config", "/config"),
    ("PUT", "/config", "/config"),
    ("POST", "/save", "/save"),
    ("POST", "/batch-delete", "/batch-delete"),
    ("GET", "/download/media-abc123", "/download/{media_id}"),
    ("GET", "/stats/a1", "/stats/{agent_id}"),
    ("POST", "/cache/clear", "/cache/clear"),
    ("GET", "/memory/mem-1", "/memory/{memory_id}"),
    ("GET", "/storage-path/image", "/storage-path/{media_type}"),
    # 参数路由本身照常工作（守卫不是禁参数路由）
    ("GET", "/media-abc123", "/{media_id}"),
    ("GET", "/media-abc123/metadata", "/{media_id}/metadata"),
    ("DELETE", "/media-abc123", "/{media_id}"),
]


@pytest.mark.parametrize("method,path,expected", PROBES)
def test_literal_prefix_resolves_to_intended_route(method, path, expected):
    """首匹配语义下，字面段前缀不得落到 /{media_id}。"""
    got = _first_match(_route_specs(), method, path)
    assert got == expected, f"{method} {path} 应命中 {expected}，实际命中 {got}（路由顺序回归？）"


def test_no_single_segment_literal_registered_after_param_route():
    """结构规则：当前路由表零违规（字面段全在 /{media_id} 之前）。"""
    assert _literal_after_param_offenders(_route_specs()) == []


def test_guard_detects_misplaced_literal_route():
    """守卫自证：把 /config 挪到 /{media_id} 之后必须被抓到（防守卫失效假绿）。"""
    from fastapi import FastAPI

    bad = FastAPI()
    bad.get("/{media_id}")(lambda media_id: None)
    bad.get("/config")(lambda: None)
    offenders = _literal_after_param_offenders(_route_specs(bad.router))
    assert offenders, "合成错位路由未被守卫抓到——守卫失效"
    assert "/config" in offenders[0]


# ---------------------------------------------------------------------------
# ④ 死模型清理：符号删除 + 路由表/行为零变化锚定
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_name", ["MediaListRequest", "MediaInfo", "MediaStats"])
def test_dead_pydantic_models_removed(model_name):
    assert not hasattr(media_module, model_name), (
        f"{model_name} 复活：零引用死模型（台账 2026-09-11 ④），引用需求须走契约评审"
    )


# 删除前捕获的真实路由表（path, methods）——④ 的行为不变锚
EXPECTED_ROUTES = [
    ("/save", {"POST"}),
    ("/list", {"GET"}),
    ("/config", {"GET"}),
    ("/config", {"PUT"}),
    ("/batch-delete", {"POST"}),
    ("/{media_id}", {"GET"}),
    ("/{media_id}/metadata", {"GET"}),
    ("/download/{media_id}", {"GET"}),
    ("/{media_id}", {"DELETE"}),
    ("/stats/{agent_id}", {"GET"}),
    ("/memory/{memory_id}", {"GET"}),
    ("/cache/clear", {"POST"}),
    ("/storage-path/{media_type}", {"GET"}),
]


def test_route_table_unchanged_after_model_cleanup():
    specs = [(p, set(m)) for p, m in _route_specs()]
    assert specs == [(p, m) for p, m in EXPECTED_ROUTES]


def test_list_endpoint_behavior_unchanged(store):
    """行为锚：/list 返回结构（code/data.media/total/offset/limit）不受 ④ 影响。"""
    media_module._media_store["media-x"] = {
        "media_id": "media-x",
        "filename": "a.png",
        "media_type": "image",
        "mime_type": "",
        "size": 1,
        "agent_id": "a1",
        "user_id": None,
        "memory_id": None,
        "storage_path": "media_storage/a1/image/media-x_a.png",
        "created_at": 1.0,
        "metadata": {},
    }
    out = asyncio.run(media_module.list_media(agent_id="a1", media_type=None, search=None, limit=50, offset=0))
    assert out["code"] == 0
    assert set(out["data"]) == {"media", "total", "offset", "limit"}
    assert out["data"]["total"] == 1
