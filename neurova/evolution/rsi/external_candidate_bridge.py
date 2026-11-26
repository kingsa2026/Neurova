# -*- coding: utf-8 -*-
"""ExternalCandidateBridge —— neuacp 外部执行体接入演化提案通道（P2-2）。

设计出处：``docs/04-plans/2026-11-21-recursive-self-evolution-plan.md``
§3.6（生成端接 neuacp）、§6 P2 批 P2-2、§9 风险登记（外部 agent 供应链防线）。

定位：外部编码 agent（neuacp 成员，swarm 名册 executor=acp/plugin）产出的
unified diff，经 :func:`submitExternalPatch` 包装为
``SelfImprovementProposer.propose_pr_patch`` 提案。本桥**只做包装与预检，
不新建任何审批面**：

- 沙箱校验（路径穿越/系统文件前缀/项目目录白名单/危险模式）复用
  ``proposer.validate_proposal``（submit_proposal 内触发），单一实现不另造；
- 禁改内核 / 白名单外目标在**提交时**即经 ``PrPatchChannel.plan`` →
  ``TargetRegistry.assertMutable`` fail-closed 拒绝——与批准时同一道闸提前到
  入口，不让"注定批不了"的提案混进待审台账制造审计噪声；
- 双 gate（人类评审主 gate + 部署阶段 gate：high→phase≥4）原样保留在
  ``approve_and_apply``，外部提案与内部提案走同一条审批链与同一条
  PrPatchChannel 生效通道（G0-G4 门禁链 + CAS 合入 + scope 快照）；
- 来源 lineage（source/agent_id/run_id + 其余 run 上下文）写入提案
  ``metadata``，随台账持久化、随治理读面出街——外部产出的提案必须能回答
  "谁在哪个 run 产出"。

错误语义（沿 ``RSIManualApplyError`` 的 status_code 映射范式）：
``ExternalPatchRejected.status_code`` 供未来治理端点映射 HTTP 状态——
422＝请求内容非法（空补丁/路径越界/目标不可演化/沙箱校验失败）；
503＝提案通道不可用（目标 agent 无 RSI 提案通道）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "ExternalPatchRejected",
    "submitExternalPatch",
    "resolveProposerForAgent",
]

#: lineage 的来源标记（metadata["source"]）：外部编码成员产出。
SOURCE_EXTERNAL = "neuacp_external"

#: runContext 里会被归一化为 metadata["run_id"] 的键（其余键原样进 run_context）。
_RUN_ID_KEYS = ("runId", "run_id", "subagentId", "subagent_id")


class ExternalPatchRejected(Exception):
    """外部补丁提交被拒的业务异常（P2-2）。

    ``status_code`` 供治理端点映射 HTTP 状态（沿 R1 ``RSIManualApplyError``
    同款范式）：422＝请求内容非法；503＝提案通道不可用。
    """

    def __init__(self, reason: str, status_code: int = 422):
        super().__init__(reason)
        self.status_code = int(status_code)


def resolveProposerForAgent(agentId: str):
    """生产缺省 proposer 解析：与治理端点 ``_get_rsi_orchestrator`` 同源
    （``neurova.api.endpoints.get_agent_instance`` 单源取法，不建第二套 agent 定位）。

    指名的 agent 不在运行池 / 未装配 RSI 编排器 → 503 语义拒绝，**不回落**到
    别的 agent——回落等于把外部产出记到别人名下（工单 011 同款纪律）。
    外部成员通常不在 agent 池中，swarm 接线时应显式传入宿主 agent 的
    proposer（见本模块文档与 P2-2 报告的接线片段）。
    """
    from neurova.api.endpoints import get_agent_instance

    agent = get_agent_instance(str(agentId or ""))
    orchestrator = getattr(agent, "rsi_orchestrator", None) if agent is not None else None
    if orchestrator is None:
        raise ExternalPatchRejected(
            f"agent {agentId!r} 无 RSI 提案通道（不在运行池或未装配 rsi_orchestrator）——"
            "外部补丁无处落脚；调用方应显式传入宿主 agent 的 proposer",
            status_code=503,
        )
    proposer = getattr(orchestrator, "self_improvement_proposer", None)
    if proposer is None:
        raise ExternalPatchRejected(
            f"agent {agentId!r} 的 RSI 编排器未装配 self_improvement_proposer",
            status_code=503,
        )
    return proposer


def _runIdFromContext(runContext: Mapping) -> str:
    """runContext → run_id（ lineage 主键；取第一个非空别名）。"""
    for key in _RUN_ID_KEYS:
        value = str(runContext.get(key) or "").strip()
        if value:
            return value
    return ""


def submitExternalPatch(
    *,
    agentId: str,
    targetFile: str,
    patchContent: str,
    description: str = "",
    runContext: Optional[Mapping] = None,
    proposer: Optional[Any] = None,
    channel: Optional[Any] = None,
) -> str:
    """把外部编码成员产出的 unified diff 包装为 PR_PATCH 提案并提交待审。

    Args:
        agentId: 产出补丁的外部成员标识（进 lineage metadata；缺省 resolver
            也以它定位宿主 RSI 通道）。
        targetFile: 补丁目标文件（仓库相对路径）。
        patchContent: unified diff 全文。
        description: 人类可读描述（人工评审 gate 的评审输入；空则自动生成
            带来源标注的默认描述）。
        runContext: 运行上下文映射（runId/tenantId/teamId 等审计字段）；
            runId 归一化进 ``metadata["run_id"]``，其余键原样保留在
            ``metadata["run_context"]``。
        proposer: 显式注入的 :class:`SelfImprovementProposer`（swarm 接线 /
            测试用）。缺省经 :func:`resolveProposerForAgent` 按 agentId 解析。
        channel: 显式注入的 :class:`PrPatchChannel`（测试用隔离实例）。
            缺省取 proposer 自己的 ``prPatchChannel``——预检与批准同一实例。

    Returns:
        proposal_id（PENDING 状态，等人工评审）。

    Raises:
        ExternalPatchRejected: 输入非法 / 预检拒绝 / 沙箱校验失败（422），
            或提案通道不可用（503）。
    """
    agentId = str(agentId or "").strip()
    if not agentId:
        raise ExternalPatchRejected("agentId 不能为空：外部补丁必须可溯源到提交成员")
    targetFile = str(targetFile or "").strip().replace("\\", "/")
    if not targetFile:
        raise ExternalPatchRejected("targetFile 不能为空：PR patch 必须指名目标文件")
    patchContent = str(patchContent or "")
    if not patchContent.strip():
        raise ExternalPatchRejected("patchContent 不能为空：空补丁不构成可评审提案")
    context: Mapping = runContext if isinstance(runContext, Mapping) else {}

    if proposer is None:
        proposer = resolveProposerForAgent(agentId)

    # 通道取 proposer 自己那份（懒构造单例形态）——外部提案与内部批准必须
    # 走同一个通道实例，否则预检用的判据/合并板与真正 apply 的那份不是同一
    # 个对象，预检结论对批准无效（EVO-04）。
    if channel is None:
        channel = proposer.prPatchChannel
    # EVO-04：判据未装配 ⇒ 通道显式不可用，503 拒绝在**入账之前**——
    # 不把注定批不了的提案塞进待审台账，也不让影子验证做无意义 IO。
    unready = channel.unavailableReason()
    if unready:
        raise ExternalPatchRejected(
            f"外部补丁通道不可用（agent={agentId}）：{unready}", status_code=503
        )

    cleanDescription = str(description or "").strip()
    if not cleanDescription:
        cleanDescription = f"外部成员 {agentId} 的代码补丁: {targetFile}"
    proposal = proposer.propose_pr_patch(
        target_file=targetFile,
        patch_content=patchContent,
        description=cleanDescription,
    )

    # 提交前预检：与批准时同一道闸（PrPatchChannel.plan → TargetRegistry
    # assertMutable fail-closed）。禁改内核 / 白名单外目标在这里就拒。
    planOutcome = channel.plan(proposal)
    if isinstance(planOutcome, str):
        raise ExternalPatchRejected(f"外部补丁预检被拒：{planOutcome}")

    # 来源 lineage 入提案 metadata（审计与世代账本的关联键）
    metadata = dict(getattr(proposal, "metadata", None) or {})
    metadata["source"] = SOURCE_EXTERNAL
    metadata["agent_id"] = agentId
    metadata["run_id"] = _runIdFromContext(context)
    metadata["run_context"] = {
        str(key): value
        for key, value in context.items()
        if key not in _RUN_ID_KEYS
    }
    proposal.metadata = metadata

    try:
        proposalId = proposer.submit_proposal(proposal)
    except ValueError as exc:
        # 沙箱校验（validate_proposal）失败：路径穿越/系统文件/白名单外等，
        # 以 422 语义如实上报，不吞不折（proposer 已产出的提案对象不入台账）
        raise ExternalPatchRejected(f"外部补丁未通过沙箱校验：{exc}") from exc

    logger.info(
        "外部补丁已入演化提案通道: proposal=%s member=%s run=%s target=%s",
        proposalId, agentId, metadata["run_id"], targetFile,
    )
    return proposalId
