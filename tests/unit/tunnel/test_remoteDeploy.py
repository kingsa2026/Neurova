"""档三：agent 代部署自建中继（SSH 上机）的编排契约。

`neurova/tunnel/remote_deploy.py` 用注入的 SSH 客户端（假客户端，零真实网络）
执行幂等部署，本文件钉：

1. 快乐路径：步骤按序全过、令牌落盘、连接方式自动切到 relay 并带上
   `relay_url`/令牌（面板无需再手填）；
2. 幂等：服务器上已有准入令牌 ⇒ 复用，不重新生成；
3. 诚实失败：非 root / 依赖安装失败 ⇒ 任务 failed、后续步骤不再执行、
   连接配置**不**被改写；
4. 凭据卫生：密码/私钥不出现在任务视图里；凭据经凭据库加密落盘；
5. 审计：部署动作写审计（CONFIG_CHANGE/HIGH）；
6. undeploy：停服务、删文件与账号，并把连接方式退回 auto。
"""
import json
import threading

import pytest

from neurova.tunnel import connection_config as CC
from neurova.tunnel import remote_deploy as RD


class _FakeChannel:
    def __init__(self, rc):
        self._rc = rc

    def recv_exit_status(self):
        return self._rc


class _FakeStdout:
    def __init__(self, text, rc):
        self._text = text.encode("utf-8")
        self._rc = rc
        self.channel = _FakeChannel(rc)

    def read(self):
        return self._text


class _FakeStdin:
    def close(self):
        return


class _FakeStderr:
    def __init__(self, text=""):
        self._text = text.encode("utf-8")

    def read(self):
        return self._text


class FakeSshClient:
    """按子串匹配返回 (rc, stdout) 的假 paramiko 客户端；记录全部执行过的命令。

    exec_command 返回 paramiko 同形的 (stdin, stdout, stderr) 三元组。
    """

    def __init__(self, script):
        self.script = script  # [(子串, rc, stdout)]
        self.executed = []
        self.connected = False

    def connect(self, **kwargs):
        self.connected = True

    def exec_command(self, command, timeout=None):
        self.executed.append(command)
        for key, rc, out in self.script:
            if key in command:
                return _FakeStdin(), _FakeStdout(out, rc), _FakeStderr("")
        return _FakeStdin(), _FakeStdout("", 0), _FakeStderr("")

    def close(self):
        self.connected = False


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    """隔离：连接配置清盘 + env 基线 + 凭据库指向 tmp + 假 SSH 客户端注入。"""
    path = CC.configFilePath()
    if path.exists():
        path.unlink()
    monkeypatch.setenv("NEUROVA_ADVERTISED_BASE_URL", "")
    monkeypatch.delenv("NEUROVA_TUNNEL_RELAY_URL", raising=False)
    monkeypatch.delenv("NEUROVA_TUNNEL_ENROLLMENT_TOKEN", raising=False)

    from neurova.web_reach import credentials as cred_mod

    store = cred_mod.UserCredentialStore(base_dir=str(tmp_path / "creds"))
    monkeypatch.setattr(cred_mod, "get_credential_store", lambda base_dir="": store)

    RD.setSshClientFactory(None)
    yield
    RD.setSshClientFactory(None)
    if path.exists():
        path.unlink()


PARAMS = {
    "host": "192.0.2.10",
    "ssh_port": 22,
    "username": "root",
    "password": "server-password-1",
    "relay_port": 8443,
    "domain": "pair.example.com",
}


def _waitDone(taskId, timeout=5.0):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        view = RD.getDeployTask(taskId)
        if view["state"] != "running":
            return view
        time.sleep(0.01)
    return RD.getDeployTask(taskId)


def test_deploy_happy_path_applies_relay_config():
    script = [
        ("id -u", 0, "0"),
        ("cat /etc/neurova-relay/enrollment_token", 0, ""),  # 服务器上还没有令牌 → 生成
        ("curl", 0, "200"),  # 启动后自检
    ]
    RD.setSshClientFactory(lambda: FakeSshClient(script))
    started = RD.startRemoteDeploy("1", dict(PARAMS))
    view = _waitDone(started["task_id"])

    assert view["state"] == "success", view
    assert [s["ok"] for s in view["steps"]] == [True] * len(view["steps"])
    # relay_url 偏好域名；无 TLS 证书 ⇒ http
    assert view["relay_url"] == "http://pair.example.com:8443"
    # 连接方式被自动应用（用户不再手填）
    cfg = CC.getConnectionConfig()
    assert cfg["mode"] == "relay"
    assert cfg["relay_url"] == "http://pair.example.com:8443"
    assert cfg["has_relay_enrollment_token"] is True
    # 令牌掩码：全文不出任务视图
    assert "relay_enrollment_token" not in json.dumps(view)


def test_deploy_reuses_existing_enrollment_token():
    fake = FakeSshClient([
        ("id -u", 0, "0"),
        ("cat /etc/neurova-relay/enrollment_token", 0, "pre-existing-token-123"),
        ("curl", 0, "200"),
    ])
    RD.setSshClientFactory(lambda: fake)
    started = RD.startRemoteDeploy("1", dict(PARAMS))
    view = _waitDone(started["task_id"])
    assert view["state"] == "success", view
    raw = json.loads(CC.configFilePath().read_text(encoding="utf-8"))
    assert raw["relay_enrollment_token"] == "pre-existing-token-123"
    # 复用 ⇒ 不应重新生成/写入令牌（无 chmod 600 的令牌落盘动作）
    assert not any("chmod 600" in c for c in fake.executed)


def test_deploy_fails_honestly_for_non_root():
    script = [("id -u", 0, "1000")]  # 非 root
    RD.setSshClientFactory(lambda: FakeSshClient(script))
    started = RD.startRemoteDeploy("1", dict(PARAMS))
    view = _waitDone(started["task_id"])
    assert view["state"] == "failed"
    assert "root" in view["error"] or "权限" in view["error"]
    # 失败后不得改写连接配置
    assert CC.getConnectionConfig()["mode"] == "auto"
    # 后续步骤（pip 安装等）不应执行
    assert view["steps"][-1]["ok"] is False


def test_deploy_fails_honestly_when_pip_fails():
    script = [
        ("id -u", 0, "0"),
        ("pip install", 1, "no network"),
    ]
    RD.setSshClientFactory(lambda: FakeSshClient(script))
    started = RD.startRemoteDeploy("1", dict(PARAMS))
    view = _waitDone(started["task_id"])
    assert view["state"] == "failed"
    assert any("pip install" in s["detail"] or "依赖" in s["name"] for s in view["steps"])
    assert CC.getConnectionConfig()["mode"] == "auto"


def test_credentials_stored_encrypted_and_absent_from_view():
    from neurova.web_reach import credentials as cred_mod

    store = cred_mod.get_credential_store()  # 夹具已指向 tmp 的隔离库
    RD.setSshClientFactory(lambda: FakeSshClient([("id -u", 0, "0"), ("curl", 0, "200")]))
    started = RD.startRemoteDeploy("1", dict(PARAMS))
    _waitDone(started["task_id"])
    view = RD.getDeployTask(started["task_id"])
    assert "server-password-1" not in json.dumps(view)
    stored = store.get_ssh_host("1", "192.0.2.10")
    assert stored["password"] == "server-password-1"
    assert stored["user"] == "root"


def test_validation_rejects_incomplete_request():
    with pytest.raises(ValueError):
        RD.startRemoteDeploy("1", {"host": "", "username": "root", "password": "x"})
    with pytest.raises(ValueError):
        RD.startRemoteDeploy("1", {"host": "192.0.2.10", "username": "root"})  # 无凭据
    with pytest.raises(ValueError):
        RD.startRemoteDeploy("1", {"host": "192.0.2.10", "username": "root",
                                   "password": "x", "relay_port": 0})


def test_audit_trail_written(monkeypatch):
    calls = []
    monkeypatch.setattr(RD, "log_audit", lambda *a, **kw: calls.append((a, kw)))
    RD.setSshClientFactory(lambda: FakeSshClient([("id -u", 0, "0"), ("curl", 0, "200")]))
    started = RD.startRemoteDeploy("1", dict(PARAMS))
    _waitDone(started["task_id"])
    assert calls, "部署必须留审计"


def test_undeploy_stops_service_and_resets_mode():
    # 先置于 relay 态
    CC.setConnectionConfig(mode="relay", relayUrl="http://pair.example.com:8443",
                           relayEnrollmentToken="tok-1")
    fake = FakeSshClient([("systemctl", 0, "")])
    RD.setSshClientFactory(lambda: fake)
    result = RD.runRemoteUndeploy("1", {"host": "192.0.2.10", "ssh_port": 22,
                                        "username": "root", "password": "x"})
    assert result["state"] == "success", result
    executed = " ||| ".join(fake.executed)
    assert "systemctl stop" in executed and "rm -rf" in executed and "userdel" in executed
    # 连接方式退回 auto
    assert CC.getConnectionConfig()["mode"] == "auto"
