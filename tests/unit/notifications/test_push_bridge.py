# -*- coding: utf-8 -*-
"""移动端推送桥单测（S-3）：token 存储、信令构造、凭据装载、扇出降级、端点鉴权。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from neurova.notifications import push_sender, push_store


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(push_store, "_DB_PATH", str(tmp_path / "mobile_push.db"))
    return tmp_path


@pytest.fixture()
def fake_notification():
    return SimpleNamespace(notification_id="notif-1", notification_type="task_completed")


def _rsaPrivateKeyPem() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


# ── push_store ────────────────────────────────────────────────────────────

class TestPushTokenStore:
    def test_upsert_and_list(self, isolated_db):
        push_store.upsert_token("u1", "android", "tok-a", "dev-1")
        rows = push_store.list_tokens_for_user("u1")
        assert len(rows) == 1
        assert rows[0].platform == "android"
        assert rows[0].push_token == "tok-a"

    def test_same_device_overwrites(self, isolated_db):
        push_store.upsert_token("u1", "android", "tok-old", "dev-1")
        push_store.upsert_token("u2", "harmony", "tok-new", "dev-1")
        rows = push_store.list_tokens_for_user("u2")
        assert len(rows) == 1 and rows[0].push_token == "tok-new"
        assert push_store.list_tokens_for_user("u1") == []

    def test_multi_device_per_user(self, isolated_db):
        push_store.upsert_token("u1", "android", "tok-a", "dev-1")
        push_store.upsert_token("u1", "harmony", "tok-b", "dev-2")
        assert len(push_store.list_tokens_for_user("u1")) == 2

    def test_remove(self, isolated_db):
        push_store.upsert_token("u1", "android", "tok-a", "dev-1")
        assert push_store.remove_token_for_user("dev-1", "u1") is True
        assert push_store.remove_token_for_user("dev-1", "u1") is False
        assert push_store.list_tokens_for_user("u1") == []

    def test_remove_rejects_foreign_owner(self, isolated_db):
        """审计 §3.1-9：注销绑定属主——只凭 device_id 注销不掉他人设备。"""
        push_store.upsert_token("u1", "android", "tok-a", "dev-1")
        assert push_store.remove_token_for_user("dev-1", "u2") is False
        assert push_store.list_tokens_for_user("u1") != []
        assert push_store.remove_token_for_user("dev-1", "u1") is True


# ── push_sender ───────────────────────────────────────────────────────────

class TestSignalingPayload:
    def test_signaling_only_carries_id_and_type(self, fake_notification):
        payload = push_sender.buildSignalingPayload(
            fake_notification.notification_id, fake_notification.notification_type)
        assert payload == {"notificationId": "notif-1", "notificationType": "task_completed"}
        assert "message" not in payload and "title" not in payload


class TestLoadCredentials:
    def test_env_wins(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_PUSH_FCM_SERVICE_ACCOUNT", '{"project_id":"p"}')
        monkeypatch.setenv("NEUROVA_PUSH_HARMONY_APP_ID", "app-1")
        monkeypatch.setenv("NEUROVA_PUSH_HARMONY_CLIENT_SECRET", "sec-1")
        creds = push_sender.loadCredentials()
        assert creds["fcm_service_account"] == '{"project_id":"p"}'
        assert creds["harmony_app_id"] == "app-1"

    def test_missing_is_empty(self, monkeypatch):
        for k in ("NEUROVA_PUSH_FCM_SERVICE_ACCOUNT", "NEUROVA_PUSH_HARMONY_APP_ID",
                  "NEUROVA_PUSH_HARMONY_CLIENT_SECRET"):
            monkeypatch.delenv(k, raising=False)
        import pathlib
        monkeypatch.setattr(push_sender, "_CREDENTIAL_FILE", pathlib.Path("/nonexistent/push_credentials.json"))
        creds = push_sender.loadCredentials()
        assert creds["fcm_service_account"] == ""


class TestFanoutDegradation:
    def test_no_tokens_is_noop(self, isolated_db, fake_notification):
        result = push_sender.pushNotificationToUser("nobody", fake_notification)
        assert result == {"sent": 0, "skipped": 0, "failed": 0}

    def test_no_credentials_counts_failed_without_raise(self, isolated_db, fake_notification, monkeypatch):
        for k in ("NEUROVA_PUSH_FCM_SERVICE_ACCOUNT", "NEUROVA_PUSH_HARMONY_APP_ID",
                  "NEUROVA_PUSH_HARMONY_CLIENT_SECRET"):
            monkeypatch.delenv(k, raising=False)
        import pathlib
        monkeypatch.setattr(push_sender, "_CREDENTIAL_FILE", pathlib.Path("/nonexistent/push_credentials.json"))
        monkeypatch.setattr(push_sender, "_tokenCache", {})
        push_store.upsert_token("u1", "android", "tok-a", "dev-1")
        result = push_sender.pushNotificationToUser("u1", fake_notification)
        assert result["sent"] == 0 and result["failed"] == 1

    def test_fcm_full_success_path(self, isolated_db, fake_notification, monkeypatch):
        """真 RSA 密钥走完 JWT→OAuth→send 全链（网络被 override），断言 sent=1。"""
        monkeypatch.setenv("NEUROVA_PUSH_FCM_SERVICE_ACCOUNT", json.dumps({
            "project_id": "proj", "client_email": "sa@proj.iam.gserviceaccount.com",
            "private_key": _rsaPrivateKeyPem(),
        }))
        monkeypatch.setattr(push_sender, "_tokenCache", {})
        calls = []

        def fake_post(url, **kwargs):
            calls.append(url)
            if "oauth2.googleapis.com" in url:
                return SimpleNamespace(status_code=200, text="ok", json=lambda: {"access_token": "tok-oauth"})
            return SimpleNamespace(status_code=200, text="ok", json=lambda: {})

        monkeypatch.setattr(push_sender, "_posterOverride", fake_post)
        push_store.upsert_token("u1", "android", "tok-a", "dev-1")
        result = push_sender.pushNotificationToUser("u1", fake_notification)
        assert result["sent"] == 1 and result["failed"] == 0
        assert any("oauth2.googleapis.com" in u for u in calls)
        assert any("fcm.googleapis.com" in u for u in calls)

    def test_fcm_oauth_failure_counts_failed_without_raise(self, isolated_db, fake_notification, monkeypatch):
        """OAuth 被拒（401）→ 诚实计 failed 且不抛。"""
        monkeypatch.setenv("NEUROVA_PUSH_FCM_SERVICE_ACCOUNT", json.dumps({
            "project_id": "proj", "client_email": "sa@proj.iam.gserviceaccount.com",
            "private_key": _rsaPrivateKeyPem(),
        }))
        monkeypatch.setattr(push_sender, "_tokenCache", {})

        def fake_post(url, **kwargs):
            return SimpleNamespace(status_code=401, text="denied", json=lambda: {})

        monkeypatch.setattr(push_sender, "_posterOverride", fake_post)
        push_store.upsert_token("u1", "android", "tok-a", "dev-1")
        result = push_sender.pushNotificationToUser("u1", fake_notification)
        assert result["sent"] == 0 and result["failed"] == 1


# ── 端点 ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(isolated_db, monkeypatch):
    from neurova.api.app import create_app
    from neurova.api.auth import get_current_user

    # 隔离其他测试模块 setdefault 的 31 字节弱密钥：
    # _is_production() 默认按生产判定（未显式 NEUROVA_DEBUG=1），弱密钥会让
    # create_app 直接拒绝启动（fail-closed）。这里显式声明开发态。
    monkeypatch.delenv("NEUROVA_JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("NEUROVA_JWT_SECRET", raising=False)
    monkeypatch.setenv("NEUROVA_DEBUG", "1")
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {"id": 7, "username": "u7"}
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def rawClient(isolated_db, monkeypatch):
    """不挂认证 override：走真实依赖（无 token → 401）。"""
    from neurova.api.app import create_app

    monkeypatch.delenv("NEUROVA_JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("NEUROVA_JWT_SECRET", raising=False)
    monkeypatch.setenv("NEUROVA_DEBUG", "1")
    return TestClient(create_app())


class TestPushEndpoints:
    def test_upsert_requires_auth(self, rawClient):
        resp = rawClient.put("/api/v1/mobile/push/push-tokens", json={
            "platform": "android", "push_token": "tok", "device_id": "d1"})
        assert resp.status_code == 401

    def test_upsert_and_status(self, client):
        resp = client.put("/api/v1/mobile/push/push-tokens", json={
            "platform": "android", "push_token": "tok-xyz-12345", "device_id": "dev-9"})
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        rows = push_store.list_tokens_for_user("7")
        assert len(rows) == 1 and rows[0].device_id == "dev-9"

        status = client.get("/api/v1/mobile/push/push-credentials/status")
        assert status.status_code == 200
        body = status.json()["data"]
        assert set(body.keys()) == {"fcm_configured", "harmony_configured"}

    def test_invalid_platform_422(self, client):
        resp = client.put("/api/v1/mobile/push/push-tokens", json={
            "platform": "windows", "push_token": "tok-xyz-12345", "device_id": "d"})
        assert resp.status_code == 422

    def test_delete_token(self, client):
        push_store.upsert_token("7", "android", "tok-abc-12345", "dev-del")
        resp = client.delete("/api/v1/mobile/push/push-tokens/dev-del")
        assert resp.status_code == 200
        assert push_store.list_tokens_for_user("7") == []
