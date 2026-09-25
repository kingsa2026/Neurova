"""
SelfImprovementProposer - 自我改进提议器

将 Agent 的"改进代码/UI"意图转化为可审查、可回滚的提案。

设计哲学（来源：用户需求 "Self-improving: 从进化工具到改进代码/UI"）：
1. Agent 不直接修改生产代码 —— 所有改进以"提案"形式提交
2. 三种渐进路径：
   - skill_manifest (低风险): 批准即装入本 agent 技能库并回灌注册表（工单 010）
   - action_definition (中风险): 尚无生效通道 → 批准时返回 not_supported
   - pr_patch (高风险): 尚无生效通道 → 批准时返回 not_supported
3. 必须经过人类评审 gate（approve_and_apply / reject_proposal）
4. 集成现有 RSI 基础设施：
   - RSIDeploymentController: 风险 gate (low=phase2, medium=phase3, high=phase4)
   - RSIRollbackManager: 应用前后创建快照，可回滚
5. 安全沙箱：提案台账按 agent 分域持久化；批准动作只经 SkillService 公开 API 落盘，
   不再由本模块自己往仓库里写文件（工单 010 拆掉了那条"写了就等于生效"的假链路）

安全模型（三层防御 + 状态机守卫 + 线程安全）：
    Layer 1 沙箱校验 (validate_proposal)：
        - 拒绝 target 含 ".." / 绝对路径（/ 或 \\ 开头）
        - 拒绝 target 匹配系统文件前缀（/etc/ /sys/ c:/windows/ 等，统一正斜杠比较）
        - skill_id / action_name 强制为简单名称（^[a-zA-Z][a-zA-Z0-9_-]*$）
          防止用作目录名/文件名时越出技能库边界
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

台账与生效路径（工单 010）：
    提案台账   <NEUROVA_PROPOSALS_ROOT 或 data/agents>/<agent_id>/proposals/<proposal_id>.json
    批准生效   SkillService(source=synthesized, human_approved=True) 装库
               → restore_market_skills_from_service 回灌注册表 → 下一轮对话可用
    回滚       SkillService.uninstall_skill + registry.unregister（撤不下就不改状态）

    历史上这里写的是仓库根下的同名目录树（proposals/skills/actions/patches 四类文件），
    技能加载链从不读它 —— 目录与格式双双不符，"APPLIED"只是一次文件写入。
    该路径已整体作废，不保留兼容读取；旧目录由运维自行清理。

构造契约（三个协作者一律由调用方注入，不默认新建）：
    proposer = SelfImprovementProposer(
        agent_id="kai",
        deployment_controller=orchestrator.deployment_controller,
        rollback_manager=orchestrator.rollback_manager,
        skill_service=SkillService("kai"),        # 缺省时按 agent_id 懒构造
        skill_registry=get_skill_registry(),      # 缺省时取进程内唯一注册表
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
import os
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
from neurova.skills.market_registry import (
    persist_synthesized_skill,
    restore_market_skills_from_service,
)
from neurova.core.data_root import callerPath

logger = get_logger(__name__)

# 「这条提案今天没有生效通道」的统一前缀 —— 端点与用例都按它判定，
# 避免各处各写一套"失败但看起来像成功"的措辞（工单 010）
_NOT_SUPPORTED = "not_supported"


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
    # 工单 010：提案必须知道自己属于哪个 agent —— 无归属时多 agent 的台账混成
    # 一堆不可溯源的记录，人工批准的动作也无从落到正确那个 agent 的技能库上
    agent_id: str = ""
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
            "agent_id": self.agent_id,
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
            agent_id=data.get("agent_id", ""),
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
    # 工单 010 的"生效证据"：装进了哪个技能、回灌后注册表是否真取得到
    applied_skill_id: str = ""
    registry_hit: bool = False


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
        *,
        agent_id: str,
        deployment_controller: RSIDeploymentController,
        rollback_manager: RSIRollbackManager,
        proposals_dir: Optional[Path] = None,
        skill_service: Any = None,
        skill_registry: Any = None,
    ) -> None:
        """初始化自我改进提议器

        Args:
            agent_id: 本提议器服务的 agent（必填）。提案台账与批准后的技能都落在
                这个 agent 名下 —— 工单 010 前提案不带 agent 归属，多 agent 的
                队列混成一堆且批准动作无处可落。
            deployment_controller: 部署控制器（必填，由调用方注入）
            rollback_manager: 回滚管理器（必填，由调用方注入）
            proposals_dir: 提案台账目录；默认
                ``$NEUROVA_PROPOSALS_ROOT/<agent_id>/proposals``，未设 env 时
                根为 ``data/agents``（与 SkillService 的落盘约定同一套目录）。
                可注入是为了让测试与多实例部署不往仓库里写。
            skill_service: 技能库门面（默认按 agent_id 构造真实 SkillService）
            skill_registry: 技能注册表（默认取进程内唯一注册表）

        三个协作者都不接受"悄悄自建"：工单 005 拆掉的正是 proposer 自带第二个
        部署控制器这条路，技能链同理 —— 自建的注册表与运行中 agent 用的那份
        不是同一个对象时，"批准即生效"仍是一句空话。
        """
        if not str(agent_id or "").strip():
            raise ValueError("agent_id 不能为空：提案台账必须按 agent 分域")
        self._agent_id = str(agent_id)

        if proposals_dir is None:
            root = callerPath(os.environ.get("NEUROVA_PROPOSALS_ROOT"), "agents")
            proposals_dir = root / self._agent_id / "proposals"
        self._proposals_dir = Path(proposals_dir)
        self._proposals_dir.mkdir(parents=True, exist_ok=True)

        # 集成现有基础设施（注入优先，缺省按 agent 取真实门面）
        self.deployment_controller = deployment_controller
        self.rollback_manager = rollback_manager
        self._skill_service = skill_service
        self._skill_registry = skill_registry

        # proposal_id → ImprovementProposal 的内存缓存（从磁盘加载）
        # 共享可变状态，所有读写必须持有 self._lock（AGENTS.md 线程安全规则）
        self._proposals_cache: Dict[str, ImprovementProposal] = {}
        self._lock = threading.RLock()
        self._load_proposals_from_disk()

        logger.info(
            "SelfImprovementProposer initialized: agent=%s, proposals_dir=%s, phase=%s",
            self._agent_id,
            self._proposals_dir,
            self.deployment_controller.get_current_phase(),
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def proposals_dir(self) -> Path:
        return self._proposals_dir

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def skill_service(self) -> Any:
        """技能库门面：按 agent 懒构造真实 SkillService（工单 010 的落点）。"""
        if self._skill_service is None:
            from neurova.skills.skill_service import SkillService

            self._skill_service = SkillService(self._agent_id)
        return self._skill_service

    @property
    def skill_registry(self) -> Any:
        """运行中进程的技能注册表 —— 回灌它才算"下一轮对话能用"。"""
        if self._skill_registry is None:
            from neurova.skill_system import get_skill_registry

            self._skill_registry = get_skill_registry()
        return self._skill_registry

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
        # 统一系统文件前缀检查（适用所有提案类型，防止 target 指向系统文件）
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
        """提交提案到本 agent 的台账目录，等待人工评审

        Args:
            proposal: 待提交的提案

        Returns:
            str: proposal_id

        Raises:
            ValueError: 提案校验失败
        """
        # 归属盖章：台账按 agent 分域，批准动作才知道该往哪个技能库装
        if not proposal.agent_id:
            proposal.agent_id = self._agent_id

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

    def list_all_proposals(self) -> List[ImprovementProposal]:
        """列出全部提案（含已审）。工单 010 加：只有 PENDING 可见时，
        "批准过什么、结果如何"在人工通道上永久消失，回滚与审计都无从进行。"""
        with self._lock:
            return list(self._proposals_cache.values())

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

    def approve_and_apply(
        self,
        proposal_id: str,
        approver: str,
        tool_sequence: Optional[List[str]] = None,
    ) -> ApplyResult:
        """人工批准并应用提案

        流程：
        1. 检查提案存在性
        2. 检查提案状态 == PENDING（状态机守卫）
        3. 检查 approver 非空（人类评审 gate）
        4. 检查部署阶段 gate（风险级别 vs 当前阶段）
        5. 判"今天能不能生效"（判不下来就拒绝，连快照都不建）
        6. 应用 = 装进本 agent 技能库 + 回灌注册表（两步都成才算生效）
        7. 更新提案状态为 APPLIED

        Args:
            tool_sequence: 批准人补交的可执行序列。manifest 里没有 tool_sequence 时
                本条提案按 `not_supported` 拒绝 —— 人工通道的意义正是"人把缺的
                东西补上再批准"，而不是把没有内容的东西记成已生效（工单 010）。

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

            # 5. 先判"这条提案今天能不能生效"——判不下来就直接拒绝，
            #    连快照都不该建（没有动作发生就不该留下动作的痕迹）
            plan = self._plan_activation(proposal, tool_sequence)
            if isinstance(plan, str):
                logger.info("提案 %s 不予激活：%s", proposal_id, plan)
                return ApplyResult(success=False, proposal=proposal, error=plan)

            # 6. 创建回滚快照（记录应用前的状态）
            pre_apply_state = self._capture_pre_apply_state(proposal)
            snapshot_id = self.rollback_manager.create_snapshot(pre_apply_state)

            # 7. 应用 = 装进技能库 + 回灌注册表；任一失败都不记 APPLIED
            outcome = self._activate_skill_manifest(plan)
            if not outcome["ok"]:
                logger.error("应用提案失败 %s: %s", proposal_id, outcome["error"])
                return ApplyResult(
                    success=False,
                    proposal=proposal,
                    snapshot_id=snapshot_id,
                    error=f"应用失败: {outcome['error']}",
                )

            # 8. 更新提案状态（直接到 APPLIED，不经过瞬态 APPROVED）
            now = datetime.now(timezone.utc).isoformat()
            proposal.approved_by = approver
            proposal.approved_at = now
            proposal.applied_at = now
            proposal.snapshot_id = snapshot_id
            proposal.status = ProposalStatus.APPLIED

            # 持久化更新
            self._save_proposal_to_disk(proposal)

            logger.info(
                "Applied proposal %s (approver=%s, snapshot=%s, skill=%s)",
                proposal_id,
                approver,
                snapshot_id,
                plan["skill_id"],
            )
            return ApplyResult(
                success=True,
                proposal=proposal,
                snapshot_id=snapshot_id,
                applied_skill_id=plan["skill_id"],
                registry_hit=outcome["registry_hit"],
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

            # 4. 撤销生效：从技能库与注册表都撤下（工单 010）。
            #    撤不下就保持 APPLIED —— 状态必须跟着事实走，不能先改账再补动作
            problem = self._deactivate_skill_manifest(proposal)
            if problem:
                logger.error("回滚提案 %s 失败（保持 APPLIED 状态）: %s", proposal_id, problem)
                return RollbackResult(
                    success=False,
                    proposal_id=proposal_id,
                    error=f"撤销生效失败，保持 APPLIED 状态: {problem}",
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

    def _capture_pre_apply_state(
        self, proposal: ImprovementProposal
    ) -> Dict[str, Any]:
        """捕获应用前状态（回滚快照）。

        工单 010 之后"应用"不再是在 `.agents/` 下写文件，而是往 agent 技能库装一个
        技能，所以快照记的是**技能层的事实**：装之前库里有没有同名条目。
        """
        skill_id = proposal.target
        try:
            preexisting = self.skill_service.get_skill_info(skill_id) is not None
        except Exception as e:  # noqa: BLE001 - 库不可读时如实记 unknown，不伪装成 False
            logger.warning("读取技能库现状失败（快照记为 unknown）: %s", e)
            preexisting = None
        return {
            "proposal_id": proposal.proposal_id,
            "proposal_type": proposal.proposal_type.value,
            "agent_id": self._agent_id,
            "target": skill_id,
            "skill_preexisted": preexisting,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _parse_manifest(content: str) -> Dict[str, Any]:
        """解析 skill manifest（YAML）。解析不出来时返回空字典，由调用方判 not_supported。"""
        try:
            import yaml

            loaded = yaml.safe_load(content or "")
        except Exception as e:  # noqa: BLE001 - 坏 YAML 不是崩溃理由，是拒绝批准的依据
            logger.warning("manifest YAML 解析失败: %s", e)
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _plan_activation(
        self, proposal: ImprovementProposal, tool_sequence: Optional[List[str]]
    ) -> Any:
        """把提案翻成"要装什么"；不可激活时返回 `not_supported` 错误串。

        返回 dict（激活计划）或 str（拒绝理由）。拒绝**必须**显式：
        把"装不上"记成 APPLIED 就是本单禁止的伪报成功。
        """
        if proposal.proposal_type is not ProposalType.SKILL_MANIFEST:
            return (
                f"{_NOT_SUPPORTED}: 提案类型 {proposal.proposal_type.value} 目前没有生效通道，"
                "批准它只会留下一次文件写入；不如实说「不生效」就不算批准"
            )
        parsed = self._parse_manifest(proposal.content)
        sequence = tool_sequence or parsed.get("tool_sequence") or []
        if not isinstance(sequence, list) or not sequence:
            return (
                f"{_NOT_SUPPORTED}: manifest 缺 tool_sequence，没有可执行内容可装；"
                "批准人可在请求里补交 tool_sequence"
            )
        return {
            "skill_id": proposal.target,
            "name": str(parsed.get("name") or proposal.target),
            "description": str(parsed.get("description") or proposal.description or ""),
            "version": str(parsed.get("version") or "1.0.0"),
            "tool_sequence": [str(step) for step in sequence],
        }

    def _activate_skill_manifest(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """装进 agent 技能库并回灌注册表 —— 两步都成才算生效（工单 010）。

        `human_approved=True`：本次安装由人显式批准，不该再被"自动行为需三个独立
        真实成功证据"那道门挡住（`SkillService` 按 source 判自动，而 RSI 提案的
        source 正是 synthesized）。判重、路径穿越与安全扫描不受该参数影响。
        """
        service = self.skill_service
        registry = self.skill_registry
        installed = persist_synthesized_skill(
            skill_id=plan["skill_id"],
            name=plan["name"],
            description=plan["description"],
            version=plan["version"],
            tool_sequence=plan["tool_sequence"],
            service=service,
            human_approved=True,
        )
        if not installed:
            return {"ok": False, "error": "SkillService 安装未成功（见 skill_service 日志）",
                    "registry_hit": False}

        try:
            restored = restore_market_skills_from_service(service, registry)
        except Exception as e:  # noqa: BLE001 - 回灌失败必须阻止 APPLIED
            return {"ok": False, "error": f"回灌注册表异常: {e}", "registry_hit": False}

        hit = (
            registry.get_skill(plan["name"]) is not None
            or registry.get_skill(plan["skill_id"]) is not None
        )
        if not hit:
            return {
                "ok": False,
                "error": (
                    f"已装入技能库但注册表取不到（restored={restored}）⇒ 下一轮对话"
                    "仍看不见它，不按 APPLIED 记账"
                ),
                "registry_hit": False,
            }
        return {"ok": True, "error": "", "registry_hit": True}

    def _deactivate_skill_manifest(self, proposal: ImprovementProposal) -> str:
        """回滚 = 把装进去的技能从库与注册表撤下。返回空串表示成功。"""
        skill_id = proposal.target
        name = self._parse_manifest(proposal.content).get("name") or skill_id
        problems: List[str] = []
        try:
            self.skill_service.uninstall_skill(skill_id)
        except Exception as e:  # noqa: BLE001
            problems.append(f"技能库卸载失败: {e}")
        try:
            self.skill_registry.unregister(str(name))
            self.skill_registry.unregister(str(skill_id))
        except Exception as e:  # noqa: BLE001
            problems.append(f"注册表注销失败: {e}")
        return "；".join(problems)

