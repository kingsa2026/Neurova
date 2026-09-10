"""BUG AUDIT S-08 回归测试: trace / audit 端点零鉴权收口。

缺陷: trace.py 的 4 个 GET 端点与 audit.py 的 3 个端点完全无鉴权,
任意匿名请求可读取全局轨迹/审计数据。

修复契约:
- trace 4 端点（列表/stats/详情/events）: 要求登录（get_current_user, 非 admin 用户可用
  —— 前端 AgentTrajectoryPage 挂在 ChatLayout 常规侧栏, 属非 admin 页面, 降级收口）;
- audit 3 端点（列表/search/stats）: 要求 admin（require_admin,
  前端 AuditPage 挂在 platformAdmin 导航分组）;
- 匿名请求一律 401。

测试只挂各模块 router（不触发完整 lifespan）, 与 test_global_admin_guards 同约定。
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_s08_0123456789abcdef")

from neurova.api.deps import get_current_user
from neurova.api.endpoints import audit, trace

MOCK_USER = {"user_id": "u1", "username": "user1", "role": "user"}
MOCK_ADMIN = {"user_id": "a1", "username": "admin1", "role": "admin"}


@pytest.fixture()
def app():
    a = FastAPI()
    a.include_router(trace.router, prefix="/api/v1/trace")
    a.include_router(audit.router, prefix="/api/v1/audit")
    return a


@pytest.fixture()
def anon(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def user_client(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        app.dependency_overrides[get_current_user] = lambda: MOCK_USER
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_client(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        app.dependency_overrides[get_current_user] = lambda: MOCK_ADMIN
        yield c
    app.dependency_overrides.clear()


TRACE_PATHS = [
    "/api/v1/trace",
    "/api/v1/trace/stats",
    "/api/v1/trace/no-such-trace-id",
    "/api/v1/trace/no-such-trace-id/events",
]

AUDIT_GET_PATHS = ["/api/v1/audit", "/api/v1/audit/stats"]


class TestTraceRequiresLogin:
    @pytest.mark.parametrize("path", TRACE_PATHS)
    def test_anonymous_get_401(self, anon, path):
        """匿名访问 trace 四端点 → 401"""
        r = anon.get(path)
        assert r.status_code == 401, f"{path}: {r.status_code}"

    @pytest.mark.parametrize("path", TRACE_PATHS)
    def test_logged_in_user_allowed(self, user_client, path):
        """普通登录用户可访问（非 admin 页面调用方 → 降级 get_current_user）"""
        r = user_client.get(path)
        # 认证通过后进入业务逻辑: 列表/stats 200, 不存在的 id 404
        assert r.status_code in (200, 404), f"{path}: {r.status_code}"


class TestAuditRequiresAdmin:
    @pytest.mark.parametrize("path", AUDIT_GET_PATHS)
    def test_anonymous_get_401(self, anon, path):
        r = anon.get(path)
        assert r.status_code == 401, f"{path}: {r.status_code}"

    def test_anonymous_search_401(self, anon):
        r = anon.post("/api/v1/audit/search", json={})
        assert r.status_code == 401, r.status_code

    @pytest.mark.parametrize("path", AUDIT_GET_PATHS)
    def test_non_admin_user_403(self, user_client, path):
        """普通登录用户 → 403（审计数据仅管理员）"""
        r = user_client.get(path)
        assert r.status_code == 403, f"{path}: {r.status_code}"

    def test_non_admin_search_403(self, user_client):
        r = user_client.post("/api/v1/audit/search", json={})
        assert r.status_code == 403, r.status_code

    @pytest.mark.parametrize("path", AUDIT_GET_PATHS)
    def test_admin_200(self, admin_client, path):
        r = admin_client.get(path)
        assert r.status_code == 200, f"{path}: {r.status_code}"

    def test_admin_search_200(self, admin_client):
        r = admin_client.post("/api/v1/audit/search", json={})
        assert r.status_code == 200, r.status_code
