"""闭环 A：自动技能改进统一走 SkillEvolutionService；自动应用受治理开关控制。"""

from types import SimpleNamespace

import pytest

from neurova.evolution.evolution_settings import (
    EvolutionSettings,
    auto_apply_skill_evolution_enabled,
)


class _FakeService:
    instances = []

    def __init__(self, agent_id):
        self.agent_id = agent_id
        self.evolve_calls = []
        self.decide_calls = []
        self.dataset = object()
        _FakeService.instances.append(self)

    def list_proposals(self, status=None):
        return []

    async def build_dataset(self, skill_id, skill_text, *, source="auto", messages=None):
        return self.dataset

    async def evolve(self, **kwargs):
        self.evolve_calls.append(kwargs)
        return SimpleNamespace(rejected=False), SimpleNamespace(
            proposal_id="evo-1", skill_id=kwargs["skill_id"]
        )

    def decide(self, proposal_id, approve, registry=None, approver=""):
        self.decide_calls.append(
            {"proposal_id": proposal_id, "approve": approve, "approver": approver}
        )
        return True


class _FakeImprover:
    def __init__(self):
        self.applied = []

    async def propose_pending_improvements_async(self):
        return [SimpleNamespace(skill_id="sk", description="heuristic")]

    def get_usage_history(self, skill_id):
        return []

    def apply_improvement(self, proposal, registry, skill_service=None):
        self.applied.append(proposal.skill_id)
        return True


@pytest.fixture
def _service_env(monkeypatch):
    _FakeService.instances = []
    monkeypatch.setattr(
        "neurova.evolution.eval.service.SkillEvolutionService", _FakeService
    )
    monkeypatch.setattr(
        "neurova.evolution.eval.config.text_evolution_enabled", lambda: True
    )
    return _FakeService


@pytest.mark.asyncio
async def test_pass_evolves_through_service_and_leaves_pending_by_default(
    _service_env, monkeypatch
):
    from neurova.post_chat_pipeline import run_skill_evolution_pass

    monkeypatch.setattr(
        "neurova.evolution.evolution_settings.auto_apply_skill_evolution_enabled",
        lambda: False,
    )
    improver = _FakeImprover()
    handled = await run_skill_evolution_pass(
        improver=improver,
        growth_log_manager=None,
        skill_registry=object(),
        skill_service=object(),
        skill_text_loader=lambda sid: "base",
        reflection_type=object(),
        agent_id="agent",
    )

    service = _service_env.instances[-1]
    assert handled == 1
    assert len(service.evolve_calls) == 1
    assert service.evolve_calls[0]["skill_id"] == "sk"
    assert service.decide_calls == []


@pytest.mark.asyncio
async def test_pass_auto_applies_only_when_governance_switch_on(
    _service_env, monkeypatch
):
    from neurova.post_chat_pipeline import run_skill_evolution_pass

    monkeypatch.setattr(
        "neurova.evolution.evolution_settings.auto_apply_skill_evolution_enabled",
        lambda: True,
    )
    await run_skill_evolution_pass(
        improver=_FakeImprover(),
        growth_log_manager=None,
        skill_registry=object(),
        skill_service=object(),
        skill_text_loader=lambda sid: "base",
        reflection_type=object(),
        agent_id="agent",
    )

    service = _service_env.instances[-1]
    assert service.decide_calls == [
        {"proposal_id": "evo-1", "approve": True, "approver": "auto:evolution"}
    ]


@pytest.mark.asyncio
async def test_pass_never_auto_applies_judge_fallback_proposal(
    _service_env, monkeypatch
):
    from neurova.post_chat_pipeline import run_skill_evolution_pass

    class _ManualService(_FakeService):
        async def evolve(self, **kwargs):
            self.evolve_calls.append(kwargs)
            return SimpleNamespace(rejected=False), SimpleNamespace(
                proposal_id="evo-manual",
                skill_id=kwargs["skill_id"],
                requires_manual_review=True,
            )

    monkeypatch.setattr(
        "neurova.evolution.eval.service.SkillEvolutionService", _ManualService
    )
    monkeypatch.setattr(
        "neurova.evolution.evolution_settings.auto_apply_skill_evolution_enabled",
        lambda: True,
    )
    await run_skill_evolution_pass(
        improver=_FakeImprover(),
        growth_log_manager=None,
        skill_registry=object(),
        skill_service=object(),
        skill_text_loader=lambda sid: "base",
        reflection_type=object(),
        agent_id="agent",
    )

    assert _ManualService.instances[-1].decide_calls == []


@pytest.mark.asyncio
async def test_pass_forwards_failure_evidence_to_service(_service_env, monkeypatch):
    from neurova.post_chat_pipeline import run_skill_evolution_pass

    from neurova.evolution.eval.mutator import JudgeFailure

    monkeypatch.setattr(
        "neurova.evolution.skill_evidence.failureJudgeFailures",
        lambda records, limit=5: [JudgeFailure("prod-fail", "out", "err", 0.0)],
    )
    await run_skill_evolution_pass(
        improver=_FakeImprover(),
        growth_log_manager=None,
        skill_registry=object(),
        skill_service=object(),
        skill_text_loader=lambda sid: "base",
        reflection_type=object(),
        agent_id="agent",
    )
    extra = _service_env.instances[-1].evolve_calls[0]["extra_failures"]
    assert extra and extra[0].task_input == "prod-fail"


@pytest.mark.asyncio
async def test_pass_forwards_domain_harnesses_to_service(_service_env, monkeypatch):
    from neurova.post_chat_pipeline import run_skill_evolution_pass

    class _Lib:
        def skillDomain(self, skill_id):
            return "legal"

        def listDomainHarnesses(self, domain, *, limit=5, exclude_skill_id=""):
            return [{"skill_id": "peer", "version": "1.2.0", "context_template": "PEER"}]

    monkeypatch.setattr(
        "neurova.skills.library_service.agentLibrary", lambda *a, **k: _Lib()
    )
    await run_skill_evolution_pass(
        improver=_FakeImprover(),
        growth_log_manager=None,
        skill_registry=object(),
        skill_service=object(),
        skill_text_loader=lambda sid: "base",
        reflection_type=object(),
        agent_id="agent",
    )
    domain = _service_env.instances[-1].evolve_calls[0]["domain_harnesses"]
    assert domain and domain[0]["skill_id"] == "peer"


@pytest.mark.asyncio
async def test_pass_skips_service_without_golden_dataset(_service_env, monkeypatch):
    from neurova.post_chat_pipeline import run_skill_evolution_pass

    class _NoDataset(_FakeService):
        async def build_dataset(self, *args, **kwargs):
            return None

    monkeypatch.setattr(
        "neurova.evolution.eval.service.SkillEvolutionService", _NoDataset
    )
    await run_skill_evolution_pass(
        improver=_FakeImprover(),
        growth_log_manager=None,
        skill_registry=object(),
        skill_service=object(),
        skill_text_loader=lambda sid: "base",
        reflection_type=object(),
        agent_id="agent",
    )
    assert _NoDataset.instances[-1].evolve_calls == []


def test_auto_apply_setting_defaults_off_and_env_wins(tmp_path, monkeypatch):
    settings_path = tmp_path / "evolution_settings.json"
    monkeypatch.setenv("NEUROVA_EVOLUTION_SETTINGS", str(settings_path))
    monkeypatch.delenv("NEUROVA_AUTO_APPLY_SKILL_EVOLUTION", raising=False)

    assert EvolutionSettings().auto_apply_skill_evolution is False
    assert auto_apply_skill_evolution_enabled() is False

    monkeypatch.setenv("NEUROVA_AUTO_APPLY_SKILL_EVOLUTION", "1")
    assert auto_apply_skill_evolution_enabled() is True

    monkeypatch.setenv("NEUROVA_AUTO_APPLY_SKILL_EVOLUTION", "0")
    assert auto_apply_skill_evolution_enabled() is False
