# -*- coding: utf-8 -*-
"""G3 适配器方法面收敛：外部成员 run 的方法级契约（计划文档 G3，拍板 D-4 仅外部成员）。

把 fork / rollback / 快照读取 / steering / handoff / switch_model 映射为**本仓既有
机制**上的方法级契约；每个方法标注所需能力维度（``BOOLEAN_CAPABILITY_DIMS`` 单源），
能力不满足抛 ``CapabilityNotDeclared``（fail-closed，不静默降级）。编排层
（updateSubagent / resumeFinishedRun 等）经本面调用，禁止绕过。

方法 ↔ 机制 ↔ 能力维度映射（机制全部复用既有实现，本面不是第二套实现）：

===================  =====================================================  ==============================
方法                 既有机制                                                能力维度
===================  =====================================================  ==============================
``steer``            steer 队列邮箱（core/steer_queue）                       无闸（见 steer docstring）
``snapshot``         swarm_event_log.readRunEvents 事件账本                   无维度（账本读数不设限）
``handoffArtifact``  SwarmManager._buildResumeHandoff（B2 上下文传递工件）     跨 executor 要求 handoff_inject
``rollback``         CheckpointService 最近检查点 + restore_with_rollback     conversation_rollback
``fork``             SwarmManager.spawn 派生链 + resumed_from 溯源            fork
``switchModel``      catalog.decideProviderTransition 五结果决策              model_switch_in_session
===================  =====================================================  ==============================

能力闸的加闸范围（防回归约束）：
- 只对**本卡新增的方法**（rollback/fork/snapshot 等此前无编排入口的）整体加闸；
- 已有能力条件分支上原本就检查的维度（switch_model/handoff_inject 在五结果决策
  中已按声明判定）保持同一判定口径；
- steer 与 snapshot 不依赖 agent 侧能力声明，**不加闸**（见各自 docstring）；
- 内部 agent（无执行体能力档，caps=None）沿用「不设限」惯例（同 C5）。

不引入 Effect、不改既有机制内部——本模块只做「能力闸 + 既有机制调用」的收敛面。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from neurova.agent.neuacp.catalog import BOOLEAN_CAPABILITY_DIMS
from neurova.agent.swarm_event_log import readRunEvents
from neurova.core.steer_queue import get_steer_queue

__all__ = [
    "CapabilityNotDeclared",
    "NeuacpMemberSurface",
    "requireCapability",
]


class CapabilityNotDeclared(RuntimeError):
    """成员执行体能力档未声明所需维度（fail-closed）。

    ``dim`` 为缺失的能力维度名（``BOOLEAN_CAPABILITY_DIMS`` 内的键）；
    文案带安装/改配指引——指明在名册 executor 能力声明或 neuacp 目录预设中
    如实补声明（取得验证证据后再开启），不改写本异常的诚实语义。
    """

    def __init__(self, dim: str, message: str = "") -> None:
        self.dim = str(dim or "")
        if not message:
            message = (
                f"能力未声明: {self.dim} —— 当前成员执行体能力档未声明 "
                f"{self.dim}=true（fail-closed：缺失与 False 同义=不支持）。"
                "请在团队名册该成员的 executor 能力声明或 neuacp 目录预设中如实补声明"
                "（取得验证证据后再开启），或改用不依赖该能力的既有路径"
                "（如 mode=restart 重派、重派全新任务）。"
            )
        self.message = message
        super().__init__(message)


def requireCapability(caps: Optional[Dict[str, Any]], dim: str) -> None:
    """能力闸单点：``caps`` 未声明 ``dim`` 为真时抛 ``CapabilityNotDeclared``。

    - ``dim`` 必须在 ``BOOLEAN_CAPABILITY_DIMS`` 单源清单内，否则 ValueError
      （防调用方拼错维度名后被静默当成「未声明」处理）；
    - ``caps is None``（内部 agent / 无名册归属）→ 放行（C5 同惯例：不设限）；
    - ``caps`` 为 dict 且 ``caps.get(dim) is True`` → 放行；
    - 其余（False / 键缺失 / 非 dict 脏数据）→ 一律 ``CapabilityNotDeclared``。
    """
    if dim not in BOOLEAN_CAPABILITY_DIMS:
        raise ValueError(
            f"未知能力维度: {dim!r}——合法维度见 "
            f"neurova.agent.neuacp.catalog.BOOLEAN_CAPABILITY_DIMS 单源清单"
        )
    if caps is None:
        return
    if isinstance(caps, dict) and caps.get(dim) is True:
        return
    raise CapabilityNotDeclared(dim)


class NeuacpMemberSurface:
    """单个子代理 run 的方法级操作面（能力声明驱动可用性）。

    经 :meth:`forRun` 构造：能力档来自 ``SwarmManager._memberExecutorCaps``
    （名册 executor.tool 的目录声明，单一事实源）；名册读不到但 run 带 spawn
    时刻能力快照时回落快照（外部成员不被静默放权）；两者皆无（本仓 agent）→
    ``caps=None`` 不设限面。
    """

    def __init__(self, run: Any, caps: Optional[Dict[str, Any]], manager: Any) -> None:
        self._run = run
        self._caps = caps
        self._manager = manager

    # ── 构造入口 ─────────────────────────────────────────────────────

    @classmethod
    def forRun(cls, run: Any) -> "NeuacpMemberSurface":
        """按 run 解析能力档并构造操作面（编排层唯一入口）。"""
        from neurova.agent.swarm import get_swarm_manager

        manager = get_swarm_manager()
        caps = manager._memberExecutorCaps(run)
        if caps is None:
            snapshot = getattr(run, "executor_caps_snapshot", None)
            if isinstance(snapshot, dict) and snapshot:
                caps = dict(snapshot)
        return cls(run, caps, manager)

    @property
    def run(self) -> Any:
        return self._run

    @property
    def caps(self) -> Optional[Dict[str, Any]]:
        return self._caps

    # ── steer：插话邮箱（无能力闸） ──────────────────────────────────

    def steer(self, text: str) -> bool:
        """向 member 会话插话队列投递一条新指令，返回是否入队成功。

        **不加能力闸**：steer 走的是本仓 steer 队列邮箱（agent loop 在下一
        工具轮间隙排空、以 user 角色并入采样），投递侧不依赖 agent/执行体
        侧的任何协议支持——给它套 ``steer`` 维度闸会把既有插话路径
        （continue_subagent mode=steer）在保守能力档（多数外部成员该维度
        未声明）下直接闸死。目录里的 ``steer`` 维度约束的是「派活期显式
        索取该能力」的打开前校验（refuseExecutorSpec），与运行期邮箱插话
        是两件事。成员已不再调用工具时本条不会送达（队列 TTL 过期丢弃），
        需要确定性送达请走 mode=restart 重派。
        """
        return bool(get_steer_queue().push(str(getattr(self._run, "member_session_id", "") or ""),
                                           str(text or "")))

    # ── snapshot：事件账本读数（无能力维度） ─────────────────────────

    def snapshot(self):
        """读取该 run 的事件账本（H-4 JSONL 账本），返回事件 dict 列表。

        账本是落盘事实源，读数不设能力维度（任何成员 run 都可被编排层
        回看）；正文不进账本，报告/错误全文在 member 会话与主链路。
        """
        return readRunEvents(str(getattr(self._run, "subagent_id", "") or ""))

    # ── handoffArtifact：B2 上下文传递工件（跨 executor 要求 handoff_inject）──

    def handoffArtifact(self, message: str = "") -> Tuple[str, Dict[str, Any]]:
        """构建续跑衔接的上下文传递工件，返回 ``(inline_text, meta)``。

        复用 ``SwarmManager._buildResumeHandoff`` 既有构建（登记/预算/省略
        可恢复/事件留痕），不在此重写第二份工件逻辑。``message`` 为随行
        续跑指令原文，仅作契约入参——工件本体不含指令，[续跑指令] 的拼接
        由编排层按既有任务书形态完成。

        能力闸（同 D-B 五结果判定的既有条件）：仅当本次交接是**跨 executor**
        （run 带 spawn 时刻能力快照且名册现值 executor.tool 与快照不一致）时，
        要求交出方（快照档）与接收方（名册现值档）**都**声明
        ``handoff_inject``；同 executor 续跑 / 无快照的本仓 agent 不加闸
        （既有行为不变）。
        """
        run = self._run
        snapshotCaps = getattr(run, "executor_caps_snapshot", None)
        if isinstance(snapshotCaps, dict) and snapshotCaps:
            targetProfile = self._manager._resumeTargetProfile(run)
            if targetProfile is not None and (
                str(targetProfile.get("tool") or "")
                != str(getattr(run, "executor_tool", "") or "")
            ):
                requireCapability(snapshotCaps, "handoff_inject")
                requireCapability(targetProfile.get("caps") or {}, "handoff_inject")
        return self._manager._buildResumeHandoff(run)

    # ── rollback：检查点服务最近检查点事务化恢复 ─────────────────────

    def rollback(self) -> Dict[str, Any]:
        """把 member 会话回滚到最近检查点（要求 ``conversation_rollback``）。

        机制勘察结论：``CheckpointService`` 的 scope API（captureScope/
        rollbackScope）在本仓**没有 member 会话的写入方**（仅测试使用），
        直接走 scope 回滚必然落空；member 会话既有且已接线的检查点机制是
        chat_pipeline._auto_checkpoint → ``snapshot_auto(session_key=
        member_session_id)`` 与 K1 恢复面（restore_with_rollback + 会话写回）。
        故本方法取该会话键下**最近的检查点**做事务化恢复（恢复前自动留档
        pre-restore，apply 失败自动回滚），会话写回复用 K1 恢复面既有实现
        （delete_session + save_message + 内存镜像同步），不另造第二份 apply。

        Returns:
            成功 ``{"success": True, "restored_ref", "pre_restore_ref",
            "messages_restored", ...}``；无检查点/恢复失败 ``{"success": False,
            "error"}``（诚实失败，不静默当成功）。

        Raises:
            CapabilityNotDeclared: 成员能力档未声明 ``conversation_rollback``。
        """
        requireCapability(self._caps, "conversation_rollback")
        run = self._run
        agentId = str(getattr(run, "agent_id", "") or "")
        sessionKey = str(getattr(run, "member_session_id", "") or "")
        if not agentId or not sessionKey:
            return {"success": False,
                    "error": "rollback 需要 run 的 agent_id 与 member_session_id（缺一不可）"}
        # 复用 K1 恢复面的服务解析（优先运行实例缓存，同一 git 仓）与会话写回
        # （单一事实源，不在本面重写第二份 apply）。
        from neurova.api.endpoints.agent_checkpoints_api import (
            _apply_restore,
            _service_for,
        )

        service = _service_for(agentId)
        snapshots = service.list_snapshots(session_key=sessionKey)
        if not snapshots:
            return {"success": False,
                    "error": (f"member 会话 {sessionKey} 名下无可用检查点"
                              "（auto/snap 均无）——无处可回滚；请确认该会话已开启检查点")}
        latest = snapshots[0]
        try:
            payload = service.restore_with_rollback(
                latest["ref"], apply_fn=_apply_restore(agentId, sessionKey))
        except (ValueError, RuntimeError) as exc:
            return {"success": False,
                    "error": f"回滚到检查点 {latest['ref']} 失败：{exc}"}
        restoredCount = 0
        try:
            restoredCount = len(
                json.loads(payload.get("session_json") or "{}").get("messages") or [])
        except Exception:  # noqa: BLE001 - 计数失败不影响回滚本身
            restoredCount = 0
        return {"success": True, "agent_id": agentId, "session_key": sessionKey,
                "restored_ref": latest["ref"],
                "restored_kind": latest.get("kind", ""),
                "pre_restore_ref": payload.get("pre_restore_ref"),
                "messages_restored": restoredCount}

    # ── fork：候选制+重派路径（spawn 派生链 + resumed_from 溯源） ─────

    async def fork(self, message: str, background: bool = False) -> Dict[str, Any]:
        """从本 run 派生一个分支 run（要求 ``fork``），返回 spawn 结果。

        机制 = 既有「候选制+重派」路径：经 ``SwarmManager.spawn`` 派生新 run
        （治理闸/团队点名/事件账本与全新派生同一条链），``resumed_from`` 指
        向本 run 作分支溯源；**不复用 member 会话**（分支从新会话起步，原 run
        不受影响——这是 fork 与 restart 的本质差别）。分支产出的结果经既有
        通道回流（chat 来源→父会话邮箱/候选板，workflow 来源→引擎 output）。

        Raises:
            CapabilityNotDeclared: 成员能力档未声明 ``fork``。
        """
        requireCapability(self._caps, "fork")
        run = self._run
        task = str(message or "").strip()
        teamOverride = None
        if run.team_id:
            teamOverride = (dict(run.team_member) if run.team_member
                            else self._manager._rosterMemberOverride(
                                run.team_id, run.agent_id))
        return await self._manager.spawn(
            task,
            agent_id=run.agent_id,
            session_id=run.session_id,
            background=background,
            origin=run.origin or "chat",
            stream=True,
            subagent_type=run.subagent_type or "general",
            reuse_member_session_id=None,
            resumed_from=run.subagent_id,
            room_id=run.room_id or None,
            project_id=run.project_id or None,
            team_id=run.team_id or None,
            team_role=run.team_role or None,
            teamMemberOverride=teamOverride,
        )

    # ── switchModel：五结果决策 switch_model_in_session 分支语义 ─────

    def switchModel(self, model: str) -> Dict[str, Any]:
        """会话内换模型判定（要求 ``model_switch_in_session``），返回决策结果。

        机制勘察结论：本仓**没有运行期任意换模型的 setter**——D-B 的
        switch_model_in_session 分支语义是「续跑/接续时以名册现值执行体
        （带新模型）复用 member 会话」。故本方法做三件事：
        1. fail-closed 能力闸（同五结果决策检查的维度）；
        2. 校验请求模型 = 名册现值模型（机制只认名册现值，不一致诚实拒绝）；
        3. 以 ``model_changed=True`` 跑 ``decideProviderTransition`` 五结果
           决策，返回决策与 member 会话复用判定；实际续跑由编排层经
           resumeFinishedRun 落地（本面不复制派生链，不是第二套实现）。

        Raises:
            CapabilityNotDeclared: 成员能力档未声明 ``model_switch_in_session``。
        """
        requireCapability(self._caps, "model_switch_in_session")
        requested = str(model or "").strip()
        if not requested:
            return {"success": False, "error": "switchModel 需要目标模型名"}
        run = self._run
        profile = self._manager._resumeTargetProfile(run)
        if profile is None:
            return {"success": False,
                    "error": "续跑目标执行体档案已不可得（名册成员或 executor 已"
                             "移除/禁用）——无法会话内换模型"}
        targetModel = str(profile.get("model") or "")
        if requested != targetModel:
            return {"success": False,
                    "error": (f"请求模型 {requested} 与名册现值模型 "
                              f"{targetModel or '(空)'} 不一致——本仓机制只在续跑时"
                              "落到名册现值执行体，无运行期任意换模型口径；"
                              "请先调整名册 executor 配置再切换")}
        snapshotCaps = getattr(run, "executor_caps_snapshot", None)
        currentCaps = (snapshotCaps if isinstance(snapshotCaps, dict) and snapshotCaps
                       else (self._caps or {}))
        from neurova.agent.neuacp.catalog import decideProviderTransition

        decision = decideProviderTransition(
            currentCaps, profile.get("caps") or {},
            same_executor=True, target_installed=bool(profile.get("installed")),
            model_changed=(str(getattr(run, "executor_model", "") or "") != requested),
        )
        if decision == "switch_model_in_session":
            return {"success": True, "decision": decision, "switched": True,
                    "reuse_member_session": True, "target_model": requested,
                    "subagent_id": run.subagent_id,
                    "member_session_id": run.member_session_id}
        if decision == "reuse":
            return {"success": True, "decision": decision, "switched": False,
                    "reuse_member_session": True, "target_model": requested,
                    "note": "请求模型与 run 当前模型一致，无需切换（会话照常复用）"}
        return {"success": False, "decision": decision,
                "error": self._manager._resumeRejectReason(
                    run, sameExecutor=True, modelChanged=True,
                    targetInstalled=bool(profile.get("installed")),
                    currentTool=str(profile.get("tool") or ""),
                    currentModel=targetModel)}
