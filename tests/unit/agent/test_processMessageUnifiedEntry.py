# -*- coding: utf-8 -*-
"""`Agent.process_message` 这条"统一入口"必须真的能走通（台账 §6-98 / D1 推荐档 (b)）。

断链原委：`agent_core.py:1688` 调 `self._router.create_message(...)`，而 `MessageRouter`
没有这个方法——它随异步化重构一并移除（`tests/unit/core/test_router.py:5-7` 明写"已移除"，
测试自己改用 `Message(content=...)` 直构）。活体复现：
`AttributeError: 'MessageRouter' object has no attribute 'create_message'`。
全仓唯一消费者是 `evolution/eval/ab_library.py:134`（其调用方只有测试替身），所以线上没症状；
而 `agent_core.py:7` 的模块 docstring 至今宣称"提供 process_message 统一入口"。

修法取 (b)：入口**自己构造 `Message`**。(a) 复活 `create_message` 等于给"怎么造一条消息"
再造第二处定义（顶教义第 6 条），(c) 退役入口则要承认对外承诺从未成立——涉对外语义，
另案裁。本文件第 ④ 格把 (a) 这条路钉死：Router 上不得再长出消息工厂。
"""

import asyncio
from types import SimpleNamespace

from neurova.agent_core import Agent
from neurova.router import Message, MessageRouter, RouteResult


class _ChatAgentStub:
    """被路由到的下游 agent（`_route_chat` 调 `agent.chat`，返回 dict）。"""

    def __init__(self):
        self.seen = []

    async def chat(self, content, **kwargs):
        self.seen.append({"content": content, **kwargs})
        return {"text": "pong"}


class _EntryHost:
    """只借出真实 `Agent.process_message` 本体的最小宿主（不构造整个 Agent）。"""

    def __init__(self, router):
        self._router = router
        self._skill_registry = None
        self.config = SimpleNamespace(name="probe-agent")

    def init_router(self):  # pragma: no cover - _router 已备好，不该被调用
        raise AssertionError("不该走自动装配支路：_router 已注入")


def _host(router):
    return _EntryHost(router), Agent.process_message


def test_processMessageRoutesAnOrdinaryTurn():
    """① 一条普通文本消息必须真的经 Router 走到 agent.chat()。"""
    downstream = _ChatAgentStub()
    router = MessageRouter(agent=downstream, skill_registry=None, memory_manager=None)
    host, process_message = _host(router)

    result = asyncio.run(process_message(host, "你好", sender="alice"))

    assert isinstance(result, RouteResult), type(result)
    assert result.success is True, result
    assert result.response == "pong", result
    assert downstream.seen and downstream.seen[0]["content"] == "你好", downstream.seen
    assert result.message_type is not None and result.message_type.value == "chat", result


def test_processMessageCarriesSenderIntoTheMessage():
    """② `sender` 必须落到 `Message.sender_id`——它是这条入口唯一的身份载体。"""
    caught = {}

    async def probeHandler(message, args):
        caught["sender_id"] = message.sender_id
        caught["content"] = message.content
        return RouteResult(success=True, response="ok", handler="command",
                           message_type=message.message_type)

    router = MessageRouter(agent=None, skill_registry=None, memory_manager=None)
    router.register_command_handler("probe", probeHandler)
    host, process_message = _host(router)

    asyncio.run(process_message(host, "/probe 一下", sender="alice"))

    assert caught.get("sender_id") == "alice", caught
    assert caught.get("content") == "/probe 一下", caught


def test_handlersStillGetTheThreeWiredReferences():
    """③ 命令处理器依赖的 agent/router/skill_registry 三项引用不得因修入口而丢失。"""
    seen = {}

    async def probeHandler(message, args):
        seen.update(message.metadata)
        return RouteResult(success=True, response="ok", handler="command",
                           message_type=message.message_type)

    router = MessageRouter(agent=None, skill_registry=None, memory_manager=None)
    router.register_command_handler("probe", probeHandler)
    host, process_message = _host(router)

    asyncio.run(process_message(host, "/probe", sender="alice"))

    assert seen.get("agent") is host, seen.keys()
    assert seen.get("router") is router, seen.keys()
    assert "skill_registry" in seen, seen.keys()


def test_entryGoesThroughTheRouterRatherThanChatDirectly():
    """⑤ "所有消息经过 Router 路由"这半句也得可证伪：入口不得抄近路直调 `agent.chat`。

    两半各钉一处：`_router` 换成没有下游 agent 的真 Router ⇒ 只能由 Router 自己回
    "Agent 未初始化"（证明确实进了 `route()`）；宿主上任何直连 `chat` 的调用都当场炸。
    """
    def _boom(*args, **kwargs):
        raise AssertionError("入口绕过了 Router，直接调了 chat")

    router = MessageRouter(agent=None, skill_registry=None, memory_manager=None)
    host, process_message = _host(router)
    host.chat = _boom  # type: ignore[attr-defined]

    result = asyncio.run(process_message(host, "你好", sender="alice"))

    assert result.success is False and "Agent 未初始化" in result.response, result


def test_routerMustNotGrowAMessageFactoryAgain():
    """④ 反向守卫：消息构造只有一处——`Message` dataclass 本身。

    复活 `MessageRouter.create_message` 能让本文件全绿，但"怎么造一条消息"就有了第二份
    定义（入口与 Router 各一份），下一处调用点选哪份全凭手感——那正是本格要拦的形态。
    """
    assert not hasattr(MessageRouter, "create_message"), (
        "MessageRouter 上又长出了 create_message：请改回由调用方直接构造 Message"
        "（见 tests/unit/core/test_router.py 记录的移除原委）")
    assert Message(content="hi").sender_id == "" and Message(content="hi").metadata == {}
