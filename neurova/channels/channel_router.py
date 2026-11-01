# -*- coding: utf-8 -*-
"""ChannelRouter —— 渠道入站消息统一路由到 agent 并回发。

背景（"下消息通路"缺失环）：ChannelManager 此前没有任何常驻消息处理器，飞书/钉钉/
微信等渠道把消息收进来后 `_dispatch_message` 找不到 handler → 无人调用 agent →
无回复
`resolve_session_id` 得到稳定会话键。NV 复用既有 `ChannelManager.add_message_handler`
与 `resolve_session_scope_id`，用**一个**常驻 handler 打通：

  入站 ChannelMessage →（agent_id 来自装配期 metadata）→ get_agent_instance(agent_id)
  → **run 台账登记 + 让位闸准入**（P2-8 §6-46：与网页/API 入口共用 `core/agent_run_ledger`
     那一份实现；等不到额度就把这一轮挂起成 parked，回一条带 run_id 的诚实回执）
  → agent.chat(user_input, session_id=resolve_session_scope_id(msg),
     metadata={user_id=发送者, source_channel=渠道, role=user})
  → 返回回复文本 → manager._dispatch_message 自动 send_message 回发到该渠道该会话。

会话键固定（同一 agent+渠道+群/私聊 → 同一 session），保证多轮上下文连续；群共享/
按发送者隔离由 resolve_session_scope_id 单点裁决（share_session_in_group）。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from neurova.channels.base import ChannelMessage
from neurova.channels.access_policy import chatAccessDecision
from neurova.channels.voice_egress import turnAudioCandidate
from neurova.voice_context_module import VOICE_CONTEXT_KEY
from neurova.channels.group_leadership import (
    get_group_leadership_arbiter,
    get_group_leadership_config,
)
from neurova.core.agent_run_ledger import (
    ENTRY_CHANNEL,
    AgentRunLedger,
    parkReceiptText,
    reportAdmissionOutcome,
    requestTurnAdmission,
)

logger = logging.getLogger(__name__)

# 默认 agent 查找回退（延迟 import 避免 channels↔api 循环依赖）
def _default_agent_lookup(agent_id: str):
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


def _channel_cfg(manager, channel_type: str, agent_id: str) -> Dict[str, Any]:
    """读该 (agent,渠道) 适配器的配置 extra（公共参数：show_thinking 等存这里）。
    未注册适配器时返回空 dict（各开关取默认）。

    策略类字段在 Gen2 适配器上被 `authenticate()` 读成**实例属性**、并不回写 extra
    （Discord/Telegram 等）。这里把实例属性补进同一视图，否则「UI 里配了 whitelist」
    在路由层永远看不到——那正是 D-5 的失败方向。
    """
    try:
        adapter = manager.get_adapter(channel_type, agent_id=agent_id)
    except Exception:
        return {}
    if adapter is None:
        return {}
    cfg = getattr(adapter, "config", None)
    extra = dict(getattr(cfg, "extra", {}) or {}) if cfg else {}
    for key in ("private_chat_strategy", "group_chat_strategy", "whitelist_users", "require_mention"):
        if key not in extra and hasattr(adapter, key):
            extra[key] = getattr(adapter, key)
    # iLink/历史配置用的是另一组键名（`private_strategy` / `ilink_*`）：不归一到同一视图，
    # 「UI 里配了 whitelist」在路由层就等于没配（D-5 的失败方向）。
    for source, target in (
        ("private_strategy", "private_chat_strategy"),
        ("group_strategy", "group_chat_strategy"),
        ("ilink_private_strategy", "private_chat_strategy"),
        ("ilink_group_strategy", "group_chat_strategy"),
        ("ilink_whitelist_users", "whitelist_users"),
        ("ilink_require_mention", "require_mention"),
    ):
        if target in extra:
            continue
        if source in extra:
            extra[target] = extra[source]
        elif hasattr(adapter, source):
            extra[target] = getattr(adapter, source)
    # 兼容顶层 use_stream 作为连接方式，不覆盖 extra 的 stream_mode（流式回复开关）
    return extra


def _flag(value: Any, default: bool = False) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off", "")
    if value is None:
        return default
    return bool(value)


async def _reportAdmission(admission) -> None:
    """回填 pacing 统计（Layer 3 间距/节律的判据来源）。

    失败只点名不抛出：这一轮的回复已经发出去了，统计回执不该把答完的回合翻成失败。
    """
    if admission is None or not admission.allowed:
        return
    try:
        await reportAdmissionOutcome(admission, success=True)
    except Exception:  # noqa: BLE001
        logger.warning("ChannelRouter: 让位闸回执失败（不影响本轮）", exc_info=True)


def _detect_sender_is_bot(message: ChannelMessage) -> bool:
    """判定入站消息发送者是否 bot/对端 agent（任务2 actionability 信号）。

    依次查适配器已解析的 metadata（sender_is_bot/is_bot）与 raw_event 里的平台真实
    字段（telegram from.is_bot / discord author.bot）。缺字段/非法一律 False（=人类，安全侧）。"""
    meta = getattr(message, "metadata", None)
    if isinstance(meta, dict) and (meta.get("sender_is_bot") or meta.get("is_bot")):
        return True
    raw = getattr(message, "raw_event", None)
    if not isinstance(raw, dict):
        return False
    sender = raw.get("from") or raw.get("author") or {}
    return isinstance(sender, dict) and bool(sender.get("is_bot") or sender.get("bot"))


def make_handler(manager, agent_lookup: Optional[Callable[[str], Any]] = None) -> Callable:
    """构造渠道→agent 处理器。agent_lookup(agent_id)->Agent|None 可注入（测试用）。"""
    lookup = agent_lookup or _default_agent_lookup

    async def _handler(message: ChannelMessage) -> Optional[str]:
        content = (message.content or "").strip()
        if not content:
            return None
        agent_id = str(message.metadata.get("agent_id") or "default")
        cfg = _channel_cfg(manager, message.channel_type, agent_id)

        # 访问控制传导（此前所有渠道都忽略这两个开关）：
        # 判定单源在 `channels/access_policy.py`；closed/whitelist/未知策略一律拒绝。
        allowed, denyReason = chatAccessDecision(message.chat_type, cfg, message.sender_id)
        if not allowed:
            logger.info(
                "ChannelRouter: %s %s 准入拒绝（%s），忽略消息",
                message.channel_type, message.chat_type, denyReason,
            )
            return None
        if message.chat_type == "group" and _flag(cfg.get("require_mention")):
            mentioned = bool(message.metadata.get("mentions")) or "@" in content
            if not mentioned:
                logger.info("ChannelRouter: 群聊 require_mention 且未@机器人，忽略")
                return None

        agent = lookup(agent_id)
        if agent is None:
            logger.warning("ChannelRouter: agent『%s』不存在，%s 消息未处理", agent_id, message.channel_type)
            return None
        session_id = manager.resolve_session_scope_id(message)
        # Wave H-W0 修复：owner_user_id 在 agent.config 上——原读
        # getattr(agent, "owner_user_id") 恒 None，渠道会话归属链自
        # 2026-09 断链设计起从未生效（save_to_session 落"共享可见"）。
        # §6-163 之后它**只**用作会话属主（显式元数据），不再进身份通道。
        owner = str(getattr(getattr(agent, "config", None), "owner_user_id", "") or "") or None
        meta: Dict[str, Any] = {
            # 渠道侧真实身份（open_id/群）记入 metadata 供来源展示/@；会话属主另设
            "channel_user_id": message.sender_id or f"channel_{message.channel_type}",
            "channel_name": message.sender_name or message.sender_id or "",
            "chat_id": message.chat_id,
            "chat_type": message.chat_type,
            "role": "user",
            "source_channel": message.channel_type,
            "channel": message.channel_type,
        }
        # 语音回合的元数据交接：预检在 `transcribe_voice_message` 成功那一刻写下 ASR 真产物，
        # 这里交给回合 metadata；下游 `chat_pipeline` 按同名键读走，喂给上下文组装的唯一实现。
        # 不在这一步接，读侧就永远等不到（此前"语音上下文进 prompt"只对评测路生效）。
        voiceContext = (message.metadata or {}).get(VOICE_CONTEXT_KEY)
        if voiceContext:
            meta[VOICE_CONTEXT_KEY] = voiceContext
        # §6-127 裁定 ①/③：渠道发送者"这一轮是谁"由绑定表解析（agent 级作用域），未绑定
        # 退到渠道专属命名空间 `ch:{渠道}:{发送者}`——不再落 default 共享桶（那正是 §6-123 的
        # 成因）。`user_id` 在这里**只产生一次**，下游 `chat_pipeline._init_agent_state` 照旧读
        # metadata；解析单点若多出一处，两条通道就会给同一个人算出两个身份。
        from neurova.channels.user_identity import UserIdentityManager

        turnIdentity = UserIdentityManager().resolveTurnIdentity(
            agent_id, message.channel_type, str(meta["channel_user_id"]))
        meta["user_id"] = turnIdentity["user_id"]
        meta["identity_bound"] = turnIdentity["bound"]
        # 记忆三层隔离键是 (neuser_id, user_id) 一对（`api/deps.py:118-125` 从 JWT 成对取）；
        # 只带一个键名过去会复现不出控制台写入的那把键，等于同一个人两份记忆。
        meta["memory_scope"] = {"neuser_id": turnIdentity["neuser_id"],
                                "user_id": turnIdentity["user_id"]}
        # 会话记录的可见性归 agent 属主（Issue #290 Wave H-W0）。§6-163 把身份合并成一条
        # "谁在说话"之后，属主**不再靠环境里那条通道捎带**——它是一条显式元数据，
        # 由 `post_chat_pipeline` 交给 `save_to_session(session_owner=…)`。
        meta["session_owner_id"] = owner or ""
        # 观察面（工单批 6）：每条入站都记下"这个 agent 的这条渠道里见过这个发送者"。
        # 控制台的绑定面板只能靠这一面列人——人抄不到自己的 `ou_xxx`/`tg_xxx`，
        # 而发码之前他得先知道"我在飞书里那个身份"是哪一格。写侧就在这一行，读侧是
        # `GET /channel-configs/identity/observed`。
        UserIdentityManager().observeSender(
            agent_id, message.channel_type, str(meta["channel_user_id"]),
            str(meta.get("channel_name") or "") or None)
        # 可信轮次来源（任务2 actionability 门控地基）：默认 human——人类/未标注一律
        # 按人类对待，门控永不抑制；仅当渠道侧显式标注发送者是 bot/对端 agent 才 bot_peer。
        sender_is_bot = _detect_sender_is_bot(message)
        meta["turn_origin"] = "bot_peer" if sender_is_bot else "human"

        # 群领导选举（spec 2026-09-19）：多我方 agent 同群仅 leader 应答，防重答/回声。
        # 默认关、仅群聊生效、fail-open（仲裁异常/缺 chat_id 一律放行，绝不吞人类）。
        gl_enabled, gl_ttl = get_group_leadership_config()
        if gl_enabled and message.chat_type == "group" and message.chat_id:
            try:
                granted = get_group_leadership_arbiter().may_respond(
                    (message.channel_type, message.chat_id), agent_id, ttl=gl_ttl
                )
            except Exception:  # noqa: BLE001 - 仲裁故障不阻断应答（安全侧放行）
                logger.debug("群领导选举异常，放行", exc_info=True)
                granted = True
            meta["leadership"] = {"granted": granted}
            if not granted:
                logger.info(
                    "ChannelRouter: 群领导选举非 leader，静默 agent=%s group=%s",
                    agent_id, message.chat_id,
                )
                return None
        # 可读会话标题（仅首轮建记录时生效）：渠道·发送者/群，替代恒"新对话"，
        # 控制台列表一眼区分是哪个渠道哪个会话。
        who = meta["channel_name"] or (message.chat_id[:8] if message.chat_id else "")
        if who:
            prefix = "群" if message.chat_type == "group" else ""
            meta["session_title"] = f"{message.channel_type}{prefix}·{who}"
        # 会话归属：把请求级身份设为 agent 所有者（owner_user_id），使渠道对话落盘的
        # session 归该管理员、在其控制台正常可见可续聊（外部发送者身份留在 metadata）。
        # 请求上下文为空时 save_to_session 会落"共享可见"，故必须显式设定。
        from neurova.core.identity_context import clear_request_user_id, set_request_user_id
        # Wave H-W0 修复：owner_user_id 在 agent.config 上——原读
        # getattr(agent, "owner_user_id") 恒 None，渠道会话归属链自
        # 2026-09 断链设计起从未生效（save_to_session 落"共享可见"）。
        owner = str(getattr(getattr(agent, "config", None), "owner_user_id", "") or "") or None
        # P2-8 §6-46：渠道回合与网页面共用同一份模型额度，也就必须问同一道闸、
        # 落同一本账。台账/闸口/续跑身份的执行体只有 `core/agent_run_ledger` 一处实现。
        # 会话属主＝agent 属主（渠道会话本就落在他名下，`session_title` 上方已设），
        # 所以挂起回执里"去网页控制台点续跑"是真能做到的。
        # 绑定码就在这条消息里消费掉：它不该进模型额度、不该落运行台账、也不该被当成
        # 一轮对话写进记忆——它唯一的效果是改写绑定表（下一轮起身份就变了）。
        from neurova.channels.identity_binding import consumeBindingCode, parseBindCommand

        submittedCode = parseBindCommand(content)
        if submittedCode:
            outcome = consumeBindingCode(
                agent_id, message.channel_type, str(meta["channel_user_id"]), submittedCode)
            if outcome["ok"]:
                return (
                    "已绑定：这个渠道身份今后按你的平台账号隔离记忆与技能库。"
                    f"（账号 {outcome['user_id']}）"
                )
            reasons = {
                "no_pending_code": "这里没有待确认的绑定码——请先在网页控制台的「渠道身份绑定」里生成。",
                "code_invalid_or_expired": "绑定码不对或已过期，请重新生成一张。",
                "code_without_account": "这张码没有记下要绑定的账号，请重新生成。",
            }
            return reasons.get(outcome["reason"], "绑定失败，请重试。")

        ledger = AgentRunLedger(session_id, owner or "", agent_id, content)
        try:
            # 唯一那条身份通道装的是**发送者**（§6-163 裁定甲）：配额、usage、
            # 浏览器 profile 池、工具三层隔离都按"谁在说话"计。会话记录的可见性
            # 不走这条通道，走上面的 `meta["session_owner_id"]`——原先"一条装属主、
            # 一条装发送者"的那处声明式分叉（§6-127 裁定 ④）就此收口成一处显式传参。
            set_request_user_id(turnIdentity["user_id"])
            memoryManager = getattr(agent, "memory_manager", None)
            if memoryManager is not None and hasattr(memoryManager, "set_request_scope"):
                memoryManager.set_request_scope(
                    neuser_id=turnIdentity["neuser_id"], user_id=turnIdentity["user_id"])
            preflight = await ledger.acquire()
            if ledger.rejected:
                # 排队期被 /chat/stop 取消，或排队超时：如实回一句，不静默吞掉
                notice = next(
                    (str(e.get("message") or "") for e in preflight if e.get("type") == "error"),
                    "该回合在排队期间被取消",
                )
                return [notice]

            admission = await requestTurnAdmission(
                ledger=ledger,
                agentId=agent_id,
                modelName="",  # 渠道不指定模型：未归因回合仍受并发/间距/限流各层约束
                sessionId=session_id,
                userInput=content,
                payload={
                    "entry": ENTRY_CHANNEL,
                    "message": content,
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "model": None,
                    "stream": False,
                },
            )
            if not admission.allowed:
                if admission.ledgerFailed:
                    # 没落库的"挂起"没人能续——按假状态处理比按成功处理更安全，但必须点名
                    return [
                        f"本轮未能执行（让位原因 {admission.parkReason or 'unspecified'}），"
                        "且挂起未能落库，请重发"
                    ]
                return [parkReceiptText(admission, resumableWhere="请在网页控制台该会话里点「续跑」")]

            try:
                resp = await agent.chat(user_input=content, session_id=session_id, metadata=meta)
            except Exception:
                logger.exception("ChannelRouter: agent.chat 失败（channel=%s agent=%s）", message.channel_type, agent_id)
                ledger.settleResult({"error": "chat_error"})
                await _reportAdmission(admission)
                return None
            ledger.settleResult(resp if isinstance(resp, dict) else {})
            await _reportAdmission(admission)
        finally:
            clear_request_user_id()
        if isinstance(resp, dict):
            text = resp.get("text") or ""
        else:
            text = str(resp or "")
        text = text.strip()

        # 2026-09-14 需求：思考/工具/正文拆成独立消息条（此前全拼一条大消息，
        # 思考过程混在正文里）。顺序：思考 → 工具摘要 → 正文。
        parts: list = []
        # show_thinking 传导：本轮思考过程（agent.current_reasoning，ContextVar）
        # 单独一条——此前渠道从不转发思考，飞书"没收到思考过程"即此断链。
        if _flag(cfg.get("show_thinking"), default=True):
            reasoning = ""
            try:
                reasoning = (getattr(agent, "current_reasoning", None) or "").strip()
            except Exception:
                reasoning = ""
            if reasoning:
                parts.append(f"💭 思考过程：\n{reasoning}")
        # show_tool_messages 传导：本轮工具调用单条摘要（只列调用，不刷结果 JSON）。
        if _flag(cfg.get("show_tool_messages")):
            try:
                snap = agent.get_tool_messages_snapshot() if hasattr(agent, "get_tool_messages_snapshot") else []
            except Exception:
                snap = []
            call_records = [r for r in (snap or []) if isinstance(r, dict) and r.get("type") == "tool_call"]
            if call_records:
                lines = []
                for r in call_records:
                    name = str(r.get("tool_name") or r.get("name") or "工具")
                    label = str(r.get("task_name") or "").strip()
                    if not label:
                        for v in (r.get("params") or {}).values():
                            label = str(v).strip()[:40]
                            break
                    lines.append(f"• {name}（{label}）" if label else f"• {name}")
                parts.append("🔧 本轮工具调用：\n" + "\n".join(lines))
        if text:
            parts.append(text)
        # 语音出站（§6-168 缺口②）：回合的 TTS 产物此前在这里被整份丢掉——
        # `post_chat_pipeline._step_generate_tts` 已把音频落盘、`chat_pipeline` 已把它
        # 放进 `resp["audio_path"]`，而这里只取 `resp["text"]`。带出去即可，
        # "这个渠道收不收音频"由 manager 按适配器能力判（那里才有名可点）。
        audioCandidate = turnAudioCandidate(resp.get("audio_path") if isinstance(resp, dict) else None, paired_text=text)
        if audioCandidate is not None:
            parts.append(audioCandidate)
        return parts or None

    return _handler


def install_channel_router(manager, agent_lookup: Optional[Callable[[str], Any]] = None) -> None:
    """在 ChannelManager 上注册统一路由处理器（幂等）。priority=50 低于审批类临时
    处理器（priority=10），保证审批回复先被专用 handler 拦截。"""
    if getattr(manager, "_channel_router_installed", False):
        return
    manager.add_message_handler(make_handler(manager, agent_lookup), priority=50)
    manager._channel_router_installed = True
    logger.info("ChannelRouter 已注册（渠道入站统一路由到 agent）")
