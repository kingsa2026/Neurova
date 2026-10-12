# -*- coding: utf-8 -*-
"""§6-168 缺口①活体自证：用户发来一段语音，拿回的是一段真音频（往返全链，除模型外都真）。

与 `channelVoiceEgress_live.py` 的分工：那一支只证出站半区（回合产物能不能出渠道），
这一支从**入站**起链——两条活路（Telegram 轮询、飞书 Stream 事件）各自真解析一条平台
语音消息，经真 `ChannelManager` 收口处的真 `transcribe_voice_message`，进真
`channel_router.make_handler`，再由真适配器把回合 TTS 产物发回渠道。

边界说明（不糊）：
- 平台服务器 = 127.0.0.1 本地桩（不开外网、不碰 telegram/飞书域名、不花服务商额度）；
- ASR = 真 `MockASREngine` 对象（`neurova/asr/mock_asr.py`），不是随手写的 lambda——预检读的是它的真返回键；
- TTS = 真 `MockTTSSimple`，产物是真 WAV 文件；
- `agent.chat()` = 替身（真跑要调 LLM 花额度，本支验的是链路不是模型）；
- 飞书适配器的 `connect()` 被钉成硬失败：它起的是真 lark WebSocket 会话，判据/活体都不许有
  通向外部的出口（§6-168 记的那形，本批在"发送前发现未连接"这条分支上又撞见一次）。

四段读数：
① Telegram 真 `_process_update` → 消息带 `audio_bytes`、类型 voice，桩侧真发生 getFile→下载两跳；
② 真预检把占位换成转写文本，进回合的正文不是 "[语音]"；
③ 飞书真入站事件 → 真 manager → 真 router → 真上传+真发送，桩侧收到的字节 == 本轮 TTS 产物；
④ 不支持语音出站的渠道（真 Telegram 适配器，能力默认 none）：文本照常、语音点名丢弃。
"""

import asyncio
import json
import logging
import pathlib
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

failures: list[str] = []


def _check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def _run(coro):
    return asyncio.run(coro)


class _PlatformStub(BaseHTTPRequestHandler):
    """一个桩同时扮 Telegram 与飞书：按路径分形，记录每一跳。"""

    seen: list = []
    tgVoice = b"TELEGRAM-OGG-VOICE-BYTES"
    fsVoice = b"FEISHU-AUDIO-VOICE-BYTES"

    def _json(self, payload: dict):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _raw(self, body: bytes, mime: str):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        type(self).seen.append({"platform": "telegram", "method": "GET", "path": self.path})
        if "/getFile" in self.path:
            return self._json({"ok": True, "result": {"file_path": "voice/live_1.ogg"}})
        if self.path.startswith("/file/bot"):
            return self._raw(type(self).tgVoice, "audio/ogg")
        if "/resources/" in self.path:
            type(self).seen[-1]["platform"] = "feishu"
            return self._raw(type(self).fsVoice, "audio/mpeg")
        return self._json({"ok": False, "description": f"unexpected GET {self.path}"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        type(self).seen.append({
            "platform": "telegram" if self.path.startswith("/bot") else "feishu",
            "method": "POST", "path": self.path,
            "content_type": self.headers.get("Content-Type") or "", "body": body,
        })
        if self.path.startswith("/bot"):
            return self._json({"ok": True, "result": {"message_id": 900900}})
        if "tenant_access_token" in self.path:
            return self._json({"code": 0, "tenant_access_token": "t-live", "expire": 3600})
        if "/im/v1/files" in self.path:
            return self._json({"code": 0, "data": {"file_key": "fk_live_rt"}})
        if "/im/v1/messages" in self.path:
            return self._json({"code": 0, "data": {"message_id": "om_live_rt"}})
        return self._json({"ok": False, "description": f"unexpected POST {self.path}"})

    def log_message(self, *args):
        pass


class _StubAgent:
    """只替 agent 本体；返回值按 chat_pipeline 的真实产物键取，并把收到的正文交回来。"""

    def __init__(self, reply: str, audioPath: pathlib.Path, sink: list):
        self._resp = {"text": reply, "audio_path": str(audioPath)}
        self._sink = sink
        self.current_reasoning = ""

    def get_tool_messages_snapshot(self):
        return []

    async def chat(self, user_input="", session_id=None, metadata=None, **kw):
        self._sink.append(user_input)
        return dict(self._resp)


class _FsUserIds:
    user_id = ""
    open_id = "ou_live_rt"
    union_id = ""


class _FsSender:
    sender_id = _FsUserIds()


class _FsMessage:
    def __init__(self, messageType: str, content: str):
        self.message_id = "om_live_in"
        self.chat_id = "oc_live_rt"
        self.chat_type = "p2p"
        self.message_type = messageType
        self.content = content
        self.mentions = None


class _FsEventBody:
    def __init__(self, message):
        self.message = message
        self.sender = _FsSender()


class _FsEvent:
    def __init__(self, message):
        self.event = _FsEventBody(message)


def _makeRealWav(dest: pathlib.Path) -> bool:
    from neurova.tts.mock_tts_simple import MockTTSSimple

    engine = MockTTSSimple()
    if not _run(engine.initialize()):
        return False
    audio = _run(engine.synthesize("这段语音是回合的回复"))
    if not audio:
        return False
    dest.write_bytes(audio)
    return True


def _waitUntil(predicate, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def main() -> int:
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    root = isolatedDataRoot()
    workdir = tempfile.mkdtemp(prefix="voiceRoundTrip-")
    print(f"数据根（临时）：{root}")

    _PlatformStub.seen = []
    server = HTTPServer(("127.0.0.1", 0), _PlatformStub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stubBase = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"本地桩（假平台）：{stubBase}")

    from neurova.asr.mock_asr import MockASREngine
    from neurova.channels import voice_precheck
    from neurova.channels.base import (
        ChannelConfig,
        ChannelMessage,
    )
    from neurova.channels.channel_router import make_handler
    from neurova.channels.feishu import FeishuAdapter
    from neurova.channels.manager import ChannelManager
    from neurova.channels.telegram_adapter import TelegramAdapter
    from neurova.channels.voice_egress import VoiceReply
    from neurova.channels.voice_ingress import AUDIO_BYTES_KEY

    # 一个跑在后台线程的事件循环，扮生产里的主循环（适配器回调都往它投）
    mainLoop = asyncio.new_event_loop()
    threading.Thread(target=mainLoop.run_forever, daemon=True).start()
    time.sleep(0.2)

    try:
        print("\n① Telegram 真解析一条语音消息：字节到、类型对、两跳真发生")
        tg = TelegramAdapter()
        tg.API_BASE = stubBase
        tg.bot_token = "15:livetoKen"
        tg._initialized = True
        received: list = []

        async def _capture(_eventType, message):
            received.append(message)

        tg.set_event_callback(_capture)
        tg._main_loop = mainLoop

        ChannelManager._instance = None
        mgr = ChannelManager()
        # telegram 的注册留到④：`register_adapter` 会顶掉①段自己设的事件回调，
        # 早注册会让①读不到消息——那是夹具的顺序问题，不是链路坏了。

        update = {
            "update_id": 9001,
            "message": {
                "message_id": 9001,
                "from": {"id": 4242, "username": "live_user"},
                "chat": {"id": 4242, "type": "private"},
                "voice": {"file_id": "vf_live", "duration": 2, "mime_type": "audio/ogg"},
            },
        }
        # 同步调用即生产形状：轮询线程里调它，事件用 run_coroutine_threadsafe 投回主 loop
        tg._process_update(update)
        _waitUntil(lambda: bool(received), 5)

        message = received[0] if received else None
        hops = [s["path"] for s in _PlatformStub.seen if s["platform"] == "telegram"]
        _check(bool(received), f"语音消息到达事件回调（收到 {len(received)} 条）")
        _check(getattr(message, "message_type", None) == "voice",
               f"类型标成 voice（实得 {getattr(message, 'message_type', None)!r}）")
        _check(bool(message and message.metadata.get(AUDIO_BYTES_KEY)), "metadata 带真音频字节")
        _check(message is not None and message.metadata.get(AUDIO_BYTES_KEY) == _PlatformStub.tgVoice,
               "字节就是桩那一跳交回的原始语音")
        _check(len(hops) == 2 and "/getFile" in hops[0] and hops[1].startswith("/file/bot"),
               f"两跳顺序 getFile→下载：{hops}")

        print("\n② 真预检把占位换成转写文本（ASR 用真 MockASREngine 对象）")
        asr = MockASREngine(transcribe_text="帮我看下明天的排程")
        _run(asr.initialize())
        voice_precheck._get_asr_transcriber = lambda: asr.transcribe
        if message is not None:
            outMsg = _run(voice_precheck.transcribe_voice_message(message))
            _check(outMsg.content == "帮我看下明天的排程",
                   f"预检后正文是转写文本（实得 {outMsg.content!r}）")
            _check(outMsg.metadata.get("voice_transcribed") is True, "转写成功被如实标注")

        print("\n③ 飞书语音往返：真入站事件 → 真 manager → 真 router → 真上传+真发送")
        wav = pathlib.Path(workdir) / "tts_live_roundtrip.wav"
        _check(_makeRealWav(wav) and wav.read_bytes()[:4] == b"RIFF",
               f"回合 TTS 产物是真 WAV：{wav.stat().st_size if wav.exists() else 0} 字节")

        seenInput: list = []
        fs = FeishuAdapter(ChannelConfig(
            channel_type="feishu", app_id="cli_live", app_secret="sec_live"))
        fs.api_base = stubBase
        fs.open_base = stubBase

        async def _forbidConnect(*_a, **_kw):
            raise AssertionError("活体脚本触发了真连接出口：适配器不应在这里 connect")

        fs.connect = _forbidConnect
        fs._connected = True
        mgr.register_adapter(fs, agent_id="default")
        mgr._message_handlers = [
            (50, "rt-handler", make_handler(mgr, lambda _aid: _StubAgent("明天上午两点有会", wav, seenInput)))
        ]

        _PlatformStub.seen = []
        fs._main_loop = mainLoop
        fs._handle_message_event(_FsEvent(_FsMessage(
            "audio", json.dumps({"file_key": "fk_live_in"}))))
        # 这一回合含真装配（会话/记忆/队列），本机实测要十几秒；等待窗口按实测给足，
        # 不然读到的是"还没走到出站"而不是"出站坏了"（默认超时打断慢用例那一形）。
        _waitUntil(lambda: any("/im/v1/messages" in s["path"] and b'"file"' in s.get("body", b"")
                           for s in _PlatformStub.seen), 90)

        upload = [s for s in _PlatformStub.seen if "/im/v1/files" in s["path"]]
        send = [s for s in _PlatformStub.seen
                if "/im/v1/messages" in s["path"] and b'"file"' in s.get("body", b"")]
        inboundDownload = [s for s in _PlatformStub.seen if "/resources/" in s["path"]]
        _check(bool(inboundDownload), "入站语音的下载跳真发生（平台引用换成字节）")
        _check(bool(seenInput) and seenInput[-1] == "帮我看下明天的排程",
               f"进回合的正文是转写文本，不是占位（实得 {seenInput[-1:]!r}）")
        _check(bool(upload) and wav.read_bytes() in upload[0]["body"],
               "出站上传那一跳的 multipart 体里是本轮那段 WAV 的字节")
        _check(bool(send) and b'"file"' in send[-1]["body"] and b"fk_live_rt" in send[-1]["body"],
               "发消息那一跳按 file 类型带上刚上传的 file_key")
        _check(bool(upload) and bool(send)
               and _PlatformStub.seen.index(upload[0]) < _PlatformStub.seen.index(send[0]),
               "先上传后发送（顺序反了平台会拒收）")

        print("\n④ 不支持语音出站的渠道：文本照常、语音点名丢弃（真 Telegram 适配器，能力默认 none）")

        async def _forbidTelegramConnect(*_a, **_kw):
            raise AssertionError("活体脚本触发了真连接出口：telegram 不应在这里 connect")

        tg.connect = _forbidTelegramConnect
        tg._connected = True  # 发送路径见"未连接"会去 connect（①段那种起轮询线程的连接）
        mgr.register_adapter(tg, agent_id="default")
        _PlatformStub.seen = []
        records: list = []

        class _Collector(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        mgrLogger = logging.getLogger("neurova.channels.manager")
        collector = _Collector()
        mgrLogger.addHandler(collector)
        try:
            textOnlyMsg = ChannelMessage(
                channel_type="telegram", message_id="m_tg_out", sender_id="4242",
                sender_name="live_user", content="文字问答", chat_id="4242", chat_type="p2p",
                metadata={"agent_id": "default"},
            )
            _run(mgr._sendReplyItems(textOnlyMsg, ["这是文字回复", VoiceReply(file_path=str(wav))]))
        finally:
            mgrLogger.removeHandler(collector)

        telegramHops = [s for s in _PlatformStub.seen if s["platform"] == "telegram"]
        # 文本按 JSON 送出，中文是 \uXXXX 转义——按字节比原始 UTF-8 会读成"没送到"
        sentTexts = []
        for hop in telegramHops:
            if "/sendMessage" in hop["path"]:
                try:
                    sentTexts.append(json.loads(hop["body"].decode("utf-8")).get("text", ""))
                except (ValueError, AttributeError):
                    sentTexts.append("")
        _check(any("语音" in m for m in records), f"丢弃被点名：{[m[:60] for m in records]}")
        _check("这是文字回复" in sentTexts,
               "文本照常送出（telegram 侧跳数 " + str(len(telegramHops)) + "）")
        _check(not [s for s in telegramHops if "/getFile" in s["path"] or "/file/bot" in s["path"]],
               "没为不支持语音的渠道去取或发语音（一次多余的平台请求都不该有）")

        print()
        if failures:
            print(f"活体未过：{len(failures)} 项")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("活体全过")
        return 0
    finally:
        server.shutdown()
        server.server_close()
        mainLoop.call_soon_threadsafe(mainLoop.stop)
        time.sleep(0.2)


if __name__ == "__main__":
    sys.exit(main())
