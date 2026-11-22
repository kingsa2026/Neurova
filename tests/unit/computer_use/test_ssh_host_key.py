"""SSH 主机密钥严格校验（U1：弃 AutoAddPolicy 的 TOFU）

验收：
- publicKeyFingerprint：OpenSSH 风格 SHA256 指纹，同一 key 稳定复算
- UnknownHostKeyPolicy：未确认→HostKeyConfirmationNeeded（携带指纹、不写库）；
  已确认且匹配→放行；指纹变化→HostKeyMismatchError（fail-closed）+ 审计 HIGH
- 严格模式默认开；NEUROVA_SSH_STRICT_HOSTKEY=off 回退 AutoAddPolicy（旧行为兼容）
"""

import pytest

paramiko = pytest.importorskip("paramiko")

from neurova.computer_use import ssh_runner
from neurova.computer_use.ssh_runner import (
    HostKeyConfirmationNeeded,
    HostKeyMismatchError,
    UnknownHostKeyPolicy,
)
from neurova.security.ssh_host_store import SshHostStore, publicKeyFingerprint

FP_STORED = "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


@pytest.fixture
def store(tmp_path):
    return SshHostStore(root_dir=tmp_path / "agents")


@pytest.fixture
def server_key():
    return paramiko.RSAKey.generate(2048)


class TestPublicKeyFingerprint:
    def test_sha256_format_and_stability(self, server_key):
        fp1 = publicKeyFingerprint(server_key)
        fp2 = publicKeyFingerprint(server_key)
        assert fp1.startswith("SHA256:"), "必须是 OpenSSH 风格 SHA256 指纹"
        assert fp1 == fp2, "同一公钥指纹必须稳定"

    def test_different_keys_different_fingerprints(self):
        fp1 = publicKeyFingerprint(paramiko.RSAKey.generate(2048))
        fp2 = publicKeyFingerprint(paramiko.RSAKey.generate(2048))
        assert fp1 != fp2


class TestUnknownHostKeyPolicy:
    def test_unknown_host_raises_confirmation_and_does_not_write(self, store, server_key):
        policy = UnknownHostKeyPolicy(store, "agent-1", "h1", 22)
        with pytest.raises(HostKeyConfirmationNeeded) as ei:
            policy.missing_host_key(None, "h1", server_key)
        assert ei.value.fingerprint == publicKeyFingerprint(server_key)
        assert ei.value.host == "h1" and ei.value.port == 22
        assert ei.value.key_type == "ssh-rsa"
        assert store.lookup("agent-1", "h1", 22) is None, "确认前不得写库（TOFU 必须经用户）"

    def test_known_and_matching_key_passes(self, store, server_key):
        store.mark_confirmed("agent-1", "h1", 22, publicKeyFingerprint(server_key))
        policy = UnknownHostKeyPolicy(store, "agent-1", "h1", 22)
        policy.missing_host_key(None, "h1", server_key)  # 不抛即放行

    def test_key_change_raises_mismatch_and_audits_high(self, store, server_key, monkeypatch):
        store.mark_confirmed("agent-1", "h1", 22, FP_STORED)
        audited = []

        def fake_audit(event_type, severity, **kwargs):
            audited.append((event_type, severity, kwargs))

        monkeypatch.setattr("neurova.security.audit_logger.log_audit", fake_audit)
        policy = UnknownHostKeyPolicy(store, "agent-1", "h1", 22)
        with pytest.raises(HostKeyMismatchError) as ei:
            policy.missing_host_key(None, "h1", server_key)
        assert ei.value.stored_fingerprint == FP_STORED
        assert ei.value.fingerprint == publicKeyFingerprint(server_key)
        assert audited, "指纹变化必须落审计"
        assert str(audited[0][1]) == "AuditSeverity.HIGH" or audited[0][1].value == "high"

    def test_store_missing_policy_still_requires_confirmation(self, server_key):
        """store 为 None（极端降级）也必须 fail-closed：不确认就连不上。"""
        policy = UnknownHostKeyPolicy(None, "agent-1", "h1", 22)
        with pytest.raises(HostKeyConfirmationNeeded):
            policy.missing_host_key(None, "h1", server_key)


class TestStrictModeSwitch:
    def test_default_is_strict(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_SSH_STRICT_HOSTKEY", raising=False)
        assert ssh_runner.strictHostKeyEnabled() is True

    def test_off_values_fall_back_to_legacy(self, monkeypatch):
        for raw in ("0", "false", "off", "no", " OFF "):
            monkeypatch.setenv("NEUROVA_SSH_STRICT_HOSTKEY", raw)
            assert ssh_runner.strictHostKeyEnabled() is False, raw

    def test_build_client_strict_installs_policy(self, store):
        client, policy = ssh_runner._buildClient(
            strict=True, store=store, agent_id="a", host="h", port=22)
        assert isinstance(policy, UnknownHostKeyPolicy)
        assert client._policy is policy, "严格模式必须装 UnknownHostKeyPolicy"

    def test_build_client_non_strict_keeps_autoadd(self):
        import paramiko

        client, policy = ssh_runner._buildClient(
            strict=False, store=None, agent_id="a", host="h", port=22)
        assert policy is None
        assert isinstance(client._policy, paramiko.AutoAddPolicy)

    def test_build_client_factory_bypasses_policy(self, store):
        sentinel = object()

        client, policy = ssh_runner._buildClient(
            strict=True, store=store, agent_id="a", host="h", port=22,
            client_factory=lambda: sentinel)
        assert client is sentinel and policy is None


class TestHostConfirmationCardFlow:
    """U1 主机确认卡：首连弹卡 → 确认后写库重连；超时未确认不执行；指纹变化拒连。"""

    def _makeExecutor(self):
        from neurova.tool_executor import ToolExecutor

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": None, "_current_user_id": "u1"})()
        return inst

    @pytest.mark.asyncio
    async def test_first_connect_emits_card_then_reconnects_after_confirm(self, monkeypatch):
        from neurova.computer_use.ssh_runner import HostKeyConfirmationNeeded
        from neurova.tool_executor import ToolExecutor

        inst = self._makeExecutor()
        fp = "SHA256:CAFEBABE0000000000000000000000000000000000000000000000000000"
        calls = {"n": 0}

        def fake_run(host, command, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise HostKeyConfirmationNeeded(fp, host=host, port=22, key_type="ssh-ed25519")
            assert "agent_id" in kw, "重连必须带 agent_id（known_hosts 按 agent 分桶）"
            return {"returncode": 0, "stdout": "after-confirm", "stderr": ""}

        monkeypatch.setattr(
            "neurova.computer_use.ssh_runner.resolve_ssh_credentials",
            lambda u, h: {"user": "root", "port": 22},
        )
        monkeypatch.setattr("neurova.computer_use.ssh_runner.run_ssh_command", fake_run)

        async def fake_confirm(self, store, agent_id, host, port, fingerprint, **k):
            assert fingerprint == fp
            return True  # 用户已在确认卡中确认（确认记录已落库）

        monkeypatch.setattr(ToolExecutor, "_awaitSshHostConfirmation", fake_confirm)
        emitted = []

        async def fake_emit(self, tool, params, result, screenshot_base64=None, terminal=None):
            emitted.append(dict(result))

        monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
        out = await inst._execute_computer_ssh_exec({"host": "h1", "command": "uptime"})
        assert out["success"] is True and out["stdout"] == "after-confirm"
        assert calls["n"] == 2, "确认后必须重连一次"
        assert any(r.get("needs_host_confirmation") for r in emitted), "首连必须弹主机确认卡"

    @pytest.mark.asyncio
    async def test_confirmation_timeout_stops_without_reconnect(self, monkeypatch):
        from neurova.computer_use.ssh_runner import HostKeyConfirmationNeeded
        from neurova.tool_executor import ToolExecutor

        inst = self._makeExecutor()
        calls = {"n": 0}

        def fake_run(host, command, **kw):
            calls["n"] += 1
            raise HostKeyConfirmationNeeded(
                "SHA256:DEAD", host=host, port=22, key_type="ssh-ed25519")

        monkeypatch.setattr(
            "neurova.computer_use.ssh_runner.resolve_ssh_credentials",
            lambda u, h: {"user": "root", "port": 22},
        )
        monkeypatch.setattr("neurova.computer_use.ssh_runner.run_ssh_command", fake_run)

        async def timeout_confirm(self, *a, **k):
            return False  # 90s 轮询窗口内用户未确认

        monkeypatch.setattr(ToolExecutor, "_awaitSshHostConfirmation", timeout_confirm)

        async def fake_emit(self, *a, **k):
            return None

        monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
        out = await inst._execute_computer_ssh_exec({"host": "h1", "command": "ls"})
        assert out["success"] is False
        assert out["needs_host_confirmation"] is True
        assert "未执行" in out["error"]
        assert calls["n"] == 1, "未确认不得重连"

    @pytest.mark.asyncio
    async def test_key_change_surfaces_mismatch_not_generic_error(self, monkeypatch):
        from neurova.computer_use.ssh_runner import HostKeyMismatchError
        from neurova.tool_executor import ToolExecutor

        inst = self._makeExecutor()

        def fake_run(host, command, **kw):
            raise HostKeyMismatchError(
                "SHA256:NEW", stored_fingerprint="SHA256:OLD", host=host, port=22)

        monkeypatch.setattr(
            "neurova.computer_use.ssh_runner.resolve_ssh_credentials",
            lambda u, h: {"user": "root", "port": 22},
        )
        monkeypatch.setattr("neurova.computer_use.ssh_runner.run_ssh_command", fake_run)

        async def fake_emit(self, *a, **k):
            return None

        monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
        out = await inst._execute_computer_ssh_exec({"host": "h1", "command": "ls"})
        assert out["success"] is False
        assert out["error_code"] == "HOST_KEY_MISMATCH"
        assert out["stored_fingerprint"] == "SHA256:OLD"

    @pytest.mark.asyncio
    async def test_host_confirmation_reaches_ws_payload(self, monkeypatch):
        """确认卡与凭据卡同通道（WS computer_action）：指纹/端口必须进事件载荷。"""
        from neurova.tool_executor import ToolExecutor

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": "s1", "_current_user_id": "u1"})()
        captured = {}

        class FakeMgr:
            def register_or_create_session(self, **k):
                pass

            async def broadcast_event(self, session_id, event):
                captured["payload"] = event.payload

        import neurova.sync.session_sync_manager as ssm

        monkeypatch.setattr(ssm, "get_session_sync_manager", lambda *a, **k: FakeMgr())
        await inst._emit_computer_event(
            "computer_ssh_exec", {"host": "9.9.9.9"},
            {"success": False, "needs_host_confirmation": True, "host": "9.9.9.9",
             "port": 2222, "fingerprint": "SHA256:XY", "key_type": "ssh-ed25519",
             "error": "x"},
        )
        assert captured["payload"].get("needs_host_confirmation") is True
        assert captured["payload"].get("host") == "9.9.9.9"
        assert captured["payload"].get("port") == 2222
        assert captured["payload"].get("fingerprint") == "SHA256:XY"
        assert captured["payload"].get("key_type") == "ssh-ed25519"
