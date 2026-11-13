"""HN3+HN4 / HC3+HC4 执行档位组＋分段预算提醒＋Stop 钩子 —— 红灯测试。

HarnessPro 对照（2026-11-13）断点：
- HN3：努力路由是关键词启发式，无置信度兜底、无预算联动；
- HN4：门控预算全局单一（无分档 profile）；Stop 钩子已定义、全仓零调用点。

本文件钉四件事：
1. 执行档位（EXEC_PROFILES）：standard=内置默认逐字不变；lite/heavy 是运营
   选档入口；env NEUROVA_EXEC_PROFILE 选择；非法值回退 standard 并告警；
   优先级 env > profile > 设置文件 > 内置默认；
2. 分段预算提醒（budget_stages）：economy/strict/finalize 三段阈值随档位
   派生且严格递增；提醒只注入文本（不终止）；NEUROVA_BUDGET_STAGES=off 关；
3. Stop 钩子接线：runStopHooks 默认关（NEUROVA_STOP_HOOKS=1 显式开），
   开启时执行 data/hooks.json 的 Stop 条目；
4. 努力回退（HN3）：resolveQueryEffort 显式 > 启发式 > 歧义显式回退
   standard（source=fallback_standard）；ambiguous 不再是"什么都不留"。
"""

import json

import pytest

from neurova.agent import budget_stages
from neurova.agent.budget_stages import (
    budgetStageGuidance,
    stageThresholds,
    stagesEnabled,
)
from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
from neurova.agent.effort_inference import resolveQueryEffort
from neurova.security import agent_limits_settings
from neurova.security.agent_limits_settings import (
    EXEC_PROFILES,
    active_exec_profile,
    get_effective_limits,
)


@pytest.fixture
def isolated_limits(monkeypatch, tmp_path):
    """隔离设置文件与档位 env：每次用例从内置默认出发。"""
    monkeypatch.setenv("NEUROVA_AGENT_LIMITS_SETTINGS", str(tmp_path / "none.json"))
    monkeypatch.delenv("NEUROVA_EXEC_PROFILE", raising=False)
    for key in ("NEUROVA_AGENT_TOKEN_BUDGET", "NEUROVA_AGENT_MAX_LOOP_ROUNDS",
                "NEUROVA_AGENT_MAX_PARALLEL_TOOLS", "NEUROVA_AGENT_GOAL_ROUND_BUDGET",
                "NEUROVA_AGENT_MAX_SUBAGENT_DEPTH", "NEUROVA_AGENT_GOAL_CONTINUATIONS"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


# ── 1. 执行档位 ─────────────────────────────────────────────────

class TestExecProfiles:
    def test_standard_profile_is_registry_defaults(self, isolated_limits):
        assert active_exec_profile() == "standard"
        limits = get_effective_limits()
        assert limits["token_budget"] == agent_limits_settings.DEFAULTS["token_budget"]
        assert limits["max_loop_rounds"] == agent_limits_settings.DEFAULTS["max_loop_rounds"]

    def test_lite_profile_narrows_budget(self, isolated_limits):
        isolated_limits.setenv("NEUROVA_EXEC_PROFILE", "lite")
        assert active_exec_profile() == "lite"
        limits = get_effective_limits()
        assert limits["token_budget"] == EXEC_PROFILES["lite"]["token_budget"]
        assert limits["max_loop_rounds"] == EXEC_PROFILES["lite"]["max_loop_rounds"]
        assert limits["max_loop_rounds"] < agent_limits_settings.DEFAULTS["max_loop_rounds"]

    def test_heavy_profile_widens_budget(self, isolated_limits):
        isolated_limits.setenv("NEUROVA_EXEC_PROFILE", "heavy")
        limits = get_effective_limits()
        assert limits["token_budget"] == EXEC_PROFILES["heavy"]["token_budget"]
        assert limits["max_loop_rounds"] > agent_limits_settings.DEFAULTS["max_loop_rounds"]

    def test_invalid_profile_falls_back_to_standard(self, isolated_limits):
        isolated_limits.setenv("NEUROVA_EXEC_PROFILE", "turbo")
        assert active_exec_profile() == "standard"

    def test_profile_overrides_settings_file(self, isolated_limits, tmp_path):
        """优先级 env > profile > 文件：选档是部署级决定，强于管理员微调文件。"""
        cfg_file = tmp_path / "limits.json"
        cfg_file.write_text(json.dumps({"token_budget": 123456}), encoding="utf-8")
        isolated_limits.setenv("NEUROVA_AGENT_LIMITS_SETTINGS", str(cfg_file))
        isolated_limits.setenv("NEUROVA_EXEC_PROFILE", "lite")
        assert get_effective_limits()["token_budget"] == EXEC_PROFILES["lite"]["token_budget"]

    def test_explicit_env_still_beats_profile(self, isolated_limits):
        isolated_limits.setenv("NEUROVA_EXEC_PROFILE", "lite")
        isolated_limits.setenv("NEUROVA_AGENT_TOKEN_BUDGET", "777777")
        assert get_effective_limits()["token_budget"] == 777777

    def test_every_profile_value_within_legal_domain(self, isolated_limits):
        """档位值经 get_effective_limits 夹紧后必须等于原值（不越合法域）。"""
        for name in EXEC_PROFILES:
            isolated_limits.setenv("NEUROVA_EXEC_PROFILE", name)
            limits = get_effective_limits()
            for key, value in EXEC_PROFILES[name].items():
                assert limits[key] == value, (name, key)


# ── 2. 分段预算提醒 ─────────────────────────────────────────────

class TestBudgetStages:
    def test_disabled_by_default_env(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_BUDGET_STAGES", raising=False)
        assert stagesEnabled() is True

    def test_off_switch(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_BUDGET_STAGES", "off")
        assert stagesEnabled() is False
        assert budgetStageGuidance(99, 20) == ""

    def test_thresholds_strictly_increasing_and_bounded(self):
        for profile in ("lite", "standard", "heavy"):
            t = stageThresholds(20, profile)
            assert 0 < t["economy"] < t["strict"] < t["finalize"] < 20
            assert t["reminder"] >= 1

    def test_guidance_fires_at_each_stage(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_BUDGET_STAGES", raising=False)
        t = stageThresholds(20, "standard")
        assert budgetStageGuidance(1, 20) == ""          # 前段不发声
        assert "批量" in budgetStageGuidance(t["economy"], 20)   # economy
        assert "探索" in budgetStageGuidance(t["strict"], 20)    # strict
        assert "收尾" in budgetStageGuidance(t["finalize"], 20)  # finalize

    def test_strict_reminder_repeats_on_cadence(self):
        t = stageThresholds(20, "standard")
        first = budgetStageGuidance(t["strict"], 20)
        assert first != ""
        # 严格段内按 reminder 周期复提醒；非周期轮次不发声
        if t["strict"] + t["reminder"] <= t["finalize"]:
            assert budgetStageGuidance(t["strict"] + t["reminder"], 20) != ""
        assert budgetStageGuidance(t["strict"] + 1, 20) == ""

    def test_profile_changes_thresholds(self):
        lite = stageThresholds(20, "lite")
        heavy = stageThresholds(20, "heavy")
        assert heavy["economy"] > lite["economy"]  # 重档位给更长的探索段

    def test_degenerate_budget_does_not_crash(self):
        assert isinstance(budgetStageGuidance(1, 1), str)
        assert isinstance(budgetStageGuidance(0, 0), str)


# ── 3. Stop 钩子接线 ────────────────────────────────────────────

class TestStopHooks:
    def test_default_off(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_STOP_HOOKS", raising=False)
        from neurova.core.hooks_engine import runStopHooks

        assert runStopHooks({"session_id": "s"}) == []

    def test_enabled_runs_stop_entries(self, monkeypatch, tmp_path):
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text(json.dumps({
            "hooks": {"Stop": [{"command": "echo stop-hook-ran"}]}
        }), encoding="utf-8")
        monkeypatch.setenv("NEUROVA_HOOKS_CONFIG", str(hooks_file))
        monkeypatch.setenv("NEUROVA_STOP_HOOKS", "1")
        from neurova.core import hooks_engine

        hooks_engine.reset_hook_engine()
        try:
            outcomes = hooks_engine.runStopHooks({"session_id": "s", "reply": "r"})
        finally:
            hooks_engine.reset_hook_engine()
        assert len(outcomes) == 1
        assert outcomes[0].get("blocked") is False

    def test_stop_event_not_executed_via_pretooluse_path(self, monkeypatch, tmp_path):
        """Stop 条目不响应 PreToolUse——事件各归各的匹配桶。"""
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text(json.dumps({
            "hooks": {"Stop": [{"command": "echo x"}]}
        }), encoding="utf-8")
        monkeypatch.setenv("NEUROVA_HOOKS_CONFIG", str(hooks_file))
        from neurova.core import hooks_engine

        hooks_engine.reset_hook_engine()
        try:
            assert hooks_engine.get_hook_engine().run("PreToolUse", {"tool_name": "t"}) == []
        finally:
            hooks_engine.reset_hook_engine()


# ── 4. 努力回退（HN3）────────────────────────────────────────────

class TestResolveQueryEffort:
    def test_explicit_wins(self):
        assert resolveQueryEffort("随便聊聊", current="deep") == ("deep", "explicit")
        assert resolveQueryEffort("分析论证", current="standard") == ("standard", "explicit")

    def test_inferred_levels(self):
        assert resolveQueryEffort("帮我分析这套系统的并发瓶颈") == ("deep", "inferred")
        assert resolveQueryEffort("你好") == ("light", "inferred")

    def test_ambiguous_falls_back_to_standard_explicitly(self):
        """歧义不再"什么都不留"：显式回退 standard，来源可读。"""
        assert resolveQueryEffort("帮我看看这个项目") == ("standard", "fallback_standard")
        assert resolveQueryEffort("") == ("standard", "fallback_standard")


def _pipeline() -> ChatPipeline:
    return object.__new__(ChatPipeline)


class TestAutoEffortFallbackWiring:
    def test_ambiguous_gets_explicit_standard_without_injection(self, monkeypatch):
        """歧义 ⇒ metadata 落 standard＋来源标记；standard 不注入指令
        （提示面与旧行为同形，元数据面从"空"变"显式档"）。"""
        monkeypatch.delenv("NEUROVA_AUTO_EFFORT", raising=False)
        pipe = _pipeline()
        ctx = ChatContext(user_input="帮我看看这个项目", metadata={}, context=[])
        pipe._apply_thinking_effort(ctx)
        assert ctx.metadata["thinking_effort"] == "standard"
        assert ctx.metadata["thinking_effort_source"] == "fallback_standard"
        assert all("回答模式" not in str(m.get("content", ""))
                   for m in ctx.context if isinstance(m, dict))
