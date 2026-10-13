# -*- coding: utf-8 -*-
"""§6-193 活体自证：MQTT 入站从此付得起那道门的货币——旧形状真投进去会整条蒸发。

真跑的东西：真 `ChannelManager.register_adapter` 装配出来的事件闭包 + 真 `MQTTAdapter`
+ 真 `_on_message`（paho 的那个回调，只是喂给它一个真读法给齐属性的桩 Msg）+ 真 asyncio 循环。
handler 链那道门（`_dispatch_message`）换成记录器：**再往下就要起 agent、调模型、花配额**，
那不是本批主张的东西。

读数分组：
① paho 回调 → 主 loop 分发 → 装配闭包 → `_on_channel_event` → 门：真到 1 条，且带齐
   `channel_type`/`sender_id`/`chat_id`/`content`/`message_type`/`metadata["agent_id"]`/`raw_event["topic"]`。
② **反证段**：把解析就地换成旧形状（`UnifiedMessage`，`metadata` 恒 None）走同一条路 ⇒
   门必须收到 **0 条**，且 `_emit_event` 的 catch-all 恰记 1 次异常。这一格把"消息去哪了"钉死在
   形状上——不是记录器太窄，也不是我没喂到。
③ 别的 agent 名下配的 MQTT 同样收得到：`register_adapter(..., agent_id="kai")` ⇒ 进门那条
   带的是 `kai`（接 §6-189/§6-190 的 agent 口径，不再只有 default 那一格算数）。
④ 对照段：真 `FeishuAdapter` 的一条文本消息照常进门 ⇒ 证明本批只换了两支违约者，
   没动其余渠道的形状。
⑤ 收尾：临时适配器注销干净、桩件复原，运行时不留状态。

一条不糊的边界：本批**不证**与真 broker 互操作（没连 1883，也不开外网），也不证 WebSocket 那一支端到端
——`WebSocketAdapter` 全仓没有生产构造路（`create_websocket_adapter` 零调用者），它的形状由常驻判据钉住，
去留属 `UnifiedMessage`/Gen2 那族那次裁。
"""

import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

failures: list[str] = []


def _check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


class _StubMsg:
    """paho 的 Msg 在这条链上被读到四面：topic / payload / qos / retain（现量自 mqtt.py）。"""

    def __init__(self, topic="server/dev01/up", payload=b"", qos=1, retain=0):
        self.topic = topic
        self.payload = payload
        self.qos = qos
        self.retain = retain


def _main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    print(f"数据根（临时）：{isolatedDataRoot()}")

    from neurova.channels import ChannelConfig, ContentType, MessageChannel, UnifiedMessage
    from neurova.channels.base import ChannelEventType
    from neurova.channels import base as baseModule
    from neurova.channels import mqtt as mqttModule
    from neurova.channels.feishu import FeishuAdapter
    from neurova.channels.manager import ChannelManager, get_channel_manager
    from neurova.channels.mqtt import MQTTAdapter

    door: list = []

    async def _recordDoor(message):
        door.append(message)

    ChannelManager._instance = None
    mgr = get_channel_manager()
    mgr.ingress_queue = False            # 入站持久队列不是本批主张，走直发路径
    originalDispatch = mgr._dispatch_message
    mgr._dispatch_message = _recordDoor  # 门后再往下就要起 agent、花配额

    adapter = MQTTAdapter()
    mgr.register_adapter(adapter, agent_id="default")
    loop = asyncio.new_event_loop()
    # `connect()` 里那句 `self._main_loop = asyncio.get_running_loop()`（mqtt.py:155）本批不连真 broker，
    # 所以按同一形状把循环交给它——`_schedule_emit` 判的就是这个（不设就是走"无循环丢弃"那一支，
    # 那样 0 条读数是探针自己的洞，不是被测代码的洞）。
    adapter._main_loop = loop
    drops: list = []
    originalWarn = mqttModule.logging.warning

    def _watchDrops(*args, **kwargs):
        text = str(args[0])[:120] if args else ""
        if "丢弃" in text:
            drops.append(text)
        return originalWarn(*args, **kwargs)

    # 只旁听、不吞：那条"无可用事件循环，丢弃入站消息"若被走到，读数就是探针自己的洞
    mqttModule.logging.warning = _watchDrops

    async def _drive(a, payloadBytes):
        """在真运行中的 loop 里调 paho 那个同步回调——`_schedule_emit` 要的就是这个条件。"""
        assert loop.is_running(), "探针自己没在跑着的循环里，读数无意义"
        a._on_message(None, None, _StubMsg(payload=payloadBytes))
        for _ in range(60):
            if door or drops:
                break
            await asyncio.sleep(0.02)

    try:
        print("\n① 真回调 → 真闭包 → 真 _on_channel_event → 门")
        payload = json.dumps({"user_id": "u-live-1", "content": "把今天的会议记下来",
                              "chat_id": "room/live"}).encode("utf-8")
        loop.run_until_complete(_drive(adapter, payload))
        _check(not drops, f"没走『无循环丢弃』那一支（旁听到 {len(drops)} 条：{drops[:1]}）")
        _check(len(door) == 1, f"门收到 {len(door)} 条（旧形状在这里是 0 条：整条消息在闭包第一行没了）")
        if door:
            got = door[0]
            _check(got.channel_type == "mqtt" and got.sender_id == "u-live-1"
                   and got.chat_id == "room/live" and got.content == "把今天的会议记下来"
                   and got.message_type == "text",
                   f"进门那条的字段：{got.channel_type}/{got.sender_id}/{got.chat_id}/"
                   f"{got.content!r}/{got.message_type}")
            _check(got.metadata.get("agent_id") == "default"
                   and got.raw_event.get("topic") == "server/dev01/up",
                   f"agent 归属与主题：{got.metadata} / topic={got.raw_event.get('topic')}")

        print("\n② 反证段：把旧形状真投进同一条路")
        door.clear()
        originalParse = adapter._parse_mqtt_message
        swallowed: list = []

        # 生产里 `_parse_mqtt_message` 是**同步**方法——桩必须同形，否则它返回一个协程对象，
        # 失败原因就是"我的桩是个协程"而不是"旧形状付不起门"（第一版就在这里自证失真）。
        def _oldShape(msg, text):
            return UnifiedMessage(message_id="m-old", channel=MessageChannel.MQTT,
                                  content_type=ContentType.TEXT, content="hi", user_id="u1",
                                  chat_id="c1", global_user_id="mqtt:u1", session_id="mqtt:c1")

        def _counting(*args, **kwargs):
            swallowed.append(" ".join(str(a)[:120] for a in args))

        # 吞异常那一处就在 `base._emit_event`（`logger.exception`）——计数打在真正记日志的那只 logger 上
        adapter._parse_mqtt_message = _oldShape
        originalExc = baseModule.logger.exception
        baseModule.logger.exception = _counting
        try:
            loop.run_until_complete(_drive(adapter, b"whatever"))
            _check(len(door) == 0, f"旧形状投进去 ⇒ 门收到 {len(door)} 条（必须 0，否则因果不成立）")
            first = swallowed[0][:160] if swallowed else ""
            _check(len(swallowed) >= 1 and "NoneType" in first and "not iterable" in first,
                   f"旧形状在闭包第一行抛的是 `in None` 那记 TypeError（本次 {len(swallowed)} 次，"
                   f"首条={first!r}）")
        finally:
            adapter._parse_mqtt_message = originalParse
            baseModule.logger.exception = originalExc
        _check(adapter._parse_mqtt_message is originalParse
               and baseModule.logger.exception is originalExc, "反证段的桩件已复原（不留运行时状态）")

        print("\n③ 非 default 名下配的 MQTT 同样收得到，且归属带的是那只 agent")
        door.clear()
        second = MQTTAdapter()
        second._main_loop = loop
        mgr.register_adapter(second, agent_id="kai")
        loop.run_until_complete(_drive(second, json.dumps(
            {"user_id": "u-kai", "content": "kai 的语音转写测试", "chat_id": "room/kai"}).encode()))
        _check(len(door) == 1 and door[0].metadata.get("agent_id") == "kai",
               f"kai 名下那条：{len(door)} 条、agent={door[0].metadata.get('agent_id') if door else None!r}")
        mgr.unregister_adapter("mqtt", agent_id="kai")

        print("\n④ 对照段：没动的那支渠道照常进门（本批只换了两支违约者）")
        door.clear()
        feishu = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="cli",
                                             app_secret="s", use_stream=False))
        mgr.register_adapter(feishu, agent_id="default")

        async def _emitNow():
            return await feishu._emit_event(
                ChannelEventType.MESSAGE_RECEIVED,
                feishu._make_message(message_id="om_1", sender_id="ou_1", sender_name="ou_1",
                                     content="照常", chat_id="oc_1", chat_type="p2p",
                                     message_type="text"))

        returned = loop.run_until_complete(_emitNow())
        _check(len(door) == 1 and door[0].channel_type == "feishu" and returned is None,
               f"飞书那条照常进门：{len(door)} 条、"
               f"channel={door[0].channel_type if door else None}")
        mgr.unregister_adapter("feishu", agent_id="default")

    finally:
        mqttModule.logging.warning = originalWarn
        loop.close()
        mgr._dispatch_message = originalDispatch
        mgr.unregister_adapter("mqtt", agent_id="default")
        _check(mgr.get_adapter("mqtt") is None and not mgr.list_adapters(),
               f"收尾：临时适配器与桩件都摘净（残留 {mgr.list_adapters()}）")

    print()
    print("  边界：不连真 broker、不开外网、不起 agent、不花模型配额；WebSocket 那一支无生产构造路，"
          "本支不证其端到端。")
    if failures:
        print(f"活体未过：{len(failures)} 项")
        for item in failures:
            print("  - " + item)
        return 1
    print("活体全过")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
