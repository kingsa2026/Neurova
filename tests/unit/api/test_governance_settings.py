"""治理遗留收口回归测试（2026-09-05：RSI 回滚天数真实来源 + 治理设置端点 + 9.96 消费链）

遗留 A：phase 评估的 days_without_rollback 恒读 metrics（无人写入）——1→2 需要
7 天无回滚数据，指标永缺意味着半自动阶段永远不可达。真实来源是
rollback_manager.get_rollback_history() 的时间戳。

遗留 B：Step9.96 的 NEUROVA_CONVERSATION_RULES 门控无管理面——生产上无法开启。
治理设置端点（GET/PUT /v1/settings/governance，require_admin + JSON 持久化）
暴露 conversation_rules_enabled 与 rsi_phase；Step9.96 改为消费设置值
（env=0 强制关 > 设置值 > 默认关）。
"""

import asyncio
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestDaysWithoutRollbackRealSource:
    """工单 004 推翻并重建了本类前三条用例，理由记在此处（教义第 3 条：
    不得靠删除或放宽断言让红色消失）。

    被推翻的旧断言 `test_no_rollback_history_returns_zero` 把
    "空回滚历史 → 0 天" 写成了期望值，其文档串称"从首次运行起算的语义由
    metrics 记录承接" —— 而 metrics 里那个键从没人写过，
    `orchestrator._started_at` 因此成了零消费方死字段。
    后果：phase 1→2 要求 ≥7 天无回滚，而该读数恒 0 → 自动执行通道三角死锁。

    新契约：回滚历史与装配时刻由 `RSIRollbackManager` 唯一持有并可持久化；
    无历史时从装配时刻起算；两者都取不到时返回 None，由编排器把该键从判据里
    摘掉（落 `unevidenced`），而不是伪装成 0。

    另外，旧实现用 `MagicMock` 喂一段**有内容**的回滚历史，
    于是"历史从不被写入"这一根因在测试里不可见 —— 本类改用真实 manager 实例。
    """

    def _orch(self):
        from neurova.evolution.rsi.orchestrator import RSIOrchestrator

        return RSIOrchestrator(
            sleep_system=MagicMock(),
            emotion_system=MagicMock(),
            experience_system=MagicMock(),
            tool_memory_system=MagicMock(),
        )

    def _manager_with_history(self, *, days_ago: float):
        from datetime import timedelta

        from neurova.evolution.rsi.rollback_manager import RSIRollbackManager

        manager = RSIRollbackManager()
        snapshot_id = manager.create_snapshot({"p": {"system": "sleep", "value": 0.7}})
        assert manager.execute_rollback(snapshot_id) is True
        manager._rollback_history[-1]["timestamp"] = (
            datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        return manager

    def test_computes_days_from_rollback_history(self):
        """最近一次回滚 3 天前 → days_since_last_rollback = 3"""
        days = self._manager_with_history(days_ago=3).days_since_last_rollback()

        assert days == pytest.approx(3, abs=0.2)

    def test_no_rollback_history_counts_from_install(self):
        """无回滚记录 → 距装配时刻的天数（工单 004 推翻旧的"恒 0"）。

        恒 0 意味着 phase 1→2 的 7 天永不可满足；
        从装配时刻起算才是它文档串里承诺的那个语义。
        """
        from neurova.evolution.rsi.rollback_manager import RSIRollbackManager

        manager = RSIRollbackManager()
        manager.installed_at = datetime.now(timezone.utc) - timedelta(days=9)

        assert manager.days_since_last_rollback() == pytest.approx(9, abs=0.2)
        assert manager.get_rollback_history() == [], "起算点修复不得伪造回滚记录"

    def test_days_is_none_without_any_anchor(self):
        """既无历史又无起算点 → None（无证据），不得编造 0。"""
        from neurova.evolution.rsi.rollback_manager import RSIRollbackManager

        manager = RSIRollbackManager()
        manager.installed_at = None

        assert manager.days_since_last_rollback() is None

    def test_run_iteration_feeds_real_days_to_phase_eval(self):
        """run_iteration 把真实回滚天数喂给 evaluate_phase_transition"""
        orch = self._orch()
        orch.deployment_controller = MagicMock()
        orch.deployment_controller.can_auto_execute.return_value = False
        orch.deployment_controller.evaluate_phase_transition.return_value = False
        orch.rollback_manager = self._manager_with_history(days_ago=8)
        orch.collect_feedback_signals = MagicMock(return_value={})
        orch.convergence_analyzer = MagicMock()
        orch.convergence_analyzer.analyze_convergence.return_value = {
            "status": "converging", "metrics": {},
        }
        orch.generate_optimizations = MagicMock(return_value=[])

        orch.run_iteration()

        metrics_arg = orch.deployment_controller.evaluate_phase_transition.call_args.args[0]
        assert metrics_arg["days_without_rollback"] == pytest.approx(8, abs=0.2)

    def test_run_iteration_omits_days_key_when_no_anchor(self):
        """取不到起算点时该键必须缺席 —— 缺席才会被控制器判成 unevidenced。"""
        from neurova.evolution.rsi.rollback_manager import RSIRollbackManager

        orch = self._orch()
        orch.deployment_controller = MagicMock()
        orch.deployment_controller.can_auto_execute.return_value = False
        orch.deployment_controller.evaluate_phase_transition.return_value = False
        manager = RSIRollbackManager()
        manager.installed_at = None
        orch.rollback_manager = manager
        orch.collect_feedback_signals = MagicMock(return_value={})
        orch.convergence_analyzer = MagicMock()
        orch.convergence_analyzer.analyze_convergence.return_value = {
            "status": "converging", "metrics": {},
        }
        orch.generate_optimizations = MagicMock(return_value=[])

        orch.run_iteration()

        metrics_arg = orch.deployment_controller.evaluate_phase_transition.call_args.args[0]
        assert "days_without_rollback" not in metrics_arg


class TestGovernanceSettingsEndpoint:
    def _client(self, tmpdir):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import neurova.api.endpoints.governance as gov
        from neurova.api.endpoints.governance import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1/governance")
        app.dependency_overrides[gov._governance_admin_dep] = lambda: {"id": 1}
        return TestClient(app), tmpdir

    def test_get_returns_defaults(self, tmp_path):
        client, _ = self._client(tmp_path)
        resp = client.get("/api/v1/governance/settings")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["conversation_rules_enabled"] is False
        assert data["rsi_phase"] == 0

    def test_put_persists_to_disk(self, tmp_path):
        client, tmp = self._client(tmp_path)
        import neurova.security.governance_settings as gs

        patcher = patch.object(gs, "settings_path", return_value=Path(tmp) / "governance_settings.json")
        patcher.start()
        resp = client.put(
                "/api/v1/governance/settings",
                json={"conversation_rules_enabled": True, "rsi_phase": 1},
            )
        assert resp.status_code == 200
        # 重新 GET（新进程语义：从磁盘加载）
        resp2 = client.get("/api/v1/governance/settings")
        data = resp2.json()["data"]
        assert data["conversation_rules_enabled"] is True
        assert data["rsi_phase"] == 1
        patcher.stop()
        # 磁盘文件真实存在
        assert (Path(tmp) / "governance_settings.json").exists()

    def test_put_rejects_invalid_phase(self, tmp_path):
        client, _ = self._client(tmp_path)
        resp = client.put(
                "/api/v1/governance/settings",
                json={"rsi_phase": 9},
            )
        assert resp.status_code == 422

    def test_rsi_phase_setting_applies_to_controller(self, tmp_path):
        """治理设置的 rsi_phase 在 RSI 编排器构建时生效（部署阶段管理面）"""
        from neurova.evolution.rsi.deployment_controller import (
            create_deployment_controller_with_settings,
        )

        ctrl = create_deployment_controller_with_settings({"rsi_phase": 2})
        assert ctrl.get_current_phase() == 2

    def test_default_still_phase_zero(self):
        from neurova.evolution.rsi.deployment_controller import (
            create_deployment_controller_with_settings,
        )

        ctrl = create_deployment_controller_with_settings({})
        assert ctrl.get_current_phase() == 0


class TestStep996ConsumesGovernanceSetting:
    @pytest.mark.asyncio
    async def test_setting_enabled_runs_step(self, tmp_path, monkeypatch):
        """治理设置 conversation_rules_enabled=True → 9.96 不再被门控跳过"""
        monkeypatch.delenv("NEUROVA_CONVERSATION_RULES", raising=False)
        settings_file = tmp_path / "governance_settings.json"
        settings_file.write_text(json.dumps({"conversation_rules_enabled": True}), encoding="utf-8")

        from neurova.post_chat_pipeline import PostChatPipeline

        agent = MagicMock()
        agent.config.agent_id = "default"
        agent._collect_tool_messages.return_value = []
        agent.rule_extractor = None
        agent.experience_fusion = None

        pipeline = PostChatPipeline(agent)
        pipeline._dependency_graph = MagicMock()

        with patch(
            "neurova.security.governance_settings.load_governance_settings",
            return_value={"conversation_rules_enabled": True, "rsi_phase": 0},
        ):
            await pipeline._step_extract_conversation_rules("q", "r", "s1")

        statuses = [(r.step_name, str(r.status)) for r in pipeline._step_results]
        # 不被门控跳过（后续可能因依赖缺失 SKIPPED，但消息不是 cost gate）
        gate_skips = [
            s for n, s in statuses
            if n == "extract_conversation_rules" and "cost gate" in s
        ]
        assert not gate_skips, "治理设置开启后不得再被 LLM 成本门控拦截"

    @pytest.mark.asyncio
    async def test_env_zero_overrides_setting(self, monkeypatch):
        """env 显式设 0 强制关（运维后门优先级最高）"""
        monkeypatch.setenv("NEUROVA_CONVERSATION_RULES", "0")
        from neurova.post_chat_pipeline import PostChatPipeline

        agent = MagicMock()
        pipeline = PostChatPipeline(agent)
        await pipeline._step_extract_conversation_rules("q", "r", "s1")
        assert any(
            r.step_name == "extract_conversation_rules"
            and str(r.status) == "StepStatus.SKIPPED"
            and "cost gate" in (r.message or "")
            for r in pipeline._step_results
        )
