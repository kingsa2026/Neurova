# -*- coding: utf-8 -*-
"""入站投递的载荷必须付得起那道门的货币——MQTT/WebSocket 两支投错了对象（§6-193 批 30）。

**门的读法（先量门，不猜）**：`ChannelManager.register_adapter` 把适配器的事件回调装配成
`_make_event_callback(agent_id)` 的闭包，闭包第一行就读 `message.metadata`（`manager.py:138`），
`_on_channel_event` 第一行读 `message.channel_type` 与 `message.sender_name`（`manager.py:351`）。
这两处要的都是 `ChannelMessage` 的字段。

**两支违约者（都是现量，不是推测）**：`mqtt.py:272` 投的是 `_parse_mqtt_message` 造的
`UnifiedMessage`——它有 `channel`/`user_id`/`raw_message`，**没有** `channel_type`/`sender_name`，
而它的 `metadata` 是 `Optional[Dict]` 且构造时没给 ⇒ 恒 `None`。于是闭包第一行
`"agent_id" not in None` 抛 **TypeError**，被 `base._emit_event` 的 catch-all 记成一行
`logger.exception` 后**整条消息消失**。`websocket.py:268` 同形。

**这条今天跑得到吗**：`_create_adapter` 有 `elif channel_type == "mqtt"`（`channel_config.py:1082`），
`MQTTAdapter.connect()` 里 `self._client.on_message = self._on_message`（`mqtt.py:172`）⇒ 配了 mqtt
渠道的部署真会走到这条链（paho 未装时 `connect` 自己失败，与本批无关）。`WebSocketAdapter` 则
**全仓没有生产构造路**（`create_websocket_adapter` 零调用者）⇒ 那一支只钉形状，不声称端到端已通,
它的去留属 `UnifiedMessage`/Gen2 那族那次裁（本档末尾登记）。

判据四组，每组都成对：
① 真 `MQTTAdapter` + 真 `ChannelManager` 装配闭包 + 真 `_on_channel_event`，只在 handler 链那道门
   （`_dispatch_message`）截住——再往下要起 agent、花模型配额，不是本批主张。断"消息真到了门"
   与"到门的是齐字段的 ChannelMessage"两样。
② 反证：把旧形状（`UnifiedMessage`，`metadata=None`）真投进装配好的闭包 ⇒ 必须当场抛 TypeError
   且点名 `NoneType`；补一个 `metadata` 为 dict 的 ⇒ 必须抛 AttributeError 且缺的是 `channel_type`。
   这一格证明红的根因是**门的读法**，不是我的桩太瘦。
③ 全仓按形状数投递点（不只审"已登记的"两支——本仓记过：手抄清单漏项恒绿零红）：`_emit_event` 的
   载荷必须出自 `_make_message`/`ChannelMessage` 或带 `ChannelMessage` 注解的形参；配牙齿样本
   （合成一份投 `UnifiedMessage` 的源码必须被点名、合法样本不误报、换个函数名混过去也要点名）。
④ 两支的 `parse_raw_message` 只是转交解析器 ⇒ 返回注解必须与真产物同形（它零调用者，本批不裁
   `UnifiedMessage`/Gen2 整族，但不许留一句假的契约文本）。
"""

import ast
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests import ast_scan  # noqa: E402

SCOPED = [REPO / "neurova" / "channels"]


def _scanFiles():
    files = []
    for base in SCOPED:
        files.extend(ast_scan.filesUnder(base))
    files.append(REPO / "neurova" / "api" / "endpoints" / "channels.py")
    return sorted(set(files))


def _trees(*pairs):
    """把 `(名字, 源码字面量)` 变成 `(名字, 语法树)`——自证格仍按源码写，读得懂。"""
    return [(name, ast.parse(src)) for name, src in pairs]


def _scanTrees():
    """`[(相对路径, 语法树)]`——解析走 `ast_scan.transientTree`（一次性入口，不留常驻树）。

    原来这里是「共享枚举 + 各消费方自付 `ast.parse`」：门禁点名的免检通道形状。
    """
    out = []
    for path in _scanFiles():
        try:
            out.append((ast_scan.relativeToRepo(path), ast_scan.transientTree(path)))
        except SyntaxError:
            continue
    return out


def _emitOffenders(sources) -> list:
    """按形状找出「`_emit_event` 的载荷付不起门」的落点：`[(文件, 行号, 载荷写法)]`。

    合法写法只有三种：① 载荷表达式本身是 `_make_message(...)` / `ChannelMessage(...)` 构造；
    ② 是同文件里由这两种构造、或由"**函数体里 return 的就是这两种构造**"的那个函数赋值来的名字
    （`websocket._receive_loop` 走这条——它交的是 `_parse_websocket_message` 的产物，而那个函数
    现在造的正是 `_make_message`）；③ 是带 `ChannelMessage` 注解的形参
    （`wecom._deliverVoiceWithBytes` 就走这条——它由调用方把 `_make_message` 的产物交进来）。
    """
    offenders = []
    for name, tree in sources:
        made = set()
        annotated = set()
        makerFuncs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if any(isinstance(r, ast.Return) and isinstance(r.value, ast.Call)
                       and _calleeName(r.value.func) in ("_make_message", "ChannelMessage")
                       for r in ast.walk(node)):
                    makerFuncs.add(node.name)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                origin = _calleeName(node.value.func)
                if origin in ("_make_message", "ChannelMessage") or origin in makerFuncs:
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name):
                            made.add(tgt.id)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in list(node.args.args) + list(node.args.kwonlyargs):
                    if _annotationName(arg.annotation) == "ChannelMessage":
                        annotated.add(arg.arg)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _calleeName(node.func) == "_emit_event"):
                continue
            if len(node.args) < 2:
                continue
            payload = node.args[1]
            if isinstance(payload, ast.Call) and \
                    _calleeName(payload.func) in ("_make_message", "ChannelMessage"):
                continue
            if isinstance(payload, ast.Name) and (payload.id in made or payload.id in annotated):
                continue
            offenders.append((name, node.lineno, ast.dump(payload)[:60]))
    return offenders


def _calleeName(node) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _annotationName(ann) -> str:
    if isinstance(ann, ast.Name):
        return ann.id
    if isinstance(ann, ast.Attribute):
        return ann.attr
    if isinstance(ann, ast.Subscript):  # Optional[...] / 别的泛型形
        return _annotationName(ann.value)
    return ""


class _StubMqttMsg:
    """paho 的 Msg 在这条链上被读到四面（现量：`msg.topic`/`msg.payload`/`msg.qos`/`msg.retain`）。

    桩面按真读法给齐——不然红会落在"我的桩少了个属性"上，而不是门的契约上。
    """

    def __init__(self, topic="server/dev01/up", payload=b""):
        self.topic = topic
        self.payload = payload
        self.qos = 1
        self.retain = 0


@pytest.fixture()
def mqttDoor():
    """真适配器 + 真 manager 装配闭包 + 真 `_on_channel_event`，只把 handler 链那道门换成记录器。"""
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    from neurova.channels.mqtt import MQTTAdapter
    from neurova.channels.manager import ChannelManager, get_channel_manager

    isolatedDataRoot()
    ChannelManager._instance = None
    mgr = get_channel_manager()
    mgr.ingress_queue = False          # 入站持久队列不是本批主张，走直发路径
    seen = []

    async def _recordDoor(message):
        seen.append(message)

    originalDispatch = mgr._dispatch_message
    mgr._dispatch_message = _recordDoor  # 再往下要起 agent、花模型配额
    adapter = MQTTAdapter()
    mgr.register_adapter(adapter, agent_id="default")
    try:
        yield mgr, adapter, seen
    finally:
        mgr._dispatch_message = originalDispatch
        mgr.unregister_adapter("mqtt", agent_id="default")
        ChannelManager._instance = None


class TestMqttInboundPaysTheDoorsCurrency:
    def testMqttMessageReachesTheHandlerDoor(self, mqttDoor):
        """红在此：今天整条消息在闭包第一行就没了，handler 链一次都没被叫到。"""
        import asyncio

        _mgr, adapter, seen = mqttDoor
        payload = json.dumps({"user_id": "u-mqtt-1", "content": "把所有笔记删掉",
                              "chat_id": "room/42"}).encode("utf-8")
        parsed = adapter._parse_mqtt_message(_StubMqttMsg(payload=payload), payload.decode("utf-8"))
        assert parsed is not None, "解析这一步自己就返了 None，后面的读数都没意义"
        asyncio.run(adapter._emit_event(_eventType(), parsed))

        assert len(seen) == 1, (
            f"MQTT 入站到了门就蒸发：handler 链被叫到 {len(seen)} 次"
            "（旧形状在 manager.py:138 抛 TypeError，被 _emit_event 的 catch-all 记成日志）")

    def testDoorReceivesTheFullChannelMessageFace(self, mqttDoor):
        import asyncio
        from neurova.channels.base import ChannelMessage

        _mgr, adapter, seen = mqttDoor
        payload = json.dumps({"user_id": "u-mqtt-1", "content": "hello",
                              "chat_id": "room/42"}).encode("utf-8")
        parsed = adapter._parse_mqtt_message(_StubMqttMsg(topic="server/dev01/up",
                                                           payload=payload),
                                             payload.decode("utf-8"))
        asyncio.run(adapter._emit_event(_eventType(), parsed))

        assert len(seen) == 1, f"门没收到消息，字段读数无从取（{len(seen)} 条）"
        got = seen[0]
        assert isinstance(got, ChannelMessage), f"进门的不是 ChannelMessage：{type(got).__name__}"
        # 这四个字段是门与下游身份口径要读的（manager.py:138/351、channel_router 的 sender 归属）
        assert got.channel_type == "mqtt", f"channel_type 不对：{got.channel_type!r}"
        assert got.sender_id == "u-mqtt-1", f"发送者没进来：{got.sender_id!r}"
        assert got.chat_id == "room/42", f"会话没进来：{got.chat_id!r}"
        assert got.content == "hello", f"正文没进来：{got.content!r}"
        assert got.metadata.get("agent_id") == "default", (
            f"装配闭包该给这条消息盖上来源 agent（实得 {got.metadata}）")
        assert (got.raw_event or {}).get("topic") == "server/dev01/up", (
            f"主题该留在 raw_event 里供排查（实得 {got.raw_event}）")

    def testTheDoorItselfRejectsTheOldShape(self, mqttDoor):
        """反证（这一格决定红是不是落在行为上）：拿旧形状真投进装配好的闭包，门自己就要抛。

        不这么钉的话，"到不了门"可能只是我的记录器太窄——这里绕过 `_emit_event` 的吞异常，
        直接叫门，取到的是门自己的读法失败。
        """
        import asyncio

        from neurova.channels.models import ContentType, MessageChannel, UnifiedMessage

        mgr, _adapter, seen = mqttDoor
        callback = mgr._make_event_callback("default")
        old = UnifiedMessage(message_id="m1", channel=MessageChannel.MQTT,
                             content_type=ContentType.TEXT, content="hi", user_id="u1",
                             chat_id="c1", global_user_id="mqtt:u1", session_id="mqtt:c1")
        with pytest.raises(TypeError) as bare:
            asyncio.run(callback(_eventType(), old))
        assert "NoneType" in str(bare.value), f"闭包第一行的失败形态变了：{bare.value}"
        assert seen == [], f"却在闭包里把消息放下去了（{len(seen)} 条）"

        old.metadata = {}
        with pytest.raises(AttributeError) as later:
            asyncio.run(callback(_eventType(), old))
        assert "channel_type" in str(later.value), (
            f"_on_channel_event 首行的读法变了（不是 channel_type 就另找）：{later.value}")
        assert seen == [], f"旧形状真进了 handler 链（{len(seen)} 条）——那本档的因果就不成立"


def _eventType():
    from neurova.channels.base import ChannelEventType

    return ChannelEventType.MESSAGE_RECEIVED


class TestWebsocketInboundPaysTheDoorsCurrency:
    """同一条根的第二个违约者。**这一支今天在生产里构造不出来**（`create_websocket_adapter` 零调用者），
    所以这里只钉形状与门读法，不声称端到端可用——去留属 `UnifiedMessage`/Gen2 那族那次裁。"""

    def testParsedWebsocketMessageIsTheDoorsCurrency(self):
        from neurova.channels.base import ChannelMessage
        from neurova.channels.websocket import WebSocketAdapter

        adapter = WebSocketAdapter()
        parsed = adapter._parse_websocket_message(json.dumps({"user_id": "ws-u1", "content": "hi"}))

        assert parsed is not None, "解析自己返了 None，读数无意义"
        assert isinstance(parsed, ChannelMessage), (
            f"websocket 入站投给门的还是别的对象：{type(parsed).__name__}")
        assert parsed.channel_type == "websocket", f"channel_type：{parsed.channel_type!r}"
        assert parsed.sender_id == "ws-u1", f"发送者：{parsed.sender_id!r}"

    def testWebsocketEmitSiteCarriesTheMadeMessage(self):
        """把 `UnifiedMessage` 留在出站/Gen2 那面，入站投递点必须换成门的货币。"""
        src = (REPO / "neurova" / "channels" / "websocket.py").read_text(encoding="utf-8")
        emitLine = next(l for l in src.splitlines() if "_emit_event(ChannelEventType" in l)
        assert "unified_msg" not in emitLine, f"投递点还在交旧对象：{emitLine.strip()}"


class TestParseRawMessageFaceStaysHonest:
    """这两支的 `parse_raw_message` 只是转交给上面那个解析器——注解必须与真产物同形。

    它全仓零调用者（现量），所以本批不替 `UnifiedMessage`/Gen2 整族做裁决，但也**不许留一句
    假的契约文本**：改了产物却写着 `-> UnifiedMessage`，下一个人就照着错形状接管线。
    """

    def testParsedProductsAreTheDoorsCurrency(self):
        from neurova.channels.base import ChannelMessage
        from neurova.channels.mqtt import MQTTAdapter
        from neurova.channels.websocket import WebSocketAdapter

        mqttOut = MQTTAdapter().parse_raw_message({"topic": "server/a/up",
                                                  "payload": json.dumps({"user_id": "u1",
                                                                         "content": "hi"})})
        wsOut = WebSocketAdapter().parse_raw_message(json.dumps({"user_id": "w1", "content": "yo"}))

        assert isinstance(mqttOut, ChannelMessage), f"mqtt 交的却是 {type(mqttOut).__name__}"
        assert isinstance(wsOut, ChannelMessage), f"websocket 交的却是 {type(wsOut).__name__}"

    def testAnnotationsMatchWhatThoseMethodsActuallyReturn(self):
        import typing

        from neurova.channels.base import ChannelMessage
        from neurova.channels.mqtt import MQTTAdapter
        from neurova.channels.websocket import WebSocketAdapter

        for cls in (MQTTAdapter, WebSocketAdapter):
            declared = typing.get_args(cls.parse_raw_message.__annotations__["return"])
            assert declared and ChannelMessage in declared, (
                f"{cls.__name__}.parse_raw_message 的返回注解里没有 ChannelMessage："
                f"{cls.parse_raw_message.__annotations__}——注解与产物分叉就是第二个事实源")


class TestEveryEmitSitePaysTheDoor:
    """全仓按形状数，不只审"已登记的两支"——新写第三处违约就当场红。"""

    def testNoEmitSiteFeedsTheDoorSomethingItCannotRead(self):
        offenders = _emitOffenders(_scanTrees())
        assert offenders == [], "这些 _emit_event 投递点交给门的对象读不起：%s" % [
            (f, ln, shape) for f, ln, shape in offenders]

    def testShapeDetectorHasTeeth(self):
        bad = chr(10).join([
            "class MqttAdapter(ChannelAdapter):",
            "    def _schedule_emit(self, message: UnifiedMessage):",
            "        self._emit_event(ChannelEventType.MESSAGE_RECEIVED, message)",
        ])
        good = chr(10).join([
            "class FeishuAdapter(ChannelAdapter):",
            "    def _on_event(self):",
            "        channel_msg = self._make_message(message_id='', sender_id='',",
            "            sender_name='', content='', chat_id='')",
            "        self._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg)",
        ])
        viaParam = chr(10).join([
            "class WeComAdapter(ChannelAdapter):",
            "    async def _deliverVoiceWithBytes(self, message: ChannelMessage):",
            "        await self._emit_event(ChannelEventType.MESSAGE_RECEIVED, message)",
        ])
        # 放宽到"一跳可达"后必须还咬着：造的东西不是门的货币，换个函数名照样要红
        hopButWrongCurrency = chr(10).join([
            "class MqttAdapter(ChannelAdapter):",
            "    def _parse_mqtt_message(self, msg, payload):",
            "        return UnifiedMessage(message_id='m', channel=None,",
            "            content_type=None, content='hi', user_id='u')",
            "    def _on_message(self):",
            "        channel_msg = self._parse_mqtt_message(None, '{}')",
            "        self._schedule_emit(channel_msg)",
            "    def _schedule_emit(self, message: UnifiedMessage):",
            "        self._emit_event(ChannelEventType.MESSAGE_RECEIVED, message)",
        ])
        offenders = _emitOffenders(_trees(("bad.py", bad)))
        assert [o[:2] for o in offenders] == [("bad.py", 3)], (
            f"投 UnifiedMessage 却没报——守卫没牙（实得 {offenders}）")
        assert _emitOffenders(_trees(("good.py", good))) == [], "合法写法被误报"
        assert _emitOffenders(_trees(("wecom.py", viaParam))) == [], "带 ChannelMessage 注解的形参被误报"
        hopped = _emitOffenders(_trees(("mqtt2.py", hopButWrongCurrency)))
        assert [o[1] for o in hopped] == [9], (
            f"换了个函数名就混过去了（只该报投递点那行，实得 {hopped}）")

    def testScanScopeActuallyFoundCallSites(self):
        """地板：取数面不能是空的（空集与"全都合规"不可分辨，与 §6-190 那一格同族）。"""
        sources = _scanTrees()
        assert len(sources) >= 25, f"扫描目录里只有 {len(sources)} 个文件，扫描面收窄了"
        # 投递点按 AST 数（文本数法会把注释与字符串也算进来，是另一种口径）
        hits = [node for _f, tree in sources for node in ast.walk(tree)
                if isinstance(node, ast.Call) and _calleeName(node.func) == "_emit_event"]
        assert len(hits) >= 15, f"投递点只数到 {len(hits)} 条，口径失效"
