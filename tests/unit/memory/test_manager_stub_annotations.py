"""P1.3 验证测试 — MemoryManager stub 标注与实际行为一致性

验证 docstring 中标注的 stub/implemented 状态与代码实际行为一致。
这是 bug-hunt Phase 4 (仪表化) 的一部分: 用测试锁定当前行为,
防止未来重构时 stub 被误用或真实实现被误删。
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

# 确保能导入 neurova
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from neurova.cognitive_layers.memory_layer.manager import MemoryManager


@pytest.fixture
def manager(tmp_path):
    """提供独立的 MemoryManager 实例"""
    db_path = str(tmp_path / "test_memory.db")
    return MemoryManager(db_path=db_path, agent_id="test", user_id="test")


# ────── Sleep: 已委托到 modules/sleep_module.py ──────


class TestSleepDelegated:
    """验证 Sleep 区域已委托到真实模块（阶段2完成）"""

    def test_light_sleep_returns_stats(self, manager):
        """run_light_sleep_cycle 应返回统计字典，而非抛出异常"""
        result = manager.run_light_sleep_cycle()
        assert isinstance(result, dict)
        assert "cycle" in result

    def test_rem_sleep_returns_stats(self, manager):
        result = manager.run_rem_sleep_cycle()
        assert isinstance(result, dict)
        assert result["cycle"] == "rem"

    def test_deep_sleep_returns_stats(self, manager):
        result = manager.run_deep_sleep_cycle()
        assert isinstance(result, dict)
        assert result["cycle"] == "deep"

    def test_dormant_returns_stats(self, manager):
        result = manager.run_dormant_cycle()
        assert isinstance(result, dict)
        assert result["cycle"] == "dormant"


# ────── Explainability: 标注为 PARTIAL ──────


class TestExplainabilityPartial:
    """验证 Explainability 区域为部分实现"""

    def test_explain_memory_found(self, manager):
        mem_id = manager.remember("test content for explain")
        result = manager.explain_memory(mem_id)
        assert result["memory_id"] == mem_id
        assert result["content"] == "test content for explain"
        assert result["reason"] == "direct recall"

    def test_explain_memory_not_found(self, manager):
        result = manager.explain_memory("nonexistent_id")
        assert result["error"] == "not found"

    def test_get_explanation_chain_delegates_to_module(self, manager):
        """已从 stub 升级为真实实现：委托 ExplainabilityModule，返回列表"""
        result = manager.get_explanation_chain()
        assert isinstance(result, list)

    def test_visualize_chain_returns_string(self, manager):
        """已从 stub 升级为真实实现：返回可视化文本（无数据时也有占位输出）"""
        result = manager.visualize_chain()
        assert isinstance(result, str)


# ────── Forgetting Recovery: 标注为 IMPLEMENTED ──────


class TestForgettingRecoveryImplemented:
    """验证 Forgetting Recovery 区域为真实实现 (非 stub)"""

    def test_archive_memory_changes_lifecycle(self, manager):
        """archive_memory 应真实修改 lifecycle_stage"""
        from neurova.cognitive_layers.memory_layer.models import LifecycleStage

        mem_id = manager.remember("to be archived")
        assert manager.archive_memory(mem_id) is True

        mem = manager._memories.get(mem_id)
        assert mem.lifecycle_stage == LifecycleStage.ARCHIVED

    def test_archive_nonexistent_returns_false(self, manager):
        assert manager.archive_memory("nonexistent") is False

    def test_recover_from_archive_restores_active(self, manager):
        """recover_from_archive 应真实恢复 lifecycle_stage"""
        from neurova.cognitive_layers.memory_layer.models import LifecycleStage

        mem_id = manager.remember("to be recovered")
        manager.archive_memory(mem_id)
        assert manager.recover_from_archive(mem_id) is True

        mem = manager._memories.get(mem_id)
        assert mem.lifecycle_stage == LifecycleStage.ACTIVE

    def test_get_archived_memories_returns_only_archived(self, manager):
        """get_archived_memories 应只返回已归档的记忆"""
        mem_id1 = manager.remember("archived one")
        mem_id2 = manager.remember("active one")
        manager.archive_memory(mem_id1)

        archived = manager.get_archived_memories(limit=10)
        archived_ids = [m["id"] for m in archived]
        assert mem_id1 in archived_ids
        assert mem_id2 not in archived_ids
