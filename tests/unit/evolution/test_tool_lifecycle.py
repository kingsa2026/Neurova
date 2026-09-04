"""
Phase 2 P2-3: ToolLifecycleManager 遗忘曲线测试

验证工具生命周期管理：
- ACTIVE → DEGRADED → ARCHIVED → FROZEN
- inactivity_decay 权重衰减
- 反遗忘机制
"""
import pytest
import time
from typing import List


# ============================================================
# P2-3.1 生命周期状态转换
# ============================================================


class TestToolLifecycleStates:
    """生命周期状态机"""

    def test_initial_state_active(self):
        """新注册工具默认为 ACTIVE"""
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager, ToolLifecycleState

        mgr = ToolLifecycleManager()
        mgr.register_tool("browser_click")

        state = mgr.get_state("browser_click")
        assert state == ToolLifecycleState.ACTIVE

    def test_degraded_after_inactivity(self):
        """不活跃超过阈值的工具标记为 DEGRADED"""
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager, ToolLifecycleState

        mgr = ToolLifecycleManager(
            degraded_after_seconds=0.0,  # 立即进入 DEGRADED
        )
        mgr.register_tool("old_tool")

        # 模拟时间流逝
        mgr._advance_time(seconds=86400)

        mgr.evaluate()

        state = mgr.get_state("old_tool")
        assert state == ToolLifecycleState.DEGRADED

    def test_archived_after_prolonged_inactivity(self):
        """长期不活跃标记为 ARCHIVED"""
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager, ToolLifecycleState

        mgr = ToolLifecycleManager(
            degraded_after_seconds=0.0,
            archived_after_seconds=0.0,  # 立即进入 ARCHIVED
        )
        mgr.register_tool("forgotten_tool")

        mgr._advance_time(seconds=5270400)
        mgr.evaluate()

        state = mgr.get_state("forgotten_tool")
        assert state == ToolLifecycleState.ARCHIVED

    def test_active_tool_not_degraded(self):
        """频繁使用的工具保持 ACTIVE"""
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager, ToolLifecycleState

        mgr = ToolLifecycleManager(degraded_after_seconds=2592000.0)
        mgr.register_tool("active_tool")

        # 模拟使用
        for _ in range(50):
            mgr.touch("active_tool")

        mgr.evaluate()

        state = mgr.get_state("active_tool")
        assert state == ToolLifecycleState.ACTIVE

    def test_cannot_delete_active_tool(self):
        """ACTIVE 状态工具不可删除"""
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager, ToolLifecycleState

        mgr = ToolLifecycleManager()
        mgr.register_tool("critical_tool")

        with pytest.raises(ValueError, match="ACTIVE"):
            mgr.delete_tool("critical_tool")

    def test_can_delete_archived_tool(self):
        """ARCHIVED 状态工具可删除"""
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager, ToolLifecycleState

        mgr = ToolLifecycleManager(
            degraded_after_seconds=0.0,
            archived_after_seconds=0.0,
        )
        mgr.register_tool("disposable_tool")

        mgr._advance_time(seconds=7862400)
        mgr.evaluate()

        mgr.delete_tool("disposable_tool")
        assert mgr.get_state("disposable_tool") is None


# ============================================================
# P2-3.2 权重衰减
# ============================================================


class TestToolWeightDecay:
    """权重衰减机制"""

    def test_inactivity_decay_integration(self):
        """与 AdaptiveToolWeights 的衰减集成

        A/B 融合（2026-09-04）：AdaptiveToolWeights 统一为 closed_loop 版本
        （含惰性时间衰减），evolution/tool_weights.py A 版死代码已删除。
        """
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager
        from neurova.evolution.closed_loop import AdaptiveToolWeights

        atw = AdaptiveToolWeights()
        atw.register_tool("browser_click")

        # 奖励
        atw.update_weight("browser_click", True)
        atw.update_weight("browser_click", True)

        # 获取权重
        weight_before = atw.get_effective_weight("browser_click")

        from neurova.evolution.tool_lifecycle import ToolLifecycleState

        mgr = ToolLifecycleManager(degraded_after_seconds=0.0)
        mgr.register_tool("browser_click")

        # 长时间不活动后应用衰减（当前契约：apply_decay 迁移生命周期状态；
        # 超过全部阈值时允许直接进入 ARCHIVED，跳过中间态）
        mgr._advance_time(seconds=5184000)
        changes = mgr.apply_decay()

        final_state = mgr.get_state("browser_click")
        assert final_state in (ToolLifecycleState.DEGRADED, ToolLifecycleState.ARCHIVED)
        assert changes["degraded"] + changes["archived"] >= 1
        # 权重本身由 record_success/failure 驱动，不受生命周期迁移影响
        weight_after = atw.get_effective_weight("browser_click")
        assert weight_after == weight_before

    def test_anti_forgetting_boost(self):
        """反遗忘机制：用户触发时权重恢复"""
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager, ToolLifecycleState

        mgr = ToolLifecycleManager(
            degraded_after_seconds=0.0,
            archived_after_seconds=10368000.0,  # 高阈值避免进入 ARCHIVED
        )
        mgr.register_tool("revived_tool")

        # 先让它进入 DEGRADED（60天 > 0 天 degraded 阈值，但 < 120 天 archived 阈值）
        mgr._advance_time(seconds=5184000)
        mgr.evaluate()
        assert mgr.get_state("revived_tool") == ToolLifecycleState.DEGRADED

        # 反遗忘：恢复
        mgr.revive("revived_tool")
        assert mgr.get_state("revived_tool") == ToolLifecycleState.ACTIVE


# ============================================================
# P2-3.3 批量评估
# ============================================================


class TestToolLifecycleBatch:
    """批量操作"""

    def test_evaluate_all_tools(self):
        """批量评估所有工具状态"""
        from neurova.evolution.tool_lifecycle import ToolLifecycleManager, ToolLifecycleState

        mgr = ToolLifecycleManager(
            degraded_after_seconds=0.0,
            archived_after_seconds=1.0,
        )
        mgr.register_tool("tool_a")
        mgr.register_tool("tool_b")
        mgr.register_tool("tool_c")

        mgr._advance_time(seconds=3888000)
        mgr.evaluate()

        report = mgr.get_lifecycle_report()
        assert report["total"] == 3
        assert report["active"] + report["degraded"] + report["archived"] == 3

    def test_get_archivable_tools(self):
        """获取可归档工具列表"""
        from neurova.evolution.tool_lifecycle import (
            ToolLifecycleManager,
            ToolLifecycleState,
        )

        mgr = ToolLifecycleManager(
            degraded_after_seconds=0.0,
            archived_after_seconds=1.0,
        )
        mgr.register_tool("keep")
        mgr.register_tool("archive_me")

        # 落在 ARCHIVED 区间（>1s 且 <90 天冻结阈值）
        mgr._advance_time(seconds=172800)
        mgr.evaluate()

        archivable = mgr.get_tools_by_state(ToolLifecycleState.ARCHIVED)
        assert len(archivable) >= 1
