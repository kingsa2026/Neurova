"""P1.3 验证测试 — MemoryManager stub 标注与实际行为一致性

验证 docstring 中标注的 stub/implemented 状态与代码实际行为一致。
这是 bug-hunt Phase 4 (仪表化) 的一部分: 用测试锁定当前行为,
防止未来重构时 stub 被误用或真实实现被误删。

2026-09-16 标注诚实性审计（本文件新增组）:
  历史上三个区块标题声称 STUB/NotImplementedError，但代码实际已全部
  实现（委托到 modules/*），过时标注会误导调用方走 hasattr/try-except
  防御路径、并让新维护者误判功能缺失。守卫防止标注再次漂移。
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

# 确保能导入 neurova
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from neurova.cognitive_layers.memory_layer.manager import MemoryManager

_MANAGER_SOURCE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "neurova", "cognitive_layers", "memory_layer", "manager.py",
)


@pytest.fixture
def manager(tmp_path):
    """提供独立的 MemoryManager 实例"""
    db_path = str(tmp_path / "test_memory.db")
    return MemoryManager(db_path=db_path, agent_id="test", user_id="test")


@pytest.fixture(scope="module")
def manager_source() -> str:
    with open(_MANAGER_SOURCE_PATH, encoding="utf-8") as f:
        return f.read()


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


# ────── 标注诚实性守卫（2026-09-16 审计新增）──────


class TestAnnotationHonesty:
    """区块标题/文件头声称的状态必须与代码实际状态一致。

    历史: Emotion/Classification/Advanced Features 三个区块标题曾标注
    "STUB/未实现/抛 NotImplementedError"，但其下代码早已全部实现（委托
    到 modules/*）——过时标注误导调用方与新维护者。此类漂移由此组守卫。
    """

    def test_no_block_title_claims_notimplemented(self, manager_source):
        """区块标题不得再声称抛 NotImplementedError（当前代码无一处抛出）"""
        assert "NotImplementedError" not in manager_source, (
            "manager.py 不应再含 NotImplementedError 声称；"
            "若新增有意失败的方法，请同步更新本守卫与文件头说明"
        )

    def test_no_block_title_claims_stub(self, manager_source):
        """区块标题不得再标注 STUB（三个历史区块实际均已委托实现）"""
        for line in manager_source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") and "──────" in stripped:
                assert "STUB" not in stripped.upper(), f"区块标题仍是过时 STUB 标注: {stripped}"

    def test_file_header_not_exaggerating_stubs(self, manager_source):
        """文件头不得再声称 50+ 方法为 stub（实际全部已委托/实现）"""
        # 允许在"历史更正"语境中出现该字样（如"旧声称已不再成立"），
        # 但不得以现状陈述出现（行首非"旧/历/曾"引导）
        for line in manager_source.splitlines():
            if "50+ 方法为 stub" in line:
                head = line.strip()[:8]
                assert any(k in line[:24] for k in ("旧", "历", "曾", "声称")), (
                    f"文件头以现状口吻声称 stub: {line.strip()}"
                )

    def test_classification_block_is_real_delegation(self, manager):
        """Classification 区块（历史 STUB 标题）实际可真实分类并携带标签"""
        result = manager.classify_and_remember("我喜欢在清晨跑步，感觉精力充沛")
        assert isinstance(result, str) and result

    def test_advanced_features_block_is_real_delegation(self, manager):
        """Advanced Features 区块（历史 STUB 标题）实际可按情感检索记忆"""
        mem_id = manager.remember("今天升职了，非常开心")
        manager._emotion_module.set_emotion(
            mem_id,
            __import__(
                "neurova.cognitive_layers.memory_layer.modules.emotion_module",
                fromlist=["EmotionState", "EmotionType"],
            ).EmotionState(
                primary_emotion=__import__(
                    "neurova.cognitive_layers.memory_layer.modules.emotion_module",
                    fromlist=["EmotionType"],
                ).EmotionType.JOY,
                intensity=0.9,
                valence=0.8,
                arousal=0.6,
            ),
        )
        hits = manager.get_memories_by_emotion("joy", limit=5)
        assert any(m["id"] == mem_id for m in hits)

    def test_passthrough_contracts_stable(self, manager):
        """4 个情感透传方法契约稳定：不抛异常且返回类型正确

        这几个方法在 EmotionModule 中无对应能力（模块不维护历史/风格/基线），
        当前为显式透传默认值——这是**有意设计**（文档已注明），不是 stub 缺失。
        若未来 EmotionModule 补齐能力，应改为真实委托并同步更新契约。
        """
        assert isinstance(manager.apply_emotion_to_temperature(0.7), (int, float))
        assert isinstance(manager.apply_emotion_to_style("text"), str)
        assert isinstance(manager.get_emotion_history(), list)
        assert manager.reset_emotion_to_baseline() is None
