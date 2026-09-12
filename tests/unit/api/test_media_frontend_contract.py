# -*- coding: utf-8 -*-
"""F-1 契约对齐防回归：NeurUI media.ts 消费的后端契约形状。

台账 docs/资源型修复登记台账_2026-09-11.md F-1：前端 listMedia 期望
``data.media``/offset/limit（而非 items/page/size），download 走
``/download/{media_id}``，info 走 ``/{media_id}/metadata``，批量删除走
``POST /batch-delete``。本文件锁定：

1. ``GET /media/list`` 响应结构（data.media/total/offset/limit + 条目字段）；
2. ``POST /media/batch-delete`` 新端点（逐个删除，回报 succeeded/failed）；
3. 路由顺序锚：字面段路由（/config、/batch-delete、/stats/{agent_id}）不得被
   ``GET /{media_id}`` 参数路由吞掉——getMediaStats 404 的根因即顺序匹配。

隔离纪律：storage_path 指向 tmp_path，全程 TestClient + 依赖覆盖，无网络。
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import media as media_module


@pytest.fixture()
def media_env(tmp_path, monkeypatch):
    """存储根指到 tmp_path；内存媒体索引每用例前后清空。"""
    monkeypatch.setattr(
        media_module,
        "_media_config",
        {**media_module._media_config, "storage_path": str(tmp_path / "media_storage")},
    )
    media_module._media_store.clear()
    yield tmp_path
    media_module._media_store.clear()


@pytest.fixture()
def client(media_env):
    """挂载 media 路由的 TestClient，认证依赖覆盖为固定用户。"""
    from neurova.api.auth import get_current_user

    app = FastAPI()
    app.include_router(media_module.router, prefix="/v1/media")
    app.dependency_overrides[get_current_user] = lambda: {"username": "tester"}
    with TestClient(app) as c:
        yield c


def _save_via_api(client: TestClient, name: str = "clip.png", content: bytes = b"png-bytes", agent_id: str = "a1"):
    return client.post(
        "/v1/media/save",
        files={"file": (name, content, "image/png")},
        data={"media_type": "image", "agent_id": agent_id},
    )


# ---------------------------------------------------------------------------
# GET /media/list — 前端 listMedia 消费的响应形状
# ---------------------------------------------------------------------------


def test_list_media_response_shape(client):
    """data.media/total/offset/limit 结构 + 条目字段（前端列表映射源）。"""
    _save_via_api(client, name="one.png", content=b"a")
    _save_via_api(client, name="two.png", content=b"bb")

    resp = client.get("/v1/media/list", params={"agent_id": "a1"})
    assert resp.status_code == 200
    body = resp.json()
    data = body["data"]
    # 分页字段：offset/limit 模式，不是 page/size，也不是 items
    assert set(data.keys()) >= {"media", "total", "offset", "limit"}
    assert "items" not in data
    assert data["total"] == 2
    assert data["offset"] == 0
    assert data["limit"] == 50

    item = data["media"][0]
    for field in ("media_id", "filename", "media_type", "mime_type", "size", "agent_id", "storage_path", "created_at"):
        assert field in item, f"列表条目缺少字段 {field}"
    assert item["media_id"]
    assert item["filename"] in ("one.png", "two.png")


def test_list_media_route_not_swallowed(client):
    """路由顺序锚：单段字面路由 /list 必须先于 GET /{media_id} 命中。"""
    resp = client.get("/v1/media/list", params={"agent_id": "a1"})
    assert resp.status_code == 200
    assert resp.json()["code"] == 0


# ---------------------------------------------------------------------------
# 路由顺序锚 — 字面段路由不得被 GET /{media_id} 参数路由吞掉
# ---------------------------------------------------------------------------


def test_config_route_not_swallowed_by_param_route(client):
    """GET /media/config 必须命中配置端点（原注册在 /{media_id} 之后，
    被 404 "Media 'config' not found" 吞掉——与 getMediaStats 同根因）。"""
    resp = client.get("/v1/media/config")
    assert resp.status_code == 200, f"GET /media/config 被参数路由吞掉: {resp.text}"
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["max_file_size"] > 0


def test_stats_agent_route_reachable(client):
    """GET /media/stats/{agent_id} 两段路径可达（防顺序回归锚）。"""
    _save_via_api(client, content=b"abc")
    resp = client.get("/v1/media/stats/a1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["total_files"] == 1
    assert body["data"]["total_size"] == 3


# ---------------------------------------------------------------------------
# POST /media/batch-delete — 新端点（F-1：前端 batchDeleteMedia）
# ---------------------------------------------------------------------------


def test_batch_delete_reports_succeeded_and_failed(client, media_env):
    """批量删除逐个执行并回报 succeeded/failed；磁盘文件同步删除。"""
    r1 = _save_via_api(client, name="gone1.png", content=b"a1bytes")
    r2 = _save_via_api(client, name="gone2.png", content=b"a2bytes")
    id1, id2 = r1.json()["data"]["media_id"], r2.json()["data"]["media_id"]
    disk1 = Path(media_env / "media_storage").rglob("*gone1.png")
    disk1_path = next(iter(disk1))
    assert disk1_path.is_file()

    resp = client.post(
        "/v1/media/batch-delete",
        json={"media_ids": [id1, "media-nonexistent", id2]},
    )
    assert resp.status_code == 200, f"batch-delete 端点缺失或被吞: {resp.text}"
    data = resp.json()["data"]
    assert data["succeeded"] == [id1, id2]
    assert len(data["failed"]) == 1
    assert data["failed"][0]["media_id"] == "media-nonexistent"
    assert data["failed"][0]["reason"]

    assert id1 not in media_module._media_store
    assert id2 not in media_module._media_store
    assert not disk1_path.exists(), "batch-delete 未同步删除磁盘文件"


def test_batch_delete_empty_list(client):
    resp = client.post("/v1/media/batch-delete", json={"media_ids": []})
    assert resp.status_code == 200
    assert resp.json()["data"] == {"succeeded": [], "failed": []}
