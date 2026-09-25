"""BUG AUDIT S-08 回归测试: console upload / annotations 端点零鉴权收口。

缺陷: POST /console/upload、GET/POST/PUT/DELETE /annotations*、
GET /annotations/export 完全无鉴权, 匿名可上传文件并增删改
精准回复命中表（直接改变线上回复行为）。

修复契约: 上述端点加 Depends(get_current_user)（前端 KnowledgePage 的
AnnotationDrawer 与 axios 拦截器恒附 Bearer token）; 匿名一律 401。
归属化（按 user 隔离标注数据）因 annotation_store 无 user 字段,
需 schema 变更, 不在本次廉价范围内（报告为后续项）。
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_s08b_0123456789abc")

from neurova.api.deps import get_current_user
from neurova.api.endpoints import console as console_module
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.core import annotation_store as annotation_store_module

MOCK_USER = {"user_id": "u1", "username": "user1", "role": "user", "neuser_id": "u1"}


@pytest.fixture()
def app():
    a = FastAPI()
    a.include_router(console_module.router, prefix="/api/v1/console")
    return a


@pytest.fixture()
def knowledge_app():
    """标注端点的真实宿主：`/v1/knowledge`（Issue #68 收口，从 console 迁入知识域）。

    挂载点变了，鉴权契约不变——匿名仍须 401。
    """
    a = FastAPI()
    a.include_router(knowledge_module.router, prefix="/api/v1/knowledge")
    return a


@pytest.fixture()
def anon(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def user_client(app, tmp_path):
    """登录用户客户端; 上传目录与标注库重定向到 tmp, 不碰真实数据。"""
    with TestClient(app, raise_server_exceptions=False) as c:
        app.dependency_overrides[get_current_user] = lambda: MOCK_USER
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def anon_knowledge(knowledge_app):
    with TestClient(knowledge_app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def user_knowledge_client(knowledge_app, tmp_path):
    with TestClient(knowledge_app, raise_server_exceptions=False) as c:
        knowledge_app.dependency_overrides[get_current_user] = lambda: MOCK_USER
        yield c
    knowledge_app.dependency_overrides.clear()


@pytest.fixture()
def isolated_stores(tmp_path):
    console_module._CONSOLE_UPLOAD_DIR = tmp_path / "uploads"
    console_module._CONSOLE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    from neurova.core.annotation_store import AnnotationStore

    store = AnnotationStore(db_path=str(tmp_path / "annotations.db"))
    annotation_store_module.set_annotation_store(store)
    yield store
    annotation_store_module.set_annotation_store(None)


class TestConsoleUploadAuth:
    def test_upload_anonymous_401(self, anon, isolated_stores):
        r = anon.post(
            "/api/v1/console/upload",
            files={"file": ("a.txt", b"hello", "text/plain")},
        )
        assert r.status_code == 401, r.status_code

    def test_upload_with_login_200(self, user_client, isolated_stores):
        r = user_client.post(
            "/api/v1/console/upload",
            files={"file": ("a.txt", b"hello", "text/plain")},
        )
        assert r.status_code == 200, r.text


class TestAnnotationsAuth:
    def test_list_anonymous_401(self, anon_knowledge, isolated_stores):
        r = anon_knowledge.get("/api/v1/knowledge/annotations")
        assert r.status_code == 401, r.status_code

    def test_list_with_login_200(self, user_knowledge_client, isolated_stores):
        r = user_knowledge_client.get("/api/v1/knowledge/annotations")
        assert r.status_code == 200, r.text

    def test_create_anonymous_401(self, anon_knowledge, isolated_stores):
        """匿名新增标注 → 401（此前任意访客可写命中表）"""
        r = anon_knowledge.post(
            "/api/v1/knowledge/annotations",
            json={"question": "q", "answer": "a"},
        )
        assert r.status_code == 401, r.status_code
        assert isolated_stores.count() == 0, "匿名请求不得写入标注库"

    def test_create_with_login_writes(self, user_knowledge_client, isolated_stores):
        r = user_knowledge_client.post(
            "/api/v1/knowledge/annotations",
            json={"question": "q", "answer": "a"},
        )
        assert r.status_code == 200, r.text
        assert isolated_stores.count() == 1

    def test_update_anonymous_401(self, anon_knowledge, isolated_stores):
        r = anon_knowledge.put("/api/v1/knowledge/annotations/ann-1", json={"enabled": False})
        assert r.status_code == 401, r.status_code

    def test_delete_anonymous_401(self, anon_knowledge, isolated_stores):
        r = anon_knowledge.delete("/api/v1/knowledge/annotations/ann-1")
        assert r.status_code == 401, r.status_code

    def test_export_anonymous_401(self, anon_knowledge, isolated_stores):
        r = anon_knowledge.get("/api/v1/knowledge/annotations/export")
        assert r.status_code == 401, r.status_code
