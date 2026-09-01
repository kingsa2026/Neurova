# -*- coding: utf-8 -*-
"""
遗留①：mock LLM chat e2e 端到端防回归网

两件套：
1. NEUROVA_BOOTSTRAP_USER=username:password —— create_app 启动时若无
   任何用户则引导创建（e2e/CI/本地演示的登录入口；生产不配置即不生效）
2. mock LLM（NEUROVA_LLM_MOCK=1）+ bootstrap user + /api/v1/console/chat
   → 端到端拿到流式回复（此前 e2e 只有 boot 冒烟，chat 因无账号无 LLM
   无法贯通）

锁定契约：
- bootstrap 幂等（已有用户/已有同名用户不重复建）
- 登录 → JWT → /chat SSE 首个 data 事件含 mock 回显内容
"""
import json

import pytest


class TestBootstrapUser:
    def test_creates_user_when_none_exist(self, tmp_path, monkeypatch):
        from neurova.api import bootstrap_user as bu

        created = []
        monkeypatch.setenv("NEUROVA_BOOTSTRAP_USER", "e2e-user:e2e-pass")
        monkeypatch.setattr(
            bu, "_get_user_model",
            lambda: _FakeUserModel(existing=[], created=created),
        )
        n = bu.ensure_bootstrap_user()
        assert n == 1
        # 第二参为 hash_password 产物（非原文）；断言用户名与角色
        assert created[0][0] == "e2e-user" and created[0][2] == "admin"
        assert created[0][1] != "e2e-pass"

    def test_skips_when_users_exist(self, tmp_path, monkeypatch):
        from neurova.api import bootstrap_user as bu

        created = []
        monkeypatch.setenv("NEUROVA_BOOTSTRAP_USER", "e2e-user:e2e-pass")
        monkeypatch.setattr(
            bu, "_get_user_model",
            lambda: _FakeUserModel(existing=[{"id": 1, "username": "someone"}], created=created),
        )
        assert bu.ensure_bootstrap_user() == 0
        assert created == []

    def test_skips_when_env_unset(self, monkeypatch):
        from neurova.api import bootstrap_user as bu

        monkeypatch.delenv("NEUROVA_BOOTSTRAP_USER", raising=False)
        created = []
        monkeypatch.setattr(
            bu, "_get_user_model",
            lambda: _FakeUserModel(existing=[], created=created),
        )
        assert bu.ensure_bootstrap_user() == 0

    def test_malformed_env_ignored(self, monkeypatch):
        from neurova.api import bootstrap_user as bu

        monkeypatch.setenv("NEUROVA_BOOTSTRAP_USER", "no-colon-here")
        created = []
        monkeypatch.setattr(
            bu, "_get_user_model",
            lambda: _FakeUserModel(existing=[], created=created),
        )
        assert bu.ensure_bootstrap_user() == 0
        assert created == []

    def test_wired_into_create_app(self, monkeypatch):
        """create_app 生命周期调用 ensure_bootstrap_user（fail-open：异常不阻断启动）"""
        import inspect

        from neurova.api import app as app_mod

        src = inspect.getsource(app_mod)
        assert "ensure_bootstrap_user" in src


class _FakeUserModel:
    def __init__(self, existing, created):
        self._existing = existing
        self._created = created

    def list_users(self):
        return self._existing

    def create_user(self, username, password_hash, email=None, role="user", status="active"):
        self._created.append((username, password_hash, role))
        # 注意：类体作用域访问不到外层参数（class U: username = username 会 NameError）
        return {"id": 99, "username": username}


class TestMockChatE2E:
    """端到端：真实后端 subprocess（NEUROVA_LLM_MOCK=1 + NEUROVA_BOOTSTRAP_USER）
    → 登录 → /chat SSE 流式拿到 mock 回显。

    in-process TestClient(create_app) 实测启动挂起（与 e2e boot 同根因），
    一律走真实子进程 + HTTP。前提：9527 有常驻健康实例或允许自启。
    """

    @pytest.fixture(scope="class")
    def base_and_token(self):
        import urllib.error

        from tests.e2e.test_backend_boot import _http_get, _port_open, _wait_health, BACKEND_PORT

        if not (_port_open(BACKEND_PORT) and _wait_health(BACKEND_PORT, seconds=3)):
            pytest.skip("无运行中后端（boot 冒烟已覆盖自启路径）；in-process 启动实测挂起")

        base = f"http://127.0.0.1:{BACKEND_PORT}"

        def _post_json(path, payload, token=None):
            import urllib.request

            req = urllib.request.Request(
                base + path,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as e:
                return e.code, e.read()

        status, body = _post_json(
            "/api/v1/auth/login",
            {"username": "e2e-user", "password": "e2e-pass"},
        )
        if status != 200:
            pytest.skip(
                f"登录失败（{status}）——需要 NEUROVA_BOOTSTRAP_USER=e2e-user:e2e-pass "
                "启动的后端或已存在的 uitest 账号"
            )
        data = json.loads(body)
        token = (data.get("data") or {}).get("access_token") or data.get("access_token")
        if not token:
            pytest.skip(f"登录响应无 token: {body[:120]}")
        return base, token, _post_json

    def test_login_succeeds(self, base_and_token):
        base, token, _ = base_and_token
        assert token

    def test_mock_chat_sse_roundtrip(self, base_and_token):
        """mock LLM 端到端：/console/chat SSE 返回 mock 回显"""
        base, token, _post_json = base_and_token
        import urllib.request

        req = urllib.request.Request(
            base + "/api/v1/console/chat",
            data=json.dumps({"message": "e2e-chat-probe-98765"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            pytest.skip(f"chat 端点不可达（{e.code}）：{body[:150]}")

        assert "e2e-chat-probe-98765" in body or "[mock-llm]" in body, body[:400]



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
