"""
Agent 归属持久化回归（遗留修复 ①）

Bug：AgentConfig.owner_user_id 在创建时写入内存，但 _save_agent_config
持久化到 workspace/agent_config.json 时丢弃该字段，_load_saved_agents
重建时也不回填——重启后 agent 归属丢失，chat 的 _user_can_access_agent
对非 admin 全部拒绝。

契约：
- _save_agent_config 持久化 owner_user_id
- _agent_config_from_saved（app.py 抽出的纯函数）从保存的 JSON 回填
  owner_user_id 与 description；旧格式无 owner 字段 → None
"""
import json
from types import SimpleNamespace

from neurova.api.endpoints.agent import _save_agent_config


def _fake_agent(workspace):
    return SimpleNamespace(
        config=SimpleNamespace(
            name="A",
            description="d",
            workspace_path=str(workspace),
            llm_config=SimpleNamespace(model="m1"),
            llm_provider="openai",
            personality="p",
            constitution="c",
            owner_user_id="42",
        )
    )


class TestSaveOwnerUserId:
    def test_save_persists_owner(self, tmp_path):
        _save_agent_config(_fake_agent(tmp_path))
        data = json.loads((tmp_path / "agent_config.json").read_text(encoding="utf-8"))
        assert data["owner_user_id"] == "42"

    def test_save_without_owner_writes_empty(self, tmp_path):
        agent = _fake_agent(tmp_path)
        agent.config.owner_user_id = None
        _save_agent_config(agent)
        data = json.loads((tmp_path / "agent_config.json").read_text(encoding="utf-8"))
        assert data["owner_user_id"] == ""

    def test_other_fields_still_saved(self, tmp_path):
        _save_agent_config(_fake_agent(tmp_path))
        data = json.loads((tmp_path / "agent_config.json").read_text(encoding="utf-8"))
        assert data["name"] == "A"
        assert data["model"] == "m1"
        assert data["provider"] == "openai"


class TestLoadOwnerUserId:
    def test_owner_roundtrips(self, tmp_path):
        from neurova.api.app import _agent_config_from_saved

        saved = {"name": "A", "model": "m1", "provider": "openai", "description": "d", "owner_user_id": "42"}
        cfg = _agent_config_from_saved(saved, "agent1", str(tmp_path))
        assert cfg.owner_user_id == "42"
        assert cfg.agent_id == "agent1"
        assert cfg.description == "d"

    def test_legacy_config_without_owner_loads_none(self, tmp_path):
        from neurova.api.app import _agent_config_from_saved

        saved = {"name": "A", "model": "m1", "provider": "openai", "description": "d"}
        cfg = _agent_config_from_saved(saved, "agent1", str(tmp_path))
        assert cfg.owner_user_id is None
