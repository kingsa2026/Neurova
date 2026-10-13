# -*- coding: utf-8 -*-
"""§6-187 活体自证：企业微信一条只给 `<MediaId>` 的语音，真能走到"素材字节 → 预检 → 回合上下文"。

真跑的东西：真 `create_app()` + 真 lifespan + 真路由 `/api/v1/channel-adapters/wecom/webhook`
+ 真 `WeComAdapter`（`connect()` 在 `use_stream=False` 下不碰网络）+ **真 HTTP 下载**
（打本机 `127.0.0.1` 上的假企微平台）+ 真 `voice_precheck`。
不真跑的东西：ASR（`_get_asr_transcriber` 换本地假转写）、access token 刷新（既有代码，本支预置好
令牌把注意力留给接缝）、agent 与模型 ⇒ 不开外网、不花任何配额。

读数分组：
① 链路面：语音回调 ⇒ 投 1 条、`metadata["audio_bytes"]` 是桩真返回的那段字节、桩真收到一次带
   `access_token`/`media_id` 的 GET；
② 线程面：发起下载的线程 ≠ 事件循环线程（并同时要求桩真收到请求）；
③ 省一次出站：平台已给 `<Recognition>` 时**不再下载**（桩 0 次 GET）；
④ 失败方向：平台回 JSON 错误体 ⇒ 不把错误体当音频、退占位、消息照投一条；
⑤ 上限：声明长度超限 ⇒ 拒收，不把超限素材挂上消息；
⑥ 下一跳：真预检接手那条真产物 ⇒ 正文换成转写文本、`voice_transcribed` 与 `voice_context` 落地；
⑦ 安全面：错签名的语音回调仍 0 事件（本批往验签之后的函数里加了分支）；
⑧ 对照：文本支照常。

边界：假平台按仓内那份请求形状应答，证的是"这条链在本仓内通了"，**不证与真企业微信互操作**。
"""

import asyncio
import json
import pathlib
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

failures: list[str] = []
CALLBACK_TOKEN = "wecom-callback-token-b27-live"
MEDIA_ID = "MEDIA_LIVE_B27"
FAKE_AUDIO = b"FAKE-WECOM-OPUS-0123456789"
TRANSCRIPT = "把周三的评审往后挪一小时"
WEBHOOK = "/api/v1/channel-adapters/wecom/webhook"

#: 假平台那一次媒体请求的行为（bytes / jsonError / declaredTooBig）
MODE = {"media": "bytes", "mediaHits": [], "threadIdents": []}


class _WecomStub(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/cgi-bin/media/get"):
            MODE["mediaHits"].append(self.path)
            MODE["threadIdents"].append(threading.get_ident())
            if MODE["media"] == "jsonError":
                body = json.dumps({"errcode": 40008, "errmsg": "invalid media id"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if MODE["media"] == "declaredTooBig":
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(999 * 1024 * 1024))
                self.end_headers()
                self.wfile.write(b"tiny")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(FAKE_AUDIO)))
            self.end_headers()
            self.wfile.write(FAKE_AUDIO)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_args):
        pass


def _check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def _xml(msgType: str, extra: str) -> str:
    return ("<xml><ToUserName><![CDATA[ww_corp_live]]></ToUserName>"
            "<FromUserName><![CDATA[manager_user_live]]></FromUserName>"
            "<CreateTime>1700000000</CreateTime><MsgType><![CDATA[" + msgType + "]]></MsgType>"
            + extra + "<MsgId>99</MsgId><AgentID>100</AgentID></xml>")


def _post(client, xml: str, events: list, expectDelta: int, signature=None):
    from neurova.channels.wecom import _wecom_callback_signature

    stamp, nonce = "1700000000", "n-live"
    sign = signature if signature is not None else _wecom_callback_signature(
        CALLBACK_TOKEN, stamp, nonce, "")
    before = len(events)
    r = client.post(f"{WEBHOOK}?msg_signature={sign}&timestamp={stamp}&nonce={nonce}",
                    content=xml.encode("utf-8"),
                    headers={"Content-Type": "application/xml"})
    deadline = time.time() + 3.0
    while time.time() < deadline and (len(events) - before) < max(expectDelta, 1):
        time.sleep(0.02)
    return r, len(events) - before


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    root = isolatedDataRoot()
    print(f"数据根（临时）：{root}")

    server = HTTPServer(("127.0.0.1", 0), _WecomStub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stubBase = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"本地桩（假企微平台）：{stubBase}")

    from fastapi.testclient import TestClient

    import neurova.channels.wecom as wecomModule
    from neurova.api.app import create_app
    from neurova.channels import voice_precheck
    from neurova.channels.base import ChannelConfig
    from neurova.channels.manager import ChannelManager, get_channel_manager
    from neurova.channels.voice_ingress import (
        AUDIO_BYTES_KEY,
        INBOUND_VOICE_PLACEHOLDER,
        VOICE_DOWNLOAD_MAX_BYTES,
    )
    from neurova.channels.wecom import WeComAdapter
    from neurova.voice_context_module import VOICE_CONTEXT_KEY

    originalBase = getattr(wecomModule, "WECOM_API_BASE", "https://qyapi.weixin.qq.com")
    wecomModule.WECOM_API_BASE = stubBase

    events: list = []

    async def _record(_eventType, message):
        events.append(message)

    ChannelManager._instance = None
    adapter = WeComAdapter(ChannelConfig(
        channel_type="wecom", app_id="ww_corp_live", app_secret="sec",
        webhook_token=CALLBACK_TOKEN, use_stream=False,
        extra={"corpid": "ww_corp_live", "agentid": "100"}))

    app = create_app()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            mgr = get_channel_manager()
            mgr.register_adapter(adapter)
            adapter._event_callback = _record

            async def _connectInLoop():
                await adapter.connect()
                return threading.get_ident()

            loopThreadIdent = client.portal.call(_connectInLoop)
            # 令牌预置：本支不证刷新那条出站（既有代码），把注意力留给接缝与下载形状
            adapter._access_token = "tok-live-b27"
            adapter._token_expires_at = time.time() + 600

            print("\n① 只给 MediaId 的语音：字节真取回来、落在预检读的那个键上")
            MODE.update(media="bytes", mediaHits=[], threadIdents=[])
            r, delta = _post(client, _xml("voice", f"<MediaId><![CDATA[{MEDIA_ID}]]></MediaId>"),
                             events, 1)
            voiceMsg = events[-1] if events else None
            _check(r.status_code == 200 and delta == 1,
                   f"合法语音回调 200 且投 1 条（HTTP={r.status_code}，新增 {delta}）")
            _check(len(MODE["mediaHits"]) == 1 and f"media_id={MEDIA_ID}" in MODE["mediaHits"][0]
                   and "access_token=tok-live-b27" in MODE["mediaHits"][0],
                   f"真发了一次素材 GET（桩收到 {len(MODE['mediaHits'])} 次：{MODE['mediaHits'][:1]}）")
            _check(voiceMsg is not None
                   and voiceMsg.metadata.get(AUDIO_BYTES_KEY) == FAKE_AUDIO,
                   f"字节落进 {AUDIO_BYTES_KEY}（实得 "
                   f"{len((voiceMsg.metadata or {}).get(AUDIO_BYTES_KEY) or b'')} 个字节）")
            _check(voiceMsg is not None and voiceMsg.content == INBOUND_VOICE_PLACEHOLDER,
                   f"取字节期间正文仍是共享占位（实得 {getattr(voiceMsg, 'content', None)!r}）")

            print("\n② 下载不在事件循环线程上")
            downloadThread = MODE["threadIdents"][0] if MODE["threadIdents"] else 0
            _check(bool(MODE["threadIdents"]) and downloadThread != loopThreadIdent,
                   f"发起下载的线程与事件循环线程不同（loop={loopThreadIdent}，下载={downloadThread}）")

            print("\n③ 平台已给转写时不再出站取素材")
            MODE.update(media="bytes", mediaHits=[], threadIdents=[])
            before = len(events)
            _post(client, _xml("voice", f"<Recognition><![CDATA[{TRANSCRIPT}]]></Recognition>"
                                        f"<MediaId><![CDATA[{MEDIA_ID}]]></MediaId>"), events, 1)
            _check(len(events) == before + 1 and events[-1].content == TRANSCRIPT
                   and MODE["mediaHits"] == [],
                   f"已转写就省掉那次出站（事件 {len(events) - before} 条，素材 GET {len(MODE['mediaHits'])} 次）")

            print("\n④ 平台回 JSON 错误体：不当音频、退占位、消息照投")
            MODE.update(media="jsonError", mediaHits=[], threadIdents=[])
            before = len(events)
            _post(client, _xml("voice", f"<MediaId><![CDATA[{MEDIA_ID}]]></MediaId>"), events, 1)
            failMsg = events[-1] if events else None
            _check(len(events) == before + 1 and failMsg is not None
                   and failMsg.content == INBOUND_VOICE_PLACEHOLDER
                   and AUDIO_BYTES_KEY not in (failMsg.metadata or {}),
                   f"错误体没被当字节（事件 {len(events) - before} 条，"
                   f"字节在否={AUDIO_BYTES_KEY in (failMsg.metadata or {}) if failMsg else None}）")

            print("\n⑤ 声明长度超限：拒收，不把超限素材挂上消息")
            MODE.update(media="declaredTooBig", mediaHits=[], threadIdents=[])
            before = len(events)
            _post(client, _xml("voice", f"<MediaId><![CDATA[{MEDIA_ID}]]></MediaId>"), events, 1)
            bigMsg = events[-1] if events else None
            _check(len(events) == before + 1 and bigMsg is not None
                   and (bigMsg.metadata or {}).get(AUDIO_BYTES_KEY) is None
                   and bigMsg.content == INBOUND_VOICE_PLACEHOLDER,
                   f"超限素材被拒收并退占位（声明上限 {VOICE_DOWNLOAD_MAX_BYTES} 字节）")

            print("\n⑥ 真预检接手 ① 那条真产物")
            asrCalls: list = []

            async def _fakeTranscriber(audioBytes):
                asrCalls.append(len(audioBytes))
                return {"text": TRANSCRIPT, "segments": [{"start": 0, "end": 3100}]}

            originalGetter = voice_precheck._get_asr_transcriber
            voice_precheck._get_asr_transcriber = lambda: _fakeTranscriber
            try:
                prechecked = asyncio.run(voice_precheck.transcribe_voice_message(voiceMsg))
            finally:
                voice_precheck._get_asr_transcriber = originalGetter
            _check(asrCalls == [len(FAKE_AUDIO)] and prechecked.content == TRANSCRIPT,
                   f"预检按真字节调了 ASR 并换掉正文（入参 {asrCalls}，正文 {prechecked.content!r}）")
            _check(prechecked.metadata.get("voice_transcribed") is True
                   and prechecked.metadata.get(VOICE_CONTEXT_KEY) is not None,
                   "voice_transcribed / voice_context 落地了")

            print("\n⑦ 仿冒的语音回调仍然进不来")
            MODE.update(media="bytes", mediaHits=[], threadIdents=[])
            before = len(events)
            _post(client, _xml("voice", f"<MediaId><![CDATA[{MEDIA_ID}]]></MediaId>"), events, 0,
                  signature="notasignature")
            _check(len(events) == before and MODE["mediaHits"] == [],
                   f"错签名 0 事件、0 次出站（累计事件 {len(events)} 条）")

            print("\n⑧ 文本支照常")
            before = len(events)
            _post(client, _xml("text", "<Content><![CDATA[普通文字]]></Content>"), events, 1)
            _check(len(events) == before + 1 and events[-1].content == "普通文字"
                   and MODE["mediaHits"] == [], "文本支未被波及且没触发出站")

            mgr.unregister_adapter("wecom")
            _check(mgr.get_adapter("wecom") is None, "收尾：临时适配器已摘净")
    finally:
        wecomModule.WECOM_API_BASE = originalBase
        server.shutdown()

    print()
    print("  边界：假平台按仓内请求形状应答 ⇒ 证本仓这条链通，不证与真企业微信逐字节互操作；"
          "access token 刷新那条出站未跑（既有代码，本支预置令牌）。")
    if failures:
        print(f"活体未过：{len(failures)} 项")
        for item in failures:
            print("  - " + item)
        return 1
    print("活体全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
