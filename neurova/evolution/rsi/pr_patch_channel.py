"""PrPatchChannel —— L2 代码级提案（PR_PATCH）的生效通道（计划书 §3.6 / §6 P2-1）。

设计出处：``docs/04-plans/2026-11-21-recursive-self-evolution-plan.md``
§2.1 三原则（候选永不直改基线）、§3.6 L2 生效通道、§5 安全红线 L2/L3 层、
§6 P2 批 P2-1。

定位：补上 ``self_improvement_proposer`` 缺的"最后一公里"。PR_PATCH 提案过去
只有"提案-校验-审批-快照"骨架，批准时返回 ``not_supported``（"批准它只会留下
一次文件写入；不如实说「不生效」就不算批准"）。本通道把批准接到真实生效：

- :meth:`plan`     提案 → :class:`PatchPlan`。仅接受 PR_PATCH；目标文件经
  ``TargetRegistry.assertMutable`` 校验——禁改内核拒绝（fail-closed），L2 白名单
  （首批登记见 §6 P2-3）之外的 target 一律拒；
- :meth:`verify`   隔离工作区 ``git apply --check`` 预检 → ``ShadowVerify``（L2
  路径，隔离数据根 + 隔离工作区副本）跑存活探针 → ``GateChain`` 编排 G0-G4，
  返回逐项三态结论；
- :meth:`apply`    门禁链全绿才动基线：先经 ``CandidateMergeBoard`` CAS 合入
  （冲突双保留升级人工，不静默覆盖），再打 ``CheckpointService`` scope 快照
  （scope_id=提案 id，ordinal=1），最后基线工作区 ``git apply``；任一步失败都
  不把提案记成 APPLIED；
- :meth:`rollback` scope 快照恢复（把应用前的目标文件字节写回工作区）。

安全语义（通道的存在不放松任何一道既有闸门）：

- 调用方 ``approve_and_apply`` 的人类评审 gate + 部署阶段 gate（high→phase≥4）
  先于本通道执行——通道不绕审批；
- "apply 前必过 G0-G4"由 :meth:`apply` 内部先跑 :meth:`verify` 结构性保证；
  G3 回归 / G4 教义判据经注入面提供，未注入即 unevidenced（无证据不冒充通过，
  沿 GateVerdict 三态纪律），此时一律拒绝应用；
- 影子验证期间补丁只存在于隔离副本，生产工作树与生产数据根零写入。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.core.data_root import repoRoot
from neurova.evolution.rsi.gate_chain import GATE_OVERALL, GateChain
from neurova.evolution.rsi.gate_verdict import STATE_PASSED, GateVerdict
from neurova.evolution.rsi.shadow_verify import KIND_PATCH, ShadowChange
from neurova.evolution.rsi.self_improvement_proposer import ProposalType
from neurova.evolution.rsi.target_registry import (
    EvolutionTarget,
    MutableTargetError,
    UnknownTargetError,
    get_target_registry,
)
from neurova.checkpoints.service import CheckpointNotFoundError
# checkpoints 包轻量（repository+service），顶层导入无碍；
# candidate_merge 属 neurova.agent 包（__init__ 链回 Agent 重模块），
# 其异常与合并板一律走方法内懒导入（AGENTS.md §3 懒加载纪律）。

logger = get_logger(__name__)

__all__ = [
    "PatchPlan",
    "PatchApplyOutcome",
    "PrPatchChannel",
]

#: 与 proposer 的「没有生效通道」前缀同一词汇（本通道只收 PR_PATCH，
#: 其余类型到这里属调用方路由错误，同样如实报 not_supported）。
_NOT_SUPPORTED = "not_supported"

#: 通道自身的拒绝前缀：类型合法但目标不在可演化白名单 / 属禁改内核。
_L2_NOT_ALLOWED = "l2_not_allowed"

#: scope 快照的固定 ordinal（一提案一补丁一快照；多次重试覆盖同一 ref）。
_SNAPSHOT_ORDINAL = 1

#: scope 快照里记录元信息的固定文件名。
_META_FILE = "_meta.json"


@dataclass(frozen=True)
class PatchPlan:
    """一次 PR_PATCH 提案的激活计划（``_plan_activation`` 的 PR_PATCH 产物）。

    ``proposalId`` 即 CheckpointService scope 快照的 scope_id；
    ``targetId`` 是 TargetRegistry 的稳定 ID（审计与世代账本的关联键）。
    """

    proposalId: str
    targetId: str
    targetFile: str
    patch: str


@dataclass
class PatchApplyOutcome:
    """apply 的机制层结果（状态机记账由 proposer 依此落账，不在此改状态）。"""

    ok: bool = False
    error: str = ""
    snapshotRef: str = ""
    mergeRevision: int = -1
    gateOverall: str = ""
    gateSummary: Dict[str, str] = field(default_factory=dict)
    conflictWith: List[str] = field(default_factory=list)


def _locatorFile(locator: str) -> str:
    """登记项 locator → 文件路径部分（去 ``:symbol`` 后缀、统一正斜杠）。"""
    return str(locator or "").split(":", 1)[0].replace("\\", "/")


class PrPatchChannel:
    """PR_PATCH 生效通道：plan / verify / apply / rollback（§3.6 接口面）。

    可注入协作方（测试与多实例部署用，缺省按生产单例懒构造）：

    - ``registry``: TargetRegistry（白名单与禁改清单的单一事实源）；
    - ``shadowVerify``: 影子验证执行器（P1-2 交付件）；
    - ``checkpointService``: scope 化检查点服务（缺省按提案 agent_id 懒构造）；
    - ``mergeBoard``: 候选 CAS 合并板（缺省进程内新板）；
    - ``workspace``: 基线工作区根（缺省仓库根；测试注入临时 git 仓）；
    - ``businessCriteria`` / ``regressionCriteria`` / ``doctrineCriteria``:
      G2 / G3 / G4 判据回调 ``(change, verdicts) -> GateVerdict | list[GateVerdict]``。
      未注入的门 = 空判据集 = unevidenced（诚实缺席，不冒充通过）。
    """

    def __init__(
        self,
        *,
        registry: Any = None,
        shadowVerify: Any = None,
        checkpointService: Any = None,
        mergeBoard: Any = None,
        workspace: Any = None,
        businessCriteria: Any = None,
        regressionCriteria: Any = None,
        doctrineCriteria: Any = None,
        gitTimeoutSeconds: int = 120,
    ) -> None:
        self._registry = registry
        self._shadow = shadowVerify
        self._checkpoints = checkpointService
        self._board = mergeBoard
        self._workspace = Path(workspace) if workspace is not None else repoRoot()
        self._businessCriteria = businessCriteria
        self._regressionCriteria = regressionCriteria
        self._doctrineCriteria = doctrineCriteria
        self._gitTimeoutSeconds = int(gitTimeoutSeconds)
        self._checkpointCache: Dict[str, Any] = {}

    # ── 可用性（EVO-04：判据未装配即显式不可用，不留死通道） ─────────

    def unavailableReason(self) -> str:
        """通道不可用原因（空串＝三判据齐备）。

        G2 由注入影子验证器提供时视为齐备（影子本身的业务判据由调用方
        负责）；G3/G4 是本通道 `_organizeGates` 的注入面，缺席即整链
        unevidenced——`apply` 永远不会放行，继续接受提案就是引用户走死路。
        """
        missing: List[str] = []
        if self._shadow is None and self._businessCriteria is None:
            missing.append("G2 业务判据（businessCriteria）")
        if self._regressionCriteria is None:
            missing.append("G3 回归判据（regressionCriteria）")
        if self._doctrineCriteria is None:
            missing.append("G4 教义判据（doctrineCriteria）")
        if not missing:
            return ""
        return (
            f"{_NOT_SUPPORTED}: PR_PATCH 通道未装配取证判据："
            f"{'、'.join(missing)}——门禁链必然 unevidenced，apply 永远拒绝；"
            "请在生产装配注入判据，或保持本通道显式不可用（不要批准注定失败的提案）"
        )

    # ── plan：提案 → 激活计划（白名单/禁改校验） ──────────────────

    def plan(self, proposal: Any) -> Any:
        """把 PR_PATCH 提案翻成 :class:`PatchPlan`；不可激活时返回拒绝理由串。

        拒绝**必须**显式：目标未登记（白名单外）、禁改内核、目标文件缺失、
        通道判据未装配，逐条点名——绝不静默放行，也绝不把"不能生效"伪
        装成"已计划"。
        """
        proposalType = getattr(proposal, "proposal_type", None)
        if proposalType is not ProposalType.PR_PATCH:
            typeValue = str(getattr(proposalType, "value", proposalType))
            return (
                f"{_NOT_SUPPORTED}: 提案类型 {typeValue} 不走 PR_PATCH 通道，"
                "目前没有生效通道；不如实说「不生效」就不算批准"
            )
        targetFile = str(getattr(proposal, "target", "") or "").replace("\\", "/")
        target = self._findTargetByLocator(targetFile)
        if target is None:
            return (
                f"{_L2_NOT_ALLOWED}: 目标 {targetFile} 未登记为可演化 L2 对象"
                "（白名单外 patch 一律拒，见计划书 §6 P2-3）"
            )
        try:
            self._targetRegistry().assertMutable(target.targetId)
        except MutableTargetError as exc:
            return f"{_L2_NOT_ALLOWED}: {exc}"
        except UnknownTargetError as exc:
            return f"{_L2_NOT_ALLOWED}: {exc}"
        if not (self._workspace / targetFile).exists():
            return f"{_L2_NOT_ALLOWED}: 目标文件在工作区不存在: {targetFile}"
        unready = self.unavailableReason()
        if unready:
            return unready
        return PatchPlan(
            proposalId=str(proposal.proposal_id),
            targetId=target.targetId,
            targetFile=targetFile,
            patch=str(getattr(proposal, "content", "") or ""),
        )

    def _findTargetByLocator(self, targetFile: str) -> Optional[EvolutionTarget]:
        """按文件路径匹配登记项；禁改内核优先诊断（给出精确的拒绝理由）。"""
        registry = self._targetRegistry()
        for target in registry.forbiddenTargets():
            if _locatorFile(target.locator) == targetFile:
                return target
        for target in registry.listByLayer("L2"):
            if _locatorFile(target.locator) == targetFile:
                return target
        return None

    # ── verify：影子验证 + 门禁链编排（G0-G4） ────────────────────

    def verify(self, proposal: Any, plan: PatchPlan) -> Dict[str, List[GateVerdict]]:
        """隔离环境验证补丁，返回 GateChain 形态的逐门三态结论。

        预检与探针都由 ``ShadowVerify`` 在隔离副本上完成（本方法不重复实现
        隔离机制）；这里只做"影子结论 → G0-G4 门禁"的编排映射。
        """
        change = ShadowChange(
            changeId=f"prpatch-{plan.proposalId}",
            kind=KIND_PATCH,
            targetId=plan.targetId,
            targetFile=plan.targetFile,
            patch=plan.patch,
        )
        shadowResult = self._shadowVerify().verify(change)
        return self._organizeGates(shadowResult, change)

    def _organizeGates(
        self, shadowResult: Any, change: ShadowChange
    ) -> Dict[str, List[GateVerdict]]:
        """影子逐项结论 → G0-G4 判据集（键名对齐计划书 §3.4 门禁表）。

        - G0 存活 = 存活探针判据（build/health/startup/minimalChat/toolExecution）；
        - G1 契约 = 补丁预检 + 守卫子集（guardSubset）；
        - G2 业务 = 影子业务判据回调（g2Business）；
        - G3 回归 / G4 教义 = 注入判据；未注入 = 空集 = unevidenced。
        补丁预检失败时探针判据整体缺席，失败结论直接扛在 G0——GateChain 据此
        短路，整体 failed（绝不把"补丁进不去"记成"证据缺失"）。
        """
        verdicts = dict(shadowResult.verdicts)
        patchApply = verdicts.pop("patchApply", None)
        guard = verdicts.pop("guardSubset", None)
        business = {
            key: verdicts.pop(key)
            for key in list(verdicts)
            if key == "g2Business" or key.startswith("g2Business[")
        }

        if patchApply is not None and not patchApply:
            survival: List[GateVerdict] = [patchApply]
            contract: List[GateVerdict] = []
        else:
            survival = list(verdicts.values())
            contract = [patchApply] if patchApply is not None else []
            if guard is not None:
                contract.append(guard)

        return GateChain().run(
            survivalVerdicts=survival,
            contractVerdicts=contract,
            businessVerdicts=list(business.values()),
            regressionVerdicts=self._criteriaList(
                self._regressionCriteria, change, shadowResult.verdicts
            ),
            doctrineVerdicts=self._criteriaList(
                self._doctrineCriteria, change, shadowResult.verdicts
            ),
        )

    @staticmethod
    def _criteriaList(
        provider: Any, change: ShadowChange, verdicts: Dict[str, GateVerdict]
    ) -> List[GateVerdict]:
        """判据回调归一化为列表；未注入 = 空列表（该门 unevidenced）。"""
        if provider is None:
            return []
        outcome = provider(change, verdicts)
        if isinstance(outcome, GateVerdict):
            return [outcome]
        return list(outcome)

    # ── apply：CAS 合入 → scope 快照 → 基线应用 ───────────────────

    def apply(self, proposal: Any, plan: PatchPlan, approver: str = "") -> PatchApplyOutcome:
        """门禁全绿后把补丁落到基线工作区（先快照、后应用、CAS 不绕行）。

        顺序即安全序：门禁链 → CAS 合入（冲突升级人工）→ scope 快照（应用前
        基线）→ ``git apply``。应用失败时把已合入候选打回 reviseRequired，
        板上不留"已合入却未生效"的假账。判据未装配时**先于影子验证**返回
        not_supported（EVO-04：不做无意义验证、不放行）。
        """
        unready = self.unavailableReason()
        if unready:
            return PatchApplyOutcome(ok=False, error=unready)
        gateResult = self.verify(proposal, plan)
        overall = gateResult[GATE_OVERALL][0]
        summary = {
            gate: verdictList[0].state
            for gate, verdictList in gateResult.items()
            if verdictList
        }
        if overall.state != STATE_PASSED:
            return PatchApplyOutcome(
                ok=False,
                error=(
                    f"门禁链未整体通过（{overall.state}），拒绝应用基线: {overall.reason}"
                ),
                gateOverall=overall.state,
                gateSummary=summary,
            )

        board = self._mergeBoard()
        from neurova.agent.candidate_merge import CandidateConflictError

        candidate = board.submitCandidate(
            runId=str(proposal.proposal_id),
            content=plan.patch,
            artifactKeys=[plan.targetFile],
        )
        try:
            merged = board.mergeCandidate(candidate.candidateId)
        except CandidateConflictError as exc:
            return PatchApplyOutcome(
                ok=False,
                error=f"CAS 合入冲突，候选保留升级人工裁决: {exc}",
                gateOverall=overall.state,
                gateSummary=summary,
                conflictWith=list(getattr(exc, "conflictWith", []) or []),
            )

        service = self._checkpointServiceFor(getattr(proposal, "agent_id", ""))
        targetPath = self._workspace / plan.targetFile
        original = targetPath.read_bytes()
        snapshotRef = service.captureScope(
            plan.proposalId,
            _SNAPSHOT_ORDINAL,
            {
                plan.targetFile: original,
                _META_FILE: json.dumps(
                    {
                        "proposal_id": plan.proposalId,
                        "target_id": plan.targetId,
                        "target_file": plan.targetFile,
                        "approver": str(approver or ""),
                    },
                    ensure_ascii=False,
                ),
            },
            message=f"prpatch pre-apply: {plan.proposalId}",
        )

        proc = self._gitApply(plan.patch, self._workspace)
        if proc.returncode != 0:
            board.markReviseRequired(
                candidate.candidateId, reason="基线应用补丁失败，打回重做"
            )
            return PatchApplyOutcome(
                ok=False,
                error=(
                    f"基线工作区应用补丁失败（目标 {plan.targetFile}）: "
                    f"{self._gitErrorHeadline(proc)}"
                ),
                snapshotRef=snapshotRef,
                gateOverall=overall.state,
                gateSummary=summary,
            )

        logger.info(
            "PR_PATCH 已应用: proposal=%s target=%s snapshot=%s mergeRevision=%s approver=%s",
            plan.proposalId, plan.targetFile, snapshotRef, merged.get("revision"), approver,
        )
        return PatchApplyOutcome(
            ok=True,
            snapshotRef=snapshotRef,
            mergeRevision=int(merged.get("revision", -1)),
            gateOverall=overall.state,
            gateSummary=summary,
        )

    # ── rollback：scope 快照恢复 ─────────────────────────────────

    def rollback(self, proposal: Any) -> str:
        """按 scope 快照把目标文件恢复到应用前字节。返回空串=成功。"""
        service = self._checkpointServiceFor(getattr(proposal, "agent_id", ""))
        targetFile = str(getattr(proposal, "target", "") or "").replace("\\", "/")
        try:
            payload = service.restoreScope(str(proposal.proposal_id), _SNAPSHOT_ORDINAL)
        except CheckpointNotFoundError as exc:
            return f"scope 快照不存在，无法回滚: {exc}"
        content = payload.get(targetFile)
        if content is None:
            return f"scope 快照缺目标文件内容: {targetFile}"
        (self._workspace / targetFile).write_bytes(content)
        logger.info("PR_PATCH 已回滚: proposal=%s target=%s", proposal.proposal_id, targetFile)
        return ""

    # ── 协作方懒构造 ─────────────────────────────────────────────

    def _targetRegistry(self):
        if self._registry is None:
            self._registry = get_target_registry()
        return self._registry

    def _shadowVerify(self):
        if self._shadow is None:
            from neurova.evolution.rsi.shadow_verify import ShadowVerify

            self._shadow = ShadowVerify(
                workspace=self._workspace, businessCriteria=self._businessCriteria
            )
        return self._shadow

    def _mergeBoard(self):
        if self._board is None:
            from neurova.agent.candidate_merge import CandidateMergeBoard

            self._board = CandidateMergeBoard()
        return self._board

    def _checkpointServiceFor(self, agentId: str):
        if self._checkpoints is not None:
            return self._checkpoints
        key = str(agentId or "").strip() or "rsi-evolution"
        if key not in self._checkpointCache:
            from neurova.checkpoints.service import CheckpointService

            self._checkpointCache[key] = CheckpointService(key)
        return self._checkpointCache[key]

    def _gitApply(self, patch: str, cwd: Path) -> "subprocess.CompletedProcess":
        # 传输委托 neurova.core.git_runner（二进制 transport）：文本模式会把
        # 补丁里的 \n 翻译成 \r\n 再进管道，git 上下文匹配即失败（Windows 三坑
        # 同款，见 checkpoints/repository.py 的同一防线）。
        from neurova.core.git_runner import run_git

        return run_git("apply", "-", cwd=str(cwd), stdin=patch,
                       timeout=self._gitTimeoutSeconds)

    @staticmethod
    def _gitErrorHeadline(proc: "subprocess.CompletedProcess") -> str:
        lines = [
            line.strip()
            for line in ((proc.stderr or "") + (proc.stdout or "")).splitlines()
            if line.strip()
        ]
        return lines[0] if lines else f"exit={proc.returncode}"
