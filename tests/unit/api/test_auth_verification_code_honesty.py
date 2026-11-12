"""P2-3 注册验证码谎报与明文落日志红测（全库断点审计 2026-11-12）

证据（审计 P2-3，endpoints/auth.py:706-713）：
- `logger.info("Verification code generated for %s: %s", email, code)`——验证码
  明文落 INFO 日志（同网段日志读取者＝拿到可注册账号的验证码）；
- 随后 TODO 注释自认"实际发送邮件"从未存在，端点仍返
  "Verification code sent"——成功壳谎报（修复教义第 2 条）。

修复口径（审计开方，桌面单机形态）：
- 不再明文落日志；
- 开发码随响应诚实返回（data.dev_code），message 写明未发送邮件。

隔离：验证码模型落 SQLite（verification_codes.db），经 NEUROVA_DATA_DIR
唯一注入口指向临时目录；router 挂 /auth 前缀镜像生产装配。
"""

import os

os.environ.setdefault("NEUROVA_JWT_SECRET", "test_secret_for_p2-3_verification_honesty")
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_for_p2-3_verification_honesty")

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import auth as auth_api


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    application = FastAPI()
    application.include_router(auth_api.router, prefix="/auth")
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def _send(client, email):
    return client.post("/auth/register/send-code", params={"email": email})


class TestHonestDevCode:
    def test_dev_code_returned_in_response(self, client):
        resp = _send(client, "honest-a@example.com")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert re.fullmatch(r"\d{6}", str(data["dev_code"])), data

    def test_message_does_not_claim_email_sent(self, client):
        resp = _send(client, "honest-b@example.com")
        message = resp.json()["message"]
        assert "sent" not in message.lower(), message

    def test_code_never_logged_in_plaintext(self, client, caplog):
        with caplog.at_level("INFO", logger="neurova.api.endpoints.auth"):
            resp = _send(client, "honest-c@example.com")
        assert resp.status_code == 200
        assert "Verification code generated" not in caplog.text, caplog.text


class TestVerifyFlowStillWorks:
    def test_returned_dev_code_passes_verify(self, client):
        email = "honest-d@example.com"
        resp = _send(client, email)
        dev_code = resp.json()["data"]["dev_code"]
        verify = client.post(
            "/auth/register/verify-code", params={"email": email, "code": dev_code}
        )
        assert verify.status_code == 200
        assert verify.json()["data"]["verified"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
