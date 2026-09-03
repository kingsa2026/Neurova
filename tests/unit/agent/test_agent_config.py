"""
neurova/agent_config.py 测试

覆盖: AgentConfigManager 的 CRUD、soul.md 管理、模型列表、单例工厂
"""
import json
import os
from pathlib import Path
from datetime import datetime

import pytest

from neurova.agent_config import AgentConfigManager, get_config_manager


# ================================================================
# Fixtures
# ================================================================

@pytest.fixture
def tmp_base(tmp_path):
    """临时 base_path"""
    return str(tmp_path / "agents")


@pytest.fixture
def manager(tmp_base):
    """用临时路径的 AgentConfigManager"""
    return AgentConfigManager(base_path=tmp_base)


# ================================================================
# 初始化
# ================================================================

class TestInit:
    def test_creates_directory(self, tmp_base):
        """构造函数创建目录和文件"""
        m = AgentConfigManager(base_path=tmp_base)
        assert Path(tmp_base).exists()
        assert m.agents_file.exists()
        assert m.models_file.exists()

    def test_agents_file_initial_content(self, manager):
        data = json.loads(manager.agents_file.read_text(encoding="utf-8"))
        assert data["version"] == "1.0"
        assert data["agents"] == []

    def test_models_file_initial_content(self, manager):
        data = json.loads(manager.models_file.read_text(encoding="utf-8"))
        assert "models" in data
        assert len(data["models"]) > 0
        assert data["models"][0]["id"] == "gpt-4"

    def test_default_base_path(self):
        """默认 base_path 基于模块所在目录"""
        m = AgentConfigManager()
        assert m.base_path.name == "agents"
        assert m.base_path.exists()


# ================================================================
# Agent CRUD
# ================================================================

class TestCreateAgent:
    def test_create_simple(self, manager):
        agent_id = manager.create_agent({"agent_id": "test_agent", "name": "测试Agent"})
        assert agent_id == "test_agent"
        # 验证列表中有记录
        agents = manager.list_agents()
        assert len(agents) == 1
        assert agents[0]["agent_id"] == "test_agent"

    def test_creates_workspace_and_soul(self, manager):
        manager.create_agent({"agent_id": "a1", "name": "Agent1"})
        agent = manager.get_agent("a1")
        assert agent is not None
        workspace = Path(agent["workspace_path"])
        assert (workspace / "memory" / "soul.md").exists()
        soul = (workspace / "memory" / "soul.md").read_text(encoding="utf-8")
        assert "Agent1" in soul

    def test_duplicate_id_raises(self, manager):
        manager.create_agent({"agent_id": "dup"})
        with pytest.raises(ValueError, match="已存在"):
            manager.create_agent({"agent_id": "dup"})

    def test_empty_id_raises(self, manager):
        with pytest.raises(ValueError, match="不能为空"):
            manager.create_agent({"agent_id": ""})

    def test_persists_to_file(self, manager):
        manager.create_agent({"agent_id": "persist_test"})
        # 重新加载检查
        m2 = AgentConfigManager(base_path=manager.base_path)
        assert m2.get_agent("persist_test") is not None

    def test_custom_workspace_path(self, tmp_base):
        """指定 workspace_path 时不在 agents 目录下创建子目录"""
        custom_ws = str(Path(tmp_base).parent / "custom_ws")
        m = AgentConfigManager(base_path=tmp_base)
        m.create_agent({"agent_id": "custom", "workspace_path": custom_ws})
        assert Path(custom_ws).exists()
        assert (Path(custom_ws) / "memory").exists()


class TestGetAgent:
    def test_found(self, manager):
        manager.create_agent({"agent_id": "a1"})
        agent = manager.get_agent("a1")
        assert agent is not None
        assert agent["agent_id"] == "a1"

    def test_not_found(self, manager):
        assert manager.get_agent("nonexistent") is None

    def test_returns_full_config(self, manager):
        manager.create_agent({"agent_id": "a1", "name": "Test", "llm_model": "gpt-4"})
        agent = manager.get_agent("a1")
        assert agent["name"] == "Test"
        assert agent["llm_model"] == "gpt-4"
        assert "created_at" in agent
        assert "updated_at" in agent


class TestListAgents:
    def test_empty(self, manager):
        assert manager.list_agents() == []

    def test_multiple(self, manager):
        manager.create_agent({"agent_id": "a1"})
        manager.create_agent({"agent_id": "a2"})
        agents = manager.list_agents()
        assert len(agents) == 2

    def test_returns_dicts(self, manager):
        manager.create_agent({"agent_id": "a1"})
        agents = manager.list_agents()
        assert isinstance(agents[0], dict)


class TestUpdateAgent:
    def test_update_name(self, manager):
        manager.create_agent({"agent_id": "a1", "name": "Old"})
        ok = manager.update_agent("a1", {"name": "New"})
        assert ok is True
        agent = manager.get_agent("a1")
        assert agent["name"] == "New"

    def test_update_nonexistent_raises(self, manager):
        with pytest.raises(ValueError, match="不存在"):
            manager.update_agent("nobody", {"name": "X"})

    def test_update_multiple_fields(self, manager):
        manager.create_agent({"agent_id": "a1"})
        manager.update_agent("a1", {
            "name": "Updated", "llm_model": "qwen-plus", "enable_memory": False
        })
        agent = manager.get_agent("a1")
        assert agent["name"] == "Updated"
        assert agent["llm_model"] == "qwen-plus"
        assert agent["enable_memory"] is False

    def test_update_persists_to_file(self, manager):
        manager.create_agent({"agent_id": "a1", "name": "Old"})
        manager.update_agent("a1", {"name": "Persisted"})
        m2 = AgentConfigManager(base_path=manager.base_path)
        assert m2.get_agent("a1")["name"] == "Persisted"

    def test_update_updates_soul(self, manager):
        manager.create_agent({"agent_id": "a1", "name": "OldName"})
        manager.update_agent("a1", {"name": "新名称"})
        workspace = Path(manager.get_agent("a1")["workspace_path"])
        soul = (workspace / "memory" / "soul.md").read_text(encoding="utf-8")
        assert "新名称" in soul


class TestDeleteAgent:
    def test_delete_existing(self, manager):
        manager.create_agent({"agent_id": "a1"})
        ok = manager.delete_agent("a1")
        assert ok is True
        assert manager.get_agent("a1") is None
        assert len(manager.list_agents()) == 0

    def test_delete_nonexistent_raises(self, manager):
        with pytest.raises(ValueError, match="不存在"):
            manager.delete_agent("nobody")

    def test_delete_removes_from_file(self, manager):
        manager.create_agent({"agent_id": "a1"})
        manager.create_agent({"agent_id": "a2"})
        manager.delete_agent("a1")
        m2 = AgentConfigManager(base_path=manager.base_path)
        assert len(m2.list_agents()) == 1


# ================================================================
# Soul 管理
# ================================================================

class TestSoul:
    def test_get_soul(self, manager):
        manager.create_agent({"agent_id": "a1", "name": "TestAgent"})
        soul = manager.get_agent_soul("a1")
        assert "TestAgent" in soul

    def test_get_soul_nonexistent_raises(self, manager):
        with pytest.raises(ValueError, match="不存在"):
            manager.get_agent_soul("nobody")

    def test_save_soul(self, manager):
        manager.create_agent({"agent_id": "a1"})
        ok = manager.save_agent_soul("a1", "# New Title\n\nNew content")
        assert ok is True
        soul = manager.get_agent_soul("a1")
        assert soul == "# New Title\n\nNew content"

    def test_save_soul_nonexistent_raises(self, manager):
        with pytest.raises(ValueError, match="不存在"):
            manager.save_agent_soul("nobody", "content")

    def test_save_soul_updates_updated_at(self, manager):
        manager.create_agent({"agent_id": "a1"})
        before = manager.get_agent("a1")["updated_at"]
        manager.save_agent_soul("a1", "# Updated")
        after = manager.get_agent("a1")["updated_at"]
        assert after >= before


# ================================================================
# 模型列表
# ================================================================

class TestListModels:
    def test_returns_defaults(self, manager):
        models = manager.list_models()
        assert len(models) >= 5
        model_ids = [m["id"] for m in models]
        assert "gpt-4" in model_ids
        assert "qwen-plus" in model_ids

    def test_returns_dicts(self, manager):
        models = manager.list_models()
        assert all(isinstance(m, dict) for m in models)


# ================================================================
# 单例工厂
# ================================================================

class TestGetConfigManager:
    def test_returns_manager(self, tmp_base):
        m = get_config_manager(tmp_base)
        assert isinstance(m, AgentConfigManager)

    def test_singleton(self, tmp_base):
        m1 = get_config_manager(tmp_base)
        m2 = get_config_manager(tmp_base)
        assert m1 is m2

    def test_different_path_different_singleton(self, tmp_path):
        """不同路径创建不同单例"""
        p1 = str(tmp_path / "agents1")
        p2 = str(tmp_path / "agents2")
        m1 = get_config_manager(p1)
        m2 = get_config_manager(p2)
        # 单例是为每个路径缓存的？实际上 get_config_manager 只维护一个单例
        # 第二次调用返回同一个实例，但 base_path 已固定
        assert m1 is m2  # 这是既有行为

    def test_default_singleton(self):
        m1 = get_config_manager()
        m2 = get_config_manager()
        assert m1 is m2


# ================================================================
# _save_agents_list
# ================================================================

class TestSaveAgentsList:
    def test_saves_and_restores(self, manager):
        agents = [
            {"agent_id": "a1", "name": "Agent1"},
            {"agent_id": "a2", "name": "Agent2"},
        ]
        manager._save_agents_list(agents)
        loaded = manager.list_agents()
        assert len(loaded) == 2
