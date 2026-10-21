"""N8 独立采纳：peer harness → pending 提案 → 人工批准写回目标技能。"""

from types import SimpleNamespace

from neurova.evolution.eval.service import SkillEvolutionService


def test_domain_adoption_is_pending_then_applied_on_approval(tmp_path, monkeypatch):
    service = SkillEvolutionService("agent", base_dir=tmp_path / "evo")
    target_skill = SimpleNamespace(
        name="target", version="1.0.0", config={"context_template": "目标旧正文"}
    )
    registry = SimpleNamespace(get_skill=lambda sid: target_skill if sid == "target" else None)

    captured = {}
    library = SimpleNamespace(
        get_skill_info=lambda sid: {
            "manifest": {"config": {"context_template": "目标旧正文"}},
            "version": "1.0.0",
        },
        update_auto_skill=lambda *a, **k: captured.update(k) or True,
    )
    monkeypatch.setattr("neurova.evolution.eval.service.agentLibrary", lambda *a, **k: library)

    proposal = service.proposeAdoption(
        target_skill_id="target",
        baseline_text="目标旧正文",
        peer_skill_id="peer",
        improved_text="同域 peer 正文",
    )
    assert proposal.status == "pending"
    assert service.list_proposals("pending")[0]["proposal_id"] == proposal.proposal_id

    ok = service.decide(
        proposal.proposal_id, approve=True, registry=registry, approver="admin"
    )

    assert ok is True
    assert captured["config"]["context_template"] == "同域 peer 正文"
    assert service.list_proposals("applied")[0]["proposal_id"] == proposal.proposal_id
