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

目录结构：
    .agents/
    ├── proposals/                # 待评审提案（JSON 持久化）
    │   └── <proposal_id>.json
    ├── skills/                   # 已应用的 skill manifest
    │   └── <skill_id>/manifest.yaml
    ├── actions/                  # 已应用的 action definition
    │   └── <action_name>.py
    └── patches/                  # 已应用的 PR patch
        └── <proposal_id>.patch

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
    # 2. 提交到评审队列
    proposer.submit_proposal(proposal)
    # 3. 人工评审
    if approved:
        result = proposer.approve_and_apply(proposal.proposal_id, approver="admin")
    else:
        proposer.reject_proposal(proposal.proposal_id, reason="...")
    # 4. 如需回滚
    proposer.rollback_applied_proposal(proposal.proposal_id, result.snapshot_id)
"""

from __future__ import annotations

import json
import re
import shutil
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

# PR patch 禁止的目标路径前