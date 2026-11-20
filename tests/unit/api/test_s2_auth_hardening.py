"""S2 安全批（审计 2026-11-16）：auth.py 三项加固的红绿判据。

覆盖：
- P0-1 主恢复密码改**构建期环境注入**（`NEUROVA_MASTER_RECOVERY_PASSWORD`）：
  源码与分发包不再含密码常量；未配置即端点禁用（fail-closed，404）；
  命中后强制改密 + 通知全部管理员 + 审计事件升 CRITICAL。
  §6-171 的自救语义由"部署/构建期注入"承接：运行者配置环境变量即可用，
  源码形态不再随包分发口令。
- P1-6 服务端部署形态（NEUROVA_HOST 绑非环回）**关闭自注册**：注册验证码
  端点直接 403，不回 dev_code；桌面形态维持上轮 P2-3 的诚实返回。
- 500 detail 带 `str(e)` 的 7 处信息泄露收口：源码不再把异常原文拼进响应。
"""

import ast
import os
import uuid
from pathlib import Path
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET", "s2-pin-0123456789abcdef-2026-11-16")

from neurova.api.auth import hash_password  # noqa: E402
from neurova.api.endpoints import auth as AUTH  # noqa: E402
from neurova.core.ast_scan import parseSource  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
AUTH_SOURCE = REPO_ROOT / "neurova" / "api" / "endpoints" / "auth.py"

OLD_PASSWORD = "0ld-Pw#not-used-01"
NEW_PASSWORD = "R3cover#admin-new-02"
INJECTED_SECRET = "injected-via-env-S2-2026"

ENV_NAME = "NEUROVA_MASTER_RECOVERY_PASSWORD"


def _setServer(monkeypatch, host="0.0.0.0"):
    monkeypatch.setenv("NEUROVA_HOST", host)


def _setDesktop(monkeypatch):
    monkeypatch.delenv("NEUROVA_HOST", raising=False)


@pytest.fixture()
def authFace(monkeypatch):
    """真端点 + 生产取法的用户模型（数据根由 conftest 钉到临时目录）。"""
    app = FastAPI()
    app.include_router(AUTH.router, prefix="/api/v1/auth")
    monkeypatch.setattr(AUTH, "_recover_attempts", {})
    monkeypatch.delenv(ENV_NAME, raising=False)
    _setDesktop(monkeypatch)

    user_model = AUTH._get_user_model()
    suffix = uuid.uuid4().hex[:8]
    admin_name = f"s2Adm{suffix}"
    member_name = f"s2Mem{suffix}"
    user_model.create_user(username=admin_name, password_hash=hash_password(OLD_PASSWORD), role="admin")
    user_model.create_user(username=member_name, password_hash=hash_password(OLD_PASSWORD), role="user")

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, admin_name, member_name


def _recover(client, username, secret, new_password=NEW_PASSWORD):
    return client.post(
        "/api/v1/auth/recover-password",
        json={
            "username": username,
            "master_password": secret,
            "new_password": new_password,
            "confirm_password": new_password,
        },
    )


# ─────────────────────────── P0-1 ───────────────────────────


class TestMasterRecoveryPasswordEnvInjection:
    def test_source_no_longer_carries_password_literal(self):
        """源码不得再含 MASTER_RECOVERY_PASSWORD 字面量赋值，也不得残留旧口令串。"""
        src = AUTH_SOURCE.read_text(encoding="utf-8")
        tree = parseSource(src)
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "MASTER_RECOVERY_PASSWORD":
                        pytest.fail(
                            "auth.py 仍有模块级 MASTER_RECOVERY_PASSWORD 赋值——"
                            "P0-1 拍板后口令只能来自构建/部署期注入的环境变量"
                        )
        assert "neurovamakehappy" not in src, "旧硬编码口令仍残留在源码里"

    def test_unconfigured_password_disables_endpoint(self, authFace):
        """未注入口令 ⇒ 端点禁用（404），任何人不得借道重置。"""
        client, admin_name, _ = authFace
        resp = _recover(client, admin_name, "whatever-guess")
        assert resp.status_code == 404, f"未配置口令应 404 禁用，实得 {resp.status_code}: {resp.text}"
        # 账号未被改动
        assert client.post(
            "/api/v1/auth/login", json={"username": admin_name, "password": OLD_PASSWORD}
        ).status_code == 200, "端点禁用后原口令必须仍可用"

    def test_empty_injected_password_disables_endpoint(self, authFace, monkeypatch):
        """注入空串视同未配置——杜绝 `compare_digest("", "")` 式放行。"""
        client, admin_name, _ = authFace
        monkeypatch.setenv(ENV_NAME, "   ")
        resp = _recover(client, admin_name, "")
        assert resp.status_code == 404, f"空口令注入应视同未配置（404），实得 {resp.status_code}"

    def test_injected_password_resets_admin(self, authFace, monkeypatch):
        """注入口令 + admin 账号 + 口令对上 ⇒ 重置成功，新口令可登录、旧口令失效。"""
        client, admin_name, _ = authFace
        monkeypatch.setenv(ENV_NAME, INJECTED_SECRET)
        resp = _recover(client, admin_name, INJECTED_SECRET)
        assert resp.status_code == 200, f"注入口令命中应放行，实得 {resp.status_code}: {resp.text}"
        assert client.post(
            "/api/v1/auth/login", json={"username": admin_name, "password": NEW_PASSWORD}
        ).status_code == 200, "重置写进去了却没被登录读到——闭环未成立"
        assert client.post(
            "/api/v1/auth/login", json={"username": admin_name, "password": OLD_PASSWORD}
        ).status_code == 401, "旧口令仍可用，说明密码根本没被改写"

    def test_hit_notifies_all_admins_and_audits_critical(self, authFace, monkeypatch):
        """命中是重大安全事件：必须通知全部管理员，且审计事件级别为 CRITICAL。"""
        import neurova.api.endpoints.notifications as NOTIF
        import neurova.security.audit_logger as AUD

        client, admin_name, _ = authFace
        monkeypatch.setenv(ENV_NAME, INJECTED_SECRET)

        notified = []
        monkeypatch.setattr(
            NOTIF, "notify_admins",
            lambda title, message, notification_type="info", data=None: notified.append((title, message)),
        )
        logged = []
        fake_logger = mock.Mock()
        fake_logger.log = lambda entry: logged.append(entry) or True
        monkeypatch.setattr(AUD, "get_audit_logger", lambda db_path=None: fake_logger)

        resp = _recover(client, admin_name, INJECTED_SECRET)
        assert resp.status_code == 200, resp.text
        assert notified, "命中后未通知管理员"
        assert logged, "命中后未写审计事件"
        from neurova.security.audit_logger import AuditSeverity
        assert any(e.severity == AuditSeverity.CRITICAL for e in logged), (
            f"审计事件未升 CRITICAL: {[str(e.severity) for e in logged]}"
        )

    def test_non_admin_with_correct_secret_refused(self, authFace, monkeypatch):
        client, _, member_name = authFace
        monkeypatch.setenv(ENV_NAME, INJECTED_SECRET)
        resp = _recover(client, member_name, INJECTED_SECRET)
        assert resp.status_code == 400, f"非 admin 应被拒（400），实得 {resp.status_code}"
        assert client.post(
            "/api/v1/auth/login", json={"username": member_name, "password": OLD_PASSWORD}
        ).status_code == 200, "拒绝却已经把普通账号口令改掉了"

    def test_wrong_secret_refused(self, authFace, monkeypatch):
        client, admin_name, _ = authFace
        monkeypatch.setenv(ENV_NAME, INJECTED_SECRET)
        resp = _recover(client, admin_name, "d3finitely-n0t-injected")
        assert resp.status_code == 400, f"口令不正确应回 400，实得 {resp.status_code}"
        assert client.post(
            "/api/v1/auth/login", json={"username": admin_name, "password": OLD_PASSWORD}
        ).status_code == 200, "口令校验失败却改动了管理员账号"

    def test_server_deployment_without_injection_stays_closed(self, authFace, monkeypatch):
        """服务端形态未注入口令同样禁用——服务器绝不因默认口令被接管。"""
        client, admin_name, _ = authFace
        _setServer(monkeypatch)
        monkeypatch.delenv(ENV_NAME, raising=False)
        resp = _recover(client, admin_name, "whatever-guess")
        assert resp.status_code == 404, f"服务端未注入应 404，实得 {resp.status_code}"


# ─────────────────────────── P1-6 ───────────────────────────


class TestServerFacingRegistrationClosed:
    def test_server_deployment_refuses_send_code(self, authFace, monkeypatch):
        """服务端部署形态：自注册关闭——验证码端点 403，不生成也不返回 dev_code。"""
        client, _, _ = authFace
        _setServer(monkeypatch)
        resp = client.post("/api/v1/auth/register/send-code", params={"email": "s2@example.com"})
        assert resp.status_code == 403, (
            f"服务端形态应 403 关闭自注册，实得 {resp.status_code}: {resp.text}"
        )
        assert "dev_code" not in resp.text, "服务端形态仍把验证码回给了响应"

    def test_desktop_form_keeps_honest_dev_code(self, authFace, monkeypatch):
        """桌面形态维持上轮 P2-3 的诚实返回：dev_code 随响应、明示未发邮件。"""
        client, _, _ = authFace
        _setDesktop(monkeypatch)
        resp = client.post("/api/v1/auth/register/send-code", params={"email": "s2desk@example.com"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("data", {}).get("dev_code"), f"桌面形态丢了 dev_code: {body}"


# ────────────────────── 500 detail 信息泄露 ──────────────────────


class TestErrorDetailsDoNotLeakExceptionText:
    def test_error_details_no_longer_carry_exception_text(self):
        """500 detail 不得拼 `str(e)`（7 处同根因）：异常详情只进日志。"""
        src = AUTH_SOURCE.read_text(encoding="utf-8")
        offenders = [
            (i + 1, line.strip())
            for i, line in enumerate(src.splitlines())
            if "{str(e)}" in line
        ]
        assert offenders == [], f"auth.py 仍把异常原文拼进响应 detail（行 {[l for l, _ in offenders]}）"
