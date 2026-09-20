"""批准即生效（工单 010）：批准之后，技能库里真的有它、下一轮对话能看见它。

审计原状：`approve_and_apply` 只是把内容写进仓库根 `.agents/skills/<id>/manifest.yaml`，
而技能真实加载链是 `SkillService`（`data/agents/{id}/skills`，`manifest.json`）→
`restore_market_skills_from_service` 回灌注册表。目录与格式双双不符、`.agents` 零读取方
⇒ 状态 APPLIED 只是一次文件写入，零运行时效应。

本套件的三件硬事实都经真装配实测（不是推断）：

1. `SkillService.install_skill` 对 `source ∈ {auto, synthesized, llm_created}` 一律按
   **自动行为**要求"至少三个独立真实成功任务证据"。人类刚批准的动作不是自动行为，
   所以必须有一条显式的人类授权通道 —— 否则 010 的正路径按构造走不通。
2. 安装成功后 `restore_market_skills_from_service` 把技能注册进注册表，键是 **name**
   （实测 `agent-esc` → 键 `agent_esc`）。id/name 统一是工单 014 的范围，
   本单按"现键域任一形态命中即算生效"判定，并把这一点写进断言消息而不是藏着。
3. 装不上/回灌不上时**不得**把状态写成 APPLIED（记账与动作不分家）。

用真 `SkillService`（skills_dir 指 tmp）与真 `SkillRegistry`；不允许用替身冒充"装上了"。
"""

from __future__ import annotations

import json

import pytest

from neurova.evolution.rsi.deployment_controller import RSIDeploymentController
from neurova.evolution.rsi.rollback_manager import RSIRollbackManager
from neurova.evolution.rsi.self_improvement_proposer import (
    ProposalType,
    SelfImprovementProposer,
)

MANIFEST_OK = (
    "name: rsi_fix_sleep\n"
    "version: 1.0.0\n"
    "description: 修睡眠整合的低收益路径\n"
    "tool_sequence: [read_memory, write_memory]\n"
)


@pytest.fixture
def registry():
    from neurova.skill_system import SkillRegistry

    return SkillRegistry()


@pytest.fixture
def service(tmp_path):
    from neurova.skills.skill_service import SkillService

    return SkillService("kai", skills_dir=str(tmp_path / "agent-skills"))


def _proposer(tmp_path, *, agent_id="kai", service=None, registry=None, phase=4,
              proposals_dir=None):
    return SelfImprovementProposer(
        agent_id=agent_id,
        proposals_dir=proposals_dir or (tmp_path / "ledger"),
        deployment_controller=RSIDeploymentController(initial_phase=phase),
        rollback_manager=RSIRollbackManager(),
        skill_service=service,
        skill_registry=registry,
    )


def _manifest_proposal(proposer, *, manifest=MANIFEST_OK, skill_id="rsi-fix-sleep"):
    proposal = proposer.propose_skill_manifest(
        skill_id=skill_id, manifest_yaml=manifest, description="RSI 升级提案"
    )
    proposer.submit_proposal(proposal)
    return proposal


def test_approval_installs_into_service_and_registry(tmp_path, service, registry):
    """票面验收 1：批准后技能页列得出、注册表取到了（下一轮才可能用它）。"""
    proposer = _proposer(tmp_path, service=service, registry=registry)
    proposal = _manifest_proposal(proposer)

    result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")

    assert result.success is True, f"批准未生效：{result.error}"
    assert result.applied_skill_id == "rsi-fix-sleep"
    assert result.registry_hit is True, (
        "回灌后注册表按现键域仍取不到 ⇒ 下一轮对话看不见它")
    assert service.get_skill_info("rsi-fix-sleep") is not None
    listed = {str(item.get("id") or item.get("skill_id")) for item in service.list_skills()}
    assert "rsi-fix-sleep" in listed, f"技能页没有它：{sorted(listed)}"


def test_missing_executable_sequence_is_not_supported(tmp_path, service, registry):
    """manifest 没有可执行内容 ⇒ 显式 not_supported，不伪报成功、也不吞掉提案。"""
    proposer = _proposer(tmp_path, service=service, registry=registry)
    proposal = _manifest_proposal(
        proposer, manifest="name: rsi_fix_sleep\nversion: 1.0.0\n")

    result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")

    assert result.success is False
    assert "not_supported" in result.error and "tool_sequence" in result.error, result.error
    assert proposal.status.value == "pending", "被拒绝的提案不得离开待审状态"
    assert service.list_skills() == [], "not_supported 却已经装进去了"


def test_approver_may_supply_the_missing_sequence(tmp_path, service, registry):
    """批准人补交 tool_sequence 是人工通道的应有形态（决策①）。"""
    proposer = _proposer(tmp_path, service=service, registry=registry)
    proposal = _manifest_proposal(
        proposer, manifest="name: rsi_fix_sleep\nversion: 1.0.0\n")

    result = proposer.approve_and_apply(
        proposal.proposal_id, approver="admin",
        tool_sequence=["read_memory", "write_memory"],
    )

    assert result.success is True, result.error
    assert service.get_skill_info("rsi-fix-sleep") is not None


@pytest.mark.parametrize("proposal_type,creator", [
    (ProposalType.ACTION_DEFINITION, "propose_action_definition"),
    (ProposalType.PR_PATCH, "propose_pr_patch"),
])
def test_types_without_an_activation_channel_are_not_supported(
        tmp_path, service, registry, proposal_type, creator):
    """没有生效通道的类型必须显式拒绝 —— 继续伪报成功就是本单禁止的表面抹除。"""
    proposer = _proposer(tmp_path, service=service, registry=registry)
    if proposal_type is ProposalType.ACTION_DEFINITION:
        proposal = getattr(proposer, creator)(
            action_name="rsi_new_action", handler_code="def handle(args):\n    return 1\n")
    else:
        proposal = getattr(proposer, creator)(
            target_file="neurova/core.py", patch_content="diff --git a/x b/x\n")
    proposer.submit_proposal(proposal)

    result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")

    assert result.success is False and "not_supported" in result.error, result.error
    assert proposal.status.value == "pending"


def test_registry_writeback_failure_is_not_reported_as_applied(tmp_path, service, registry,
                                                               monkeypatch):
    """装进了库但回灌注册表失败 ⇒ 不得报 APPLIED，状态必须留在 PENDING。"""
    from neurova.evolution.rsi import self_improvement_proposer as sip

    proposer = _proposer(tmp_path, service=service, registry=registry)
    proposal = _manifest_proposal(proposer)
    monkeypatch.setattr(sip, "restore_market_skills_from_service", lambda *a, **k: 0)

    result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")

    assert result.success is False, "回灌 0 条仍被报成批准生效"
    assert registry._skills == {}, "注册表没装上却被记为 APPLIED"
    stored = json.loads(
        (proposer.proposals_dir / f"{proposal.proposal_id}.json").read_text(encoding="utf-8"))
    assert stored["status"] == "pending", f"失败仍被记账为 {stored['status']}"


def test_ledger_is_agent_scoped_and_survives_restart(tmp_path, service, registry):
    """台账按 agent 分域、跨重启保状态，且提案带上 agent_id（票面交付 3、4）。"""
    kai = _proposer(tmp_path / "kai", agent_id="kai", proposals_dir=tmp_path / "ledger-kai",
                    service=service, registry=registry)
    proposal = _manifest_proposal(kai)
    kai.approve_and_apply(proposal.proposal_id, approver="admin")

    restarted = _proposer(tmp_path / "kai", agent_id="kai", proposals_dir=tmp_path / "ledger-kai")
    other = _proposer(tmp_path / "ling", agent_id="yi_ling", proposals_dir=tmp_path / "ledger-ling")

    states = {p.proposal_id: p.status.value for p in restarted.list_all_proposals()}
    assert states[proposal.proposal_id] == "applied", f"重启后状态丢失：{states}"
    assert proposal.proposal_id not in {p.proposal_id for p in other.list_all_proposals()}, (
        "两个 agent 的台账串了")
    assert restarted.list_all_proposals()[0].agent_id == "kai"
    on_disk = json.loads(
        (tmp_path / "ledger-kai" / f"{proposal.proposal_id}.json").read_text(encoding="utf-8"))
    assert on_disk["agent_id"] == "kai"


def test_rollback_uninstalls_the_skill(tmp_path, service, registry):
    """回滚必须真的把技能从库与注册表撤下（原实现只是删 .agents 里的文件）。"""
    proposer = _proposer(tmp_path, service=service, registry=registry)
    proposal = _manifest_proposal(proposer)
    applied = proposer.approve_and_apply(proposal.proposal_id, approver="admin")
    assert applied.success is True, applied.error

    rolled = proposer.rollback_applied_proposal(proposal.proposal_id, applied.snapshot_id)

    assert rolled.success is True, rolled.error
    assert service.get_skill_info("rsi-fix-sleep") is None, "回滚后技能页仍挂着它"
    assert registry._skills == {}, "回滚后注册表仍挂着它"


def test_next_turn_restore_sees_the_approved_skill(tmp_path, service, registry):
    """批准之后"下一轮"从库里重建也看得见它（票面 e2e 里"生效"那一步的等价物）。

    用一个**全新注册表**模拟下一轮 / 重启后的重建，不依赖 :9527 常驻后端 ——
    真起后端 + 真发一轮对话属运维级验证，本用例只声称它能声称的部分：
    持久化的 manifest 能被 `restore_market_skills_from_service` 还原成注册表条目。
    """
    from neurova.evolution.rsi.self_improvement_proposer import (
        restore_market_skills_from_service,
    )
    from neurova.skill_system import SkillRegistry

    proposer = _proposer(tmp_path, service=service, registry=registry)
    proposal = _manifest_proposal(proposer)
    assert proposer.approve_and_apply(
        proposal.proposal_id, approver="admin").success is True

    fresh = SkillRegistry()
    assert restore_market_skills_from_service(service, fresh) >= 1
    assert (
        fresh.get_skill("rsi_fix_sleep") is not None
        or fresh.get_skill("rsi-fix-sleep") is not None
    ), "重建后注册表里没有它 ⇒ 下一轮对话仍然看不见"


def test_human_approval_does_not_disable_the_duplicate_gate(tmp_path, service, registry):
    """人类授权只解除"自动行为需三个成功证据"这一道门，判重/安全扫描不得跟着松。"""
    proposer = _proposer(tmp_path, service=service, registry=registry)
    first = _manifest_proposal(proposer)
    assert proposer.approve_and_apply(first.proposal_id, approver="admin").success is True

    second = _manifest_proposal(proposer, skill_id="rsi-fix-sleep-2")

    result = proposer.approve_and_apply(second.proposal_id, approver="admin")
    listed = {str(item.get("id") or item.get("skill_id")) for item in service.list_skills()}
    assert len(listed) == 1, f"人类授权把判重也一起旁路了：{sorted(listed)}"
    assert result.success is False or "duplicate" in (result.error or "").lower(), result.error


def test_proposer_requires_an_agent_id(tmp_path):
    """没有 agent 归属就不能开台账（多 agent 混合不可溯源是审计点名的缺陷）。"""
    with pytest.raises(TypeError):
        SelfImprovementProposer(
            proposals_dir=tmp_path / "ledger",
            deployment_controller=RSIDeploymentController(initial_phase=4),
            rollback_manager=RSIRollbackManager(),
        )


def test_no_agents_mailbox_left_in_production_code():
    """票面净删除断言：生产源码里不再有 `.agents` 这个死信箱路径。"""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[4] / "neurova"
    pattern = re.compile(r"""["']\.agents[/"']""")
    offenders = [
        str(p.relative_to(root)) for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"仍写/读 .agents 死信箱：{offenders}"

    source = (root / "evolution" / "rsi" / "self_improvement_proposer.py").read_text(
        encoding="utf-8")
    for name in ("_apply_proposal_to_disk", "_remove_applied_files", "_get_apply_target_path"):
        assert name not in source, f".agents 时代的残留方法：{name}"
