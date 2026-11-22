"""TDD：SSH 主机确认端点 + WS 载荷 agent_id（U1 适配卡 A 后端侧）。

背景：后端弹 needs_host_confirmation 卡后全仓无消费口——
SshHostStore.mark_confirmed 无生产调用方（确认接口缺失），
SSH 新主机首连执行会卡到 90s 轮询超时。本卡补齐：
- POST /v1/settings/ssh-credentials/host-key/confirm（经 mark_confirmed 落库）
- WS computer_action 载荷补 agent_id（前端确认时回带，known_hosts 按 agent 分桶）
"""

import pytest
from types import SimpleNamespace
from unittest.mock import patch

paramiko = pytest.importorskip("paramiko")

from neurova.api.endpoints import settings as settings_api
from neurova.security.ssh_host_store import SshHostStore


def _user(uid="42", role="user"):
    return {"user_id": uid, "username": "tester", "role": role}


def _req():
    return SimpleNamespace(state=SimpleNamespace(request_id="test-req"))


@pytest.fixture
def store(tmp_path):
    return SshHostStore(root_dir=tmp_path / "agents")


class TestSshHostKeyConfirmEndpoint:
    @pytest.mark.asyncio
    async def test_confirm_writes_store_via_mark_confirmed(self, store, monkeypatch):
        import neurova.api.agent_access as agent_access

        monkeypatch.setattr(agent_access, "agentOwnerById", lambda aid: "42")
        with patch("neurova.security.ssh_host_store.get_ssh_host_store",
                   return_value=store):
            resp = await settings_api.confirmSshHostKey(
                _req(),
                settings_api.SshHostKeyConfirmRequest(
                    agent_id="agent-1", host="10.0.0.9", port=22,
                    fingerprint="SHA256:CAFEBABE", key_type="ssh-ed25519"),
                current_user=_user(),
            )
        assert resp["code"] == 0, f"确认应成功: {resp}"
        entry = store.lookup("agent-1", "10.0.0.9", 22)
        assert entry is not None, "确认必须经 SshHostStore.mark_confirmed 落库"
        assert entry["key_fingerprint"] == "SHA256:CAFEBABE"
        assert entry["confirmed_via"] == "user_card"

    @pytest.mark.asyncio
    async def test_confirm_blank_host_or_fingerprint_rejected(self, store, monkeypatch):
        import neurova.api.agent_access as agent_access

        monkeypatch.setattr(agent_access, "agentOwnerById", lambda aid: "42")
        with patch("neurova.security.ssh_host_store.get_ssh_host_store",
                   return_value=store):
            for host, fp in [(" ", "SHA256:X"), ("h1", " ")]:
                with pytest.raises(Exception):
                    await settings_api.confirmSshHostKey(
                        _req(),
                        settings_api.SshHostKeyConfirmRequest(
                            agent_id="agent-1", host=host, port=22, fingerprint=fp),
                        current_user=_user(),
                    )
        assert store.lookup("agent-1", "h1", 22) is None, "非法输入不得写库"

    @pytest.mark.asyncio
    async def test_confirm_agent_ownership_enforced(self, store, monkeypatch):
        """agent 归属校验：非属主且非 admin → 403；属主本人/admin 放行。"""
        import neurova.api.agent_access as agent_access

        monkeypatch.setattr(agent_access, "agentOwnerById", lambda aid: "42")
        with patch("neurova.security.ssh_host_store.get_ssh_host_store",
                   return_value=store):
            # 属主本人 → 放行
            resp = await settings_api.confirmSshHostKey(
                _req(),
                settings_api.SshHostKeyConfirmRequest(
                    agent_id="agent-1", host="h1", port=22, fingerprint="SHA256:A"),
                current_user=_user(uid="42"),
            )
            assert resp["code"] == 0
            # 非 admin 且非属主 → 403
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as ei:
                await settings_api.confirmSshHostKey(
                    _req(),
                    settings_api.SshHostKeyConfirmRequest(
                        agent_id="agent-1", host="h1", port=22, fingerprint="SHA256:A"),
                    current_user=_user(uid="999"),
                )
            assert ei.value.status_code == 403
            # admin → 放行
            resp = await settings_api.confirmSshHostKey(
                _req(),
                settings_api.SshHostKeyConfirmRequest(
                    agent_id="agent-1", host="h1", port=22, fingerprint="SHA256:A"),
                current_user=_user(uid="1", role="admin"),
            )
            assert resp["code"] == 0


class TestWsPayloadCarriesAgentId:
    """前端确认时要回带 agent_id——WS 确认卡载荷必须携带。"""

    @pytest.mark.asyncio
    async def test_host_confirmation_payload_has_agent_id(self, monkeypatch):
        from neurova.computer_use.ssh_runner import HostKeyConfirmationNeeded
        from neurova.tool_executor import ToolExecutor

        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = type("A", (), {"current_session_id": "s1", "_current_user_id": "u1"})()
        payloads = []

        class FakeMgr:
            def register_or_create_session(self, **k):
                pass

            async def broadcast_event(self, session_id, event):
                payloads.append(dict(event.payload))

        import neurova.sync.session_sync_manager as ssm

        monkeypatch.setattr(ssm, "get_session_sync_manager", lambda *a, **k: FakeMgr())

        async def fake_confirm(self, store, agent_id, host, port, fingerprint, **k):
            return True  # 用户已在确认卡确认（轮询命中）

        monkeypatch.setattr(ToolExecutor, "_awaitSshHostConfirmation", fake_confirm)

        def fake_run(host, command, **kw):
            return {"returncode": 0, "stdout": "after-confirm", "stderr": ""}

        hk = HostKeyConfirmationNeeded(
            "SHA256:XY", host="h1", port=2222, key_type="ssh-ed25519")
        out = await inst._handleSshHostConfirmation(
            "h1", "uptime", hk, "agent-9", {"host": "h1"}, fake_run,
            {"port": 2222}, user_id="u1")
        assert out["success"] is True
        cards = [p for p in payloads if p.get("needs_host_confirmation")]
        assert cards, "首连必须弹主机确认卡"
        assert cards[0].get("agent_id") == "agent-9", (
            "WS 确认卡载荷必须带 agent_id（前端确认时回带）"
        )
        assert cards[0].get("fingerprint") == "SHA256:XY"
