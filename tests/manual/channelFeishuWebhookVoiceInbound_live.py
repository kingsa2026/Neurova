# -*- coding: utf-8 -*-
"""§6-185 活体自证：飞书 webhook 那条入站路，语音真的能走到"字节 → 预检 → 回合上下文"。

真跑的东西：真 `create_app()` + 真 lifespan + 真路由 `/api/v1/channel-adapters/feishu/webhook`
+ 真 `FeishuAdapter` + **真 HTTP 下载**（打本机 `127.0.0.1` 上的假平台桩）+ 真 `voice_precheck`。
不真跑的东西：ASR —— `_get_asr_transcriber` 换成本地假转写函数（不打开任何提供方、不花配额）；
事件回调换 recorder（不起 agent、不开外网）。

七组读数：
① audio 事件 ⇒ 投出 1 条、正文是共享占位、`metadata["audio_bytes"]` 是**桩真返回的那段字节**
   （即下载真的发生、且落在 `voice_ingress` 那个键上）；
② 下载发生在**事件循环之外的线程**（拿 loop 线程 ident 与发起下载的线程 ident 相比，
   并同时要求桩侧真的收到带 Bearer 的 GET——只证"没在循环里"会退化成"下载被关掉了"）；
③ 真预检接手那条真产物 ⇒ 正文被换成转写文本、`voice_transcribed`/`VOICE_CONTEXT_KEY` 落地；
④ 外部发送者（`user_id` 为空、只有 `open_id`）⇒ `sender_id` 不再是空串（§6-123/§6-163 读的就是它）；
⑤ @提及 ⇒ 结构化进 metadata，正文里的 "@_user_N" 换成可读昵称；
⑥ 错令牌的同一条语音回调 ⇒ 仍然 0 事件（本批改的是投递之后的内容口径，验签那道门不得被顺手放宽）；
⑦ text 事件 ⇒ 照常（对照组，防"整条入站被改写"这种假修）。

一条如实边界：假平台桩的形状照仓内 `_download_media_bytes` 的请求形状写，
证的是"这条链在本仓内是通的"，**不证与真飞书逐字节互操作**（那要有凭据的批次做）。
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
VERIFY_TOKEN = "fs-verification-token-batch26-live"
FAKE_AUDIO = b"FAKEOPUS-HEADER-0123456789"
TRANSCRIPT = "帮我订明天上午的会议室"
WEBHOOK = "/api/v1/channel-adapters/feishu/webhook"


class _PlatformStub(BaseHTTPRequestHandler):
    """假平台：发 tenant token、按 file_key 回一段真字节。"""

    seen: list = []

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler 的命名
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        body = json.dumps({"code": 0, "tenant_access_token": "t-stub", "expire": 7200}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        _PlatformStub.seen.append({
            "path": self.path,
            "authorization": self.headers.get("Authorization", ""),
            "threadIdent": threading.get_ident(),
        })
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(FAKE_AUDIO)))
        self.end_headers()
        self.wfile.write(FAKE_AUDIO)

    def log_message(self, *_args):  # 静音
        pass


def _check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def _eventBody(messageType="audio", content=None, userId="ou_internal",
               openId="ou_open", mentions=None):
    if content is None:
        content = json.dumps({"file_key": "fk_live_1", "duration_ms": 2400})
    message = {"message_id": "om_live_1", "chat_id": "oc_live_1", "chat_type": "p2p",
               "message_type": messageType, "content": content}
    if mentions is not None:
        message["mentions"] = mentions
    return {"schema": "2.0",
            "header": {"event_type": "im.message.receive_v1", "token": VERIFY_TOKEN},
            "event": {"sender": {"sender_id": {"user_id": userId, "open_id": openId,
                                               "union_id": "on_union"}},
                      "message": message}}


def _waitUntil(predicate, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    root = isolatedDataRoot()
    print(f"数据根（临时）：{root}")

    _PlatformStub.seen = []
    server = HTTPServer(("127.0.0.1", 0), _PlatformStub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stubBase = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"本地桩（假平台）：{stubBase}")

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.channels import voice_precheck
    from neurova.channels.base import ChannelConfig
    from neurova.channels.feishu import FeishuAdapter
    from neurova.channels.manager import ChannelManager, get_channel_manager
    from neurova.channels.voice_ingress import AUDIO_BYTES_KEY, INBOUND_VOICE_PLACEHOLDER
    from neurova.voice_context_module import VOICE_CONTEXT_KEY

    events: list = []

    async def _record(_eventType, message):
        events.append(message)

    ChannelManager._instance = None
    adapter = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="cli_live26",
                                          app_secret="sec_live26",
                                          verification_token=VERIFY_TOKEN))
    adapter.api_base = f"{stubBase}/open-apis"
    adapter.open_base = stubBase

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        mgr = get_channel_manager()
        mgr.register_adapter(adapter)
        adapter._event_callback = _record

        async def _whoAmI():
            return threading.get_ident()

        loopThreadIdent = client.portal.call(_whoAmI)

        print("\n① audio 事件：正文有东西、字节真到了那个键")
        beforeDownloads = len(_PlatformStub.seen)
        r = client.post(WEBHOOK, json=_eventBody())
        gotEvent = _waitUntil(lambda: len(events) >= 1, 3.0)
        msg = events[0] if events else None
        _check(r.status_code == 200 and gotEvent,
               f"合法语音回调进得来（HTTP={r.status_code}，事件 {len(events)} 条）")
        _check(msg is not None and msg.content == INBOUND_VOICE_PLACEHOLDER,
               f"预检前正文是共享占位而非空串（实得 {getattr(msg, 'content', None)!r}）")
        downloaded = len(_PlatformStub.seen) > beforeDownloads
        _check(downloaded and msg is not None
               and msg.metadata.get(AUDIO_BYTES_KEY) == FAKE_AUDIO,
               f"真下载发生且字节落进 {AUDIO_BYTES_KEY}（桩收到 "
               f"{len(_PlatformStub.seen) - beforeDownloads} 次 GET，"
               f"字节 {len((msg.metadata or {}).get(AUDIO_BYTES_KEY) or b'')} 个）")
        _check(_PlatformStub.seen and _PlatformStub.seen[-1]["authorization"] == "Bearer t-stub",
               f"下载带的是租户令牌（实得 {_PlatformStub.seen[-1]['authorization'] if _PlatformStub.seen else '没请求'!r}）")

        print("\n② 下载不在事件循环线程上")
        downloadThread = _PlatformStub.seen[-1]["threadIdent"] if _PlatformStub.seen else 0
        _check(downloaded and downloadThread != loopThreadIdent,
               f"发起下载的线程与事件循环线程不同（loop={loopThreadIdent}，"
               f"下载={downloadThread}）——一次慢下载不该拖住整条入站")

        print("\n③ 真预检接手这条真产物")
        asrCalls: list = []

        async def _fakeTranscriber(audioBytes):
            asrCalls.append(len(audioBytes))
            return {"text": TRANSCRIPT, "segments": [{"start": 0, "end": 2400}]}

        originalGetter = voice_precheck._get_asr_transcriber
        voice_precheck._get_asr_transcriber = lambda: _fakeTranscriber
        try:
            prechecked = asyncio.run(voice_precheck.transcribe_voice_message(msg))
        finally:
            voice_precheck._get_asr_transcriber = originalGetter
        _check(asrCalls == [len(FAKE_AUDIO)] and prechecked.content == TRANSCRIPT,
               f"预检按真字节调了 ASR 并把正文换成转写（调用入参 {asrCalls}，正文 {prechecked.content!r}）")
        _check(prechecked.metadata.get("voice_transcribed") is True
               and prechecked.metadata.get(VOICE_CONTEXT_KEY) is not None,
               f"回合上下文写侧落地（voice_transcribed={prechecked.metadata.get('voice_transcribed')}，"
               f"voice_context 有值={prechecked.metadata.get(VOICE_CONTEXT_KEY) is not None}）")

        print("\n④ 外部发送者不再是空 sender_id")
        events.clear()
        client.post(WEBHOOK, json=_eventBody(userId="", openId="ou_external_live"))
        _waitUntil(lambda: len(events) >= 1, 3.0)
        _check(bool(events) and events[0].sender_id == "ou_external_live",
               f"只带 open_id 的外部用户 sender_id 落到了 open_id（实得 "
               f"{events[0].sender_id if events else None!r}）")

        print("\n⑤ @提及：结构化 + 昵称替换")
        events.clear()
        client.post(WEBHOOK, json=_eventBody(
            messageType="text",
            content=json.dumps({"text": "@_user_1 看下这份报表"}),
            mentions=[{"key": "@_user_1", "name": "小明", "id": {"open_id": "ou_open"}}]))
        _waitUntil(lambda: len(events) >= 1, 3.0)
        mentionMsg = events[0] if events else None
        _check(mentionMsg is not None and (mentionMsg.metadata or {}).get("mentions"),
               f"mentions 结构化进 metadata（实得 "
               f"{(mentionMsg.metadata or {}).get('mentions') if mentionMsg else None!r}）")
        _check(mentionMsg is not None and "@_user_1" not in mentionMsg.content
               and "小明" in mentionMsg.content,
               f"正文占位符换成昵称（实得 {getattr(mentionMsg, 'content', None)!r}）")

        print("\n⑥ 仿冒的语音回调仍然进不来")
        events.clear()
        forged = _eventBody()
        forged["header"]["token"] = "not-the-token"
        r = client.post(WEBHOOK, json=forged)
        _check(r.status_code in (400, 401, 403) and not events,
               f"错令牌的语音回调被拒且 0 事件（HTTP={r.status_code}，事件 {len(events)} 条）")

        print("\n⑦ 文本事件照常（对照）")
        events.clear()
        client.post(WEBHOOK, json=_eventBody(messageType="text",
                                             content=json.dumps({"text": "普通文字"})))
        _waitUntil(lambda: len(events) >= 1, 3.0)
        _check(bool(events) and events[0].content == "普通文字",
               f"文本支未被波及（实得 {events[0].content if events else None!r}）")

        mgr.unregister_adapter("feishu")
        _check(mgr.get_adapter("feishu") is None, "收尾：临时适配器已从管理器摘净")

    server.shutdown()
    print()
    print("  边界：假平台桩按仓内请求形状应答，证的是本仓这条链通，不证与真飞书逐字节互操作。")
    if failures:
        print(f"活体未过：{len(failures)} 项")
        for item in failures:
            print("  - " + item)
        return 1
    print("活体全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
