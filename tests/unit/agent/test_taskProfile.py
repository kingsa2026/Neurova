"""R3+R6 任务级执行档位 —— 红灯测试。

§10.2 R3（按任务动态档位）/ R6（per-agent 档位派发）：

1. turn_profile ContextVar：set/get/reset 与非法值拒收；
2. applyTurnProfileOverlay：任务级档位覆盖 limits（lite 收窄/heavy 放宽）；
3. classifyTaskProfile（rubric 分类器）：正常解析、低置信度回退 standard、
   LLM 失败 fail-open standard、开关默认关；
4. per-agent 档位存储（agent_profile_settings）：合法域校验＋持久往返；
5. chat_pipeline._resolve_task_profile 优先级：显式 metadata > agent 存储 >
   分类器（灰度）> 部署 env（不设即回落）；
6. budget_stages/tool_offload 读任务级档位优先于部署档位。
"""

import pytest

from neurova.agent import budget_stages, turn_profile
from neurova.agent.turn_profile import (
    applyTurnProfileOverlay,
    classifyTaskProfile,
    clearTurnProfile,
    getTurnProfile,
    resetTurnProfile,
    setTurnProfile,
    taskProfileEnabled,
)
from neurova.security import agent_profile_settings, agent_limits_settings


@pytest.fixture(autouse=True)
def _cleanTurnProfile():
    clearTurnProfile()
    yield
    clearTurnProfile()


# ── 1/2. ContextVar 与覆盖 ───────────────────────────────────────

class TestTurnProfile:
    def test_set_get_reset(self):
        token = setTurnProfile("lite")
        assert getTurnProfile() == "lite"
        resetTurnProfile(token)
        assert getTurnProfile() is None

    def test_invalid_name_ignored(self):
        token = setTurnProfile("turbo")
        assert getTurnProfile() is None
        if token is not None:
            resetTurnProfile(token)

    def test_overlay_narrows_for_lite(self):
        limits = agent_limits_settings.DEFAULTS.copy()
        overlaid = applyTurnProfileOverlay(limits, "lite")
        assert overlaid["max_loop_rounds"] == 10
        assert overlaid["token_budget"] == 40000

    def test_overlay_standard_is_noop(self):
        limits = agent_limits_settings.DEFAULTS.copy()
        assert applyTurnProfileOverlay(limits, "standard") == limits

    def test_overlay_unknown_name_noop(self):
        limits = agent_limits_settings.DEFAULTS.copy()
        assert applyTurnProfileOverlay(limits, "turbo") == limits


# ── 3. rubric 分类器 ─────────────────────────────────────────────

class TestClassifyTaskProfile:
    def test_switch_default_off(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_TASK_PROFILE", raising=False)
        assert taskProfileEnabled() is False

    def test_switch_on(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_TASK_PROFILE", "1")
        assert taskProfileEnabled() is True

    @pytest.mark.asyncio
    async def test_classifies_via_injected_llm(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_TASK_PROFILE", "1")

        async def llm(messages, model):
            return {"success": True,
                    "response": '{"profile": "heavy", "confidence": 0.9, "reason": "多系统重构"}'}

        profile, source, confidence = await classifyTaskProfile(
            "把整个订单系统迁移到新的分片架构并保证数据一致", llm_call=llm)
        assert (profile, source) == ("heavy", "classified")
        assert confidence == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_low_confidence_falls_back_to_standard(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_TASK_PROFILE", "1")

        async def llm(messages, model):
            return {"success": True,
                    "response": '{"profile": "lite", "confidence": 0.3, "reason": "拿不准"}'}

        profile, source, confidence = await classifyTaskProfile("帮我看看这个项目", llm_call=llm)
        assert (profile, source) == ("standard", "low_confidence")
        assert confidence == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_llm_failure_fails_open_to_standard(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_TASK_PROFILE", "1")

        async def llm(messages, model):
            return {"success": False, "error": "no provider"}

        profile, source, confidence = await classifyTaskProfile("随便什么任务", llm_call=llm)
        assert (profile, source) == ("standard", "classifier_failed")
        assert confidence == 0.0

    @pytest.mark.asyncio
    async def test_invalid_profile_rejected(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_TASK_PROFILE", "1")

        async def llm(messages, model):
            return {"success": True, "response": '{"profile": "turbo", "confidence": 0.9}'}

        profile, source, _ = await classifyTaskProfile("x", llm_call=llm)
        assert (profile, source) == ("standard", "classifier_failed")


# ── 4. per-agent 档位存储（R6）───────────────────────────────────

class TestAgentProfileStore:
    def test_roundtrip_and_domain(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_AGENT_PROFILES_SETTINGS", str(tmp_path / "profiles.json"))
        assert agent_profile_settings.get_agent_profile("agent-1") == ""
        assert agent_profile_settings.set_agent_profile("agent-1", "lite") is True
        assert agent_profile_settings.get_agent_profile("agent-1") == "lite"
        # 重启（重新加载）仍在
        assert agent_profile_settings.all_agent_profiles()["agent-1"] == "lite"

    def test_invalid_profile_rejected(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_AGENT_PROFILES_SETTINGS", str(tmp_path / "profiles.json"))
        assert agent_profile_settings.set_agent_profile("agent-1", "turbo") is False
        assert agent_profile_settings.get_agent_profile("agent-1") == ""

    def test_unknown_agent_reads_empty(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_AGENT_PROFILES_SETTINGS", str(tmp_path / "profiles.json"))
        assert agent_profile_settings.get_agent_profile("nobody") == ""


# ── 5. 管线解析优先级 ────────────────────────────────────────────

class _StubAgent:
    def __init__(self, agent_id: str = ""):
        self.agent_id = agent_id


def _pipeline(agent_id: str = "agent-1"):
    from neurova.agent.chat_pipeline import ChatPipeline

    pipe = object.__new__(ChatPipeline)
    pipe._agent = _StubAgent(agent_id)
    return pipe


def _ctx(user_input: str = "处理一个任务", metadata=None):
    from neurova.agent.chat_pipeline import ChatContext

    return ChatContext(user_input=user_input, metadata=metadata, context=[])


class TestResolveTaskProfile:
    @pytest.mark.asyncio
    async def test_explicit_metadata_wins(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_AGENT_PROFILES_SETTINGS",
                           str(__import__("pathlib").Path(__file__).parent / "none.json"))
        monkeypatch.delenv("NEUROVA_TASK_PROFILE", raising=False)
        pipe = _pipeline("agent-1")
        ctx = _ctx(metadata={"task_profile": "heavy"})
        await pipe._resolve_task_profile(ctx)
        assert getTurnProfile() == "heavy"

    @pytest.mark.asyncio
    async def test_agent_stored_profile_second(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_AGENT_PROFILES_SETTINGS", str(tmp_path / "profiles.json"))
        monkeypatch.delenv("NEUROVA_TASK_PROFILE", raising=False)
        agent_profile_settings.set_agent_profile("agent-1", "lite")
        pipe = _pipeline("agent-1")
        ctx = _ctx()
        await pipe._resolve_task_profile(ctx)
        assert getTurnProfile() == "lite"

    @pytest.mark.asyncio
    async def test_classifier_off_leaves_deployment_default(self, monkeypatch, tmp_path):
        """分类器默认关、agent 未设档 ⇒ 不设任务级档位（回落部署 env 档）。"""
        monkeypatch.setenv("NEUROVA_AGENT_PROFILES_SETTINGS", str(tmp_path / "profiles.json"))
        monkeypatch.delenv("NEUROVA_TASK_PROFILE", raising=False)
        pipe = _pipeline("agent-1")
        ctx = _ctx()
        await pipe._resolve_task_profile(ctx)
        assert getTurnProfile() is None

    @pytest.mark.asyncio
    async def test_classifier_enabled_classifies(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_AGENT_PROFILES_SETTINGS", str(tmp_path / "profiles.json"))
        monkeypatch.setenv("NEUROVA_TASK_PROFILE", "1")

        import neurova.agent.turn_profile as tp

        async def fake_classify(text, **kw):
            return "heavy", "classified", 0.95

        monkeypatch.setattr(tp, "classifyTaskProfile", fake_classify)
        pipe = _pipeline("agent-1")
        ctx = _ctx()
        await pipe._resolve_task_profile(ctx)
        assert getTurnProfile() == "heavy"
        assert ctx.metadata["task_profile_source"] == "classified"

    @pytest.mark.asyncio
    async def test_fail_open_does_not_raise(self, monkeypatch, tmp_path):
        """解析链任何异常都不阻断对话（fail-open）。"""
        monkeypatch.setenv("NEUROVA_AGENT_PROFILES_SETTINGS", str(tmp_path / "profiles.json"))
        monkeypatch.setenv("NEUROVA_TASK_PROFILE", "1")

        async def boom(text, **kw):
            raise RuntimeError("classifier down")

        import neurova.agent.turn_profile as tp

        monkeypatch.setattr(tp, "classifyTaskProfile", boom)
        pipe = _pipeline("agent-1")
        ctx = _ctx()
        await pipe._resolve_task_profile(ctx)  # 不抛
        assert getTurnProfile() is None


# ── 6. 分段提醒/溢出阈值读任务级档位 ─────────────────────────────

class TestTurnProfileConsumers:
    def test_budget_stages_prefers_turn_profile(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_EXEC_PROFILE", "heavy")
        token = setTurnProfile("lite")
        try:
            assert budget_stages.activeProfile() == "lite"
            t = budget_stages.stageThresholds(20)
            assert t["economy"] == budget_stages.stageThresholds(20, "lite")["economy"]
        finally:
            resetTurnProfile(token)
        assert budget_stages.activeProfile() == "heavy"

    def test_offload_multiplier_prefers_turn_profile(self, monkeypatch):
        from neurova.security import tool_offload_settings as tos

        monkeypatch.setenv("NEUROVA_EXEC_PROFILE", "standard")
        token = setTurnProfile("heavy")
        try:
            assert tos.get_threshold_kb() == 128
        finally:
            resetTurnProfile(token)
        assert tos.get_threshold_kb() == 64


# ── 7. 分类器开关设置项化（env > 文件 > 默认关）──────────────────

class TestTaskProfileSettings:
    def test_default_off(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_TASK_PROFILE_SETTINGS", str(tmp_path / "tp.json"))
        monkeypatch.delenv("NEUROVA_TASK_PROFILE", raising=False)
        from neurova.security import task_profile_settings as tps

        assert tps.classification_enabled() is False

    def test_file_persists_and_env_wins(self, monkeypatch, tmp_path):
        from neurova.security import task_profile_settings as tps

        cfg = tmp_path / "tp.json"
        monkeypatch.setenv("NEUROVA_TASK_PROFILE_SETTINGS", str(cfg))
        monkeypatch.delenv("NEUROVA_TASK_PROFILE", raising=False)
        assert tps.save_settings(True, cfg) is True
        assert tps.load_settings(cfg)["classification_enabled"] is True
        # env=0 压过文件的开
        monkeypatch.setenv("NEUROVA_TASK_PROFILE", "0")
        assert tps.classification_enabled() is False
        # env=1 压过文件的关
        tps.save_settings(False, cfg)
        monkeypatch.setenv("NEUROVA_TASK_PROFILE", "1")
        assert tps.classification_enabled() is True

    def test_turn_profile_switch_reads_settings(self, monkeypatch, tmp_path):
        from neurova.security import task_profile_settings as tps

        cfg = tmp_path / "tp.json"
        monkeypatch.setenv("NEUROVA_TASK_PROFILE_SETTINGS", str(cfg))
        monkeypatch.delenv("NEUROVA_TASK_PROFILE", raising=False)
        tps.save_settings(True, cfg)
        assert taskProfileEnabled() is True
        tps.save_settings(False, cfg)
        assert taskProfileEnabled() is False

    def test_corrupt_file_falls_back(self, monkeypatch, tmp_path):
        cfg = tmp_path / "tp.json"
        cfg.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("NEUROVA_TASK_PROFILE_SETTINGS", str(cfg))
        monkeypatch.delenv("NEUROVA_TASK_PROFILE", raising=False)
        from neurova.security import task_profile_settings as tps

        assert tps.classification_enabled() is False
