# -*- coding: utf-8 -*-
"""P2-2 外部 Agent 握手/注册持久化单元测试。

覆盖：
- _saveExternalState/_loadExternalState 原子往返（重启恢复语义）；
- 损坏文件按空态起步（不阻断启动）；
- handshake 端点变更后触发落盘。
"""

import json

import pytest

from neurova.api.endpoints import agent_communication_api as mod
from neurova.api.endpoints.agent_communication_api import HandshakeRequestModel


@pytest.fixture()
def stateFile(tmp_path, monkeypatch):
    path = tmp_path / "external_agents_state.json"
    monkeypatch.setattr(mod, "_EXTERNAL_STATE_FILE", path)
    return path


class TestExternalStatePersistence:
    def test_round_trip(self, stateFile, monkeypatch):
        mod._handshakes.clear()
        mod._external_agents.clear()
        mod._handshakes["hs-1"] = {"handshake_id": "hs-1", "external_agent_id": "ext-1", "status": "completed"}
        mod._external_agents["ext-1"] = {"agent_id": "ext-1", "name": "外部", "user_id": "u1"}

        mod._saveExternalState()
        assert stateFile.exists()

        # 模拟重启：清空内存后从盘恢复
        mod._handshakes.clear()
        mod._external_agents.clear()
        mod._loadExternalState()
        assert mod._handshakes["hs-1"]["external_agent_id"] == "ext-1"
        assert mod._external_agents["ext-1"]["name"] == "外部"

    def test_corrupt_file_starts_empty(self, stateFile, monkeypatch):
        stateFile.write_text("{not json", encoding="utf-8")
        mod._handshakes.clear()
        mod._external_agents.clear()
        mod._loadExternalState()  # 不抛出，按空态起步
        assert mod._handshakes == {}
        assert mod._external_agents == {}

    @pytest.mark.asyncio
    async def test_handshake_triggers_save(self, stateFile, monkeypatch):
        saved = []
        monkeypatch.setattr(mod, "_saveExternalState", lambda: saved.append(True))
        monkeypatch.setattr(mod, "_externalQuotaRules",
                            lambda auth: {"external_rate_limit_per_minute": 30})
        mod._handshakes.clear()
        mod._external_agents.clear()

        body = HandshakeRequestModel(agent_id="ext-9", agent_name="外部九", capabilities=["chat"])
        resp = await mod.handshake(body, {"user_id": "u1"})
        assert resp["code"] == 0
        assert saved, "握手落库后必须触发持久化"
        assert mod._external_agents["ext-9"]["user_id"] == "u1"

    def test_saved_file_is_valid_json(self, stateFile, monkeypatch):
        mod._handshakes.clear()
        mod._external_agents.clear()
        mod._external_agents["ext-2"] = {"agent_id": "ext-2", "name": "n"}
        mod._saveExternalState()
        payload = json.loads(stateFile.read_text(encoding="utf-8"))
        assert "external_agents" in payload and "handshakes" in payload
