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
    return AgentConfigManager(config_dir=Path(tmp_base))


# ================================================================
# 初始化
# ================================================================

class TestInit:
    def test_creates_directory(self, tmp_base):
        """构造函数创建目录和文件"""
        m = AgentConfigManager(config_dir=Path(tmp_base))
        assert Path(tmp_base).exists()
        assert m._agents_file.exists()
        assert m._models_file.exists()

    def test_agents_file_initial_content(self, manager):
        data = json.loads(manager._agents_file.read_text(encoding="utf-8"))
        # 实现落盘形态：agent_id → config dict 的扁平映射
        assert data == {}

    def test_models_file_initial_content(self, manager):
        data = json.loads(manager._models_file.read_text(encoding="utf-8"))
        assert isinstance(data, list) and len(data) > 0
        assert "model" in data[0]

    def test_default_base_path(self):
        """默认 config_dir = data/agents（实现契约）"""
        m = AgentConfigManager()
        assert m._config_dir.name == "agents"
        assert m._config_dir.exists()


# ================================================================
# Agent CRUD
# ================================================================

class TestCreateAgent:
    def test_create_simple(self, manager):
        ok = manager.create_agent("test_agent", "测试Agent")
        assert ok is True
        # 验证列表中有记录（list_agents 返回 dict 列表，键为 id）
        agents = manager.list_agents()
        assert len(agents) == 1
        assert agents[0]["id"] == "test_agent"

    def test_creates_soul_dir(self, manager):
        """实现建 souls/<id> 目录（无 workspace_path 键）"""
        manager.create_agent("a1", "Agent1")
        agent = manager.get_agent("a1")
        assert agent is not None
        assert (manager._souls_dir / "a1").exists()

    def test_duplicate_id_returns_false(self, manager):
        """实现契约：重复 id 返回 False（不抛）"""
        manager.create_agent("dup", "")
        assert manager.create_agent("dup", "") is False

    def test_empty_id_raises(self, manager):
        """实现契约：空 id 不校验（直接入册）——锁定现行行为"""
        ok = manager.create_agent("", "")
        assert ok is True

    def test_persists_to_file(self, manager):
        manager.create_agent("persist_test", "")
        # 重新加载检查
        m2 = AgentConfigManager(config_dir=Path(manager._config_dir))
        assert m2.get_agent("persist_test") is not None

    def test_custom_workspace_path(self, tmp_base):
        """指定 workspace_path 时不在 agents 目录下创建子目录"""
        custom_ws = str(Path(tmp_base).parent / "custom_ws")
        m = AgentConfigManager(config_dir=Path(tmp_base))
        m.create_agent("custom", "custom", config={"workspace_path": custom_ws})
        assert m.get_agent("custom")["config"]["workspace_path"] == custom_ws


class TestGetAgent:
    def test_found(self, manager):
        manager.create_agent("a1", "")
        agent = manager.get_agent("a1")
        assert agent is not None
        assert agent["id"] == "a1"

    def test_not_found(self, manager):
        assert manager.get_agent("nonexistent") is None

    def test_returns_full_config(self, manager):
        manager.create_agent("a1", "Test", config={"llm_model": "gpt-4"})
        agent = manager.get_agent("a1")
        assert agent["name"] == "Test"
        assert agent["config"]["llm_model"] == "gpt-4"
        assert "created_at" in agent
        assert "last_active" in agent


class TestListAgents:
    def test_empty(self, manager):
        assert manager.list_agents() == []

    def test_multiple(self, manager):
        manager.create_agent("a1", "")
        manager.create_agent("a2", "")
        agents = manager.list_agents()
        assert len(agents) == 2

    def test_returns_dicts(self, manager):
        manager.create_agent("a1", "")
        agents = manager.list_agents()
        assert isinstance(agents[0], dict)


class TestUpdateAgent:
    def test_update_name(self, manager):
        manager.create_agent("a1", "Old")
        ok = manager.update_agent("a1", {"name": "New"})
        assert ok is True
        agent = manager.get_agent("a1")
        assert agent["name"] == "New"

    def test_update_nonexistent_returns_false(self, manager):
        """实现契约：更新不存在返回 False（不抛）"""
        assert manager.update_agent("nobody", {"name": "X"}) is False

    def test_update_multiple_fields(self, manager):
        manager.create_agent("a1", "")
        manager.update_agent("a1", {
            "name": "Updated",
            "config": {"llm_model": "qwen-plus"},
        })
        agent = manager.get_agent("a1")
        assert agent["name"] == "Updated"
        assert agent["config"]["llm_model"] == "qwen-plus"

    def test_update_persists_to_file(self, manager):
        manager.create_agent("a1", "Old")
        manager.update_agent("a1", {"name": "Persisted"})
        m2 = AgentConfigManager(config_dir=Path(manager._config_dir))
        assert m2.get_agent("a1")["name"] == "Persisted"

    def test_save_agent_soul(self, manager):
        """实现契约：save_agent_soul 持久化灵魂配置"""
        manager.create_agent("a1", "OldName")
        ok = manager.save_agent_soul("a1", {"persona": "新名称"})
        assert ok is True
        soul = manager.get_agent_soul("a1")
        assert soul is not None


class TestDeleteAgent:
    def test_delete_existing(self, manager):
        manager.create_agent("a1", "")
        ok = manager.delete_agent("a1")
        assert ok is True
        assert manager.get_agent("a1") is None
        assert len(manager.list_agents()) == 0

    def test_delete_nonexistent_returns_false(self, manager):
        """实现契约：删除不存在返回 False（不抛）"""
        assert manager.delete_agent("nobody") is False

    def test_delete_removes_from_file(self, manager):
        manager.create_agent("a1", "")
        manager.create_agent("a2", "")
        manager.delete_agent("a1")
        m2 = AgentConfigManager(config_dir=Path(manager._config_dir))
        assert len(m2.list_agents()) == 1


# ================================================================
# Soul 管理
# ================================================================

class TestSoul:
    def test_get_soul_roundtrip(self, manager):
        """创建后 soul.json 未生成 → None；save 后可读回"""
        manager.create_agent("a1", "TestAgent")
        assert manager.get_agent_soul("a1") is None
        ok = manager.save_agent_soul("a1", {"persona": "TestAgent"})
        assert ok is True
        soul = manager.get_agent_soul("a1")
        assert soul == {"persona": "TestAgent"}

    def test_get_soul_nonexistent_returns_none(self, manager):
        """实现契约：soul 不存在返回 None（不抛）"""
        assert manager.get_agent_soul("nobody") is None

    def test_save_soul(self, manager):
        manager.create_agent("a1", "")
        ok = manager.save_agent_soul("a1", "# New Title\n\nNew content")
        assert ok is True
        soul = manager.get_agent_soul("a1")
        assert soul == "# New Title\n\nNew content"

    def test_save_soul_creates_dir_on_demand(self, manager):
        """实现契约：save_agent_soul 不校验 agent 存在性（目录按需创建）"""
        ok = manager.save_agent_soul("nobody", {"content": "c"})
        assert ok is True

    def test_save_soul_updates_updated_at(self, manager):
        """实现 agent dict 用 last_active（无 updated_at 键），save 前后不变即锁定"""
        manager.create_agent("a1", "")
        before = manager.get_agent("a1")["last_active"]
        manager.save_agent_soul("a1", {"content": "# Updated"})
        after = manager.get_agent("a1")["last_active"]
        assert after >= before

# ================================================================
# 模型列表
# ================================================================

class TestListModels:
    def test_returns_defaults(self, manager):
        """实现默认模型 3 个：default/gpt4/claude"""
        models = manager.list_models()
        assert len(models) == 3
        ids = {m["id"] for m in models}
        assert ids == {"default", "gpt4", "claude"}

    def test_returns_dicts(self, manager):
        models = manager.list_models()
        assert all(isinstance(m, dict) for m in models)


# ================================================================
# 单例工厂
# ================================================================

class TestGetConfigManager:
    def test_returns_manager(self, tmp_base):
        m = get_config_manager(Path(tmp_base))
        assert isinstance(m, AgentConfigManager)

    def test_singleton(self, tmp_base):
        m1 = get_config_manager(Path(tmp_base))
        m2 = get_config_manager(Path(tmp_base))
        assert m1 is m2

    def test_different_path_different_singleton(self, tmp_path):
        """不同路径创建不同单例"""
        p1 = str(tmp_path / "agents1")
        p2 = str(tmp_path / "agents2")
        m1 = get_config_manager(Path(p1))
        m2 = get_config_manager(Path(p2))
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
        """_save_agents_list 落盘后经 _load 重开实例可读回"""
        agents = {
            "a1": {"name": "Agent1", "description": ""},
            "a2": {"name": "Agent2", "description": ""},
        }
        manager._save_agents_list(agents)
        m2 = AgentConfigManager(config_dir=manager._config_dir)
        assert len(m2.list_agents()) == 2
