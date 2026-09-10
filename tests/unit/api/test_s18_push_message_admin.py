"""BUG AUDIT S-18 回归测试: /console/push/message 必须仅限管理员。

缺陷: POST /console/push/message 仅要求登录（get_current_user）,
任意普通用户可向全部 WebSocket 连接广播任意内容（全体消息注入）。

修复契约: 参照同文件 /debug/logs 等 admin 端点模式改 require_admin ——
匿名 401 / 普通用户 403 / admin 200。前端无调用方（pushSystemMessage
为死代码且指向 /console/push）, 无破坏面。
"""
import os
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_s18_0123456789abc")

from neurova.api.deps import get_current_user
from neurova.api.endpoints import console as console_module

MOCK_USER = {"user_id": "u1", "username": "user1", "role": "user", "neuser_id": "u1"}
MOCK_ADMIN = {"user_id": "a1", "username": "admin1", "role": "admin", "neuser_id": "a1"}


@pytest.fixture()
def app():
    a = FastAPI()
    a.include_router(console_module.router, prefix="/api/v1/console")
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


class TestPushMessageRequiresAdmin:
    def test_anonymous_401(self, anon):
        r = anon.post("/api/v1/console/push/message", json={"content": "hi"})
        assert r.status_code == 401, r.status_code

    def test_non_admin_user_403(self, user_client):
        """普通登录用户 → 403（此前 200, 可向全体连接广播）"""
        r = user_client.post("/api/v1/console/push/message", json={"content": "hi"})
        assert r.status_code == 403, r.status_code

    def test_non_admin_broadcast_not_stored(self, user_client):
        """被拒请求不得产生任何广播/存储副作用"""
        user_client.post("/api/v1/console/push/message", json={"content": "spam"})
        assert console_module._manager.get_messages("u1", since=0) == []

    def test_admin_200_and_stored(self, admin_client):
        r = admin_client.post("/api/v1/console/push/message", json={"content": "notice"})
        assert r.status_code == 200, r.text
        msgs = console_module._manager.get_messages("a1", since=0)
        assert any(m.get("content") == "notice" for m in msgs)


class TestPushMessagesPollingUnchanged:
    def test_polling_still_requires_login(self, anon):
        """GET /push/messages 保持登录要求（行为不变）"""
        r = anon.get("/api/v1/console/push/messages")
        assert r.status_code == 401, r.status_code
