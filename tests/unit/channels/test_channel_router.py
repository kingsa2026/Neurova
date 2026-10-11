# -*- coding: utf-8 -*-
"""ChannelRouter 契约测试——渠道入站消息统一路由到 agent 并回发。

补齐"下消息通路"缺失的环：此前 ChannelManager 无任何常驻处理器把入站消息交给
agent.chat()，飞书/钉钉/微信等消息进得来却无人接
process 注入 + resolve_session_id 模型）。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from neurova.channels.base import ChannelConfig, ChannelMessage
from neurova.channels import channel_router
from neurova.channels.manager import ChannelManager


class FakeAgent:
    def __init__(self, reply="pong", reasoning="", tools=None):
        self.reply = reply
        self.reasoning = reasoning
        self.tools = tools or []
        self.calls = []

    @property
    def current_reasoning(self):
        return self.reasoning

    def get_tool_messages_snapshot(self):
        return list(self.tools)

    async def chat(self, user_input, session_id=None, metadata=None, **kw):
        self.calls.append({"user_input": user_input, "session_id": session_id, "metadata": metadata})
        return {"text": self.reply}


class _CfgAdapter:
    """仅承载 config.extra 供 _channel_cfg 读取。"""
    def __init__(self, extra):
        self.config = SimpleNamespace(extra=extra)
        self.channel_type = "feishu"
        self.is_connected = True
        self.sent = []

    async def send_message(self, chat_id, content, message_type="text", **kw):
        self.sent.append(content)
        return "mid"


def _msg(content="嗨", channel_type="feishu", chat_id="oc_1", sender="ou_9", agent_id="default", chat_type="p2p"):
    return ChannelMessage(
        channel_type=channel_type, message_id="m1", sender_id=sender, sender_name=sender,
        content=content, chat_id=chat_id, chat_type=chat_type,
        metadata={"agent_id": agent_id},
    )


@pytest.fixture
def manager():
    ChannelManager._instance = None
    m = ChannelManager()
    yield m
    ChannelManager._instance = None


@pytest.mark.asyncio
async def test_handler_routes_to_agent_and_returns_reply(manager):
    agent = FakeAgent("你好，我是Neurova")
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    msg = _msg("嗨")
    reply = await handler(msg)
    assert reply == ["你好，我是Neurova"]
    assert agent.calls[0]["user_input"] == "嗨"
    # session 用 manager 的固定作用域键（agent+渠道+chat）
    assert agent.calls[0]["session_id"] == manager.resolve_session_scope_id(msg)
    md = agent.calls[0]["metadata"]
    assert md["channel_user_id"] == "ou_9"  # 渠道侧身份入 metadata（会话属主走 ContextVar）
    assert md["source_channel"] == "feishu"


@pytest.mark.asyncio
async def test_handler_empty_content_no_agent_call(manager):
    agent = FakeAgent()
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    assert await handler(_msg(content="   ")) is None
    assert agent.calls == []


@pytest.mark.asyncio
async def test_handler_agent_missing_returns_none(manager):
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: None)
    assert await handler(_msg()) is None


@pytest.mark.asyncio
async def test_handler_non_default_agent_id_lookup(manager):
    seen = {}
    def lookup(aid):
        seen["agent_id"] = aid
        return FakeAgent("ok")
    handler = channel_router.make_handler(manager, agent_lookup=lookup)
    await handler(_msg(agent_id="agent-77"))
    assert seen["agent_id"] == "agent-77"


def test_install_registers_handler_once(manager):
    channel_router.install_channel_router(manager, agent_lookup=lambda aid: FakeAgent())
    n1 = len(manager._message_handlers)
    channel_router.install_channel_router(manager, agent_lookup=lambda aid: FakeAgent())
    assert len(manager._message_handlers) == n1, "install 必须幂等，不重复注册"
    assert n1 == 1


@pytest.mark.asyncio
async def test_dispatch_sends_reply_back_to_channel(manager, monkeypatch):
    """端到端：_dispatch_message 经 router handler 得回复 → send_message 回发渠道。"""
    agent = FakeAgent("回复内容")
    channel_router.install_channel_router(manager, agent_lookup=lambda aid: agent)

    sent = {}
    class FakeAdapter:
        channel_type = "feishu"
        is_connected = True
        async def send_message(self, chat_id, content, message_type="text", **kw):
            sent["chat_id"] = chat_id
            sent["content"] = content
            return "mid"
    manager._adapters["feishu"] = FakeAdapter()

    await manager._dispatch_message(_msg("嗨"))
    assert sent.get("content") == "回复内容"
    assert sent.get("chat_id") == "oc_1"


# ------------------------------------------------------------------
# 公共参数传导（show_thinking / 访问控制 / require_mention）
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_show_thinking_sends_reasoning_as_separate_part(manager):
    """2026-09-14 需求：思考过程/正文分条消息，不再拼成一条大消息。"""
    agent = FakeAgent("答案", reasoning="先分析问题再回答")
    manager._adapters["feishu"] = _CfgAdapter({"show_thinking": True})
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    parts = await handler(_msg("你好"))
    assert parts == ["💭 思考过程：\n先分析问题再回答", "答案"]


@pytest.mark.asyncio
async def test_show_thinking_off_excludes_reasoning(manager):
    agent = FakeAgent("答案", reasoning="不该出现的思考")
    manager._adapters["feishu"] = _CfgAdapter({"show_thinking": False})
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    reply = await handler(_msg("你好"))
    assert reply == ["答案"]


@pytest.mark.asyncio
async def test_show_tool_messages_sends_tool_summary_part(manager):
    """show_tool_messages 开：工具调用单独一条摘要消息，夹在思考与正文之间。"""
    tools = [
        {"type": "tool_call", "tool_name": "web_search", "params": {"query": "AI新闻"}, "task_name": "搜中文AI新闻"},
        {"type": "tool_result", "tool_name": "web_search", "content": "{}", "success": True},
        {"type": "tool_call", "tool_name": "rss_read", "params": {"url": "https://x"}},
    ]
    agent = FakeAgent("答案", reasoning="思考", tools=tools)
    manager._adapters["feishu"] = _CfgAdapter({"show_thinking": True, "show_tool_messages": True})
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    parts = await handler(_msg("你好"))
    assert len(parts) == 3, "思考/工具/正文 三条"
    assert parts[0].startswith("💭")
    assert parts[1].startswith("🔧")
    assert "web_search" in parts[1] and "搜中文AI新闻" in parts[1]
    assert "rss_read" in parts[1]
    assert "tool_result" not in parts[1]  # 只列调用，不刷结果 JSON
    assert parts[2] == "答案"


@pytest.mark.asyncio
async def test_tool_messages_hidden_by_default(manager):
    """show_tool_messages 默认关：有工具记录也不发摘要条。"""
    tools = [{"type": "tool_call", "tool_name": "web_search", "params": {}}]
    agent = FakeAgent("答案", tools=tools)
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    parts = await handler(_msg("你好"))
    assert parts == ["答案"]


@pytest.mark.asyncio
async def test_dispatch_sends_each_part_in_order(manager):
    """manager._dispatch_message 支持 handler 返回多条：按序逐条回发。"""
    agent = FakeAgent("答案", reasoning="思考")
    adapter = _CfgAdapter({"show_thinking": True})
    manager._adapters["feishu"] = adapter
    channel_router.install_channel_router(manager, agent_lookup=lambda aid: agent)
    await manager._dispatch_message(_msg("你好"))
    assert adapter.sent == ["💭 思考过程：\n思考", "答案"]


@pytest.mark.asyncio
async def test_private_strategy_closed_skips(manager):
    agent = FakeAgent()
    manager._adapters["feishu"] = _CfgAdapter({"private_chat_strategy": "closed"})
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    assert await handler(_msg("你好", chat_type="p2p")) is None
    assert agent.calls == []


@pytest.mark.asyncio
async def test_group_require_mention_without_mention_skips(manager):
    agent = FakeAgent()
    manager._adapters["feishu"] = _CfgAdapter({"group_chat_strategy": "open", "require_mention": True})
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    assert await handler(_msg("随便聊天", chat_type="group")) is None
    # 带 @ 或 mentions 元数据则放行
    m = _msg("@机器人 你好", chat_type="group")
    assert await handler(m) == ["pong"]


@pytest.mark.asyncio
async def test_send_message_resolves_agent_instance_and_forwards_context(manager):
    """2.2：send_message 按 (agent_id,channel) 取实例，并把 at_user_id/chat_type 转发适配器。"""
    captured = {}

    class SpyAdapter:
        channel_type = "feishu"
        is_connected = True
        def set_event_callback(self, cb): pass
        async def send_message(self, chat_id, content, message_type="text", **kw):
            captured["chat_id"] = chat_id
            captured["at_user_id"] = kw.get("at_user_id")
            captured["chat_type"] = kw.get("chat_type")
            captured["has_agent_id"] = "agent_id" in kw  # agent_id 不应转发给适配器
            return "mid"

    agent_inst = SpyAdapter()
    manager._agent_adapters[("a7", "feishu")] = agent_inst
    manager._adapters["feishu"] = SpyAdapter()  # default 视图（不应被 a7 命中）

    mid = await manager.send_message("feishu", "oc_x", "回复", agent_id="a7",
                                     at_user_id="ou_9", chat_type="group")
    assert mid == "mid"
    assert captured["at_user_id"] == "ou_9" and captured["chat_type"] == "group"
    assert captured["has_agent_id"] is False, "agent_id 用于查实例，不应透传给适配器"


@pytest.mark.asyncio
async def test_dispatch_forwards_reply_kwargs(manager):
    """_dispatch_message 回发带 sender/chat_type/agent_id 上下文。"""
    seen = {}
    class SpyAdapter:
        channel_type = "feishu"
        is_connected = True
        async def send_message(self, chat_id, content, message_type="text", **kw):
            seen.update(kw); return "m"
    manager._adapters["feishu"] = SpyAdapter()
    agent = FakeAgent("回复")
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    manager.add_message_handler(handler, priority=50)
    await manager._dispatch_message(_msg("你好", chat_type="group", sender="ou_55"))
    assert seen.get("at_user_id") == "ou_55"
    assert seen.get("chat_type") == "group"
    assert "agent_id" not in seen, "agent_id 用于查实例，不透传适配器"


@pytest.mark.asyncio
async def test_session_owned_by_agent_owner_via_request_context(manager):
    """阶段4.1：agent.chat 期间请求上下文 user = agent 属主（会话归管理员）。

    Wave H-W0 修正：属主在 agent.config.owner_user_id（真实 Agent 形状）——
    原测试把 owner 挂在实例属性上，恰好镜像了 channel_router 的读错对象 bug
    （getattr(agent,"owner_user_id") 恒 None），生产链其实从未生效。
    """
    from types import SimpleNamespace

    from neurova.core.identity_context import get_request_user_id
    seen = {}

    class OwnerAgent(FakeAgent):
        def __init__(self):
            super().__init__()
            self.config = SimpleNamespace(owner_user_id="admin-77")

        async def chat(self, user_input, session_id=None, metadata=None, **kw):
            seen["req_user"] = get_request_user_id()
            return {"text": "ok"}

    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: OwnerAgent())
    await handler(_msg("嗨"))
    assert seen["req_user"] == "admin-77"
    # chat 结束后清除，不污染后续
    assert get_request_user_id() in (None, "")


class _ScopeSpy:
    """承载 memory_manager 的最小替身：只记录 set_request_scope 的成对入参。"""

    def __init__(self):
        self.scopes = []

    def set_request_scope(self, neuser_id=None, user_id=None):
        self.scopes.append((neuser_id, user_id))


def _bindManager(tmp_path):
    from neurova.channels.user_identity import UserIdentityManager

    UserIdentityManager.resetInstance()
    return UserIdentityManager(str(tmp_path / "bindings.db"))


@pytest.mark.asyncio
async def test_unboundSenderGetsChannelNamespaceNotDefault(manager, tmp_path):
    """§6-127 裁定 ①：未绑定的渠道发送者落 `ch:{渠道}:{发送者}`，不再进 default 共享桶。"""
    _bindManager(tmp_path)
    agent = FakeAgent("ok")
    agent.memory_manager = _ScopeSpy()
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    manager.add_message_handler(handler, priority=50)

    await manager._dispatch_message(_msg("你好", sender="ou_55"))

    meta = agent.calls[0]["metadata"]
    assert meta["user_id"] == "ch:feishu:ou_55", meta
    assert meta["identity_bound"] == "false", meta
    assert agent.memory_manager.scopes == [("ch:feishu:ou_55", "ch:feishu:ou_55")]


@pytest.mark.asyncio
async def test_boundSenderUsesPlatformAccountAndScopePair(manager, tmp_path):
    """已绑定 → 轮身份是平台账号，且记忆作用域成对下发（少一个键就复现不出控制台那把键）。"""
    mgr = _bindManager(tmp_path)
    mgr.bindIdentity("default", "feishu", "ou_55", "u-alice", neuserId="ne-u1",
                     boundBy="admin")
    agent = FakeAgent("ok")
    agent.memory_manager = _ScopeSpy()
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    manager.add_message_handler(handler, priority=50)

    await manager._dispatch_message(_msg("你好", sender="ou_55"))

    meta = agent.calls[0]["metadata"]
    assert meta["identity_bound"] == "true", meta
    assert meta["user_id"] == "u-alice", meta
    assert meta["channel_user_id"] == "ou_55", "渠道原身份仍要留着（来源展示/群内 @ 用它）"
    assert agent.memory_manager.scopes == [("ne-u1", "u-alice")]


@pytest.mark.asyncio
async def test_bindingIsScopedPerAgentOnTheChannelPath(manager, tmp_path):
    """裁定 ③＝agent 级：换 agent 不认这条绑定，各自算各自的身份。"""
    mgr = _bindManager(tmp_path)
    mgr.bindIdentity("a1", "feishu", "ou_55", "u-alice", neuserId="ne-u1")
    for agentId, expected in (("a1", "u-alice"), ("default", "ch:feishu:ou_55")):
        agent = FakeAgent("ok")
        agent.memory_manager = _ScopeSpy()
        handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
        manager._message_handlers = [h for h in manager._message_handlers
                                     if getattr(h, "__name__", "") != "<lambda>"]
        manager.add_message_handler(handler, priority=50)
        await manager._dispatch_message(_msg("你好", sender="ou_55", agent_id=agentId))
        assert agent.calls[0]["metadata"]["user_id"] == expected, (agentId, agent.calls)


# ── 批 4：渠道内自助绑定（工单 §6-127 裁定 ①②③）──
#
# 这四格守的是"绑定这条消息**只**改绑定表"：它不进模型额度、不落运行台账、不写记忆。
# 若哪天有人把拦截点挪到 ledger 之后，前两条立刻红。

@pytest.fixture
def codesInMemory(monkeypatch):
    from neurova.auth.verification_code import VerificationCodeModel

    model = VerificationCodeModel(":memory:")
    monkeypatch.setattr(
        "neurova.auth.verification_code.get_verification_code_model", lambda: model)
    return model


class _LedgerSpy:
    """记录 AgentRunLedger 被构造了几次——绑定消息应当一次都不构造（不占额度账）。"""

    def __init__(self):
        self.built = []

    def __call__(self, *args, **kwargs):
        self.built.append(args)
        raise AssertionError("绑定消息不该构造运行台账")


@pytest.mark.asyncio
async def test_bindCodeIsConsumedWithoutTouchingModelOrLedger(manager, tmp_path, codesInMemory,
                                                              monkeypatch):
    """"绑定 <码>" 就地消费：回一句确认，agent 一次都不被调用，台账一次都不构造。"""
    from neurova.channels.identity_binding import issueBindingCode

    _bindManager(tmp_path)
    code = issueBindingCode("default", "feishu", "u-alice", neuserId="ne-1")
    spy = _LedgerSpy()
    monkeypatch.setattr(channel_router, "AgentRunLedger", spy)

    agent = FakeAgent("pong")
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    reply = await handler(_msg(f"绑定 {code}", sender="ou_77"))

    assert reply and "已绑定" in str(reply), reply
    assert agent.calls == [], "绑定消息不该进模型（既花额度又写记忆）"
    assert spy.built == [], "绑定消息不该落运行台账"


@pytest.mark.asyncio
async def test_bindCodeFailureRepliesNamedReason(manager, tmp_path, codesInMemory):
    """没有待确认的码 ⇒ 回话点名原因并指路，而不是把这条消息当对话丢给模型糊过去。"""
    _bindManager(tmp_path)
    agent = FakeAgent("pong")
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)

    reply = await handler(_msg("绑定 123456", sender="ou_77"))

    assert reply and "网页控制台" in str(reply), reply
    assert agent.calls == []


@pytest.mark.asyncio
async def test_boundSenderNextTurnUsesPlatformAccount(manager, tmp_path, codesInMemory):
    """闭环：码绑上之后，同一发送者的**下一轮**身份就是平台账号（写→读→反馈）。"""
    from neurova.channels.identity_binding import issueBindingCode

    mgr = _bindManager(tmp_path)
    code = issueBindingCode("default", "feishu", "u-alice", neuserId="ne-1")
    agent = FakeAgent("pong")
    agent.memory_manager = _ScopeSpy()
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)

    await handler(_msg(f"绑定 {code}", sender="ou_77"))
    assert mgr.resolveTurnIdentity("default", "feishu", "ou_77")["bound"] == "true"

    await handler(_msg("刚才说的那些还记得吗", sender="ou_77"))

    meta = agent.calls[0]["metadata"]
    assert meta["user_id"] == "u-alice", meta
    assert agent.memory_manager.scopes == [("ne-1", "u-alice")]


@pytest.mark.asyncio
async def test_chatMentioningBindingStillGoesToAgent(manager, tmp_path, codesInMemory):
    """聊普通内容时提到"绑定"两个字，不得被当成指令吃掉。"""
    _bindManager(tmp_path)
    agent = FakeAgent("pong")
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)

    reply = await handler(_msg("帮我绑定一下账号，怎么弄", sender="ou_77"))

    assert len(agent.calls) == 1, agent.calls
    assert reply == ["pong"]


# ── 批 6：观察面写侧（"按渠道查人"的读数从这一行开始长）──

@pytest.mark.asyncio
async def testInboundMessageRegistersObservedSender(manager, tmp_path):
    """每条入站都登记发送者：面板要列"可绑的人"只有这一个来源（用户抄不到 open_id）。"""
    mgr = _bindManager(tmp_path)
    agent = FakeAgent("ok")
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)

    await handler(_msg("你好", sender="ou_77"))

    rows = mgr.listObservedSenders("default")
    assert [(r["channel_user_id"], r["display_name"]) for r in rows] == [("ou_77", "ou_77")]
    assert rows[0]["namespace"] == "ch:feishu:ou_77"
    assert rows[0]["bound_user_id"] is None, "登记不等于绑定"


@pytest.mark.asyncio
async def testBindCodeMessageStillRegistersSender(manager, tmp_path, codesInMemory):
    """消费绑定码那条消息也要登记——否则"绑上之后"的人反而从观察面消失。"""
    from neurova.channels.identity_binding import bindCommandText, issueBindingCode

    mgr = _bindManager(tmp_path)
    code = issueBindingCode("default", "feishu", "u-alice", neuserId="ne-1")
    agent = FakeAgent("ok")
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)

    await handler(_msg(bindCommandText(code), sender="ou_88"))

    row = next(r for r in mgr.listObservedSenders("default") if r["channel_user_id"] == "ou_88")
    assert row["bound_user_id"] == "u-alice"
