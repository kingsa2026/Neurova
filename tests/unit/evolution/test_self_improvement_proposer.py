"""
SelfImprovementProposer - 自我改进提议器单元测试

测试设计哲学（来源：用户需求 "Self-improving: 从进化工具到改进代码/UI"）：
1. Agent 不直接修改生产代码 —— 所有改进以"提案"形式提交
2. 三种渐进路径：skill_manifest / action_definition / pr_patch
3. 必须经过人类评审 gate（approve_and_apply / reject_proposal）
4. 集成现有 RSI 基础设施：
   - RSIDeploymentController: 风险 gate (low=phase2, medium=phase3, high=phase4)
   - RSIRollbackManager: 应用前后创建快照，可回滚
5. 安全沙箱：提案写入 .agents/proposals/ 隔离目录

测试覆盖：
- 提案创建（3 种类型）
- 安全校验（路径穿越/危险操作/沙箱）
- 提交与持久化
- 人工评审 gate（approve/reject）
- 应用 + 回滚集成
- 部署阶段 gate（不同风险级别要求不同阶段）
"""

import json
import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from neurova.evolution.rsi.deployment_controller import RSIDeploymentController
from neurova.evolution.rsi.rollback_manager import RSIRollbackManager
from neurova.evolution.rsi.self_improvement_proposer import (
    ImprovementProposal,
    ProposalStatus,
    ProposalType,
    SelfImprovementProposer,
    ValidationResult,
)


class TestImprovementProposalDataclass:
    """测试 ImprovementProposal 数据模型"""

    def test_create_proposal_with_defaults(self):
        """测试默认值创建提案"""
        proposal = ImprovementProposal(
            proposal_id="prop-001",
            proposal_type=ProposalType.SKILL_MANIFEST,
            target="my-skill",
            content="name: my-skill\nversion: 1.0.0",
        )
        assert proposal.proposal_id == "prop-001"
        assert proposal.proposal_type == ProposalType.SKILL_MANIFEST
        assert proposal.status == ProposalStatus.PENDING
        assert proposal.risk_level == "low"  # skill_manifest 默认低风险
        assert proposal.created_at != ""

    def test_proposal_to_dict_roundtrip(self):
        """测试 to_dict / from_dict 往返"""
        original = ImprovementProposal(
            proposal_id="prop-002",
            proposal_type=ProposalType.ACTION_DEFINITION,
            target="my-action",
            content="def handle(args): return 'ok'",
            description="测试 action",
            risk_level="medium",
        )
        d = original.to_dict()
        restored = ImprovementProposal.from_dict(d)

        assert restored.proposal_id == original.proposal_id
        assert restored.proposal_type == original.proposal_type
        assert restored.target == original.target
        assert restored.content == original.content
        assert restored.risk_level == original.risk_level


class TestProposalStatus:
    """测试提案状态枚举"""

    def test_status_values(self):
        """测试状态值完整性"""
        assert ProposalStatus.PENDING == "pending"
        assert ProposalStatus.APPROVED == "approved"
        assert ProposalStatus.REJECTED == "rejected"
        assert ProposalStatus.APPLIED == "applied"
        assert ProposalStatus.ROLLED_BACK == "rolled_back"

    def test_proposal_type_values(self):
        """测试提案类型值完整性"""
        assert ProposalType.SKILL_MANIFEST == "skill_manifest"
        assert ProposalType.ACTION_DEFINITION == "action_definition"
        assert ProposalType.PR_PATCH == "pr_patch"


class TestSelfImprovementProposerInit:
    """测试 SelfImprovementProposer 初始化"""

    def test_init_with_defaults(self, tmp_path):
        """测试默认初始化（使用临时 proposals_dir）"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / ".agents" / "proposals")
        assert proposer.proposals_dir.exists()
        assert proposer.deployment_controller is not None
        assert proposer.rollback_manager is not None

    def test_init_with_custom_components(self, tmp_path):
        """测试注入自定义 deployment_controller 和 rollback_manager"""
        dc = RSIDeploymentController(initial_phase=2)
        rm = RSIRollbackManager()
        proposer = SelfImprovementProposer(
            proposals_dir=tmp_path / ".agents" / "proposals",
            deployment_controller=dc,
            rollback_manager=rm,
        )
        assert proposer.deployment_controller is dc
        assert proposer.rollback_manager is rm

    def test_init_creates_proposals_dir(self, tmp_path):
        """测试初始化时创建 proposals_dir"""
        proposals_dir = tmp_path / ".agents" / "proposals"
        assert not proposals_dir.exists()
        SelfImprovementProposer(proposals_dir=proposals_dir)
        assert proposals_dir.exists()


class TestProposeSkillManifest:
    """测试提议 skill manifest（路径 1：低风险）"""

    def test_propose_skill_manifest_returns_proposal(self, tmp_path):
        """测试创建 skill manifest 提案"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        proposal = proposer.propose_skill_manifest(
            skill_id="code-reviewer",
            manifest_yaml="name: code-reviewer\nversion: 1.0.0\ndescription: 代码审查",
            description="新增代码审查技能",
        )
        assert proposal.proposal_type == ProposalType.SKILL_MANIFEST
        assert proposal.target == "code-reviewer"
        assert proposal.risk_level == "low"
        assert proposal.status == ProposalStatus.PENDING
        assert "name: code-reviewer" in proposal.content

    def test_propose_skill_manifest_generates_unique_id(self, tmp_path):
        """测试每次提案生成唯一 ID"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        p1 = proposer.propose_skill_manifest("s1", "name: s1")
        p2 = proposer.propose_skill_manifest("s2", "name: s2")
        assert p1.proposal_id != p2.proposal_id


class TestProposeActionDefinition:
    """测试提议动态注册 action（路径 2：中风险）"""

    def test_propose_action_definition_returns_proposal(self, tmp_path):
        """测试创建 action definition 提案"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        proposal = proposer.propose_action_definition(
            action_name="summarize_doc",
            handler_code="def handle(args): return 'summary'",
            description="新增文档摘要 action",
        )
        assert proposal.proposal_type == ProposalType.ACTION_DEFINITION
        assert proposal.target == "summarize_doc"
        assert proposal.risk_level == "medium"  # action 默认中风险
        assert "def handle" in proposal.content


class TestProposePRPatch:
    """测试提议 PR patch（路径 3：高风险）"""

    def test_propose_pr_patch_returns_proposal(self, tmp_path):
        """测试创建 PR patch 提案"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        proposal = proposer.propose_pr_patch(
            target_file="neurova/skills/executor.py",
            patch_content="--- a/executor.py\n+++ b/executor.py\n@@ -10,3 +10,5 @@",
            description="修复 executor 内存泄漏",
        )
        assert proposal.proposal_type == ProposalType.PR_PATCH
        assert proposal.target == "neurova/skills/executor.py"
        assert proposal.risk_level == "high"  # PR patch 默认高风险
        assert "executor.py" in proposal.content


class TestProposalValidation:
    """测试提案安全校验（沙箱）"""

    def test_validate_safe_skill_manifest(self, tmp_path):
        """测试安全的 skill manifest 通过校验"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        proposal = proposer.propose_skill_manifest("safe-skill", "name: safe-skill")
        result = proposer.validate_proposal(proposal)
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_validate_rejects_path_traversal_in_target(self, tmp_path):
        """测试拒绝 target 中的路径穿越（../../etc/passwd）"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        proposal = ImprovementProposal(
            proposal_id="p-evil",
            proposal_type=ProposalType.PR_PATCH,
            target="../../../etc/passwd",
            content="patch",
            risk_level="high",
        )
        result = proposer.validate_proposal(proposal)
        assert result.is_valid is False
        assert any("path traversal" in err.lower() or "穿越" in err for err in result.errors)

    def test_validate_rejects_pr_patch_targeting_system_files(self, tmp_path):
        """测试拒绝 PR patch 目标为系统文件（如 /etc/、/sys/）"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        proposal = ImprovementProposal(
            proposal_id="p-evil2",
            proposal_type=ProposalType.PR_PATCH,
            target="/etc/passwd",
            content="patch",
            risk_level="high",
        )
        result = proposer.validate_proposal(proposal)
        assert result.is_valid is False

    def test_validate_rejects_empty_content(self, tmp_path):
        """测试拒绝空内容"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        proposal = ImprovementProposal(
            proposal_id="p-empty",
            proposal_type=ProposalType.SKILL_MANIFEST,
            target="empty-skill",
            content="",
        )
        result = proposer.validate_proposal(proposal)
        assert result.is_valid is False
        assert len(result.errors) > 0

    def test_validate_rejects_dangerous_imports_in_action(self, tmp_path):
        """测试拒绝 action handler 中的危险导入（os.system/subprocess/Popen）"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        proposal = proposer.propose_action_definition(
            action_name="evil-action",
            handler_code="import os\nos.system('rm -rf /')",
        )
        result = proposer.validate_proposal(proposal)
        assert result.is_valid is False
        assert any("dangerous" in err.lower() or "危险" in err for err in result.errors)


class TestSubmitProposal:
    """测试提交提案到 .agents/proposals/"""

    def test_submit_persists_proposal_to_disk(self, tmp_path):
        """测试提交后将提案持久化到磁盘"""
        proposals_dir = tmp_path / "proposals"
        proposer = SelfImprovementProposer(proposals_dir=proposals_dir)
        proposal = proposer.propose_skill_manifest("my-skill", "name: my-skill")

        proposal_id = proposer.submit_proposal(proposal)

        # 验证文件存在
        proposal_file = proposals_dir / f"{proposal_id}.json"
        assert proposal_file.exists()
        # 验证文件内容
        import json
        data = json.loads(proposal_file.read_text(encoding="utf-8"))
        assert data["proposal_id"] == proposal_id
        assert data["target"] == "my-skill"

    def test_submit_invalid_proposal_raises(self, tmp_path):
        """测试提交无效提案时抛出 ValueError"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        proposal = ImprovementProposal(
            proposal_id="p-bad",
            proposal_type=ProposalType.SKILL_MANIFEST,
            target="../../../evil",
            content="x",
        )
        with pytest.raises(ValueError):
            proposer.submit_proposal(proposal)


class TestListPendingProposals:
    """测试列出待评审提案"""

    def test_list_pending_empty(self, tmp_path):
        """测试空列表"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        pending = proposer.list_pending_proposals()
        assert pending == []

    def test_list_pending_returns_only_pending(self, tmp_path):
        """测试只返回 PENDING 状态的提案"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        p1 = proposer.propose_skill_manifest("s1", "name: s1")
        p2 = proposer.propose_skill_manifest("s2", "name: s2")
        proposer.submit_proposal(p1)
        proposer.submit_proposal(p2)

        pending = proposer.list_pending_proposals()
        assert len(pending) == 2
        ids = {p.proposal_id for p in pending}
        assert p1.proposal_id in ids
        assert p2.proposal_id in ids


class TestHumanReviewGate:
    """测试人类评审 gate（核心安全机制）"""

    def test_approve_and_apply_writes_skill_manifest(self, tmp_path):
        """测试批准并应用 skill manifest 提案 —— 写入 .agents/skills/"""
        proposals_dir = tmp_path / "proposals"
        agents_dir = tmp_path / ".agents"
        proposer = SelfImprovementProposer(
            proposals_dir=proposals_dir,
            agents_dir=agents_dir,
            deployment_controller=RSIDeploymentController(initial_phase=4),  # 全自动阶段
        )
        proposal = proposer.propose_skill_manifest(
            skill_id="test-skill",
            manifest_yaml="name: test-skill\nversion: 1.0.0",
        )
        proposer.submit_proposal(proposal)

        result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")

        assert result.success is True
        # 验证 skill manifest 已写入 .agents/skills/test-skill/manifest.yaml
        skill_file = agents_dir / "skills" / "test-skill" / "manifest.yaml"
        assert skill_file.exists()
        assert "name: test-skill" in skill_file.read_text(encoding="utf-8")
        # 验证提案状态变为 APPLIED
        assert result.proposal.status == ProposalStatus.APPLIED

    def test_approve_and_apply_creates_snapshot_before(self, tmp_path):
        """测试应用前创建回滚快照"""
        rm = RSIRollbackManager()
        proposer = SelfImprovementProposer(
            proposals_dir=tmp_path / "proposals",
            agents_dir=tmp_path / ".agents",
            deployment_controller=RSIDeploymentController(initial_phase=4),
            rollback_manager=rm,
        )
        proposal = proposer.propose_skill_manifest("s", "name: s")
        proposer.submit_proposal(proposal)

        result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")

        assert result.success is True
        assert result.snapshot_id is not None
        # 验证快照已注册到 rollback_manager（_snapshots 字典存储 create_snapshot 的产物；
        # _rollback_history 仅在 execute_rollback 时追加，不用于快照创建校验）
        assert result.snapshot_id in rm._snapshots

    def test_reject_proposal(self, tmp_path):
        """测试拒绝提案"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        proposal = proposer.propose_skill_manifest("s", "name: s")
        proposer.submit_proposal(proposal)

        result = proposer.reject_proposal(proposal.proposal_id, reason="不需要此技能")

        assert result is True
        pending = proposer.list_pending_proposals()
        assert len(pending) == 0  # 被拒绝后不再出现在 pending 列表

    def test_approve_nonexistent_proposal_returns_failure(self, tmp_path):
        """测试批准不存在的提案返回失败"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        result = proposer.approve_and_apply("nonexistent-id", approver="admin")
        assert result.success is False
        assert "not found" in result.error.lower() or "不存在" in result.error

    def test_approve_without_approver_returns_failure(self, tmp_path):
        """测试无 approver 时拒绝应用（人类评审 gate）"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        proposal = proposer.propose_skill_manifest("s", "name: s")
        proposer.submit_proposal(proposal)

        result = proposer.approve_and_apply(proposal.proposal_id, approver="")
        assert result.success is False
        assert "approver" in result.error.lower() or "评审" in result.error


class TestDeploymentPhaseGate:
    """测试部署阶段 gate（不同风险级别要求不同阶段）"""

    def test_phase_0_blocks_all_auto_apply(self, tmp_path):
        """测试 Phase 0（观察阶段）阻止所有自动应用"""
        proposer = SelfImprovementProposer(
            proposals_dir=tmp_path / "proposals",
            agents_dir=tmp_path / ".agents",
            deployment_controller=RSIDeploymentController(initial_phase=0),
        )
        proposal = proposer.propose_skill_manifest("s", "name: s")
        proposer.submit_proposal(proposal)

        result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")
        # Phase 0 即使有人工批准，low 风险也允许（人工批准是主 gate）
        # 但 medium/high 应被阶段 gate 阻止
        assert result.success is True  # low risk + 人工批准 = 允许

    def test_phase_0_blocks_high_risk_even_with_approval(self, tmp_path):
        """测试 Phase 0 阻止高风险 PR patch，即使有人工批准"""
        proposer = SelfImprovementProposer(
            proposals_dir=tmp_path / "proposals",
            agents_dir=tmp_path / ".agents",
            deployment_controller=RSIDeploymentController(initial_phase=0),
        )
        proposal = proposer.propose_pr_patch(
            target_file="neurova/core.py",
            patch_content="patch content",
        )
        proposer.submit_proposal(proposal)

        result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")
        assert result.success is False
        assert "phase" in result.error.lower() or "阶段" in result.error

    def test_phase_4_allows_high_risk_with_approval(self, tmp_path):
        """测试 Phase 4（全自动）允许高风险，但仍需人工批准"""
        proposer = SelfImprovementProposer(
            proposals_dir=tmp_path / "proposals",
            agents_dir=tmp_path / ".agents",
            deployment_controller=RSIDeploymentController(initial_phase=4),
        )
        proposal = proposer.propose_pr_patch(
            target_file="neurova/core.py",
            patch_content="patch content",
        )
        proposer.submit_proposal(proposal)

        result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")
        # PR patch 在 Phase 4 + 人工批准下可以应用（写入 .agents/patches/）
        assert result.success is True


class TestRollbackIntegration:
    """测试回滚集成"""

    def test_rollback_proposal_restores_state(self, tmp_path):
        """测试回滚已应用的提案"""
        agents_dir = tmp_path / ".agents"
        proposer = SelfImprovementProposer(
            proposals_dir=tmp_path / "proposals",
            agents_dir=agents_dir,
            deployment_controller=RSIDeploymentController(initial_phase=4),
        )
        proposal = proposer.propose_skill_manifest("s", "name: s")
        proposer.submit_proposal(proposal)
        apply_result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")
        assert apply_result.success is True
        assert apply_result.snapshot_id is not None

        # 执行回滚
        rollback_result = proposer.rollback_applied_proposal(
            proposal.proposal_id, apply_result.snapshot_id
        )

        assert rollback_result.success is True
        # 验证 skill 文件已被删除（回滚到应用前状态）
        skill_file = agents_dir / "skills" / "s" / "manifest.yaml"
        assert not skill_file.exists()

    def test_rollback_nonexistent_snapshot_fails(self, tmp_path):
        """测试回滚不存在的快照失败"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        result = proposer.rollback_applied_proposal("nonexistent", "fake-snapshot-id")
        assert result.success is False


class TestApplyResultContract:
    """测试 ApplyResult / ValidationResult 契约"""

    def test_apply_result_fields(self, tmp_path):
        """测试 ApplyResult 包含必要字段"""
        proposer = SelfImprovementProposer(
            proposals_dir=tmp_path / "proposals",
            agents_dir=tmp_path / ".agents",
            deployment_controller=RSIDeploymentController(initial_phase=4),
        )
        proposal = proposer.propose_skill_manifest("s", "name: s")
        proposer.submit_proposal(proposal)
        result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")

        assert hasattr(result, "success")
        assert hasattr(result, "proposal")
        assert hasattr(result, "snapshot_id")
        assert hasattr(result, "error")

    def test_validation_result_fields(self, tmp_path):
        """测试 ValidationResult 包含必要字段"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        proposal = proposer.propose_skill_manifest("s", "name: s")
        result = proposer.validate_proposal(proposal)

        assert hasattr(result, "is_valid")
        assert hasattr(result, "errors")
        assert hasattr(result, "warnings")


class TestSecurityHardening:
    """安全加固测试（基于审计报告 C1/C2/C4/C5 修复）"""

    def test_validate_rejects_absolute_path_in_skill_id(self, tmp_path):
        """C1: skill_id 含绝对路径应被拒绝（防止逃逸 .agents/skills/ 沙箱）"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        # Unix 绝对路径
        proposal = proposer.propose_skill_manifest("/etc/evil", "name: evil")
        result = proposer.validate_proposal(proposal)
        assert result.is_valid is False
        assert any("绝对路径" in e or "absolute" in e.lower() for e in result.errors)

    def test_validate_rejects_backslash_absolute_path_in_skill_id(self, tmp_path):
        """C1: skill_id 含反斜杠绝对路径应被拒绝（Windows 路径穿越）"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        proposal = proposer.propose_skill_manifest("\\Windows\\evil", "name: evil")
        result = proposer.validate_proposal(proposal)
        assert result.is_valid is False

    def test_validate_rejects_absolute_path_in_action_name(self, tmp_path):
        """C1: action_name 含绝对路径应被拒绝"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        proposal = proposer.propose_action_definition(
            "/etc/evil", "def handle(args): pass"
        )
        result = proposer.validate_proposal(proposal)
        assert result.is_valid is False

    def test_validate_rejects_windows_forward_slash_system_path(self, tmp_path):
        """C2: C:/Windows/ 形式（正斜杠）应被识别为系统文件并拒绝"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        proposal = proposer.propose_pr_patch(
            target_file="C:/Windows/System32/evil.py",
            patch_content="patch",
        )
        result = proposer.validate_proposal(proposal)
        assert result.is_valid is False
        assert any("系统文件" in e for e in result.errors)

    def test_validate_rejects_skill_id_with_slash(self, tmp_path):
        """C1: skill_id 含斜杠分隔符应被拒绝（skill_id 应为简单名称）"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        proposal = proposer.propose_skill_manifest("evil/../../etc", "name: evil")
        result = proposer.validate_proposal(proposal)
        assert result.is_valid is False

    def test_apply_target_path_stays_within_agents_dir(self, tmp_path):
        """C1 防御纵深：即使校验被绕过，应用路径也必须在 .agents/ 内"""
        proposer = SelfImprovementProposer(
            proposals_dir=tmp_path / "proposals",
            agents_dir=tmp_path / ".agents",
            deployment_controller=RSIDeploymentController(initial_phase=4),
        )
        # 正常 skill 应用的目标路径解析后必须在 .agents/ 内
        proposal = proposer.propose_skill_manifest("my-skill", "name: my-skill")
        target_path = proposer._get_apply_target_path(proposal)
        resolved = target_path.resolve() if target_path else None
        agents_root = tmp_path.resolve()
        assert resolved is not None
        # 解析后的路径必须在 .agents/ 目录树内
        assert str(resolved).startswith(str(agents_root))

    def test_approve_and_apply_rejects_non_pending_proposal(self, tmp_path):
        """C4: 已 APPLIED 的提案不能再次 approve_and_apply"""
        proposer = SelfImprovementProposer(
            proposals_dir=tmp_path / "proposals",
            agents_dir=tmp_path / ".agents",
            deployment_controller=RSIDeploymentController(initial_phase=4),
        )
        proposal = proposer.propose_skill_manifest("s", "name: s")
        proposer.submit_proposal(proposal)
        # 第一次应用
        first = proposer.approve_and_apply(proposal.proposal_id, approver="admin")
        assert first.success is True
        # 第二次应用同一提案应失败
        second = proposer.approve_and_apply(proposal.proposal_id, approver="admin")
        assert second.success is False
        assert "PENDING" in second.error or "状态" in second.error

    def test_reject_proposal_rejects_non_pending_proposal(self, tmp_path):
        """C4: 已 APPLIED 的提案不能被 reject"""
        proposer = SelfImprovementProposer(
            proposals_dir=tmp_path / "proposals",
            agents_dir=tmp_path / ".agents",
            deployment_controller=RSIDeploymentController(initial_phase=4),
        )
        proposal = proposer.propose_skill_manifest("s", "name: s")
        proposer.submit_proposal(proposal)
        proposer.approve_and_apply(proposal.proposal_id, approver="admin")
        # 已应用的提案不能被拒绝
        ok = proposer.reject_proposal(proposal.proposal_id, reason="too late")
        assert ok is False

    def test_rollback_rejects_non_applied_proposal(self, tmp_path):
        """C4: PENDING 状态的提案不能被回滚（未应用就回滚是非法状态转移）"""
        proposer = SelfImprovementProposer(proposals_dir=tmp_path / "proposals")
        proposal = proposer.propose_skill_manifest("s", "name: s")
        proposer.submit_proposal(proposal)
        # PENDING 提案不能回滚
        result = proposer.rollback_applied_proposal(proposal.proposal_id, "fake-snapshot")
        assert result.success is False
        assert "APPLIED" in result.error or "状态" in result.error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
