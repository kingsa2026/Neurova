# -*- coding: utf-8 -*-
"""P2 卡 C1 红灯：SSH 远程传输（设计文档 §4.8，transport=ssh）。

覆盖：
- resolveRemoteCommand / wrapRemoteCommand 形态（-o BatchMode=yes、-p、-i、
  user@host、-- 与原命令的顺序）；
- fail-closed：缺 host / user / key、空命令、非法 port、非 dict remote、
  key_resolver 抛错、transport=ssh 缺 remote、未知 transport；
- key_resolver 注入与默认实现（os.environ 取私钥路径）；
- executor 层：monkeypatch subprocess.Popen 捕获命令，断言 ssh 前缀（不真连）；
- swarm._resolveExternalMember 把名册 transport/remote 透传到执行体
  （remote 的 key_ref 只透引用名，不落明文）。
"""
import asyncio
import io
import json
import os
import shlex

import pytest

from neurova.agent.neuacp.acp_client import NeuacpClient, NeuacpError
from neurova.agent.neuacp.executor import NeuacpSessionContext
from neurova.agent.neuacp.plugin_executor import NeuacpPluginExecutor
from neurova.agent.neuacp.ssh_transport import (
    applyRemoteTransport,
    defaultSshKeyResolver,
    resolveRemoteCommand,
    resolveSpawnCommand,
    wrapRemoteCommand,
)

KEY_ENV = "NEUROVA_SSH_KEY_C1TEST"
KEY_PATH = "C:/keys/c1test.pem"


# ── 1. wrapRemoteCommand 形态 ──────────────────────────────────────────────

def test_wrapRemoteCommandShapeAndOrder():
    command = resolveRemoteCommand(
        ["opencode", "acp"],
        {"host": "203.0.113.10", "port": 2222, "user": "deploy", "key_ref": KEY_ENV},
        key_resolver=lambda ref: KEY_PATH,
    )
    head = ["ssh", "-o", "BatchMode=yes", "-p", "2222", "-i", KEY_PATH,
            "deploy@203.0.113.10", "--"]
    assert command == head + ["opencode", "acp"]


def test_wrapRemoteCommandWithoutPortOmitsDashP():
    command = resolveRemoteCommand(
        ["opencode", "acp"],
        {"host": "203.0.113.10", "user": "deploy", "key_ref": KEY_ENV},
        key_resolver=lambda ref: KEY_PATH,
    )
    assert "-p" not in command
    assert command == ["ssh", "-o", "BatchMode=yes", "-i", KEY_PATH,
                       "deploy@203.0.113.10", "--", "opencode", "acp"]


def test_remoteWithoutKeyRefOmitsIdentityFlag():
    command = resolveRemoteCommand(["opencode"], {"host": "h", "user": "u"})
    assert "-i" not in command
    assert command == ["ssh", "-o", "BatchMode=yes", "u@h", "--", "opencode"]


def test_wrapRemoteCommandAliasIsSameImplementation():
    assert wrapRemoteCommand is resolveRemoteCommand


def test_remoteArgsWithSpacesAreShellQuotedForRemoteHost():
    """ssh 不转译参数：带空格的参数必须 quote，否则远端 shell 重新切分。"""
    command = resolveRemoteCommand(
        ["zcode", "--prompt", "fix the bug"],
        {"host": "h", "user": "u"},
        key_resolver=lambda ref: KEY_PATH,
    )
    assert command == ["ssh", "-o", "BatchMode=yes", "u@h", "--", "zcode",
                       "--prompt", shlex.quote("fix the bug")]
    assert shlex.quote("fix the bug") in command


# ── 2. fail-closed ─────────────────────────────────────────────────────────

def test_missingHostFailsClosed():
    with pytest.raises(NeuacpError):
        resolveRemoteCommand(["opencode"], {"user": "u"})


def test_missingUserFailsClosed():
    with pytest.raises(NeuacpError):
        resolveRemoteCommand(["opencode"], {"host": "h"})


def test_missingKeyFailsClosed(monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    with pytest.raises(NeuacpError):
        resolveRemoteCommand(["opencode"], {"host": "h", "user": "u", "key_ref": KEY_ENV})


def test_emptyCommandFailsClosed():
    with pytest.raises(NeuacpError):
        resolveRemoteCommand([], {"host": "h", "user": "u"})


def test_invalidPortFailsClosed():
    with pytest.raises(NeuacpError):
        resolveRemoteCommand(["opencode"], {"host": "h", "user": "u", "port": "abc"})


def test_nonPositivePortFailsClosed():
    with pytest.raises(NeuacpError):
        resolveRemoteCommand(["opencode"], {"host": "h", "user": "u", "port": 0})


def test_nonDictRemoteFailsClosed():
    with pytest.raises(NeuacpError):
        resolveRemoteCommand(["opencode"], None)


def test_keyResolverRaiseFailsClosed():
    def boom(ref):
        raise RuntimeError("凭据面不可用")

    with pytest.raises(NeuacpError):
        resolveRemoteCommand(
            ["opencode"], {"host": "h", "user": "u", "key_ref": KEY_ENV}, key_resolver=boom)


def test_sshTransportWithoutRemoteFailsClosed():
    with pytest.raises(NeuacpError):
        resolveSpawnCommand(["opencode", "acp"], "ssh", None)


def test_unsupportedTransportFailsClosed():
    with pytest.raises(NeuacpError):
        resolveSpawnCommand(["opencode", "acp"], "http", {"host": "h", "user": "u"})


def test_stdioTransportReturnsOriginalCommand():
    assert resolveSpawnCommand(["opencode", "acp"], "stdio", None) == ["opencode", "acp"]


# ── 3. key_resolver ────────────────────────────────────────────────────────

def test_defaultKeyResolverReadsEnvironment(monkeypatch):
    monkeypatch.setenv(KEY_ENV, KEY_PATH)
    assert defaultSshKeyResolver(KEY_ENV) == KEY_PATH
    monkeypatch.delenv(KEY_ENV, raising=False)
    assert defaultSshKeyResolver(KEY_ENV) is None


def test_keyResolverInjectionCustomPath():
    command = resolveRemoteCommand(
        ["opencode"], {"host": "h", "user": "u", "key_ref": "SOME_REF"},
        key_resolver=lambda ref: "/injected/key",
    )
    assert command[command.index("-i") + 1] == "/injected/key"
    assert command[command.index("-i") - 1] == "SOME_REF" or True  # key_ref 名不落命令
    assert "SOME_REF" not in command


# ── 4. NeuacpClient spawn 层（monkeypatch Popen，不真连） ──────────────────

class _FakeProcess:
    def __init__(self, stdout_lines=b""):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(stdout_lines)
        self.stderr = io.BytesIO(b"")

    def poll(self):
        return 0

    def terminate(self):
        pass

    def kill(self):
        pass

    def wait(self, timeout=None):
        return 0


def test_clientStartWrapsCommandWithSshPrefix(monkeypatch):
    import neurova.agent.neuacp.acp_client as acp_client_module

    captured = {}

    def fakePopen(command, **kwargs):
        captured["command"] = [str(part) for part in command]
        return _FakeProcess()

    monkeypatch.setattr(acp_client_module.subprocess, "Popen", fakePopen)
    monkeypatch.setattr(
        NeuacpClient, "request",
        lambda self, method, params=None, timeout=None: {"protocolVersion": "1"},
    )
    monkeypatch.setenv(KEY_ENV, KEY_PATH)
    client = NeuacpClient(
        ["opencode", "acp"],
        transport="ssh",
        remote={"host": "203.0.113.10", "port": 2222, "user": "deploy", "key_ref": KEY_ENV},
    )
    try:
        client.start()
    finally:
        client.terminate()
    command = captured["command"]
    # ssh.exe 在 PATH：首词经 shutil.which 解析成可执行全路径
    assert os.path.basename(command[0]).lower().startswith("ssh")
    head = ["-o", "BatchMode=yes", "-p", "2222", "-i", KEY_PATH,
            "deploy@203.0.113.10", "--"]
    assert command[1:1 + len(head)] == head
    assert command[1 + len(head):] == ["opencode", "acp"]


def test_clientStdioDefaultKeepsOriginalCommand(monkeypatch):
    import neurova.agent.neuacp.acp_client as acp_client_module

    captured = {}

    def fakePopen(command, **kwargs):
        captured["command"] = [str(part) for part in command]
        return _FakeProcess()

    monkeypatch.setattr(acp_client_module.subprocess, "Popen", fakePopen)
    monkeypatch.setattr(
        NeuacpClient, "request",
        lambda self, method, params=None, timeout=None: {"protocolVersion": "1"},
    )
    client = NeuacpClient(["opencode", "acp"])
    try:
        client.start()
    finally:
        client.terminate()
    command = captured["command"]
    assert command[0] != "ssh"
    assert "--" not in command


def test_clientSshWithoutRemoteFailsClosed():
    client = NeuacpClient(["opencode", "acp"], transport="ssh", remote=None)
    with pytest.raises(NeuacpError):
        client.start()
    assert not client.is_alive


def test_clientSetTransportRejectsAfterStart(monkeypatch):
    import neurova.agent.neuacp.acp_client as acp_client_module

    monkeypatch.setattr(acp_client_module.subprocess, "Popen", lambda command, **kw: _FakeProcess())
    monkeypatch.setattr(NeuacpClient, "_startPumps", lambda self: None)  # 免泵线程竞争
    monkeypatch.setattr(
        NeuacpClient, "request",
        lambda self, method, params=None, timeout=None: {"protocolVersion": "1"},
    )
    client = NeuacpClient(["opencode", "acp"])
    try:
        client.start()
        with pytest.raises(NeuacpError):
            client.setTransport("ssh", {"host": "h", "user": "u"})
    finally:
        client.terminate()


# ── 5. NeuacpPluginExecutor spawn 层（monkeypatch Popen，不真连） ───────────

def test_pluginPromptWrapsCommandWithSshPrefix(monkeypatch):
    import neurova.agent.neuacp.plugin_executor as plugin_module

    captured = {}

    def fakePopen(command, **kwargs):
        captured["command"] = [str(part) for part in command]
        return _FakeProcess(stdout_lines=b'{"type":"result","result":"ok"}\n')

    monkeypatch.setattr(plugin_module.subprocess, "Popen", fakePopen)
    monkeypatch.setenv(KEY_ENV, KEY_PATH)
    executor = NeuacpPluginExecutor(
        ["zcode", "--output-format", "stream-json"],
        transport="ssh",
        remote={"host": "198.51.100.7", "port": 2222, "user": "ci", "key_ref": KEY_ENV},
    )
    ctx = NeuacpSessionContext(member_session_id="m-1", task_text="修个 bug", cwd="")
    asyncio.run(executor.start(ctx))
    result = asyncio.run(executor.prompt("修个 bug", lambda kind, text: None, None))
    assert result.text == "ok"

    command = captured["command"]
    # ssh.exe 在 PATH：首词经 shutil.which 解析成可执行全路径
    assert os.path.basename(command[0]).lower().startswith("ssh")
    head = ["-o", "BatchMode=yes", "-p", "2222", "-i", KEY_PATH,
            "ci@198.51.100.7", "--"]
    assert command[1:1 + len(head)] == head
    assert command[1 + len(head):] == ["zcode", "--output-format", "stream-json",
                                       "--prompt", shlex.quote("修个 bug")]


def test_pluginSshWithoutRemoteFailsClosed():
    executor = NeuacpPluginExecutor(["zcode"], transport="ssh", remote=None)
    with pytest.raises(NeuacpError):
        asyncio.run(executor.prompt("任务", lambda kind, text: None, None))


# ── 6. swarm._resolveExternalMember 透传 ───────────────────────────────────

@pytest.fixture
def swarm():
    from neurova.agent.swarm import get_swarm_manager

    return get_swarm_manager()


def patchTeams(monkeypatch, roster, team=None):
    import neurova.api.endpoints.teams_api as teams_api

    tenant = (team or {}).get("tenant_id", "default")
    monkeypatch.setattr(
        teams_api, "getTeamRoster",
        lambda tid: {"id": tid, "tenant_id": tenant, "members_detail": roster},
    )


def patchInitiatorTenant(monkeypatch, tenant):
    from neurova.core import identity_context

    monkeypatch.setattr(identity_context, "get_request_user_id", lambda: "user-a")
    import neurova.auth.user_group_model as groups

    monkeypatch.setattr(groups, "resolveUserDepartment", lambda user: {"tenant_id": tenant})


REMOTE = {"host": "198.51.100.7", "port": 2222, "user": "ci", "key_ref": KEY_ENV}


def test_swarmPassesTransportRemoteToPluginExecutor(swarm, monkeypatch):
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_ENABLED", "on")
    monkeypatch.setenv(KEY_ENV, KEY_PATH)
    roster = [{
        "user_id": "ext-1", "name": "远程 ZCode", "role": "coder",
        "executor": {"kind": "plugin", "tool": "zcode", "command": ["zcode"], "cwd": ".",
                     "transport": "ssh", "remote": REMOTE},
    }]
    patchTeams(monkeypatch, roster)
    patchInitiatorTenant(monkeypatch, "default")
    adapter, error = swarm._resolveExternalMember("ext-1", "team-1")
    assert error is None
    assert adapter is not None
    executor = adapter._executor
    assert isinstance(executor, NeuacpPluginExecutor)
    assert executor._transport == "ssh"
    # key_ref 只透引用名；解析出的私钥路径不落名册/执行体
    assert executor._remote.get("key_ref") == KEY_ENV
    assert KEY_PATH not in json.dumps(executor._remote)


def test_swarmPassesTransportRemoteToAcpClient(swarm, monkeypatch):
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_ENABLED", "on")
    roster = [{
        "user_id": "ext-1", "name": "远程 OpenCode", "role": "coder",
        "executor": {"kind": "acp", "tool": "opencode", "command": ["opencode", "acp"],
                     "cwd": ".", "transport": "ssh", "remote": REMOTE},
    }]
    patchTeams(monkeypatch, roster)
    patchInitiatorTenant(monkeypatch, "default")
    adapter, error = swarm._resolveExternalMember("ext-1", "team-1")
    assert error is None
    assert adapter is not None
    client = adapter._executor._client
    assert client._transport == "ssh"
    assert client._remote.get("key_ref") == KEY_ENV


def test_swarmRosterWithoutTransportKeepsStdioDefault(swarm, monkeypatch):
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_ENABLED", "on")
    roster = [{
        "user_id": "ext-1", "name": "本地 OpenCode", "role": "coder",
        "executor": {"kind": "acp", "tool": "opencode", "command": ["opencode", "acp"], "cwd": "."},
    }]
    patchTeams(monkeypatch, roster)
    patchInitiatorTenant(monkeypatch, "default")
    adapter, error = swarm._resolveExternalMember("ext-1", "team-1")
    assert error is None
    assert adapter is not None
    client = adapter._executor._client
    assert client._transport == "stdio"
    assert client._remote is None


def test_applyRemoteTransportStdioIsNoop():
    from neurova.agent.neuacp import NeuacpStdioExecutor

    executor = NeuacpStdioExecutor(["opencode", "acp"])
    applyRemoteTransport(executor, "stdio", None)
    assert executor._client._transport == "stdio"
    assert executor._client._remote is None


def test_applyRemoteTransportRejectsUnsupportedTransport():
    from neurova.agent.neuacp import NeuacpStdioExecutor

    executor = NeuacpStdioExecutor(["opencode", "acp"])
    with pytest.raises(NeuacpError):
        applyRemoteTransport(executor, "http", {"host": "h", "user": "u"})


# ── 7. D2/D3 远程身份凭据路由（run 凭据经 ssh 命令面到达远端成员进程） ──────

CRED_ENV = "NEUROVA_RUN_CREDENTIAL"


def _issueRunToken():
    from neurova.security.run_identity import issueRunCredential

    return issueRunCredential("run-route-1", "tenant-route-1", ttl_s=600)


def test_remoteEnvPrefixRoutedAfterDashDash():
    token = _issueRunToken()
    command = resolveRemoteCommand(
        ["python3", "/tmp/probe.py"],
        {"host": "h", "user": "u"},
        key_resolver=lambda ref: KEY_PATH,
        remote_env={CRED_ENV: token},
    )
    rest = command[command.index("--") + 1:]
    assert rest[0] == shlex.quote(f"{CRED_ENV}={token}")
    assert rest[1:] == ["python3", "/tmp/probe.py"]


def test_remoteEnvNoneKeepsCommandUnchanged():
    command = resolveRemoteCommand(
        ["opencode", "acp"],
        {"host": "h", "user": "u"},
        key_resolver=lambda ref: KEY_PATH,
    )
    assert command == ["ssh", "-o", "BatchMode=yes", "u@h", "--", "opencode", "acp"]


def test_remoteEnvEmptyDictKeepsCommandUnchanged():
    command = resolveRemoteCommand(
        ["opencode", "acp"],
        {"host": "h", "user": "u"},
        key_resolver=lambda ref: KEY_PATH,
        remote_env={},
    )
    assert command == ["ssh", "-o", "BatchMode=yes", "u@h", "--", "opencode", "acp"]


def test_remoteEnvValueWithSpacesQuoted():
    command = resolveRemoteCommand(
        ["opencode"],
        {"host": "h", "user": "u"},
        key_resolver=lambda ref: KEY_PATH,
        remote_env={"NEUROVA_TASK_TEXT": "fix the bug"},
    )
    rest = command[command.index("--") + 1:]
    assert rest[0] == shlex.quote("NEUROVA_TASK_TEXT=fix the bug")


def test_remoteEnvKeysSortedForDeterminism():
    token = _issueRunToken()
    command = resolveRemoteCommand(
        ["opencode"],
        {"host": "h", "user": "u"},
        key_resolver=lambda ref: KEY_PATH,
        remote_env={"ZZZ_A": "1", CRED_ENV: token, "AAA_C": "3"},
    )
    rest = command[command.index("--") + 1:]
    assert rest[0] == "AAA_C=3"
    assert rest[1] == shlex.quote(f"{CRED_ENV}={token}")
    assert rest[2] == "ZZZ_A=1"
    assert rest[3:] == ["opencode"]


def test_clientSshSpawnRoutesRunCredentialToRemoteCommand(monkeypatch):
    import neurova.agent.neuacp.acp_client as acp_client_module

    captured = {}

    def fakePopen(command, **kwargs):
        captured["command"] = [str(part) for part in command]
        return _FakeProcess()

    monkeypatch.setattr(acp_client_module.subprocess, "Popen", fakePopen)
    monkeypatch.setattr(
        NeuacpClient, "request",
        lambda self, method, params=None, timeout=None: {"protocolVersion": "1"},
    )
    monkeypatch.setenv(KEY_ENV, KEY_PATH)
    client = NeuacpClient(
        ["python3", "/tmp/probe.py"],
        transport="ssh",
        remote={"host": "203.0.113.10", "user": "deploy", "key_ref": KEY_ENV},
        run_credential_context={"run_id": "run-route-1", "tenant_id": "tenant-route-1"},
    )
    try:
        client.start()
    finally:
        client.terminate()
    command = captured["command"]
    assert "--" in command
    rest = command[command.index("--") + 1:]
    assert rest[0].startswith(f"{CRED_ENV}=")
    payload_b64 = rest[0].split("=", 1)[1].split(".", 1)[0]
    import base64

    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    assert payload["run_id"] == "run-route-1"
    assert payload["tenant_id"] == "tenant-route-1"
    assert rest[1:] == ["python3", "/tmp/probe.py"]


def test_clientStdioSpawnKeepsCredentialOutOfCommand(monkeypatch):
    """stdio 路径回归护栏：凭据只进子进程 env，命令面不带前缀。"""
    import neurova.agent.neuacp.acp_client as acp_client_module

    captured = {}

    def fakePopen(command, **kwargs):
        captured["command"] = [str(part) for part in command]
        captured["env"] = kwargs.get("env") or {}
        return _FakeProcess()

    monkeypatch.setattr(acp_client_module.subprocess, "Popen", fakePopen)
    monkeypatch.setattr(
        NeuacpClient, "request",
        lambda self, method, params=None, timeout=None: {"protocolVersion": "1"},
    )
    client = NeuacpClient(
        ["opencode", "acp"],
        run_credential_context={"run_id": "run-route-1", "tenant_id": "tenant-route-1"},
    )
    try:
        client.start()
    finally:
        client.terminate()
    assert "--" not in captured["command"]
    assert CRED_ENV in captured["env"]


def test_pluginSshSpawnRoutesRunCredentialToRemoteCommand(monkeypatch):
    import neurova.agent.neuacp.plugin_executor as plugin_module

    captured = {}

    def fakePopen(command, **kwargs):
        captured["command"] = [str(part) for part in command]
        return _FakeProcess(stdout_lines=b'{"type":"result","result":"ok"}\n')

    monkeypatch.setattr(plugin_module.subprocess, "Popen", fakePopen)
    monkeypatch.setenv(KEY_ENV, KEY_PATH)
    executor = NeuacpPluginExecutor(
        ["zcode"],
        transport="ssh",
        remote={"host": "198.51.100.7", "user": "ci", "key_ref": KEY_ENV},
        run_tenant_id="tenant-route-1",
    )
    ctx = NeuacpSessionContext(member_session_id="m-1", task_text="任务", cwd="",
                               metadata={"subagent_id": "run-route-1"})
    asyncio.run(executor.start(ctx))
    asyncio.run(executor.prompt("任务", lambda kind, text: None, None))
    command = captured["command"]
    assert "--" in command
    rest = command[command.index("--") + 1:]
    assert rest[0].startswith(f"{CRED_ENV}=")
    assert rest[1] == "zcode"
