"""闭环 D：技能正文已变时，旧基线提案必须被拒绝应用。"""

from types import SimpleNamespace

from neurova.evolution.eval.service import EvolutionProposal, SkillEvolutionService


def _service(tmp_path):
    return SkillEvolutionService("agent", base_dir=tmp_path / "evo")


def _append(service, baseline="旧正文"):
    service._append_proposal(
        EvolutionProposal(
            proposal_id="p-1",
            agent_id="agent",
            skill_id="sk",
            artifact_type="skill",
            baseline_text=baseline,
            improved_text="新正文",
        )
    )


def test_baseline_changed_rejects_proposal(tmp_path):
    service = _service(tmp_path)
    _append(service)
    skill = SimpleNamespace(config={"context_template": "已经改过的正文"})
    registry = SimpleNamespace(get_skill=lambda sid: skill if sid == "sk" else None)

    ok = service.decide("p-1", approve=True, registry=registry, approver="admin")

    assert ok is False
    rows = service.list_proposals("rejected")
    assert rows and rows[0]["status_reason"] == "baseline_changed"
