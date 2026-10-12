# -*- coding: utf-8 -*-
"""§6-168 阶段一活体自证：回合语音真能出到渠道（全链路，除 agent 本体外都真）。

边界说明（不糊）：`agent.chat()` 用替身——真跑它会调 LLM、花服务商额度，而本批要验的不是
模型而是"音频有没有走出渠道"。其余全是生产对象：真 `TTSManager`（mock 引擎离线出 WAV）、
真 `channel_router.make_handler`、真 `ChannelManager` 回发链、真 `FeishuAdapter` 上传+发送两跳，
网络出口只到 127.0.0.1 的本地桩（不开外网、不碰飞书域名）。

四段：
① TTS 产物是真的 WAV（非空、RIFF 头、有采样帧）——否则后面全是空谈。
② 真 router：回合返回 audio_path 时，回发项里带出语音条（旧行为：只取 text，音频被丢）。
③ 真 manager + 真 FeishuAdapter：两跳真发生（multipart 上传 → file 消息带 file_key），
   且桩侧收到的字节就是①那个文件的内容。
④ 真 manager + 不支持语音的渠道：文本照常送达、不发语音，且日志点名（今天正是静默丢弃）。
"""

import asyncio
import os
import pathlib
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

failures: list[str] = []


def _check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


class _Stub(BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        type(self).seen.append({
            "path": self.path,
            "content_type": self.headers.get("Content-Type") or "",
            "body": self.rfile.read(length),
        })
        payload = b'{"code": 0, "data": {"file_key": "fk_live", "message_id": "om_live"}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class _StubAgent:
    """只替 agent 本体（避免调 LLM）；返回值形状按 chat_pipeline 的真实产物键取。"""

    def __init__(self, reply: str, audio_path: str):
        self._resp = {"text": reply, "audio_path": audio_path}
        self.current_reasoning = ""

    def get_tool_messages_snapshot(self):
        return []

    async def chat(self, user_input="", session_id=None, metadata=None, **kw):
        return dict(self._resp)


async def _makeRealWav(dest: pathlib.Path) -> bool:
    from neurova.tts.mock_tts_simple import MockTTSSimple

    engine = MockTTSSimple()
    if not await engine.initialize():
        return False
    audio = await engine.synthesize("这是给渠道的语音回复")
    if not audio:
        return False
    dest.write_bytes(audio)
    return True


def main() -> int:
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    root = isolatedDataRoot()
    workdir = tempfile.mkdtemp(prefix="voiceEgress-")
    print(f"数据根（临时）：{root}")

    _Stub.seen = []
    server = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stubBase = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"本地桩（假飞书）：{stubBase}")

    try:
        from neurova.channels.base import ChannelConfig, ChannelMessage
        from neurova.channels.channel_router import make_handler
        from neurova.channels.feishu import FeishuAdapter
        from neurova.channels.manager import ChannelManager
        from neurova.channels.voice_egress import VOICE_OUT_NONE, VoiceReply
        from neurova.core.logger import get_logger

        print("\n① TTS 产物是真的 WAV")
        wav = pathlib.Path(workdir) / "tts_live_sess_1.wav"
        ok = asyncio.run(_makeRealWav(wav))
        _check(ok and wav.is_file() and wav.stat().st_size > 1000,
               f"真引擎落盘：{wav.name} 大小={wav.stat().st_size if wav.exists() else 0}")
        _check(wav.read_bytes()[:4] == b"RIFF", "产物是 RIFF/WAVE（不是随便一段字节）")

        print("\n② 真 router 把语音条带进回发项")
        ChannelManager._instance = None
        mgr = ChannelManager()
        handler = make_handler(mgr, lambda aid: _StubAgent("文字回复", str(wav)))
        msg = ChannelMessage(
            channel_type="feishu", message_id="m_live", sender_id="ou_live", sender_name="ou_live",
            content="你好", chat_id="oc_live", chat_type="p2p", metadata={"agent_id": "default"},
        )
        parts = asyncio.run(handler(msg))
        voice = [p for p in (parts or []) if isinstance(p, VoiceReply)]
        _check(any(isinstance(p, str) and "文字回复" in p for p in parts), "文本条仍在位")
        _check(len(voice) == 1, f"回发项里有语音条（实得 {len(voice)}）")

        print("\n③ 真 manager + 真 FeishuAdapter：上传与发送两跳真发生")
        adapter = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="cli_stub", app_secret="s"))
        adapter.api_base = f"{stubBase}/open-apis"
        adapter.open_base = stubBase
        adapter._token_lock = threading.Lock()
        adapter._tenant_access_token = "t-stub"
        adapter._token_expires_at = 4e12
        adapter._connected = True
        mgr._adapters["feishu"] = adapter

        asyncio.run(mgr._sendReplyItems(msg, parts))

        # 只看语音那两跳：文本条走 lark SDK，它有自己的 token manager（也被钉到了本地桩，
        # 所以会出现一条 auth 请求）——那不是本段的判据对象。
        voiceHops = [s for s in _Stub.seen if "/im/v1/" in s["path"]]
        hops = [s["path"].split("?")[0].rsplit("/im/", 1)[-1] for s in voiceHops]
        print(f"  桩侧收到：{[s['path'] for s in _Stub.seen]}")
        print(f"  语音两跳：{hops}")
        _check(hops == ["v1/files", "v1/messages"], f"两跳顺序：{hops}")
        _check(bool(voiceHops) and voiceHops[0]["content_type"].startswith("multipart/form-data"),
               "第一跳是 multipart 上传")
        _check(any(wav.read_bytes()[64:128] in s["body"] for s in _Stub.seen),
               "对岸收到的字节就是本轮那段音频（不是空 form）")
        _check(len(_Stub.seen) >= 2 and b"fk_live" in _Stub.seen[-1]["body"],
               "第二跳消息带上了上传返回的 file_key")

        print("\n④ 不支持语音的渠道：文本照常、不发语音、日志点名")

        class _TextOnly:
            channel_type = "probe_text"
            voiceOutMode = VOICE_OUT_NONE
            is_connected = True

            def __init__(self):
                self.sent = []

            async def send_message(self, chat_id, content, message_type="text", **kw):
                self.sent.append(message_type)
                return "mid"

            async def connect(self):
                return True

        textOnly = _TextOnly()
        mgr._adapters["probe_text"] = textOnly
        records: list = []

        import logging as _logging

        class _Collect(_logging.Handler):
            def emit(self, record):
                records.append(record)

        mgrLogger = get_logger("neurova.channels.manager")
        collector = _Collect()
        mgrLogger.addHandler(collector)
        try:
            msg2 = ChannelMessage(
                channel_type="probe_text", message_id="m_live2", sender_id="u2", sender_name="u2",
                content="你好", chat_id="chat_2", chat_type="p2p", metadata={"agent_id": "default"},
            )
            # 以同一生产分派口驱动（音频那段已在②③验过，这里不再走一次 agent 替身）
            asyncio.run(mgr._sendReplyItems(msg2, ["文字回复", VoiceReply(file_path=str(wav))]))
        finally:
            mgrLogger.removeHandler(collector)

        _check(textOnly.sent == ["text"], f"只发了文本（实得 {textOnly.sent}）")
        named = [r for r in records if r.levelname in {"WARNING", "ERROR"} and "语音" in r.getMessage()]
        _check(bool(named), f"丢弃被点名：{[r.getMessage()[:80] for r in named]}")
    finally:
        server.shutdown()
        server.server_close()

    print("\n" + ("活体全过" if not failures else f"{len(failures)} 处未过：\n- " + "\n- ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
