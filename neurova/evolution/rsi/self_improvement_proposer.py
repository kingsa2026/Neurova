"""
SelfImprovementProposer - 自我改进提议器

将 Agent 的"改进代码/UI"意图转化为可审查、可回滚的提案。

设计哲学（来源：用户需求 "Self-improving: 从进化工具到改进代码/UI"）：
1. Agent 不直接修改生产代码 —— 所有改进以"提案"形式提交
2. 三种渐进路径：
   - skill_manifest (低风险): 写新 skill manifest 到 .agents/skills/
   - action_definition (中风险): 动态注册新 action 到 .agents/actions/
   - pr_patch (高风险): PR patch 提案到 .agents/patches/
3. 必须经过人类评审 gate（approve_and_apply / reject_proposal）
4. 集成现有 RSI 基础设施：
   - RSIDeploymentController: 风险 gate (low=phase2, medium=phase3, high=phase4)
   - RSIRollbackManager: 应用前后创建快照，可回滚
5. 安全沙箱：提案写入 .agents/proposals/ 隔离目录；应用时仅写入 .agents/ 子目录

安全模型（三层防御 + 状态机守卫 + 线程安全）：
    Layer 1 沙箱校验 (validate_proposal)：
        - 拒绝 target 含 ".." / 绝对路径（/ 或 \\ 开头）
        - 拒绝 target 匹配系统文件前缀（/etc/ /sys/ c:/windows/ 等，统一正斜杠比较）
        - skill_id / action_name 强制为简单名称（^[a-zA-Z][a-zA-Z0-9_-]*$）
          防止用作目录名/文件名时逃逸 .agents/ 沙箱
        - action handler 黑名单扫描（os.system / subprocess / eval / exec / __import__ 等）
        - PR patch target 必须是项目内相对路径（neurova/ tests/ NeurUI/ scripts/ config/）

    Layer 2 部署阶段 gate (approve_and_apply)：
        - 双 gate 语义：人类评审 gate（主 gate）+ 部署阶段 gate（次级约束）
        - low 风险：任意阶段 + 人工批准 = 允许（人工评审是主防御）
        - medium 风险：phase >= 3 + 人工批准 = 允许
        - high 风险：phase >= 4 + 人工批准 = 允许
        - 注意：这与 deployment_controller.can_auto_execute 语义不同 ——
          can_auto_execute 表示"无需人工批准的自动执行"，而本方法始终要求人工批准

    Layer 3 人类评审 gate (approve_and_apply)：
        - approver 必须非空字符串（禁止程序化绕过）
        - 应用前创建回滚快照（rollback_manager.create_snapshot）
        - 应用失败时不更新状态（保持 PENDING）

    状态机守卫（防止非法状态转移）：
        PENDING → APPLIED (via approve_and_apply)
        PENDING → REJECTED (via reject_proposal)
        APPLIED → ROLLED_BACK (via rollback_applied_proposal)
        - approve_and_apply 仅接受 PENDING；已 APPLIED/REJECTED/ROLLED_BACK 的提案不可再次应用
        - reject_proposal 仅接受 PENDING
        - rollback_applied_proposal 仅接受 APPLIED

    线程安全（遵循 AGENTS.md RLock 规则）：
        - self._lock = threading.RLock() 保护 self._proposals_cache
        - 所有 mutating 方法（submit/approve/reject/rollback）+ list_pending_proposals
          均在 with self._lock: 块内执行
        - 单例层 _proposer_lock 独立保护单例创建

目录结构：
    .agents/
    ├── proposals/                # 待评审提案（JSON 持久化）
    │   └── <proposal_id>.json
    ├── skills/                   # 已应用的 skill manifest
    │   └── <skill_id>/manifest.yaml
    ├── actions/                  # 已应用的 action definition
    │   └── <action_name>.py
    └── patches/                  # 已应用的 PR patch（不直接修改生产代码）
        └── <proposal_id>_<safe_name>.patch

构造契约：
    proposer = SelfImprovementProposer(
        proposals_dir=Path(".agents/proposals"),
        agents_dir=Path(".agents"),
        deployment_controller=RSIDeploymentController(initial_phase=0),
        rollback_manager=RSIRollbackManager(),
    )

使用流程：
    # 1. Agent 创建提案
    proposal = proposer.propose_skill_manifest("my-skill", manifest_yaml="...")
    # 2. 提交到评审队列（自动校验安全性）
    proposer.submit_proposal(proposal)
    # 3. 人工评审
    if approved:
        result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")
    else:
        proposer.reject_proposal(proposal.proposal_id, reason="...")
    # 4. 如需回滚（仅 APPLIED 状态可回滚）
    proposer.rollback_applied_proposal(proposal.proposal_id, result.snapshot_id)

测试覆盖（41 项，tests/unit/evolution/test_self_improvement_proposer.py）：
    - 数据模型 / 枚举 / 初始化（7 项）
    - 三种提案创建（4 项）
    - 安全校验（5 项 + 6 项安全加固）
    - 提交持久化 / 列表（4 项）
    - 人类评审 gate（5 项）
    - 部署阶段 gate（3 项）
    - 回滚集成（2 项）
    - 契约字段（2 项）
    - 安全加固 C1/C2/C4（9 项：路径穿越/Windows 绕过/状态机守卫）
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.evolution.rsi.deployment_controller import RSIDeploymentController
from neurova.evolution.rsi.rollback_manager import RSIRollbackManager

logger = get_logger(__name__)


# ────── Enums ──────


class ProposalType(str, Enum):
    """提案类型

    三种渐进路径，对应不同风险级别：
    - SKILL_MANIFEST: 低风险，写新 skill manifest
    - ACTION_DEFINITION: 中风险，动态注册新 action
    - PR_PATCH: 高风险，PR patch 提案
    """

    SKILL_MANIFEST = "skill_manifest"
    ACTION_DEFINITION = "action_definition"
    PR_PATCH = "pr_patch"


class ProposalStatus(str, Enum):
    """提案状态

    状态机：PENDING → APPROVED → APPLIED → (可选 ROLLED_BACK)
                  ↘ REJECTED
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


# ────── 每种提案类型的默认风险级别 ──────

_DEFAULT_RISK_LEVEL: Dict[ProposalType, str] = {
    ProposalType.SKILL_MANIFEST: "low",
    ProposalType.ACTION_DEFINITION: "medium",
    ProposalType.PR_PATCH: "high",
}


# ────── 安全：危险操作黑名单 ──────

# action handler 中的危险导入/调用模式（用于沙箱校验）
_DANGEROUS_PATTERNS = [
    r"\bos\.system\s*\(",
    r"\bsubprocess\.(run|call|Popen|check_output|check_call)\s*\(",
    r"\bos\.popen\s*\(",
    r"\b__import__\s*\(\s*['\"](?:subprocess|shutil|ctypes|os|sys)['\"]",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bopen\s*\(\s*['\"](?:/etc/|/sys/|/proc/|/dev/)",
    r"\brm\s+-rf\b",
    r"\bshutil\.rmtree\s*\(",
]

# PR patch 禁止的目标路径前缀（系统文件）—— 统一用正斜杠形式，
# 校验时先将 target 的反斜杠归一化为正斜杠再比较，避免 C:\ → C:/ 绕过
_FORBIDDEN_TARGET_PREFIXES = (
    "/etc/",
    "/sys/",
    "/proc/",
    "/dev/",
    "/root/",
    "/home/",
    "/usr/",
    "/boot/",
    "/var/log/",
    "c:/windows/",
    "c:/system32/",
    "c:/program files/",
    "c:/users/",
)


# ────── Data Models ──────


@dataclass
class ImprovementProposal:
    """改进提案

    Attributes:
        proposal_id: 唯一 ID (uuid)
        proposal_type: 提案类型
        target: 目标 (skill_id / action_name / file_path)
        content: 提案内容 (yaml / python code / patch)
        description: 人类可读描述
        risk_level: 风险级别 (low/medium/high)
        status: 当前状态
        created_at: 创建时间 (ISO)
        approved_by: 批准者 (空字符串表示未批准)
        approved_at: 批准时间 (ISO，空字符串表示未批准)
        applied_at: 应用时间 (ISO，空字符串表示未应用)
        snapshot_id: 应用前创建的快照 ID (空字符串表示未应用)
        rejection_reason: 拒绝原因 (空字符串表示未被拒绝)
    """

    proposal_id: str = ""
    proposal_type: ProposalType = ProposalType.SKILL_MANIFEST
    target: str = ""
    content: str = ""
    description: str = ""
    risk_level: str = "low"
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: str = ""
    approved_by: str = ""
    approved_at: str = ""
    applied_at: str = ""
    snapshot_id: str = ""
    rejection_reason: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.proposal_id:
            self.proposal_id = f"prop-{uuid.uuid4().hex[:12]}"
        # 兼容从 dict 传入字符串的枚举
        if isinstance(self.proposal_type, str):
            self.proposal_type = ProposalType(self.proposal_type)
        if isinstance(self.status, str):
            self.status = ProposalStatus(self.status)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "proposal_type": self.proposal_type.value,
            "target": self.target,
            "content": self.content,
            "description": self.description,
            "risk_level": self.risk_level,
            "status": self.status.value,
            "created_at": self.created_at,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "applied_at": self.applied_at,
            "snapshot_id": self.snapshot_id,
            "rejection_reason": self.rejection_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImprovementProposal":
        return cls(
            proposal_id=data.get("proposal_id", ""),
            proposal_type=ProposalType(data.get("proposal_type", "skill_manifest")),
            target=data.get("target", ""),
            content=data.get("content", ""),
            description=data.get("description", ""),
            risk_level=data.get("risk_level", "low"),
            status=ProposalStatus(data.get("status", "pending")),
            created_at=data.get("created_at", ""),
            approved_by=data.get("approved_by", ""),
            approved_at=data.get("approved_at", ""),
            applied_at=data.get("applied_at", ""),
            snapshot_id=data.get("snapshot_id", ""),
            rejection_reason=data.get("rejection_reason", ""),
        )


@dataclass
class ValidationResult:
    """校验结果

    Attributes:
        is_valid: 是否通过校验
        errors: 错误列表（阻止提交）
        warnings: 警告列表（不阻止提交，但需评审者注意）
    """

    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class ApplyResult:
    """应用结果

    Attributes:
        success: 是否成功
        proposal: 应用后的提案（状态已更新）
        snapshot_id: 应用前创建的快照 ID（成功时非空）
        error: 失败原因（失败时非空）
    """

    success: bool = False
    proposal: Optional[ImprovementProposal] = None
    snapshot_id: Optional[str] = None
    error: str = ""


@dataclass
class RollbackResult:
    """回滚结果

    Attributes:
        success: 是否成功
        proposal_id: 回滚的提案 ID
        error: 失败原因（失败时非空）
    """

    success: bool = False
    proposal_id: str = ""
    error: str = ""


# ────── SelfImprovementProposer ──────


class SelfImprovementProposer:
    """自我改进提议器

    将 Agent 的"改进代码/UI"意图转化为可审查、可回滚的提案。
    所有提案必须经过人类评审 gate 才能应用。

    安全机制：
    1. 沙箱校验：拒绝路径穿越、危险导入、系统文件目标
    2. 部署阶段 gate：高风险提案需要更高部署阶段
    3. 人类评审 gate：所有应用必须指定 approver
    4. 回滚机制：应用前创建快照，可一键回滚
    """

    def __init__(
        self,
        proposals_dir: Optional[Path] = None,
        agents_dir: Optional[Path] = None,
        deployment_controller: Optional[RSIDeploymentController] = None,
        rollback_manager: Optional[RSIRollbackManager] = None,
    ) -> None:
        """初始化自我改进提议器

        Args:
            proposals_dir: 提案持久化目录（默认 .agents/proposals/）
            agents_dir: 已应用提案的根目录（默认 .agents/）
            deployment_controller: 部署控制器（默认新建 phase=0）
            rollback_manager: 回滚管理器（默认新建）
        """
        # 默认目录
        if agents_dir is None:
            agents_dir = Path(".agents")
        if proposals_dir is None:
            proposals_dir = agents_dir / "proposals"

        self._agents_dir = Path(agents_dir)
        self._proposals_dir = Path(proposals_dir)
        self._skills_dir = self._agents_dir / "skills"
        self._actions_dir = self._agents_dir / "actions"
        self._patches_dir = self._agents_dir / "patches"

        # 创建目录
        self._proposals_dir.mkdir(parents=True, exist_ok=True)
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        self._actions_dir.mkdir(parents=True, exist_ok=True)
        self._patches_dir.mkdir(parents=True, exist_ok=True)

        # 集成现有基础设施
        self.deployment_controller = deployment_controller or RSIDeploymentController(initial_phase=0)
        self.rollback_manager = rollback_manager or RSIRollbackManager()

        # proposal_id → ImprovementProposal 的内存缓存（从磁盘加载）
        # 共享可变状态，所有读写必须持有 self._lock（AGENTS.md 线程安全规则）
        self._proposals_cache: Dict[str, ImprovementProposal] = {}
        self._lock = threading.RLock()
        self._load_proposals_from_disk()

        logger.info(
            "SelfImprovementProposer initialized: proposals_dir=%s, agents_dir=%s, phase=%s",
            self._proposals_dir,
            self._agents_dir,
            self.deployment_controller.get_current_phase(),
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def proposals_dir(self) -> Path:
        return self._proposals_dir

    @property
    def agents_dir(self) -> Path:
        return self._agents_dir

    # ------------------------------------------------------------------
    # 提案创建 API（3 种渐进路径）
    # ------------------------------------------------------------------

    def propose_skill_manifest(
        self,
        skill_id: str,
        manifest_yaml: str,
        description: str = "",
        risk_level: Optional[str] = None,
    ) -> ImprovementProposal:
        """提议创建新 skill manifest（路径 1：低风险）

        Args:
            skill_id: 技能 ID
            manifest_yaml: manifest YAML 内容
            description: 人类可读描述
            risk_level: 自定义风险级别（默认 low）

        Returns:
            ImprovementProposal: PENDING 状态的提案
        """
        proposal = ImprovementProposal(
            proposal_type=ProposalType.SKILL_MANIFEST,
            target=skill_id,
            content=manifest_yaml,
            description=description or f"新增技能: {skill_id}",
            risk_level=risk_level or _DEFAULT_RISK_LEVEL[ProposalType.SKILL_MANIFEST],
        )
        logger.debug("Created skill_manifest proposal: %s for %s", proposal.proposal_id, skill_id)
        return proposal

    def propose_action_definition(
        self,
        action_name: str,
        handler_code: str,
        description: str = "",
        risk_level: Optional[str] = None,
    ) -> ImprovementProposal:
        """提议动态注册新 action（路径 2：中风险）

        Args:
            action_name: action 名称
            handler_code: handler Python 代码（含 def handle(args): ...）
            description: 人类可读描述
            risk_level: 自定义风险级别（默认 medium）

        Returns:
            ImprovementProposal: PENDING 状态的提案
        """
        proposal = ImprovementProposal(
            proposal_type=ProposalType.ACTION_DEFINITION,
            target=action_name,
            content=handler_code,
            description=description or f"新增 action: {action_name}",
            risk_level=risk_level or _DEFAULT_RISK_LEVEL[ProposalType.ACTION_DEFINITION],
        )
        logger.debug("Created action_definition proposal: %s for %s", proposal.proposal_id, action_name)
        return proposal

    def propose_pr_patch(
        self,
        target_file: str,
        patch_content: str,
        description: str = "",
        risk_level: Optional[str] = None,
    ) -> ImprovementProposal:
        """提议 PR patch（路径 3：高风险）

        Args:
            target_file: 目标文件路径（相对项目根）
            patch_content: patch 内容（unified diff 格式）
            description: 人类可读描述
            risk_level: 自定义风险级别（默认 high）

        Returns:
            ImprovementProposal: PENDING 状态的提案
        """
        proposal = ImprovementProposal(
            proposal_type=ProposalType.PR_PATCH,
            target=target_file,
            content=patch_content,
            description=description or f"PR patch: {target_file}",
            risk_level=risk_level or _DEFAULT_RISK_LEVEL[ProposalType.PR_PATCH],
        )
        logger.debug("Created pr_patch proposal: %s for %s", proposal.proposal_id, target_file)
        return proposal

    # ------------------------------------------------------------------
    # 安全校验（沙箱）
    # ------------------------------------------------------------------

    def validate_proposal(self, proposal: ImprovementProposal) -> ValidationResult:
        """校验提案安全性

        检查项：
        1. content 非空
        2. target 无路径穿越
        3. PR patch target 不指向系统文件
        4. action handler 无危险导入/调用

        Args:
            proposal: 待校验的提案

        Returns:
            ValidationResult: 校验结果
        """
        errors: List[str] = []
        warnings: List[str] = []

        # 1. content 非空
        if not proposal.content or not proposal.content.strip():
            errors.append("提案内容不能为空")

        # 2. target 无路径穿越 —— 统一规则：禁止绝对路径、禁止 ..
        target = proposal.target
        target_normalized = target.replace("\\", "/").lower()
        if ".." in target:
            errors.append(f"path traversal 检测：target 含 '..' ({target})")
        if target.startswith("/") or target.startswith("\\"):
            errors.append(f"path traversal 检测：target 为绝对路径 ({target})")
        # 统一系统文件前缀检查（适用所有提案类型，防止 .agents/ 沙箱逃逸）
        for forbidden in _FORBIDDEN_TARGET_PREFIXES:
            if target_normalized.startswith(forbidden.lower()):
                errors.append(f"target 为系统文件: {target} (禁止前缀 {forbidden})")
                break

        # 3. PR patch 额外约束：必须是项目内相对路径
        if proposal.proposal_type == ProposalType.PR_PATCH and not errors:
            if not target.startswith(("neurova/", "tests/", "NeurUI/", "scripts/", "config/")):
                # 项目目录外 → 报错（不再仅 warning，防止写入任意路径）
                errors.append(
                    f"PR patch 目标不在已知项目目录内: {target} "
                    f"(允许前缀: neurova/ tests/ NeurUI/ scripts/ config/)"
                )

        # 4. action handler 无危险导入/调用
        if proposal.proposal_type == ProposalType.ACTION_DEFINITION:
            for pattern in _DANGEROUS_PATTERNS:
                matches = re.findall(pattern, proposal.content)
                if matches:
                    errors.append(
                        f"dangerous 操作检测：action handler 含禁止模式 {pattern} (匹配 {len(matches)} 处)"
                    )

        # 5. skill_id / action_name 命名规范 —— 强制为简单名称（禁止任何路径分隔符）
        # 这是沙箱防御的核心：skill_id/action_name 用作目录名/文件名，含分隔符会逃逸沙箱
        if proposal.proposal_type == ProposalType.SKILL_MANIFEST:
            if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", target):
                errors.append(
                    f"skill_id 命名不规范（仅允许字母开头 + 字母数字下划线连字符）: {target}"
                )
        elif proposal.proposal_type == ProposalType.ACTION_DEFINITION:
            if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", target):
                errors.append(
                    f"action_name 命名不规范（仅允许字母开头 + 字母数字下划线）: {target}"
                )

        is_valid = len(errors) == 0
        return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)

    # ------------------------------------------------------------------
    # 提交与持久化
    # ------------------------------------------------------------------

    def submit_proposal(self, proposal: ImprovementProposal) -> str:
        """提交提案到 .agents/proposals/ 等待人工评审

        Args:
            proposal: 待提交的提案

        Returns:
            str: proposal_id

        Raises:
            ValueError: 提案校验失败
        """
        # 安全校验（只读，无需持锁）
        validation = self.validate_proposal(proposal)
        if not validation.is_valid:
            raise ValueError(f"提案校验失败: {validation.errors}")

        # 持久化 + 更新缓存（线程安全）
        with self._lock:
            self._save_proposal_to_disk(proposal)
            self._proposals_cache[proposal.proposal_id] = proposal

        logger.info(
            "Submitted proposal %s (type=%s, target=%s, risk=%s)",
            proposal.proposal_id,
            proposal.proposal_type.value,
            proposal.target,
            proposal.risk_level,
        )
        return proposal.proposal_id

    def list_pending_proposals(self) -> List[ImprovementProposal]:
        """列出所有 PENDING 状态的提案

        Returns:
            List[ImprovementProposal]: PENDING 提案列表
        """
        with self._lock:
            return [
                p for p in self._proposals_cache.values() if p.status == ProposalStatus.PENDING
            ]

    # ------------------------------------------------------------------
    # 人类评审 gate
    # ------------------------------------------------------------------

    def approve_and_apply(self, proposal_id: str, approver: str) -> ApplyResult:
        """人工批准并应用提案

        流程：
        1. 检查提案存在性
        2. 检查提案状态 == PENDING（状态机守卫）
        3. 检查 approver 非空（人类评审 gate）
        4. 检查部署阶段 gate（风险级别 vs 当前阶段）
        5. 创建回滚快照
        6. 应用提案（写入 .agents/ 子目录）
        7. 更新提案状态为 APPLIED

        双 gate 语义（设计决策，由测试契约固化）：
        - 人类评审 gate（主 gate）：所有应用必须指定非空 approver
        - 部署阶段 gate（次级约束）：medium/high 风险需要更高部署阶段
        - 注意：这与 deployment_controller.can_auto_execute 语义不同 ——
          can_auto_execute 表示"无需人工批准的自动执行"，而本方法的 gate 始终要求
          人工批准，phase gate 是额外的风险约束。low 风险在任意阶段 + 人工批准
          即可应用，因为人工评审是主防御。

        Args:
            proposal_id: 提案 ID
            approver: 批准者（必须非空）

        Returns:
            ApplyResult: 应用结果
        """
        with self._lock:
            # 1. 检查提案存在性
            proposal = self._proposals_cache.get(proposal_id)
            if proposal is None:
                return ApplyResult(success=False, error=f"proposal not found: {proposal_id}")

            # 2. 状态机守卫：仅 PENDING 可被批准应用
            if proposal.status != ProposalStatus.PENDING:
                return ApplyResult(
                    success=False,
                    proposal=proposal,
                    error=(
                        f"非法状态转移：当前状态 {proposal.status.value}，"
                        f"期望 PENDING（仅 PENDING 提案可被批准应用）"
                    ),
                )

            # 3. 检查 approver 非空（人类评审 gate）
            if not approver or not approver.strip():
                return ApplyResult(
                    success=False,
                    proposal=proposal,
                    error="approver 不能为空（人类评审 gate 要求显式批准）",
                )

            # 4. 检查部署阶段 gate
            # 低风险: 任何阶段 + 人工批准 = 允许
            # 中风险: phase >= 3 + 人工批准 = 允许
            # 高风险: phase >= 4 + 人工批准 = 允许
            risk = proposal.risk_level
            min_phase_required = {"low": 0, "medium": 3, "high": 4}.get(risk, 4)
            current_phase = self.deployment_controller.get_current_phase()
            if current_phase < min_phase_required:
                return ApplyResult(
                    success=False,
                    proposal=proposal,
                    error=(
                        f"部署阶段 gate 阻止：风险级别 {risk} 要求 phase>={min_phase_required}，"
                        f"当前 phase={current_phase}"
                    ),
                )

            # 5. 创建回滚快照（记录应用前的状态）
            pre_apply_state = self._capture_pre_apply_state(proposal)
            snapshot_id = self.rollback_manager.create_snapshot(pre_apply_state)

            # 6. 应用提案
            try:
                self._apply_proposal_to_disk(proposal)
            except Exception as e:
                logger.error("应用提案失败 %s: %s", proposal_id, e)
                return ApplyResult(
                    success=False,
                    proposal=proposal,
                    snapshot_id=snapshot_id,
                    error=f"应用失败: {e}",
                )

            # 7. 更新提案状态（直接到 APPLIED，不经过瞬态 APPROVED）
            now = datetime.now(timezone.utc).isoformat()
            proposal.approved_by = approver
            proposal.approved_at = now
            proposal.applied_at = now
            proposal.snapshot_id = snapshot_id
            proposal.status = ProposalStatus.APPLIED

            # 持久化更新
            self._save_proposal_to_disk(proposal)

            logger.info(
                "Applied proposal %s (approver=%s, snapshot=%s)",
                proposal_id,
                approver,
                snapshot_id,
            )
            return ApplyResult(
                success=True,
                proposal=proposal,
                snapshot_id=snapshot_id,
            )

    def reject_proposal(self, proposal_id: str, reason: str = "") -> bool:
        """拒绝提案

        状态机守卫：仅 PENDING 状态可被拒绝。

        Args:
            proposal_id: 提案 ID
            reason: 拒绝原因

        Returns:
            bool: 是否成功（提案不存在或非 PENDING 状态返回 False）
        """
        with self._lock:
            proposal = self._proposals_cache.get(proposal_id)
            if proposal is None:
                return False

            # 状态机守卫：仅 PENDING 可被拒绝
            if proposal.status != ProposalStatus.PENDING:
                logger.warning(
                    "拒绝提案失败 %s：当前状态 %s，期望 PENDING",
                    proposal_id,
                    proposal.status.value,
                )
                return False

            proposal.status = ProposalStatus.REJECTED
            proposal.rejection_reason = reason

            # 持久化更新
            self._save_proposal_to_disk(proposal)

            logger.info("Rejected proposal %s: %s", proposal_id, reason)
            return True

    # ------------------------------------------------------------------
    # 回滚
    # ------------------------------------------------------------------

    def rollback_applied_proposal(
        self, proposal_id: str, snapshot_id: str
    ) -> RollbackResult:
        """回滚已应用的提案

        流程：
        1. 检查提案存在性
        2. 状态机守卫：仅 APPLIED 可被回滚
        3. 检查快照存在性（通过 rollback_manager）
        4. 执行回滚（删除应用时创建的文件）
        5. 更新提案状态为 ROLLED_BACK

        Args:
            proposal_id: 提案 ID
            snapshot_id: 应用前创建的快照 ID

        Returns:
            RollbackResult: 回滚结果
        """
        with self._lock:
            # 1. 检查提案存在性
            proposal = self._proposals_cache.get(proposal_id)
            if proposal is None:
                return RollbackResult(
                    success=False, proposal_id=proposal_id, error="proposal not found"
                )

            # 2. 状态机守卫：仅 APPLIED 可被回滚
            if proposal.status != ProposalStatus.APPLIED:
                return RollbackResult(
                    success=False,
                    proposal_id=proposal_id,
                    error=(
                        f"非法状态转移：当前状态 {proposal.status.value}，"
                        f"期望 APPLIED（仅 APPLIED 提案可被回滚）"
                    ),
                )

            # 3. 通过 rollback_manager 执行回滚（验证快照存在）
            rollback_ok = self.rollback_manager.execute_rollback(snapshot_id)
            if not rollback_ok:
                return RollbackResult(
                    success=False,
                    proposal_id=proposal_id,
                    error=f"snapshot not found or rollback failed: {snapshot_id}",
                )

            # 4. 删除应用时创建的文件
            # 文件删除失败应阻止状态更新，避免状态与磁盘不一致
            try:
                self._remove_applied_files(proposal)
            except Exception as e:
                logger.error("回滚时删除文件失败（保持 APPLIED 状态）: %s", e)
                return RollbackResult(
                    success=False,
                    proposal_id=proposal_id,
                    error=f"回滚时删除文件失败，保持 APPLIED 状态: {e}",
                )

            # 5. 更新提案状态
            proposal.status = ProposalStatus.ROLLED_BACK
            self._save_proposal_to_disk(proposal)

            logger.info("Rolled back proposal %s (snapshot=%s)", proposal_id, snapshot_id)
            return RollbackResult(success=True, proposal_id=proposal_id)

    # ------------------------------------------------------------------
    # 内部：磁盘 I/O
    # ------------------------------------------------------------------

    def _load_proposals_from_disk(self) -> None:
        """从磁盘加载所有提案到缓存"""
        for proposal_file in self._proposals_dir.glob("*.json"):
            try:
                data = json.loads(proposal_file.read_text(encoding="utf-8"))
                proposal = ImprovementProposal.from_dict(data)
                self._proposals_cache[proposal.proposal_id] = proposal
            except Exception as e:
                logger.warning("加载提案文件失败 %s: %s", proposal_file, e)

    def _save_proposal_to_disk(self, proposal: ImprovementProposal) -> None:
        """保存提案到磁盘"""
        proposal_file = self._proposals_dir / f"{proposal.proposal_id}.json"
        proposal_file.write_text(
            json.dumps(proposal.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _capture_pre_apply_state(self, proposal: ImprovementProposal) -> Dict[str, Any]:
        """捕获应用前的状态（用于回滚）

        记录将被创建/修改的文件路径，以便回滚时删除。
        """
        target_path = self._get_apply_target_path(proposal)
        return {
            "proposal_id": proposal.proposal_id,
            "proposal_type": proposal.proposal_type.value,
            "target": proposal.target,
            "target_path": str(target_path) if target_path else None,
            "target_path_existed_before": (
                target_path.exists() if target_path else False
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _get_apply_target_path(self, proposal: ImprovementProposal) -> Optional[Path]:
        """获取提案应用时的目标文件路径"""
        if proposal.proposal_type == ProposalType.SKILL_MANIFEST:
            return self._skills_dir / proposal.target / "manifest.yaml"
        elif proposal.proposal_type == ProposalType.ACTION_DEFINITION:
            return self._actions_dir / f"{proposal.target}.py"
        elif proposal.proposal_type == ProposalType.PR_PATCH:
            # PR patch 写入 patches 目录（不直接修改生产代码）
            safe_name = proposal.target.replace("/", "_").replace("\\", "_")
            return self._patches_dir / f"{proposal.proposal_id}_{safe_name}.patch"
        return None

    def _apply_proposal_to_disk(self, proposal: ImprovementProposal) -> None:
        """将提案内容写入磁盘（仅写入 .agents/ 子目录）"""
        target_path = self._get_apply_target_path(proposal)
        if target_path is None:
            raise ValueError(f"未知提案类型: {proposal.proposal_type}")

        # 确保父目录存在
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入内容
        target_path.write_text(proposal.content, encoding="utf-8")

        logger.debug("Applied proposal %s to %s", proposal.proposal_id, target_path)

    def _remove_applied_files(self, proposal: ImprovementProposal) -> None:
        """回滚时删除应用创建的文件"""
        target_path = self._get_apply_target_path(proposal)
        if target_path is None or not target_path.exists():
            return

        # 删除文件
        target_path.unlink()

        # 如果是 skill manifest，删除空的 skill 目录
        if proposal.proposal_type == ProposalType.SKILL_MANIFEST:
            skill_dir = self._skills_dir / proposal.target
            if skill_dir.exists() and not any(skill_dir.iterdir()):
                skill_dir.rmdir()

        logger.debug("Removed applied files for proposal %s", proposal.proposal_id)


# ────── 工厂函数（遵循现有 create_* 模式） ──────


def create_self_improvement_proposer(
    proposals_dir: Optional[Path] = None,
    agents_dir: Optional[Path] = None,
    deployment_controller: Optional[RSIDeploymentController] = None,
    rollback_manager: Optional[RSIRollbackManager] = None,
) -> SelfImprovementProposer:
    """创建自我改进提议器实例

    Args:
        proposals_dir: 提案持久化目录
        agents_dir: 已应用提案的根目录
        deployment_controller: 部署控制器
        rollback_manager: 回滚管理器

    Returns:
        SelfImprovementProposer: 提议器实例
    """
    return SelfImprovementProposer(
        proposals_dir=proposals_dir,
        agents_dir=agents_dir,
        deployment_controller=deployment_controller,
        rollback_manager=rollback_manager,
    )


# ────── 全局单例（遵循现有 get_* 模式） ──────

_proposer_instance: Optional[SelfImprovementProposer] = None
_proposer_lock = None


def get_self_improvement_proposer() -> SelfImprovementProposer:
    """获取全局自我改进提议器单例

    Returns:
        SelfImprovementProposer: 全局单例
    """
    global _proposer_instance, _proposer_lock
    if _proposer_lock is None:
        import threading

        _proposer_lock = threading.Lock()
    if _proposer_instance is None:
        with _proposer_lock:
            if _proposer_instance is None:
                _proposer_instance = SelfImprovementProposer()
    return _proposer_instance


def reset_self_improvement_proposer() -> None:
    """重置全局自我改进提议器单例（用于测试）"""
    global _proposer_instance
    if _proposer_lock is not None:
        with _proposer_lock:
            _proposer_instance = None
    else:
        _proposer_instance = None
