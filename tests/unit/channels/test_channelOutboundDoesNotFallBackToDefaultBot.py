# -*- coding: utf-8 -*-
"""出站的 default 视角收口：点名叫哪一只，就不许由另一只 bot 把这条消息发出去（§6-195 批 31）。

两条面都在同一个默认视图上（§6-190 收的是健康视图，本档收发送与广播）：

1. **`manager.send_message` 无条件回落**。`agent_id = kwargs.pop("agent_id", "default")` 之后是
   `_agent_adapters.get((agent_id, t)) or self._adapters.get(t)`——**点名的那一只取不到时，
   它照用 default 那只**。今天真能点到这条路：§6-190 给 `/send` 加了 `agent_id` Query（缺省 default、
   向后兼容），于是 `POST /feishu/send?agent_id=kai` 在 kai 名下没配飞书时，**由 default 的 bot
   发出这条消息**，回执还写着 `success: true`。同一族里更拧巴的是 `_sendVoiceReply`：
   探能力用 `get_adapter(t, agent_id)`（严格，取不到就 VOICE_OUT_NONE），真发送走 `send_message`
   （回落）——**一轮之内两份视图**，文本回了、语音没了，日志看不出是两只 bot。
2. **`broadcast_message` 只遍历 `self._adapters`**（default 兼容视图）。唯一生产调用者是工作流审批
   通知（`collaboration/neurflow/builtin.py:2135`）⇒ 审批只发给 default 名下那几只渠道，
   挂在别的 agent 名下的渠道**收不到审批，工作流卡在 pending 等人**。

**哪些调用者真依赖兜底（现量三条，别一刀切）**：`_sendReplyItems`/`_sendVoiceReply`/错误回发
都经 `_reply_kwargs` 交 `metadata["agent_id"]`，那个值是投递这条消息的那只适配器注册时的 agent
（§6-189/§6-193 之后闭包与实例同源）⇒ **点名必命中，回落在这条路上根本不该被走到**；
`neurflow` 那处 `send_message(channel_type=..., chat_id=..., content=...)` **不带 agent_id**，
它要的正是"default 有什么发什么"⇒ 未点名那一态必须原样保留，否则审批通知从"发错 bot"变成"发不出去"。

裁定（写成判据前的口径）：**未点名＝视同 default（含 legacy 兼容视图）；点名＝严格按那一只，
取不到就 `return None` 并在日志里点名是哪个 agent——不回落，回落就是用别人的 bot 说话。**
广播改遍历全量实例表，键沿用 `_adapterViewKey` 单源（default 仍是裸键 ⇒ 现有 caller
`list(results.values())[0]` 与 mock 测试的 `{"feishu": ...}` 形状都不破）。

"""

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
MANAGER_PY = REPO / "neurova" / "channels" / "manager.py"
MANAGER_SRC = MANAGER_PY.read_text(encoding="utf-8")


def _calleesInside(src: str, funcName: str) -> set:
    """某个函数体里被调用的名字集合（按形状数，不按注释里的名字）。"""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == funcName:
            out = set()
            for call in ast.walk(node):
                if isinstance(call, ast.Call):
                    f = call.func
                    out.add(f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else ""))
            return out
    raise AssertionError(f"没有那个函数：{funcName}")


def _viewKeyForgers(src: str) -> list:
    """除 `_adapterViewKey` 之外，还有哪个函数在就地拼"实例视图键"那一形。

    谓词按**两个插值的名字**收口：只认"agent 那半 + channel/type 那半"这种配对
    （`f"{agent_id}:{channel_type}"`）。会话作用域键 `f"{agent}:{message.chat_id}"`
    （`resolve_session_scope_id` 里那条，2026-09-13 裁定的 `{agent_id}:{chat_id}` 口径）
    **同形不同域**，不在这条守卫的范围里——两份口径各自演进，硬并成一份就是制造耦合。
    """
    tree = ast.parse(src)
    owners = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                if isinstance(inner, ast.JoinedStr):
                    owners[id(inner)] = node.name
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr) or owners.get(id(node)) == "_adapterViewKey":
            continue
        vals = node.values
        for i in range(1, len(vals) - 1):
            if not (isinstance(vals[i], ast.Constant) and vals[i].value == ":"
                    and isinstance(vals[i - 1], ast.FormattedValue)
                    and isinstance(vals[i + 1], ast.FormattedValue)):
                continue
            left = ast.unparse(vals[i - 1].value).lower()
            right = ast.unparse(vals[i + 1].value).lower()
            if "agent" in left and ("channel" in right or "type" in right):
                out.append(owners.get(id(node), "<module>"))
                break
    return sorted(set(out))


@pytest.fixture()
def twoBots():
    """default 与 kai 各一只飞书实例，`send_message` 换成记录器、会话回写桩掉——不再往下走。"""
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    from neurova.channels.base import ChannelConfig
    from neurova.channels.feishu import FeishuAdapter
    from neurova.channels.manager import ChannelManager, get_channel_manager

    isolatedDataRoot()
    ChannelManager._instance = None
    mgr = get_channel_manager()
    mgr.ingress_queue = False   # 入站持久队列不是本批主张，走直发路径
    sent = {}

    def _make(agentId):
        adapter = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id=f"cli_{agentId}",
                                              app_secret="sec", use_stream=False))
        adapter._connected = True

        async def _send(chat_id, content, message_type="text", **kwargs):
            sent.setdefault(agentId, []).append((chat_id, content, message_type))
            return f"msg_{agentId}"

        adapter.send_message = _send
        return adapter

    for agentId in ("default", "kai"):
        mgr.register_adapter(_make(agentId), agent_id=agentId)

    async def _noSessionSync(*args, **kwargs):
        return None

    mgr._sync_reply_to_session = _noSessionSync   # 会话回写不是本批主张
    try:
        yield mgr, sent
    finally:
        for agentId in ("default", "kai"):
            mgr.unregister_adapter("feishu", agent_id=agentId)
        ChannelManager._instance = None


class TestNamedAgentIsNotAnsweredByAnotherBot:
    def testNamedMissingAgentTouchesNoBot(self, twoBots):
        """点名叫 kai 之外的 ghost ⇒ 一只都不许动、返回 None（今天由 default 那只发出去）。"""
        import asyncio

        mgr, sent = twoBots
        mid = asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_1",
                                           content="发给 ghost 名下的那条", agent_id="ghost"))

        assert mid is None, f"ghost 名下没有渠道，却拿到了消息 ID：{mid!r}"
        assert "default" not in sent, (
            f"点名叫 ghost，实际是 default 那只 bot 发出去的（sent={ {k: len(v) for k, v in sent.items()} }）")
        assert "kai" not in sent, f"却发给了另一只 agent 的实例：{sorted(sent)}"

    def testFailureNamesTheAgentItCouldNotFind(self, twoBots):
        """诚实形态：失败必须点名"哪个 agent 的哪条渠道没有"，不许留一句 No adapter for channel。"""
        import asyncio

        from neurova.channels import manager as managerModule

        mgr, _sent = twoBots
        logs = []
        original = managerModule.logger.error

        def _capture(fmt, *args, **kwargs):
            logs.append(str(fmt) % args if args else str(fmt))
            return original(fmt, *args, **kwargs)

        managerModule.logger.error = _capture
        try:
            asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_1",
                                         content="x", agent_id="ghost"))
        finally:
            managerModule.logger.error = original

        assert any("ghost" in l and "feishu" in l for l in logs), (
            f"没有一条日志点出是哪个 agent 落空（实得 {logs}）")

    def testNamedOwnerStillSendsThroughThatBot(self, twoBots):
        """对照（不许顺手改坏）：点名 kai ⇒ 只动 kai 那只。"""
        import asyncio

        mgr, sent = twoBots
        mid = asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_9",
                                           content="kai 的话", agent_id="kai"))

        assert mid == "msg_kai" and sorted(sent) == ["kai"], f"实得 {mid!r} / { {k: len(v) for k, v in sent.items()} }"

    def testUnnamedKeepsTheDefaultCompatView(self, twoBots):
        """未点名＝今天那一态：`neurflow` 审批通知不带 agent_id，它要的就是 default 有什么发什么。"""
        import asyncio

        mgr, sent = twoBots
        mid = asyncio.run(mgr.send_message(channel_type="feishu", chat_id="oc_2",
                                           content="审批请回复"))

        assert mid == "msg_default" and sorted(sent) == ["default"], (
            f"未点名的旧语义被改了：{mid!r} / {sorted(sent)}")

    def testNamedDefaultAcceptsLegacyOnlyRegistration(self, twoBots):
        """点名 default ⇒ 允许命中 legacy `_adapters` 那一格（向后兼容不许破）。"""
        import asyncio

        from neurova.channels.base import ChannelConfig
        from neurova.channels.feishu import FeishuAdapter

        mgr, _sent = twoBots
        legacy = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="legacy",
                                             app_secret="y", use_stream=False))
        legacy._connected = True
        hits = []

        async def _stubSend(chat_id, content, message_type="text", **kwargs):
            hits.append(chat_id)
            return "msg_legacy"

        legacy.send_message = _stubSend
        mgr._adapters["dingtalk"] = legacy          # 只进兼容视图，没有复合键
        mid = asyncio.run(mgr.send_message(channel_type="dingtalk", chat_id="c",
                                           content="旧登记面", agent_id="default"))
        mgr._adapters.pop("dingtalk", None)

        assert mid == "msg_legacy" and hits == ["c"], (
            f"点名 default 却打不到只在兼容视图里的那一只：{mid!r} / {hits}")

    def testReplyPathAlwaysNamesTheBotThatReceivedIt(self, twoBots):
        """收紧的安全凭据：回发那条路上的 agent_id 由投递闭包盖章，**点名必命中**。

        这一格不是装饰——它证明"点名为 ghost ⇒ None"的语义改动打不到回发路：入站消息是谁那只
        适配器送进来的，`metadata["agent_id"]` 就是谁，回发也就只能走它。
        """
        import asyncio

        mgr, sent = twoBots
        from neurova.channels.base import ChannelEventType, ChannelMessage

        kai = mgr.get_adapter("feishu", agent_id="kai")
        incoming = ChannelMessage(channel_type="feishu", message_id="om_2", sender_id="ou_2",
                                 sender_name="ou_2", content="问一句", chat_id="oc_2")
        asyncio.run(kai._event_callback(ChannelEventType.MESSAGE_RECEIVED, incoming))
        assert incoming.metadata.get("agent_id") == "kai", (
            f"闭包没盖上归属（实得 {incoming.metadata}）——那下面那条断言就没意义")
        asyncio.run(mgr._sendReplyItems(incoming, "回你一句"))

        assert sent.get("kai") == [("oc_2", "回你一句", "text")], (
            f"回发没走 kai 那只（实得 {sorted(sent)}）")
        assert "default" not in sent, f"回发串到 default 那只 bot 了：{sorted(sent)}"


class TestBroadcastSweepsEveryAgentInstance:
    def testBroadcastReachesNonDefaultInstance(self, twoBots):
        """审批通知今天只发给 default 名下那几只：非 default 的渠道收不到，工作流卡在 pending。"""
        import asyncio

        mgr, sent = twoBots
        results = asyncio.run(mgr.broadcast_message(content="审批请回复", message_type="text"))

        assert "kai" in sent, (
            f"kai 名下那只实例没收到广播（键集={sorted(results)}，被叫到的是 {sorted(sent)}）")
        assert len(sent.get("default", [])) == 1, "default 那只好不容易只被叫一次"

    def testBroadcastKeysStayBackwardCompatible(self, twoBots):
        """键沿用单源约定：default 仍是裸键 ⇒ 现有 caller `list(results.values())[0]` 与 mock 不破。"""
        import asyncio

        mgr, _sent = twoBots
        results = asyncio.run(mgr.broadcast_message(content="审批请回复"))

        assert "feishu" in results, f"default 的裸键丢了（实得键集 {sorted(results)}）"
        assert "kai:feishu" in results, f"非 default 那格没进结果（实得键集 {sorted(results)}）"
        assert list(results.values())[0] is not None, "caller 取第一条读数变成了 None"

    def testBroadcastUsesTheOneViewKey(self):
        """键约定只许一份：`_adapterViewKey` 定义唯一，且四份对外视图都用它。"""
        defs = [n for n in ast.walk(ast.parse(MANAGER_SRC))
                if isinstance(n, ast.FunctionDef) and n.name == "_adapterViewKey"]
        assert len(defs) == 1, f"`_adapterViewKey` 定义了 {len(defs)} 次"
        for func in ("list_adapters", "health_check", "broadcast_message", "conflict_check"):
            assert "_adapterViewKey" in _calleesInside(MANAGER_SRC, func), (
                f"{func} 没共用那份键约定——加维度时必然漏改一处")

    def testNoSecondInlineViewKey(self):
        """视图键的写法只许一份（教义第 6）：`_adapterViewKey` 之外不许再拼一遍。"""
        forgers = _viewKeyForgers(MANAGER_SRC)
        assert forgers == [], f"这些函数又各拼了一遍实例视图键：{forgers}"

    def testViewKeyDetectorHasTeeth(self):
        """两向都测：同域的再拼一遍要抓到；**同形不同域**的会话作用域键不许抓。"""
        sameDomain = chr(10).join([
            "def _adapterViewKey(agentId, channelType):",
            "    return channelType if agentId == 'default' else f\"{agentId}:{channelType}\"",
            "",
            "def otherFace(agent_id, channel_type):",
            "    return [f\"{agent_id}:{channel_type}\"]",
        ])
        otherDomain = chr(10).join([
            "def resolve_session_scope_id(message, agent):",
            "    return message.chat_id if agent == 'default' else f\"{agent}:{message.chat_id}\"",
        ])
        assert _viewKeyForgers(sameDomain) == ["otherFace"], "同域再拼一遍却没抓到＝没有牙"
        assert _viewKeyForgers(otherDomain) == [], (
            "把会话作用域键（同形不同域、2026-09-13 另一次裁定）也报成违约＝口径过宽")
