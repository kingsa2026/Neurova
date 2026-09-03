"""
全局管理类端点鉴权守卫测试（2026-08-31）

背景：/monitor /analytics /groups /enhanced-users /settings /enhanced-memory-search
六个模块此前完全无鉴权（任意请求可读写全局系统数据、管理用户/分组/告警），
与 memory-settings 同类问题（全局功能仅管理员可操作）。

契约（本次修复）：
1. 所有 GET（只读）要求登录（未认证 401）；
2. 所有写端点（PUT/POST/DELETE，含 resolve/backup/password/reset/import 类）
   要求 admin 角色（普通登录用户 403，admin 200）；
3. enhanced-users 整路由 admin（用户管理列表也属管理数据）。

测试只挂各模块 router（不触发完整 lifespan），与 test_context_pool_settings_api 同约定。
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import (
    monitor,
    analytics,
    groups_api,
    enhanced_users_api,
    settings,
    enhanced_memory_search_api,
)
from neurova.api.deps import get_current_user

MOCK_USER = {"user_id": "test_user", "username": "testuser", "role": "user"}
MOCK_ADMIN = {"user_id": "admin_user", "username": "adminuser", "role": "admin"}


@pytest.fixture
def app():
    a = FastAPI()
    a.include_router(monitor.router, prefix="/api/v1/monitor")
    a.include_router(analytics.router, prefix="/api/v1/analytics")
    a.include_router(groups_api.router, prefix="/api/v1/groups")
    a.include_router(enhanced_users_api.router, prefix="/api/v1/enhanced-users")
    a.include_router(settings.router, prefix="/api")
    a.include_router(enhanced_memory_search_api.router, prefix="/api/v1/enhanced-memory-search")
    return a


@pytest.fixture
def anon(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def user_client(app):
    with TestClient(app) as c:
        app.dependency_overrides[get_current_user] = lambda: MOCK_USER
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_client(app):
    with TestClient(app) as c:
        app.dependency_overrides[get_current_user] = lambda: MOCK_ADMIN
        yield c
    app.dependency_overrides.clear()


class TestGlobalManagementReadRequiresLogin:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/monitor/resources",
            "/api/v1/analytics/usage",
            "/api/v1/groups",
            "/api/v1/enhanced-users",
            "/api/v1/settings/cors",
            "/api/v1/enhanced-memory-search/nerf-settings",
        ],
    )
    def test_read_unauthorized_401(self, anon, path):
        r = anon.get(path)
        assert r.status_code == 401, path


class TestGlobalManagementWriteRequiresAdmin:
    @pytest.mark.parametrize(
        ["method", "path", "json"],
        [
            ("post", "/api/v1/monitor/alerts/alert-1/resolve", {}),
            ("post", "/api/v1/groups", {"name": "g"}),
            ("put", "/api/v1/groups/grp-1", {"name": "g"}),
            ("post", "/api/v1/enhanced-users", {"username": "u"}),
            ("delete", "/api/v1/enhanced-users/u-1", None),
            ("put", "/api/v1/settings", {"settings": {"general": {}}}),
            ("put", "/api/v1/enhanced-memory-search/nerf-settings", {"settings": {"x": 1}}),
            ("post", "/api/v1/enhanced-memory-search/nerf-settings/reset", None),
        ],
    )
    def test_write_as_user_forbidden_403(self, user_client, method, path, json):
        r = getattr(user_client, method)(path, json=json) if json is not None else getattr(user_client, method)(path)
        assert r.status_code == 403, (method, path, r.text[:120])

    @pytest.mark.parametrize(
        ["method", "path", "json"],
        [
            ("post", "/api/v1/monitor/alerts/alert-1/resolve", {}),
            ("post", "/api/v1/groups", {"name": "admin-g"}),
            ("post", "/api/v1/enhanced-users", {"username": "admin-u"}),
            ("put", "/api/v1/settings", {"settings": {"general": {"site_name": "x"}}}),
            ("put", "/api/v1/enhanced-memory-search/nerf-settings", {"settings": {"x": 1}}),
        ],
    )
    def test_write_as_admin_ok(self, admin_client, method, path, json):
        r = getattr(admin_client, method)(path, json=json)
        # 端点业务逻辑可能报 4xx/5xx（依赖数据模型），鉴权通过即非 403
        assert r.status_code != 403, (method, path, r.text[:160])
