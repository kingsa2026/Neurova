"""精准回复命中表（`/annotations*`）契约（Issue #68 收口：由 console 域迁入知识域）。

根因（把报错恢复原状就会复现）：annotations router 此前只被 `console.py` 的
聚合器 include，挂载在 `/api/v1/console/annotations*` 下；而它的唯一消费者是
知识域的 `KnowledgePage` → `AnnotationDrawer`，前端按 `/api/v1/knowledge/annotations*`
请求 —— 实测恒 404，标注管理功能整体不可用。

标注是知识资产（重训练化集的语料来源），其归属就是知识域：本文件钉死
「路由挂在 knowledge 聚合器上、鉴权在位、处理函数真身属 console_annotations 叶子模块」。
"""
import inspect
import os

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_kb_ann_012345")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import Mock

from neurova.api.endpoints import knowledge as kb
from neurova.api.endpoints import console_annotations as leaf
from neurova.api.deps import get_current_user
from tests.route_table import leafRoutes

_ANNOTATION_ENDPOINTS = (
    "list_annotations", "create_annotation", "update_annotation",
    "delete_annotation", "export_training_set",
)


def test_annotations_are_mounted_on_the_knowledge_router():
    """五条标注端点都必须挂在 knowledge 聚合器上（真身仍在叶子模块）。"""
    names = {route.name for route in leafRoutes(kb.router)}
    missing = [name for name in _ANNOTATION_ENDPOINTS if name not in names]
    assert not missing, f"标注端点未挂在 knowledge 聚合器上: {missing}"


def test_annotations_handlers_are_the_leaf_module_objects():
    """聚合器上的路由终点必须是叶子模块的真身，不是就近复制出来的第二份实现。"""
    by_name = {route.name: route.endpoint for route in leafRoutes(kb.router)}
    for name in _ANNOTATION_ENDPOINTS:
        assert by_name.get(name) is getattr(leaf, name), (
            f"{name} 的路由终点不是 console_annotations 的真身"
            f"（改绑到拷贝或别的实现即红）"
        )


def test_cors_style_no_console_prefix_leak():
    """迁移后不得在 console 聚合器上再留一份（同一个事实只有一处挂载）。"""
    console_names = {route.name for route in leafRoutes(__import__(
        "neurova.api.endpoints.console", fromlist=["router"]).router)}
    leaked = [name for name in _ANNOTATION_ENDPOINTS if name in console_names]
    assert not leaked, f"标注端点在 console 聚合器上仍有一份副本: {leaked}"


@pytest.fixture
def client(monkeypatch):
    store = Mock()
    item = {"id": "a", "question": "Question", "answer": "Answer"}
    store.list_annotations.return_value = [item]
    store.count.return_value = 1
    store.add.return_value = "a"
    store.get.return_value = item
    store.delete.return_value = True
    store.export_training_set.return_value = ["one", "two"]
    from neurova.core import annotation_store
    monkeypatch.setattr(annotation_store, "get_annotation_store", lambda: store)
    app = FastAPI()
    app.include_router(kb.router, prefix="/api/v1/knowledge")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "test", "role": "admin"}
    with TestClient(app) as c:
        yield c, store


def test_annotations_mock_store(client):
    c, store = client
    assert c.get("/api/v1/knowledge/annotations?q=question").json()["data"] == {"items": [
        {"id": "a", "question": "Question", "answer": "Answer"}], "total": 1}
    assert c.get("/api/v1/knowledge/annotations?q=missing").json()["data"]["items"] == []
    assert c.get("/api/v1/knowledge/annotations?limit=0").status_code == 422
    assert c.post("/api/v1/knowledge/annotations", json={"question": " q ", "answer": " a "}).json()["data"]["id"] == "a"
    store.add.assert_called_once_with("q", "a", source="manual")
    assert c.post("/api/v1/knowledge/annotations", json={"question": " ", "answer": "a"}).status_code == 400
    assert c.put("/api/v1/knowledge/annotations/a", json={"answer": "new", "enabled": False}).status_code == 200
    store.update_answer.assert_called_once_with("a", "new")
    store.set_enabled.assert_called_once_with("a", False)
    assert c.get("/api/v1/knowledge/annotations/export").json()["data"] == {"jsonl": "one\ntwo", "count": 2}
    assert c.delete("/api/v1/knowledge/annotations/a").status_code == 200
    store.get.return_value = None
    assert c.put("/api/v1/knowledge/annotations/a", json={"answer": "new"}).status_code == 404
    store.delete.return_value = False
    assert c.delete("/api/v1/knowledge/annotations/a").status_code == 404


def test_annotations_request_models_are_the_leaf_module_identity():
    """请求模型真身属叶子模块——`console.AnnotationCreateRequest` 这类旧别名已随迁移撤掉。"""
    by_name = {route.name: route for route in leafRoutes(kb.router)}
    for name, model in (
        ("create_annotation", leaf.AnnotationCreateRequest),
        ("update_annotation", leaf.AnnotationUpdateRequest),
    ):
        endpoint = by_name[name].endpoint
        assert inspect.signature(endpoint).parameters["body"].annotation is model
        assert model.__module__ == leaf.__name__
