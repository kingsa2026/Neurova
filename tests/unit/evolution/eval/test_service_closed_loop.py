"""Wave 核验 — SkillEvolutionService 闭环测试(提案 pending → 批准写回)。"""

import json

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.service import SkillEvolutionService


BASELINE = "基础技能正文。" + "补充说明文字用于满足增长闸的基线长度要求。" * 2  # >60 字符


def _ds():
    return EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="r") for i in range(4)],
        val=[EvalExample(task_input=f"v{i}", expected_behavior="r") for i in range(2)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="r") for i in range(2)],
    )


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
    return SkillEvolutionService("agent-x", base_dir=tmp_path / "evo")


async def _judge(*, task_input, expected_behavior, output, skill_text, **kw):
    from neurova.evolution.eval.fitness import FitnessScore
    c = 0.9 if "IMPROVED" in skill_text else 0.2
    return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")


async def _mutate(*, artifact_text, artifact_type, failures):
    return artifact_text + "\nIMPROVED"


class _FakeAgent:
    async def run(self, *, skill_text, task_input):
        return skill_text


class TestEvolveFlow:
    @pytest.mark.asyncio
    async def test_disabled_returns_rejected(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NEUROVA_TEXT_EVOLUTION", raising=False)
        monkeypatch.setenv("NEUROVA_EVOLUTION_SETTINGS", str(tmp_path / "settings.json"))
        service = SkillEvolutionService("agent-x", base_dir=tmp_path / "evo")
        result, proposal = await service.evolve(
            skill_id="s1", skill_text="BASE", dataset=_ds(),
            agent=_FakeAgent(),
        )
        assert result.rejected and result.reject_reason == "disabled"
        assert proposal is None

    @pytest.mark.asyncio
    async def test_accept_produces_pending_proposal(self, svc):
        result, proposal = await svc.evolve(
            skill_id="s1", skill_text=BASELINE, dataset=_ds(),
            agent=_FakeAgent(), config=EvolutionConfig(iterations=1, min_improvement=0.0),
            judge=_judge, mutate=_mutate, bench_gate=None,
        )
        assert not result.rejected
        assert proposal is not None and proposal.status == "pending"
        assert proposal.improved_text == BASELINE + "\nIMPROVED"
        assert proposal.holdout_after > proposal.holdout_before
        # 提案落盘且默认列表含 pending
        pending = svc.list_proposals(status="pending")
        assert len(pending) == 1
        assert pending[0]["skill_id"] == "s1"
        # 拒绝的变体不会写技能:approve 前正文仍是基线
        assert result.deployed_text != BASELINE
        assert pending[0]["improved_text"] != pending[0]["baseline_text"]

    @pytest.mark.asyncio
    async def test_proposal_approve_writes_back(self, svc, tmp_path, monkeypatch):
        """批准是唯一变更点:improved_text 写回 config.context_template。"""
        applied = {}

        class _Entry:
            def __init__(self, cfg):
                self._cfg = cfg

        def fake_update_auto_skill(skill_id, version=None, config=None):
            applied["config"] = config
            applied["version"] = version
            return True

        proposal = {
            "proposal_id": "evo_test", "agent_id": "agent-x", "skill_id": "s1",
            "artifact_type": "skill", "baseline_text": "BASE",
            "improved_text": "BASE+IMPROVED", "status": "pending",
        }
        (svc._dir).mkdir(parents=True, exist_ok=True)
        (svc._proposals_file).write_text(json.dumps([proposal]), encoding="utf-8")

        import neurova.skills.skill_service as ss_mod

        fake_info = {"id": "s1", "version": "1.0.0",
                     "manifest": {"config": {"context_template": "BASE"}}}
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ss_mod.SkillService, "get_skill_info", lambda self, sid: fake_info)
            mp.setattr(ss_mod.SkillService, "update_auto_skill",
                       lambda self, sid, version=None, config=None: fake_update_auto_skill(sid, version, config))
            ok = svc.decide("evo_test", approve=True)
        assert ok
        assert applied["config"]["context_template"] == "BASE+IMPROVED"
        assert applied["version"] == "1.0.1"
        assert svc.list_proposals()[0]["status"] == "approved"

    @pytest.mark.asyncio
    async def test_proposal_reject_keeps_skill(self, svc):
        proposal = {
            "proposal_id": "evo_r", "agent_id": "agent-x", "skill_id": "s1",
            "baseline_text": "BASE", "improved_text": "X", "status": "pending",
        }
        (svc._dir).mkdir(parents=True, exist_ok=True)
        (svc._proposals_file).write_text(json.dumps([proposal]), encoding="utf-8")
        assert svc.decide("evo_r", approve=False)
        assert svc.list_proposals()[0]["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_double_decide_idempotent(self, svc):
        proposal = {
            "proposal_id": "evo_d", "agent_id": "agent-x", "skill_id": "s1",
            "baseline_text": "B", "improved_text": "I", "status": "approved",
        }
        (svc._dir).mkdir(parents=True, exist_ok=True)
        (svc._proposals_file).write_text(json.dumps([proposal]), encoding="utf-8")
        assert not svc.decide("evo_d", approve=True), "已处理提案不得重复决定"

    @pytest.mark.asyncio
    async def test_run_audit_persisted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        service = SkillEvolutionService("agent-y", base_dir=tmp_path / "evo")
        monkeypatch.setattr(
            "neurova.evolution.eval.runner.SkillEvolutionRunner._call_judge",
            lambda self, **kw: _judge(**kw),
        )
        result, proposal = await service.evolve(
            skill_id="s1", skill_text=BASELINE, dataset=_ds(),
            agent=_FakeAgent(), config=EvolutionConfig(iterations=1, min_improvement=0.0),
            judge=_judge, mutate=_mutate, bench_gate=None,
        )
        runs = list((tmp_path / "evo" / "runs").glob("run_*.json"))
        assert runs, "每次进化运行必须落审计文件"
        payload = json.loads(runs[0].read_text(encoding="utf-8"))
        assert payload["skill_id"] == "s1"
        assert "holdout_before" in payload
