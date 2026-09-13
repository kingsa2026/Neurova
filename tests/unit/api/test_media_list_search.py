# -*- coding: utf-8 -*-
"""媒体搜索后端化防回归（台账 2026-09-11 第七节新登记 ③）。

原缺陷：AgentMediaPage 搜索为纯前端过滤，只覆盖已加载的 limit 页（约 50 条），
数据量大时搜不到未加载条目；后端 GET /media/list 无 search 参数。

本测试经 HTTP 层（TestClient）锁定后端 search 契约（参数名/默认值与
NeurUI listMedia 传参对齐——不区分大小写匹配 filename/media_id，可选
agent_id/media_type 过滤下执行），返回结构与分页语义不变（total 反映过滤后总数）：

1. search 命中 filename（大小写不敏感）；
2. search 命中 media_id 子串；
3. search 与 agent_id / media_type 过滤组合；
4. search + offset/limit 分页——total = 过滤后总数，media 为当前页切片；
5. 无 search（缺省/空串）返回全量（向后兼容）；
6. 无命中返回 total=0、media=[]。

隔离纪律：list 端点仅读内存媒体索引，条目经 _media_store 直构注入，
不触磁盘；storage_path 仍 monkeypatch 到 tmp_path 防误写真实目录。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import media as media_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """挂载 media 路由的 TestClient；认证覆盖、存储根指向 tmp_path、索引清空。"""
    from neurova.api.auth import get_current_user

    monkeypatch.setattr(
        media_module,
        "_media_config",
        {**media_module._media_config, "storage_path": str(tmp_path / "media_storage")},
    )
    app = FastAPI()
    app.include_router(media_module.router, prefix="/v1/media")
    app.dependency_overrides[get_current_user] = lambda: {"username": "tester"}
    media_module._media_store.clear()
    with TestClient(app) as c:
        yield c
    media_module._media_store.clear()


def _put(media_id, filename, *, agent_id="a1", media_type="image", created_at=0.0):
    media_module._media_store[media_id] = {
        "media_id": media_id,
        "filename": filename,
        "media_type": media_type,
        "mime_type": "",
        "size": 10,
        "agent_id": agent_id,
        "user_id": None,
        "memory_id": None,
        "storage_path": f"media_storage/{agent_id}/{media_type}/{media_id}_{filename}",
        "created_at": created_at,
        "metadata": {},
    }


def _list(client, **params):
    resp = client.get("/v1/media/list", params=params)
    assert resp.status_code == 200, f"GET /media/list 失败（参数路由吞并或 422）: {resp.text}"
    return resp.json()["data"]


# ---------------------------------------------------------------------------
# search 命中
# ---------------------------------------------------------------------------


def test_search_matches_filename_case_insensitive(client):
    _put("media-aaa1", "Cat_Photo.png")
    _put("media-aaa2", "dog.png")
    _put("media-aaa3", "bird.png")

    data = _list(client, agent_id="a1", search="CAT")

    assert data["total"] == 1, "search 应过滤掉未命中条目，total 反映过滤后总数"
    assert [m["media_id"] for m in data["media"]] == ["media-aaa1"]


def test_search_matches_media_id_substring(client):
    _put("media-ff00aa", "one.png")
    _put("media-99bbcc", "two.png")

    data = _list(client, agent_id="a1", search="ff00")

    assert data["total"] == 1
    assert data["media"][0]["media_id"] == "media-ff00aa"


def test_search_none_or_empty_returns_all(client):
    _put("media-1", "a.png")
    _put("media-2", "b.png")

    assert _list(client, agent_id="a1")["total"] == 2
    assert _list(client, agent_id="a1", search="")["total"] == 2, "空串视同无 search（向后兼容）"


def test_search_no_match_returns_empty(client):
    _put("media-1", "a.png")
    data = _list(client, agent_id="a1", search="zzz")
    assert data["total"] == 0
    assert data["media"] == []


# ---------------------------------------------------------------------------
# search 与过滤组合
# ---------------------------------------------------------------------------


def test_search_respects_agent_filter(client):
    _put("media-1", "shared.png", agent_id="a1")
    _put("media-2", "shared.png", agent_id="a2")

    data = _list(client, agent_id="a1", search="shared")
    assert data["total"] == 1
    assert data["media"][0]["media_id"] == "media-1"


def test_search_respects_media_type_filter(client):
    _put("media-1", "report.png", media_type="image")
    _put("media-2", "report.wav", media_type="audio")

    data = _list(client, agent_id="a1", media_type="audio", search="report")
    assert data["total"] == 1
    assert data["media"][0]["media_id"] == "media-2"


# ---------------------------------------------------------------------------
# search 与分页协同
# ---------------------------------------------------------------------------


def test_search_pagination_total_and_slice(client):
    # 5 条命中（filename 含 hit，created_at 降序 hit0>hit1>...），3 条噪声
    for i in range(5):
        _put(f"media-hit{i}", f"hit-{i}.png", created_at=100 - i)
    for i in range(3):
        _put(f"media-noise{i}", f"noise-{i}.png", created_at=50 - i)

    data = _list(client, agent_id="a1", search="hit", limit=2, offset=0)
    # total 反映过滤后总数（5），而非全量（8）
    assert data["total"] == 5
    assert data["offset"] == 0
    assert data["limit"] == 2
    assert [m["media_id"] for m in data["media"]] == ["media-hit0", "media-hit1"]

    data2 = _list(client, agent_id="a1", search="hit", limit=2, offset=4)
    assert data2["total"] == 5
    assert [m["media_id"] for m in data2["media"]] == ["media-hit4"], "末页切片应落在过滤后列表上"
