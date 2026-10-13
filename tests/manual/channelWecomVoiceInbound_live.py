# -*- coding: utf-8 -*-
"""§6-184 活体自证：企业微信语音回调经真 webhook 路由进得来，转写文本落在正文上。

真跑的东西：真 `create_app()` + 真 lifespan + 真路由 `/api/v1/channel-adapters/wecom/webhook`
+ 真 `WeComAdapter`（`connect()` 在 `use_stream=False` 下不碰网络，只捕主 loop 引用）。
事件回调一律换成 recorder ⇒ 不起 agent、不调模型、不开外网、不花任何配额。

读数分四组：
① 装配面：`connect()` 捕到的 loop 就是驱动请求的那个 loop——否则 `handle_callback` 走的是
   "主循环未运行，丢弃消息"那条 warn 分支，读到的 0 条是夹具没驱动而不是链路坏了（§6-168 那一形）。
② 链路面：合法签名 + `<Recognition>` ⇒ 200 且事件的 `content` 就是那句转写；无转写 ⇒ 退回共享占位；
   文本消息不受影响（对照组，防"所有消息都被改写"这种假修）。
③ 安全面：错签名的语音回调必须 0 事件——本批往 `handle_callback` 里加了分支，不能顺手把
   §6-181 之前那条 fail-closed 验签放宽。
④ 下一跳：把②拿到的**真产物**喂进 `voice_precheck.transcribe_voice_message`——它没有音频字节，
   必须原样直通并保留占位，不得凭空转写出内容（metadata 里也确没被塞 `audio_bytes`/媒体引用）。

不证的边界：`MediaId` → 音频字节这条仍没接（`WeComAdapter` 不带 `WeChatMediaMixin`，那个下载器
要的是 `WeChatAdapter` 才有的同步 token 方法），本支只证平台已给出的文本进得来。
"""

import asyncio
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

failures: list[str] = []
CALLBACK_TOKEN = "wecom-callback-token-live"
WEBHOOK = "/api/v1/channel-adapters/wecom/webhook"


def _check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def _signed(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    from neurova.channels.wecom import _wecom_callback_signature

    return _wecom_callback_signature(token, timestamp, nonce, encrypt)


def _xml(msgType: str, extra: str) -> str:
    return ("<xml><ToUserName><![CDATA[ww_corp_live]]></ToUserName>"
            "<FromUserName><![CDATA[manager_user_live]]></FromUserName>"
            "<CreateTime>1700000000</CreateTime><MsgType><![CDATA[" + msgType + "]]></MsgType>"
            + extra + "<MsgId>77</MsgId><AgentID>100</AgentID></xml>")


def _post(client, xml: str, signature: str, events: list, expectDelta: int):
    """投一条回调并按**谓词**等异步投递落地（`handle_callback` 把事件 sched 到主 loop）。"""
    before = len(events)
    r = client.post(
        WEBHOOK + "?msg_signature=" + signature + "&timestamp=1700000000&nonce=n-live",
        content=xml.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
    )
    deadline = time.time() + 3.0
    while time.time() < deadline and (len(events) - before) < max(expectDelta, 1):
        time.sleep(0.02)
    return r, len(events) - before


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    root = isolatedDataRoot()
    print(f"数据根（临时）：{root}")

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.channels.base import ChannelConfig
    from neurova.channels.manager import ChannelManager, get_channel_manager
    from neurova.channels.voice_ingress import AUDIO_BYTES_KEY, INBOUND_VOICE_PLACEHOLDER
    from neurova.channels.wecom import WeComAdapter

    events: list = []

    async def _record(_t, message):
        events.append(message)

    ChannelManager._instance = None
    adapter = WeComAdapter(ChannelConfig(
        channel_type="wecom", app_id="ww_corp_live", app_secret="sec",
        webhook_token=CALLBACK_TOKEN, use_stream=False,
        extra={"agentid": "100"}))
    _check(adapter._callback_token == CALLBACK_TOKEN,
           f"回调密钥经 ChannelConfig.webhook_token 落到适配器（实得 {adapter._callback_token!r}）")

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        mgr = get_channel_manager()
        mgr.register_adapter(adapter)
        adapter._event_callback = _record

        print("\n① 装配面：connect() 捕到的就是驱动请求的那个 loop")

        async def _connectAndReportLoop():
            await adapter.connect()
            return asyncio.get_running_loop()

        loopUsedByRequest = client.portal.call(_connectAndReportLoop)
        _check(adapter._main_loop is not None and adapter._main_loop is loopUsedByRequest,
               f"_main_loop 已捕到 portal loop（同一对象={adapter._main_loop is loopUsedByRequest}）")

        print("\n② 链路面：语音回调的正文")
        sig = _signed(CALLBACK_TOKEN, "1700000000", "n-live", "")
        r, delta = _post(client, _xml("voice", "<Recognition><![CDATA[明天天气怎么样]]></Recognition>"
                                         "<MediaId><![CDATA[MEDIA_1]]></MediaId>"), sig, events, 1)
        transcriptMsg = events[-1] if events else None
        _check(r.status_code == 200 and delta == 1,
               f"合法签名的语音回调 200 且投递 1 条（HTTP={r.status_code}，新增 {delta}）")
        _check(transcriptMsg is not None and transcriptMsg.content == "明天天气怎么样",
               f"平台转写文本进了正文（实得 {getattr(transcriptMsg, 'content', None)!r}）")
        _check(transcriptMsg is not None and transcriptMsg.message_type == "voice",
               f"消息类型保持 voice（实得 {getattr(transcriptMsg, 'message_type', None)!r}）")

        r, delta = _post(client, _xml("voice", "<MediaId><![CDATA[MEDIA_2]]></MediaId>"),
                         sig, events, 1)
        noAsrMsg = events[-1] if events else None
        _check(delta == 1 and noAsrMsg is not None
               and noAsrMsg.content == INBOUND_VOICE_PLACEHOLDER,
               f"未开语音识别时退回共享占位而非空串（实得 {getattr(noAsrMsg, 'content', None)!r}）")

        r, delta = _post(client, _xml("text", "<Content><![CDATA[普通文字]]></Content>"),
                         sig, events, 1)
        textMsg = events[-1] if events else None
        _check(delta == 1 and textMsg is not None and textMsg.content == "普通文字",
               f"文本支未被波及（实得 {getattr(textMsg, 'content', None)!r}）——否则就是整条入站被改写")

        print("\n③ 安全面：仿冒的语音回调仍然进不来")
        before = len(events)
        r, _ = _post(client, _xml("voice", "<Recognition><![CDATA[冒充别人]]></Recognition>"),
                     "deadbeef" * 5, events, 0)
        _check(len(events) == before,
               f"错签名 0 事件（累计 {len(events)} 条，HTTP={r.status_code}）——本批没放宽 §6-181 那条门")

        print("\n④ 下一跳：没有字节时预检必须原样直通，不凭空转写")
        from neurova.channels import voice_precheck

        beforeContent = noAsrMsg.content
        prechecked = asyncio.run(voice_precheck.transcribe_voice_message(noAsrMsg))
        _check(getattr(prechecked, "content", None) == beforeContent
               and AUDIO_BYTES_KEY not in (getattr(noAsrMsg, "metadata", None) or {}),
               f"无字节 ⇒ 占位直通、未被编出文本（content={getattr(prechecked, 'content', None)!r}）")
        _check(not [k for k in (transcriptMsg.metadata or {}) if "media" in k.lower()],
               f"没有塞进没人读的媒体引用字段（metadata 键={sorted((transcriptMsg.metadata or {}))}）")

        mgr.unregister_adapter("wecom")
        _check(mgr.get_adapter("wecom") is None, "收尾：临时适配器已从管理器摘净，不留运行时状态")

    print()
    print("  边界：本支不证与真企业微信互操作（签名用仓内公式本地自算），也不证 MediaId→字节那条路")
    print("        ——那条在本仓仍未接（见档头）。")
    if failures:
        print(f"活体未过：{len(failures)} 项")
        for f in failures:
            print("  - " + f)
        return 1
    print("活体全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
