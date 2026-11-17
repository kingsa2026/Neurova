"""RoomTurnRouter — 协作房间轮次调度：@路由 + 默认应答者，落库/广播/调 Agent.chat。

职责：收到一条人类消息 → 持久化并广播 → 解析应回应的成员 Agent → 逐个调用其
`Agent.chat`（session_id=room_id，turn_origin=collaboration）→ 落库并广播回应。
失败发 AGENT_ERROR，不静默、不抛出打断请求。

依赖注入（store/bus/agent_lookup）便于单测；默认接既有单例。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.collaboration.room_bus import RoomBus, get_room_bus
from neurova.collaboration.room_store import RoomStore, get_room_store
from neurova.sync.session_sync_manager import EventType
from neurova.core.lazy_singleton import lazySingleton

logger = get_logger(__name__)

# ── S11 入口二：用户经项目房间直发多 agent 协作 ─────────────────────────
# 触发：@全部成员的协作消息，或房间"发起协作"动作端点。编排机制与入口一共用
# 同一套 SwarmManager（不建第二套编排引擎，教义第 6 条）；本路由只做识别+拼装+发起。
#: 任务指令进任务书的截断上限（具名常量——"正文不得按字面量砍长度"钉子）
ROOM_COLLAB_TASK_MAX_CHARS = 4000
#: 房间近期上下文摘要的截断上限（具名常量）
ROOM_COLLAB_HISTORY_DIGEST_CHARS = 1200
#: 注入任务书的房间近史条数（具名常量）
ROOM_COLLAB_HISTORY_MAX_TURNS = 10


def isCollaborationTrigger(text: str, members: List[Dict[str, str]]) -> bool:
    """识别协作模式：@全部成员（≥2 名成员全部被点名）= 协作指令。

    单人房间/部分点名/无点名都走既有逐个独立应答路径；"发起协作"动作走
    专用端点（start_room_collaboration），不依赖本判据。
    """
    real = [m for m in (members or []) if m.get("id")]
    if len(real) < 2:
        return False
    mentioned = set(resolve_targets(text or "", real, ""))
    return bool(mentioned) and mentioned >= {m["id"] for m in real}


def composeRoomCollabBrief(
    roomId: str,
    actor: str,
    leadId: str,
    members: List[Dict[str, str]],
    text: str,
    historyRows: List[Dict[str, Any]],
    nameById: Dict[str, str],
    maxTaskChars: int = ROOM_COLLAB_TASK_MAX_CHARS,
    historyTurns: int = ROOM_COLLAB_HISTORY_MAX_TURNS,
    digestChars: int = ROOM_COLLAB_HISTORY_DIGEST_CHARS,
) -> str:
    """统一任务书拼装：房间协作指令 → 结构化协作任务书。

    不要把房间消息当 TaskUnit 正文直通——任务书带房间/发起人/主从分工/
    任务指令（按具名常量截断）/近史摘要/产出要求，member 据此入池编排。
    """
    leadName = nameById.get(leadId, leadId)
    supporters = [m for m in (members or []) if m.get("id") and m["id"] != leadId]
    supporterNames = "、".join(f"{nameById.get(m['id'], m['id'])}({m['id']})" for m in supporters)
    lines = [
        "【协作任务书】",
        f"- 房间：{roomId}",
        f"- 发起人：{actor}",
        f"- 主执行者：{leadName}（{leadId}）——先行执行，产出第一轮结果",
    ]
    if supporterNames:
        lines.append(f"- 支援成员：{supporterNames}——在主执行者产出基础上接力/复核")
    lines.append(f"- 任务指令：{(text or '').strip()[:maxTaskChars]}")
    digest = build_room_history(historyRows, text or "", nameById, max_turns=historyTurns)
    if digest:
        digestText = " / ".join(f"{t['role']}:{t['content']}" for t in digest)[:digestChars]
        lines.append(f"- 房间近期上下文（衔接用，勿重复）：{digestText}")
    lines.append("- 产出要求：以结构化报告收尾；结果将进入候选板，由房间按权限裁决采纳")
    return "\n".join(lines)


def resolve_targets(text: str, members: List[Dict[str, str]], responder_agent_id: str = "") -> List[str]:
    """解析一条消息应回应的成员 Agent id 列表。

    - 命中 @成员名 或 @成员id → 返回被 @ 的成员（按 members 顺序，可多个）。
    - 无 @ → 默认应答者 responder_agent_id；其未配置则取 members 首个。
    - members 为空 → []。
    """
    text = text or ""
    # 忽略空 id 成员（历史遗留：/start 未传 owner 时写入的空键成员）。
    real = [m for m in (members or []) if m.get("id")]
    matched = [
        m["id"] for m in real
        if ("@" + m["id"]) in text or (m.get("name") and ("@" + m["name"]) in text)
    ]
    if matched:
        return matched
    if responder_agent_id:
        return [responder_agent_id]
    return [real[0]["id"]] if real else []


def _extract_text(response: Any) -> str:
    """从 Agent.chat 返回值提取文本（dict{"text"} / str / 对象.content）。"""
    if isinstance(response, dict):
        return str(response.get("text", ""))
    if hasattr(response, "content"):
        return str(response.content)
    return str(response) if response is not None else ""


_HISTORY_MAX_TURNS = 20  # 注入每个 agent 的近 N 条房间转录，跨 agent 共享上下文


def build_room_history(
    rows: List[Dict[str, Any]],
    current_text: str,
    name_by_id: Dict[str, str],
    max_turns: int = _HISTORY_MAX_TURNS,
) -> List[Dict[str, str]]:
    """把房间持久行转为管线可消费的 caller-history（[{role, content}]）。

    - 去掉本轮当前 user 消息（另作 user_input 传入，避免重复）；
    - 人类 → role user；agent 发言 → role assistant 并以 `[显示名]: ` 前缀冠名，
      使被 @ 的 agent 能区分“别人说的”与“自己说的”，从而接住跨 agent 上下文；
    - 仅保留最近 max_turns 条，防止上下文膨胀。
    """
    items = list(rows or [])
    # 移除最后一条与 current_text 相同的 user 行（即本轮触发消息）。
    for i in range(len(items) - 1, -1, -1):
        r = items[i]
        if r.get("sender_type") == "user" and (r.get("content") or "") == current_text:
            items.pop(i)
            break
    turns: List[Dict[str, str]] = []
    for r in items:
        st = r.get("sender_type")
        content = (r.get("content") or "").strip()
        if not content:
            continue
        if st == "user":
            turns.append({"role": "user", "content": content})
        elif st == "agent":
            speaker_id = r.get("sender_id") or ""
            speaker = name_by_id.get(speaker_id, speaker_id or "agent")
            turns.append({"role": "assistant", "content": f"[{speaker}]: {content}"})
    return turns[-max_turns:] if max_turns else turns


def _extract_turn_meta(response: Any) -> Dict[str, Any]:
    """从 Agent.chat 返回 dict 提取本轮工具消息与推理，供房间持久化/广播。

    ChatPipeline.execute 已在结果 dict 内携带 reasoning 与 tool_messages（见
    chat_pipeline.execute 组装处）；房间据此重建步骤时间轴，刷新可回看。
    """
    if not isinstance(response, dict):
        return {"tool_calls": [], "reasoning_content": ""}
    tool_messages = response.get("tool_messages") or []
    reasoning = response.get("reasoning") or ""
    return {
        "tool_calls": tool_messages if isinstance(tool_messages, list) else [],
        "reasoning_content": str(reasoning),
    }


class RoomTurnRouter:
    def __init__(
        self,
        store: Optional[RoomStore] = None,
        bus: Optional[RoomBus] = None,
        agent_lookup: Optional[Any] = None,
    ) -> None:
        self.store = store or get_room_store()
        self.bus = bus or get_room_bus()
        if agent_lookup is None:
            from neurova.api.endpoints import get_agent_instance  # 延迟导入避免环依赖

            agent_lookup = get_agent_instance
        self._agent_lookup = agent_lookup

    async def handle_user_message(
        self,
        room_id: str,
        text: str,
        actor_user: str,
        members: List[Dict[str, str]],
        responder_agent_id: str = "",
    ) -> None:
        # 1. 人类消息落库 + 广播
        self.store.append(room_id, "user", actor_user, text)
        await self.bus.publish(room_id, EventType.USER_MESSAGE.value, {"sender_id": actor_user, "content": text})
        # 2. S11 入口二：@全部成员的协作指令 → 交 SwarmManager 编排（不再逐个独立应答）
        if isCollaborationTrigger(text, members):
            await self.orchestrateRoomCollaboration(
                room_id, text, actor_user, members, responder_agent_id=responder_agent_id)
            return
        # 3. 普通消息：解析目标并逐个回应；先把成员 id → 显示名解析好，供共享转录冠名。
        name_by_id = {m["id"]: (m.get("name") or m["id"]) for m in (members or []) if m.get("id")}
        for agent_id in resolve_targets(text, members, responder_agent_id):
            await self._run_agent(room_id, text, agent_id, name_by_id)

    async def orchestrateRoomCollaboration(
        self,
        room_id: str,
        text: str,
        actor_user: str,
        members: List[Dict[str, str]],
        responder_agent_id: str = "",
        budgetSeconds: Optional[float] = None,
        maxMembers: Optional[int] = None,
    ) -> Dict[str, Any]:
        """入口二：把房间成员交 SwarmManager 编排（多 agent 协作）。

        - 主从/依赖：默认应答者（或首名成员）为主执行者先行；其余成员为支援，
          task_unit.dependencies 指向主的 subagent_id（依赖门自动接力）；
        - 观测：spawn 的 session_id/room_id 指向房间会话——subagent_started/chunk/
          completed 事件回房间广播（复用 H-4 时间线与 S9 房间投递通道），终态报告
          以 candidate 落房间（S4 候选板 + S9 呈现面）；
        - 治理：发起人显式预算（budgetSeconds）落到每路 run 的运行窗口；未给则沿用
          蜂群治理默认（房间所属 agent 治理参数）；三明治照常生效；
        - 执行机制与入口一共用同一套 SwarmManager——不建第二套编排引擎。
        """
        from neurova.agent.swarm import get_swarm_manager

        swarm = get_swarm_manager()
        name_by_id = {m["id"]: (m.get("name") or m["id"]) for m in (members or []) if m.get("id")}
        # 只编排**可解析为 Agent 实例**的成员：房间成员表里混有群主（人类用户 id，
        # S9 /start 语义）——给人派蜂群 run 是浪费治理槽且必然失败，跳过并如实记账。
        agentMembers: List[Dict[str, str]] = []
        skipped: List[str] = []
        for m in (members or []):
            mid = str(m.get("id") or "").strip()
            if not mid:
                continue
            try:
                if self._agent_lookup(agent_id=mid) is None:
                    skipped.append(mid)
                    continue
            except Exception:  # noqa: BLE001 - 解析失败按非 agent 处理
                skipped.append(mid)
                continue
            agentMembers.append(m)
        memberIds = [m["id"] for m in agentMembers]
        leadId = responder_agent_id if responder_agent_id in memberIds else (memberIds[0] if memberIds else "")
        if not leadId:
            await self.bus.publish(
                room_id, EventType.AGENT_ERROR.value,
                {"sender_id": "swarm", "content": "房间没有可编排的 Agent 成员"})
            return {"success": False, "error": "房间没有可编排的 Agent 成员",
                    "skipped": skipped}

        # 统一任务书拼装（不把房间消息当 TaskUnit 正文直通；截断守具名常量纪律）
        brief = composeRoomCollabBrief(
            room_id, actor_user, leadId, members, text,
            self.store.history(room_id), name_by_id)

        supporters = [mid for mid in memberIds if mid != leadId]
        if maxMembers is not None:
            supporters = supporters[:max(0, int(maxMembers))]

        # 主执行者先行
        leadResult = await swarm.spawn(
            task=brief,
            agent_id=leadId,
            session_id=room_id,
            background=True,
            origin="room_collab",
            room_id=room_id,
            runtimeBudgetSec=budgetSeconds,
        )
        if leadResult.get("rejected") or leadResult.get("error"):
            rejection = leadResult.get("rejection") or {}
            msg = (f"协作发起被拒：{rejection.get('message') or leadResult.get('error') or '未知原因'}"
                   f"（{rejection.get('code', '')}）")
            await self.bus.publish(
                room_id, EventType.AGENT_ERROR.value, {"sender_id": "swarm", "content": msg})
            return {"success": False, "error": msg, "lead_result": leadResult}
        leadRunId = str(leadResult.get("subagent_id") or "")

        # 支援成员：依赖主执行者的产出（依赖门按 subagent_id 接力）
        dispatches = [{"member": leadId, "subagent_id": leadRunId, "role": "lead"}]
        for mid in supporters:
            memberResult = await swarm.spawn(
                task=brief,
                agent_id=mid,
                session_id=room_id,
                background=True,
                origin="room_collab",
                room_id=room_id,
                runtimeBudgetSec=budgetSeconds,
                task_unit={
                    "goal": f"支援主执行者（{name_by_id.get(leadId, leadId)}）完成房间协作任务",
                    "dependencies": [leadRunId],
                },
            )
            if memberResult.get("rejected") or memberResult.get("error"):
                rejection = memberResult.get("rejection") or {}
                logger.warning(
                    "RoomCollab: 支援成员派生被拒 (room=%s member=%s): %s",
                    room_id, mid, rejection.get("message") or memberResult.get("error"))
            dispatches.append({
                "member": mid, "subagent_id": memberResult.get("subagent_id"),
                "role": "supporter",
                "rejected": bool(memberResult.get("rejected")),
            })

        # 发起事实以系统消息上墙（房间可回看；前端按 kind=swarm_collab 渲染进度卡）
        from neurova.collaboration.room_bus import publishRoomSystemMessage

        runIds = [d["subagent_id"] for d in dispatches if d.get("subagent_id")]
        publishRoomSystemMessage(
            room_id,
            f"【协作】{actor_user} 发起蜂群协作：主={name_by_id.get(leadId, leadId)}"
            f"，支援={ '、'.join(name_by_id.get(m, m) for m in supporters) or '无' }"
            f"（{len(runIds)} 路 run 已编排）",
            meta={"kind": "swarm_collab", "phase": "started", "lead": leadId,
                  "members": memberIds, "subagent_ids": runIds},
        )
        return {
            "success": True,
            "room_id": room_id,
            "lead": leadId,
            "supporters": supporters,
            "dispatches": dispatches,
            "subagent_ids": runIds,
            "budget_seconds": budgetSeconds,
            "skipped": skipped,
        }

    async def _run_agent(
        self, room_id: str, text: str, agent_id: str, name_by_id: Optional[Dict[str, str]] = None
    ) -> None:
        try:
            agent = self._agent_lookup(agent_id=agent_id)
            if agent is None:
                await self.bus.publish(
                    room_id, EventType.AGENT_ERROR.value, {"sender_id": agent_id, "content": "Agent 未就绪"}
                )
                return
            # 跨 agent 共享上下文：把房间全量多发送者转录按既有 caller-history 契约嗂入。
            shared_history = build_room_history(self.store.history(room_id), text, name_by_id or {})
            response = await agent.chat(
                text,
                session_id=room_id,
                metadata={"turn_origin": "collaboration", "history": shared_history},
            )
            reply = _extract_text(response)
            meta = _extract_turn_meta(response)
            # 持久化携带 tool_calls/reasoning_content → 刷新回看可重建工具/推理步骤。
            self.store.append(room_id, "agent", agent_id, reply, meta=meta)
            await self.bus.publish(
                room_id,
                EventType.AGENT_REPLY.value,
                {
                    "sender_id": agent_id,
                    "content": reply,
                    "tool_messages": meta["tool_calls"],
                    "reasoning": meta["reasoning_content"],
                },
            )
        except Exception as e:  # noqa: BLE001 — 单成员失败不拖垮整轮，发错误事件不静默
            logger.exception("RoomTurnRouter._run_agent 失败 (room=%s agent=%s)", room_id, agent_id)
            await self.bus.publish(
                room_id, EventType.AGENT_ERROR.value, {"sender_id": agent_id, "content": str(e)}
            )


_router: Optional[RoomTurnRouter] = None


@lazySingleton("_router")
def get_room_turn_router() -> RoomTurnRouter:
    return RoomTurnRouter()


def reset_room_turn_router() -> None:
    global _router
    _router = None
