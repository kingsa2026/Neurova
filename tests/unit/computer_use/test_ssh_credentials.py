"""SSH 多主机凭据（按 host 分键）+ 执行 + API

验收：
- 凭据存储：set/get/list（脱敏，不回显密钥/密码）/delete，多主机互不串
- ssh_runner：key_text 优先（pkey 注入）、resolve 按 host 读
- API：POST 校验 host+凭据、GET 脱敏列表、DELETE；按当前用户分桶
"""

import pytest

from neurova.web_reach.credentials import UserCredentialStore


@pytest.fixture
def store(tmp_path):
    return UserCredentialStore(base_dir=str(tmp_path / "creds"), encryption_key="k" * 32)


class TestSSHHostCredentials:
    def test_set_get_roundtrip(self, store):
        assert store.set_ssh_host("u1", "10.0.0.5", user="root", port=22, password="pw")
        cfg = store.get_ssh_host("u1", "10.0.0.5")
        assert cfg["user"] == "root" and cfg["password"] == "pw" and cfg["port"] == 22

    def test_multi_host_isolation(self, store):
        store.set_ssh_host("u1", "host-a", user="ua", password="pa")
        store.set_ssh_host("u1", "host-b", user="ub", key_text="KEYB")
        assert store.get_ssh_host("u1", "host-a")["user"] == "ua"
        assert store.get_ssh_host("u1", "host-b")["key_text"] == "KEYB"
        assert store.get_ssh_host("u1", "host-a").get("key_text", "") == ""

    def test_list_masked(self, store):
        store.set_ssh_host("u1", "h1", user="root", password="secret-pw")
        store.set_ssh_host("u1", "h2", user="deploy", key_text="PRIVATEKEY")
        hosts = store.list_ssh_hosts("u1")
        names = {h["host"] for h in hosts}
        assert names == {"h1", "h2"}
        blob = str(hosts)
        assert "secret-pw" not in blob and "PRIVATEKEY" not in blob, "列表不得回显密钥/密码"
        auths = {h["host"]: h["auth"] for h in hosts}
        assert auths == {"h1": "password", "h2": "key"}

    def test_delete(self, store):
        store.set_ssh_host("u1", "h1", password="p")
        assert store.delete_ssh_host("u1", "h1")
        assert store.get_ssh_host("u1", "h1") == {}

    def test_empty_host_rejected(self, store):
        assert store.set_ssh_host("u1", "  ", password="p") is False

    def test_per_user_isolation(self, store):
        store.set_ssh_host("u1", "h1", password="p1")
        assert store.get_ssh_host("u2", "h1") == {}


class TestSSHRunnerKeyText:
    def test_key_text_preferred_as_pkey(self, monkeypatch):
        from neurova.computer_use import ssh_runner

        monkeypatch.setattr(ssh_runner, "_load_pkey", lambda t: f"PKEY<{t}>")

        class C:
            def __init__(self): self.kw = None
            def set_missing_host_key_policy(self, p): pass
            def connect(self, **kw): self.kw = kw
            def exec_command(self, cmd, timeout=None):
                class S:
                    channel = type("Ch", (), {"recv_exit_status": lambda s: 0})()
                    def read(self): return b""
                return (None, S(), S())
            def close(self): pass

        c = C()
        ssh_runner.run_ssh_command("h", "ls", user="u", key_text="ABC", password="pw", client_factory=lambda: c)
        assert c.kw["pkey"] == "PKEY<ABC>"
        assert "password" not in c.kw, "key_text 优先于 password"

    def test_bad_key_text_structured(self, monkeypatch):
        from neurova.computer_use import ssh_runner

        def boom(t):
            raise ValueError("bad key")

        monkeypatch.setattr(ssh_runner, "_load_pkey", boom)
        out = ssh_runner.run_ssh_command("h", "ls", key_text="x")
        assert out["returncode"] == -1 and "私钥解析失败" in out["stderr"]

    def test_resolve_reads_per_host(self, monkeypatch):
        from neurova.computer_use import ssh_runner

        class S:
            def get_ssh_host(self, uid, host):
                return {"user": "root", "port": 2222, "key_text": "K", "password": ""}

        monkeypatch.setattr("neurova.web_reach.credentials.get_credential_store", lambda *a, **k: S())
        creds = ssh_runner.resolve_ssh_credentials("u1", "h1")
        assert creds["user"] == "root" and creds["port"] == 2222 and creds["key_text"] == "K"


class TestSSHCredentialAPI:
    @pytest.fixture
    def client(self, tmp_path):
        from fastapi import FastAPI
        from starlette.testclient import TestClient
        from neurova.api.endpoints.settings import router
        from neurova.api.deps import get_current_user
        from neurova.web_reach import credentials as cred
        from neurova.web_reach.credentials import UserCredentialStore

        # 隔离到 tmp：API 测试不得写真实 data/web_reach_credentials
        cred._credential_store_instance = UserCredentialStore(
            base_dir=str(tmp_path / "creds"), encryption_key="k" * 32
        )
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "api-u", "role": "user"}
        yield TestClient(app)
        cred._credential_store_instance = None

    def test_post_get_delete(self, client):
        r = client.post("/v1/settings/ssh-credentials", json={"host": "1.2.3.4", "user": "root", "password": "pw"})
        assert r.status_code == 200, r.text
        lst = client.get("/v1/settings/ssh-credentials").json()["data"]["hosts"]
        assert any(h["host"] == "1.2.3.4" for h in lst)
        assert "pw" not in str(lst)
        assert client.delete("/v1/settings/ssh-credentials/1.2.3.4").status_code == 200

    def test_post_requires_credential(self, client):
        r = client.post("/v1/settings/ssh-credentials", json={"host": "x", "user": "u"})
        assert r.status_code == 422

    def test_post_requires_host(self, client):
        r = client.post("/v1/settings/ssh-credentials", json={"host": "", "password": "p"})
        assert r.status_code in (422, 400)
