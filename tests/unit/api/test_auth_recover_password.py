"""
忘记密码/取回密码端点测试 — 管理员账号 + 最高权重密码双条件（2026-09-03）

用户契约：
1. 双条件缺一不可：username 必须是系统内 admin 角色账号（第一步），
   master_password 必须等于写死的最高权重密码 nerovamakehappy（第二步）；
2. 两者都对上 → 允许重置该管理员账号密码（新密码 + 确认一致）；
3. 任一条件不满足 → 400 统一文案（不泄露账号是否存在/角色）；
4. 限流：同 (username|ip) 15 分钟内 5 次失败 → 429。

最小 FastAPI 只挂 auth router（与 test_memory_settings_api_auth 同约定）。
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import auth
from neurova.auth.user_model import UserModel

MAGIC = auth.MASTER_RECOVERY_PASSWORD


@pytest.fixture
def client(tmp_path):
    """最小测试客户端 + tmp 独立用户库（避免污染真实 data/users.db）。"""
    # 重置 auth 模块状态：库指向 tmp，窗口限流清空
    auth._user_model = UserModel(db_path=str(tmp_path / "users.db"))
    auth._recover_attempts.clear()

    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1/auth")
    with TestClient(app) as c:
        yield c
    auth._user_model = None


def _ensure_admin(client, username="admin1", password="Admin#12345", role="admin"):
    """直接经 UserModel 造管理员账号（注册端点会校验角色首启逻辑，略绕）。"""
    model = auth._get_user_model()
    user = model.create_user(
        username=username,
        password_hash=auth.hash_password(password),
        email="",
        role=role,
    )
    return user


def _recover(client, username="admin1", master=MAGIC, new="NewPass#2026", confirm="NewPass#2026"):
    return client.post("/api/v1/auth/recover-password", json={
        "username": username,
        "master_password": master,
        "new_password": new,
        "confirm_password": confirm,
    })


class TestRecoverPassword:
    def test_double_condition_success(self, client):
        _ensure_admin(client, "admin1", "Admin#12345")
        resp = _recover(client, "admin1", master=MAGIC, new="Reset#99999", confirm="Reset#99999")
        assert resp.status_code == 200
        assert resp.json().get("data", {}).get("username") == "admin1"

        # 新密码可登录
        login = client.post("/api/v1/auth/login", json={"username": "admin1", "password": "Reset#99999"})
        assert login.status_code == 200
        # 旧密码失效
        old_login = client.post("/api/v1/auth/login", json={"username": "admin1", "password": "Admin#12345"})
        assert old_login.status_code == 401

    def test_condition_admin_account_missing(self, client):
        resp = _recover(client, "ghost_admin", master=MAGIC)
        assert resp.status_code == 400
        assert "管理员账号或最高权重密码不正确" in (resp.json() or {}).get("detail", "")

    def test_condition_master_password_wrong(self, client):
        _ensure_admin(client, "admin1", "Admin#12345")
        resp = _recover(client, "admin1", master="wrong-master-pwd")
        assert resp.status_code == 400

    def test_condition_existing_but_not_admin_role(self, client):
        _ensure_admin(client, "user1", "User#12345", role="user")
        resp = _recover(client, "user1", master=MAGIC)
        assert resp.status_code == 400
        # 非 admin 即使魔密正确也拒绝（缺一不可）
        assert "管理员账号或最高权重密码不正确" in (resp.json() or {}).get("detail", "")

    def test_new_password_mismatch(self, client):
        _ensure_admin(client, "admin1", "Admin#12345")
        resp = _recover(client, "admin1", master=MAGIC, new="Aaa#11111", confirm="Bbb#22222")
        assert resp.status_code == 400
        assert "新密码不一致" in (resp.json() or {}).get("detail", "")

    def test_rate_limit_after_5_failures(self, client):
        _ensure_admin(client, "admin1", "Admin#12345")
        for _ in range(5):
            assert _recover(client, "admin1", master="wrong").status_code == 400
        resp = _recover(client, "admin1", master=MAGIC)
        assert resp.status_code == 429, "第 6 次（即使参数正确）应被限流"
