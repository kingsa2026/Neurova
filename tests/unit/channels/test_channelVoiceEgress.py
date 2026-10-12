"""渠道语音出站契约（§6-168 阶段一 · 缺口②的调用点接线）。

复核过的前置：传输层早就支持类型化回发（`manager.send_message(..., message_type=...)`
在 `manager.py:211-256`，全部适配器签名齐备且有契约测试 `test_b4_gen1_send_signature.py`
钉着），**缺的是两个调用点**——`channel_router` 只读 `resp["text"]` 拼文本条，把回合已经
生成好的 `audio_path`（`post_chat_pipeline._step_generate_tts` 落盘 → `chat_pipeline.py:2933`）
整份丢掉；`manager._dispatch_message` 回发时也不传类型。所以本批不新造出站机制，
只做三件事：把音频从回合结果带到回发项、按渠道能力决定怎么发、发不出去时点名而不是静默。

判据拦四种退化：
- 接了却不带上（音频又被丢了）；
- 文件不存在也照样发（谎报有语音）；
- 渠道不支持时静默丢弃（今天就是这一形）；
- **只声明能力、不实现出口**（置个 True 就当支持——本仓反复出现的"文档/标志声称有、
  代码没有"形态），故有一格按 AST 验"声明支持的适配器真消费那条路径"，并配反向对照。
"""

import ast
import inspect
import json
import pathlib
import wave

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
CHANNELS = REPO / "neurova" / "channels"

from neurova.channels.voice_egress import (  # noqa: E402
    VOICE_OUT_AUDIO_FILE,
    VOICE_OUT_NONE,
    VoiceReply,
    resolveVoiceReply,
)


def _makeWav(path: pathlib.Path, seconds: float = 0.05) -> pathlib.Path:
    """真 WAV 文件（不是随便写几个字节）——出站判据要能证明带得出去的是可读音频。"""
    frames = int(8000 * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * frames)
    return path


class _FakeAgent:
    """替身只替"agent 回合"这一边界：返回生产同款 dict（含 audio_path）。

    字段名按 `chat_pipeline.py:2931-2934` 的真实产物键取，不自造键名。
    """

    def __init__(self, resp):
        self._resp = resp
        self.config = type("C", (), {"show_thinking": False, "show_tool_messages": False})()
        self.current_reasoning = ""

    def get_tool_messages_snapshot(self):
        return []

    async def chat(self, user_input="", session_id="", metadata=None, **kw):
        return dict(self._resp)


class _RecordingAdapter:
    """实现 base 契约形状的假适配器：记录收到的 message_type 与 kwargs。"""

    def __init__(self, channel_type="probe", voice_out=VOICE_OUT_NONE, connected=True):
        self.channel_type = channel_type
        self.voiceOutMode = voice_out
        self.is_connected = connected
        self.sent = []

    async def connect(self):
        self.is_connected = True
        return True

    async def disconnect(self):
        self.is_connected = False

    async def send_message(self, chat_id, content, message_type="text", **kwargs):
        self.sent.append({"chat_id": chat_id, "content": content, "message_type": message_type, **kwargs})
        return "msg_1"


def _routerHandler(manager, agent):
    from neurova.channels.channel_router import make_handler

    return make_handler(manager, lambda agent_id: agent)


class TestTurnAudioReachesReplyItems:
    """用真 `ChannelManager` + 真 handler 驱动（`ChannelManager` 是单例，必须重置——
    沿用 tests/unit/channels/test_channel_router.py 的夹具口径，不另造假 manager：
    假对象缺真接口会把红落在 AttributeError 上，而不是落在行为上）。"""

    @staticmethod
    def _manager():
        from neurova.channels.manager import ChannelManager

        ChannelManager._instance = None
        return ChannelManager()

    @pytest.mark.asyncio
    async def test_audioPathBecomesAVoiceReplyItem(self, tmp_path):
        """回合带真音频文件时，回发项里必须出现一条语音项并带上那条路径。"""
        wav = _makeWav(tmp_path / "tts_sess-1_1700000000.wav")
        agent = _FakeAgent({"text": "这是回答", "audio_path": str(wav)})
        handler = _routerHandler(self._manager(), agent)

        parts = await handler(_inboundMessage())

        voice = [p for p in (parts or []) if isinstance(p, VoiceReply)]
        assert len(voice) == 1, f"回合生成了音频，回发项里却没有语音条：{parts}"
        assert pathlib.Path(voice[0].file_path) == wav, "语音项带的不是回合那条音频路径"
        assert any(isinstance(p, str) and "这是回答" in p for p in parts), "文本条不能因加语音而丢失"

    @pytest.mark.asyncio
    async def test_absentAudioFileProducesNoVoiceItem(self, tmp_path):
        """路径指向不存在的文件 ⇒ 不得产出语音项（不能对着空气发语音）。"""
        ghost = tmp_path / "tts_sess-1_1700000001.wav"
        agent = _FakeAgent({"text": "这是回答", "audio_path": str(ghost)})
        parts = await _routerHandler(self._manager(), agent)(_inboundMessage())

        assert [p for p in (parts or []) if isinstance(p, VoiceReply)] == []
        assert any(isinstance(p, str) and "这是回答" in p for p in parts)

    def test_capabilityVocabularyIsSingleSource(self):
        """适配器声明能力只能引用契约常量，不得自写字面串（防第二份词汇表）。

        按**属性赋值形状**判而不是扫字符串值——`"none"` 这类词在别的语义里到处都是
        （websocket.py 的 mode 判断就有），扫值会既假红又漏（§6-166 刚记的那枚形态，
        本档第一版自己就踩了一次）。
        """
        offenders = []
        for path in sorted(CHANNELS.rglob("*.py")):
            if "__pycache__" in path.parts or path.name == "voice_egress.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            for node in ast.walk(tree):
                targets = []
                value = None
                if isinstance(node, ast.Assign):
                    targets, value = node.targets, node.value
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    targets, value = [node.target], node.value
                for t in targets:
                    if isinstance(t, ast.Attribute) and t.attr == "voiceOutMode":
                        if not (isinstance(value, ast.Name) and value.id.startswith("VOICE_OUT_")):
                            offenders.append(f"{path.relative_to(REPO).as_posix()}:{node.lineno}")
        assert offenders == [], f"voiceOutMode 被赋成契约之外的字面量：{offenders}"


class TestManagerDispatchByCapability:
    def _managerWith(self, adapter):
        from neurova.channels.manager import ChannelManager

        ChannelManager._instance = None
        mgr = ChannelManager()
        mgr._adapters[adapter.channel_type] = adapter
        return mgr

    @staticmethod
    async def _dispatch(mgr, items):
        """走真入口 `_dispatch_message`（处理器返回回发项）。

        不直调本批新增的 helper：那样"改前"的红会是 AttributeError（形状红），
        证明不了行为没接上。
        """
        async def _handler(_msg):
            return items

        mgr._message_handlers = [(50, "probe-handler", _handler)]
        await mgr._dispatch_message(_inboundMessage())

    @pytest.mark.asyncio
    async def test_supportingChannelSendsVoiceWithBoundShape(self, tmp_path):
        """声明支持的渠道：必须收到 message_type="voice" 且 file_path 指向真音频。

        调用形状用 `inspect.signature().bind` 校——此前桩件与被调点犯同一个错时，
        测试一路"通过"着生产里必抛的形状（记忆条目：桩件替坏契约背书）。
        """
        wav = _makeWav(tmp_path / "tts_sess-1_1700000002.wav")
        adapter = _RecordingAdapter(voice_out=VOICE_OUT_AUDIO_FILE)
        mgr = self._managerWith(adapter)

        sig = inspect.signature(adapter.send_message)
        sig.bind("chat-1", "", message_type="voice", file_path=str(wav))  # 契约必须收得下这套 kwargs

        await self._dispatch(mgr, [VoiceReply(file_path=str(wav))])

        voiceSends = [s for s in adapter.sent if s["message_type"] == "voice"]
        assert voiceSends, f"支持语音出站的渠道没收到语音发送调用：{adapter.sent}"
        assert voiceSends[0]["file_path"] == str(wav)

    @pytest.mark.asyncio
    async def test_unsupportingChannelNamesTheDrop(self, tmp_path):
        """不支持的渠道：文本照常发、不发语音，但必须在日志里点名（今天正是静默丢弃）。"""
        wav = _makeWav(tmp_path / "tts_sess-1_1700000003.wav")
        adapter = _RecordingAdapter(channel_type="probe", voice_out=VOICE_OUT_NONE)
        mgr = self._managerWith(adapter)

        records = _attachCollector(_channelLogger())
        try:
            await self._dispatch(mgr, ["这是回答", VoiceReply(file_path=str(wav))])
        finally:
            records.detach()

        assert [s for s in adapter.sent if s["message_type"] == "voice"] == []
        assert any(s["message_type"] == "text" for s in adapter.sent), "文本回发不能被语音那格打断"
        loud = [r for r in records.items if r.levelname in {"WARNING", "ERROR"} and "语音" in r.getMessage()]
        assert loud, "音频被丢弃却没在日志里点名——静默丢弃正是本批要根修的形态"

    def test_resolveVoiceReplyDoesNotInventAPath(self, tmp_path):
        """能力判定单点：文件不在位一律降级，不把不存在的路径交给适配器。"""
        missing = tmp_path / "nope.wav"
        assert resolveVoiceReply(str(missing), VOICE_OUT_AUDIO_FILE) is None
        ok = _makeWav(tmp_path / "tts_sess-1_1700000004.wav")
        resolved = resolveVoiceReply(str(ok), VOICE_OUT_AUDIO_FILE)
        assert resolved is not None and pathlib.Path(resolved.file_path) == ok


class TestDeclaredCapabilityMustBeImplemented:
    """反空转格：凡声明支持语音出站的适配器，`send_message` 里必须真消费那条路径。"""

    _MODE_ATTRS = ("voiceOutMode",)

    def _declarations(self):
        out = []
        for path in sorted(CHANNELS.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
                mode = None
                for stmt in cls.body:
                    if isinstance(stmt, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id in self._MODE_ATTRS for t in stmt.targets
                    ):
                        mode = _constName(stmt.value)
                if mode in {VOICE_OUT_AUDIO_FILE}:
                    out.append((cls.name, path, mode))
        return out

    def test_everyDeclaringAdapterReadsTheFilePath(self):
        offenders = []
        for cls_name, path, mode in self._declarations():
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name)
            send = next((n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "send_message"), None)
            if send is None:
                offenders.append(f"{cls_name}: 无 send_message")
                continue
            read = {n.id for n in ast.walk(send) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
            usesKwargs = "kwargs" in read or "file_path" in read
            if not usesKwargs:
                offenders.append(f"{cls_name}: 声明 {mode} 却不读音频路径")
        assert offenders == [], f"声明了语音出站能力却没有出口：{offenders}"

    def test_detectorIsNotBlind(self):
        """反向对照：同一段代码里把 send_message 换成不读任何 kwargs，探测器必须报出来。"""
        src = "class A:\n    voiceOutMode = VOICE_OUT_AUDIO_FILE\n    async def send_message(self, c, x, **kw):\n        return 1\n"
        tree = ast.parse(src)
        cls = tree.body[0]
        send = cls.body[1]
        read = {n.id for n in ast.walk(send) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        assert "kwargs" not in read and "file_path" not in read


class TestFeishuEgressIsReal:
    """声明 `audio_file` 的那条渠道必须真把两步走完：上传拿 file_key → 发文件消息。

    用本地回环真 HTTP 桩（127.0.0.1）收两跳——不开外网、不碰飞书域名。
    这一档存在的理由：`voiceOutMode` 只是声明，声明与实现可以各说各话
    （§6-168 反空转格那形，也是本仓"文档/标志声称有、代码没有"的复发点）。
    """

    @staticmethod
    def _stubServer():
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        seen = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                seen.append({
                    "path": self.path,
                    "content_type": self.headers.get("Content-Type") or "",
                    "body": self.rfile.read(length),
                })
                payload = b'{"code": 0, "data": {"file_key": "fk_1", "message_id": "om_1"}}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), H)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, seen, thread

    def _adapter(self, apiBase):
        from neurova.channels.base import ChannelConfig
        from neurova.channels.feishu import FeishuAdapter

        adapter = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="cli_x", app_secret="s"))
        # 两个基址都钉到本地桩：`api_base` 是我这条路用的，`open_base` 是 lark SDK 用的。
        # 只钉前者会在"改前"状态下让判据掉进 SDK 分支、真的朝 open.feishu.cn 发出
        # 一次取 token 的请求（实测：假凭据被回 code 10003）。判据不许有任何一条
        # 出口通向外部服务——包括它不该走到的那条。
        adapter.api_base = f"{apiBase}/open-apis"
        adapter.open_base = apiBase
        import threading as _th

        adapter._token_lock = _th.Lock()
        adapter._tenant_access_token = "t-stub"
        adapter._token_expires_at = 4e12
        return adapter

    @pytest.mark.asyncio
    async def test_voiceSendUploadsThenSendsFileMessage(self, tmp_path):
        server, seen, thread = self._stubServer()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            wav = _makeWav(tmp_path / "tts_sess-1_1700000009.wav")
            adapter = self._adapter(base)

            mid = await adapter.send_message("oc_1", "", "voice", file_path=str(wav))

            assert mid == "om_1", f"语音发送没拿到消息号（实得 {mid!r}）"
            # 按后缀比：`api_base` 含 /open-apis 前缀（生产就是这么拼的），判据不该把它写死
            hops = [s["path"].split("?")[0].rsplit("/im/", 1)[-1] for s in seen]
            assert hops == ["v1/files", "v1/messages"], f"两跳顺序/路径不对：{[s['path'] for s in seen]}"
            assert seen[0]["content_type"].startswith("multipart/form-data"), "上传不是 multipart"
            assert b"fk_1" in seen[1]["body"], "文件消息没带上上传回来的 file_key"
            assert b'"msg_type": "file"' in seen[1]["body"] or b'"msg_type":"file"' in seen[1]["body"], (
                "第二条消息的 msg_type 不是 file"
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    @pytest.mark.asyncio
    async def test_missingAudioFileSendsNothing(self, tmp_path):
        """文件不在位 ⇒ 一跳都不发（不能先发消息再报失败，那等于对用户谎报）。"""
        server, seen, thread = self._stubServer()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            adapter = self._adapter(base)
            mid = await adapter.send_message("oc_1", "", "voice", file_path=str(tmp_path / "absent.wav"))
            assert mid is None
            assert seen == [], f"音频不在位却仍向平台发了请求：{[s['path'] for s in seen]}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_declaringModeIsBackedByAnUploadCall(self):
        """AST 反查：声明 audio_file 的适配器，其语音分支必须真调用上传面。"""
        src = (CHANNELS / "feishu.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "FeishuAdapter")
        called = {
            getattr(c.func, "attr", "")
            for fn in [m for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for c in ast.walk(fn)
            if isinstance(c, ast.Call)
        }
        assert "upload_file" in called, "声明支持音频出站却不上传素材"


def _constName(node):
    """取常量引用名（`VOICE_OUT_AUDIO_FILE` 或字符串字面量）。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _inboundMessage():
    from neurova.channels.base import ChannelMessage

    return ChannelMessage(
        channel_type="probe",
        message_id="m_1",
        sender_id="u_1",
        sender_name="u_1",
        content="你好",
        chat_id="chat-1",
        chat_type="p2p",
        metadata={"agent_id": "default"},
    )


def _channelLogger():
    from neurova.core.logger import get_logger

    return get_logger("neurova.channels.manager")


def _attachCollector(logger):
    import logging

    class Collector(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.DEBUG)
            self.items = []

        def emit(self, record):
            self.items.append(record)

    c = Collector()
    logger.addHandler(c)
    prior = logger.level
    logger.setLevel(logging.DEBUG)

    def detach():
        logger.removeHandler(c)
        logger.setLevel(prior)

    c.detach = detach  # type: ignore[attr-defined]
    return c


def test_replyContractIsSerializableForLogs():
    """VoiceReply 要能在被记日志/调试时自证内容（不是裸对象）；同时不被当成文本发出去。"""
    wr = VoiceReply(file_path="/tmp/a.wav")
    assert "a.wav" in repr(wr)
    assert not isinstance(wr, str), "语音项若继承 str，回发循环会把它当文本发（等于又丢一次）"
