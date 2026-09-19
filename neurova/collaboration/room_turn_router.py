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

logger = get_logger(__name__)


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
        # 2. 解析目标并逐个回应；先把成员 id → 显示名解析好，供共享转录冠名。
        name_by_id = {m["id"]: (m.get("name") or m["id"]) for m in (members or []) if m.get("id")}
        for agent_id in resolve_targets(text, members, responder_agent_id):
            await self._run_agent(room_id, text, agent_id, name_by_id)

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


def get_room_turn_router() -> RoomTurnRouter:
    global _router
    if _router is None:
        _router = RoomTurnRouter()
    return _router


def reset_room_turn_router() -> None:
    global _router
    _router = None
