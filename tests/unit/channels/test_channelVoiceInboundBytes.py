# -*- coding: utf-8 -*-
"""渠道入站语音：字节要真到、词汇只一处定义、一条链要能被证明确实打通（§6-168 缺口①）。

复核实状后本批立三格靶子：

1. **活路上的入站语音不取字节**。全仓只有两处生产者交 `audio_bytes`
   （`channels/feishu.py:237-239`、`channels/wechat_ilink.py:253-264`）。Telegram 这条
   活路更糟：`_process_update` 的正文取法是 `msg.get("text") or msg.get("caption") or ""`
   （`telegram_adapter.py:280`），语音消息两者皆无 ⇒ **content 是空串**、`message_type`
   硬编码 `"text"`（`:289`）——连"占位"都没有，agent 收到一条空消息。
2. **同一口径的第二份定义**。`"audio_bytes"` 字面量散在两个写入点 + 预检读点；语音类型集合
   `{"voice","audio"}` 在 `voice_precheck.py:25` 自定义；下载大小上限在 `feishu.py:37` 自定义。
   本批要加第三个下载者（Telegram），不先收口就是再造一份（教义第 6 条）。
3. **"适配器 → manager → 预检 → 回合 → 出口"这条链从来没有一条测试打通过**（逐档读过：
   `test_voice_precheck.py` 只测预检本体、`test_feishu_voice_download.py` 只到 metadata 键、
   `test_wechat_ilink_adapter.py` 用假客户端断形状）。出站那两档（§6-168）也不含入站半区。

判据一律走生产入口：Telegram 用真 `_process_update` + 真 `_emit_event` 回调，端到端格用真
`FeishuAdapter` 入站 + 真 `ChannelManager` + 真 `transcribe_voice_message` + 真
`channel_router.make_handler` + 真飞书出口。替身只放在两个边界：**平台服务器**（本地回环
真 HTTP 桩）与**模型**（ASR 转写文本、agent 回合产物）——ASR/LLM 真跑要开外网并花服务商额度，
而本批验的是"字节流不流得到、类型标不标得对"，不是模型质量。
"""

import ast
import asyncio
import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
CHANNELS = REPO / "neurova" / "channels"
INGRESS_MODULE = CHANNELS / "voice_ingress.py"

from neurova.channels.base import ChannelEventType  # noqa: E402

from tests import ast_scan as _astScan  # noqa: E402


# --------------------------------------------------------------------------
# 本地回环桩：Telegram 服务器形状
# --------------------------------------------------------------------------

class _TelegramStub(BaseHTTPRequestHandler):
    """按 Telegram Bot API 的响应形状回话，并记录每一跳的路径顺序。

    `getFile` 交回 `file_path`，下载跳交回原始字节——两跳分开记，才能断言"顺序"而不是
    只看"发出去了"。超限格用 `stream` 语义：只读头部就能拒收，不必把 10MB 吸进内存。
    """

    host = ""
    captured = []
    file_body = b"OGG-BYTES-VOICE-NOTE"
    declared_length_override = None
    getfile_ok = True

    def _replyJson(self, payload: dict):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        type(self).captured.append(self.path)
        if self.path.startswith("/bot") and "/getMe" in self.path:
            return self._replyJson({"ok": True, "result": {"id": 1, "username": "nv_probe_bot"}})
        if "/getFile" in self.path:
            if not type(self).getfile_ok:
                return self._replyJson({"ok": False, "description": "file id invalid"})
            return self._replyJson({
                "ok": True,
                "result": {"file_id": "vf_1", "file_path": "voice/file_1.ogg"},
            })
        if self.path.startswith("/file/bot"):
            body = type(self).file_body
            self.send_response(200)
            self.send_header("Content-Type", "audio/ogg")
            declared = type(self).declared_length_override
            self.send_header(
                "Content-Length", str(len(body) if declared is None else declared))
            self.end_headers()
            # 声明超限时只交头部、不交体：真实现必须先按声明长度拒收（否则会把大文件吸进内存）
            if declared is None:
                self.wfile.write(body)
            return
        return self._replyJson({"ok": False, "description": f"unexpected path {self.path}"})

    def log_message(self, *args):  # 静音
        pass


@pytest.fixture()
def tgStub():
    _TelegramStub.captured = []
    _TelegramStub.file_body = b"OGG-BYTES-VOICE-NOTE"
    _TelegramStub.declared_length_override = None
    _TelegramStub.getfile_ok = True
    server = HTTPServer(("127.0.0.1", 0), _TelegramStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _TelegramStub.host = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield _TelegramStub
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _telegramAdapter(stub_host: str):
    from neurova.channels.telegram_adapter import TelegramAdapter

    adapter = TelegramAdapter()
    adapter.API_BASE = stub_host  # 类属性可注入；不注入就会有真请求飞出外网
    adapter.bot_token = "123:probe"
    adapter._initialized = True
    return adapter


def _voiceUpdate() -> dict:
    return {
        "update_id": 101,
        "message": {
            "message_id": 5001,
            "from": {"id": 777, "username": "kai"},
            "chat": {"id": 777, "type": "private"},
            "voice": {"file_id": "vf_1", "duration": 3, "mime_type": "audio/ogg"},
        },
    }


async def _driveTelegram(adapter, update: dict) -> list:
    """走真 `_process_update`：它在轮询线程里同步跑，再把事件调度回主循环。

    测试里保持同一形状——用 `asyncio.to_thread` 起线程调它，回调落在本测试的 loop 上，
    与生产一致；不直调任何本批新增的 helper（否则"改前"的红会是形状红而不是行为红）。
    """
    received = []

    async def _callback(eventType, message):
        received.append((eventType, message))

    adapter.set_event_callback(_callback)
    adapter._main_loop = asyncio.get_running_loop()
    await asyncio.to_thread(adapter._process_update, update)
    for _ in range(100):
        if received:
            break
        await asyncio.sleep(0.02)
    return received


# --------------------------------------------------------------------------
# 靶子 1：Telegram 语音必须带字节、带类型
# --------------------------------------------------------------------------

class TestTelegramVoiceInbound:

    @pytest.mark.asyncio
    async def testVoiceNoteCarriesAudioBytesAndVoiceType(self, tgStub):
        adapter = _telegramAdapter(tgStub.host)
        received = await _driveTelegram(adapter, _voiceUpdate())

        assert received, "语音消息没有到达事件回调（今天：content 空串、类型 text，或不发）"
        eventType, message = received[0]
        assert eventType == ChannelEventType.MESSAGE_RECEIVED
        assert message.message_type == "voice", (
            f"语音消息的类型没有标成 voice：{message.message_type!r}")
        raw = message.metadata.get("audio_bytes")
        assert raw == tgStub.file_body, f"语音字节没有进 metadata：{message.metadata.keys()}"

    @pytest.mark.asyncio
    async def testDownloadHopFollowsGetFileAndStaysOnInjectedBase(self, tgStub):
        """两跳顺序与出口：getFile → /file/bot.../<file_path>，且第二跳的 host 就是注入的基址。

        断"顺序 + 真到对岸"而不是断"没出现硬编码域名"——排除型断言在功能不存在时自动成立，
        绿得没道理（本卷反复记的那形）。
        """
        adapter = _telegramAdapter(tgStub.host)
        await _driveTelegram(adapter, _voiceUpdate())

        hops = [p for p in tgStub.captured if "/getFile" in p or p.startswith("/file/bot")]
        assert len(hops) == 2, f"取语音应是两跳（getFile→下载），实得 {hops}"
        assert "/getFile" in hops[0] and hops[1].startswith("/file/bot"), f"跳序不对：{hops}"
        received = await _driveTelegram(_telegramAdapter(tgStub.host), _voiceUpdate())
        assert received[0][1].metadata.get("audio_bytes"), "下载跳没把字节带回来"

    @pytest.mark.asyncio
    async def testGetFileFailureKeepsPlaceholderWithoutLosingMessage(self, tgStub):
        """取不到字节 ⇒ 消息照发、内容是真占位（不得是空串），并留下可查的降级痕迹。"""
        tgStub.getfile_ok = False
        adapter = _telegramAdapter(tgStub.host)
        received = await _driveTelegram(adapter, _voiceUpdate())

        assert received, "下载失败不能把整条消息吞掉"
        message = received[0][1]
        assert message.message_type == "voice"
        assert message.content == "[语音]", f"降级后应保留占位，实得 {message.content!r}"
        assert "audio_bytes" not in message.metadata

    @pytest.mark.asyncio
    async def testDeclaredOversizeIsRefusedWithoutBuffering(self, tgStub):
        """平台声明的长度超上限 ⇒ 拒收，且不能为了拒收先把整份吸进内存。"""
        tgStub.declared_length_override = 40 * 1024 * 1024
        adapter = _telegramAdapter(tgStub.host)
        received = await _driveTelegram(adapter, _voiceUpdate())

        assert received and received[0][1].content == "[语音]"
        assert "audio_bytes" not in received[0][1].metadata, "超限语音被收下了"

    @pytest.mark.asyncio
    async def testPlainTextUpdateShapeIsUnchanged(self, tgStub):
        """反向对照：文字消息不得因语音分支而改形状。"""
        adapter = _telegramAdapter(tgStub.host)
        update = {
            "update_id": 102,
            "message": {
                "message_id": 5002,
                "from": {"id": 777, "username": "kai"},
                "chat": {"id": 777, "type": "private"},
                "text": "你好",
            },
        }
        received = await _driveTelegram(adapter, update)

        assert received, "文字消息掉了"
        message = received[0][1]
        assert message.content == "你好" and message.message_type == "text"
        assert "audio_bytes" not in message.metadata
        assert not [p for p in tgStub.captured if p.startswith("/file/bot")], "文字消息不该触发下载"


# --------------------------------------------------------------------------
# 靶子 2：入站语音的口径只允许一处定义
# --------------------------------------------------------------------------

def _moduleTree(path: pathlib.Path) -> ast.Module:
    """单文件语法树：单文件解析不是「全仓扫描」，但与 `_channelModules` 配成
    一处枚举 + 一处解析时就等同私有全仓扫描（Issue #148）。故本文件统一改走
    下面 `_channelTrees()` 一次取数，不再逐文件 `ast.parse`。"""
    return ast.parse(path.read_text(encoding="utf-8", errors="replace"))


def _channelTrees(exclude: tuple = ()):
    """渠道子树里 `(相对路径, 语法树)` 清单——枚举 + 解析都在共享预算内。

    取数走 `tests/ast_scan`（Issue #148）：私有 `rglob` + 逐文件 `ast.parse`
    把「解析量」绑成「代码总量」，与其余受保护文件共享机器时撞 30s 墙钟。
    保留型入口 `parsedModules` 在此正当：下面三格各扫同一片树两次以上。
    """
    return [(ref.path.relative_to(REPO).as_posix(), _astScan._cachedParse(ref.stamp, ref.code))
            for ref in _astScan.sourceRefsUnder(CHANNELS)
            if ref.path.name not in exclude]


def _dataUsesOfStringLiteral(tree: ast.Module, value: str) -> list:
    """按**用途**数：下标键或函数实参里出现的字符串常量。

    只按"文件里有没有这个串"判会被 docstring 骗（`voice_precheck.py` 的说明文字就写着
    audio_bytes），那是本卷记过的"文本包含两头失真"。
    """
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            if node.slice.value == value:
                hits.append(node.lineno)
        elif isinstance(node, ast.Call):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and arg.value == value:
                    hits.append(node.lineno)
            for kw in node.keywords:
                if isinstance(kw.value, ast.Constant) and kw.value.value == value:
                    hits.append(kw.lineno)
    return hits


def _setLiteralsMatching(tree: ast.Module, members: set) -> list:
    hits = []
    for node in ast.walk(tree):
        got = None
        if isinstance(node, ast.Set):
            got = {e.value for e in node.elts if isinstance(e, ast.Constant)}
        elif isinstance(node, (ast.List, ast.Tuple)):
            got = {e.value for e in node.elts if isinstance(e, ast.Constant)}
        if got == members:
            hits.append(node.lineno)
    return hits


def _constInt(node: ast.AST):
    """折叠 `10 * 1024 * 1024` 这类算式——真代码里的上限就是这么写的，
    只认 Constant 会让探测器放过它（本档的自证格当场抓到这一形）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Add, ast.Sub)):
        left, right = _constInt(node.left), _constInt(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Mult):
            return left * right
        return left + right if isinstance(node.op, ast.Add) else left - right
    return None


def _intCapAssignments(tree: ast.Module) -> list:
    hits = []
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        number = _constInt(value)
        if number is None:
            continue
        for t in targets:
            name = getattr(t, "id", None) or getattr(t, "attr", None) or ""
            if name.endswith("MAX_BYTES") and number >= 1024 * 1024:
                hits.append(f"{name}:{node.lineno}")
    return hits


class TestInboundVoiceVocabularyIsSingleSource:
    """定义处 = `neurova/channels/voice_ingress.py`；其余各点必须引它。"""

    def testIngressModuleExistsAndDefinesTheVocabulary(self):
        assert INGRESS_MODULE.is_file(), "入站语音口径没有唯一定义处"
        tree = _moduleTree(INGRESS_MODULE)
        names = set()
        for node in tree.body:
            if isinstance(node, ast.Assign):
                names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        assert {"AUDIO_BYTES_KEY", "INBOUND_VOICE_TYPES", "VOICE_DOWNLOAD_MAX_BYTES"} <= names, (
            f"定义处缺项，实有 {sorted(names)}")

    def testAudioBytesKeyIsNotRestatedElsewhere(self):
        offenders = []
        for rel, tree in _channelTrees(exclude=("voice_ingress.py",)):
            hits = _dataUsesOfStringLiteral(tree, "audio_bytes")
            if hits:
                offenders.append(f"{rel}:{hits}")
        assert offenders == [], f"`audio_bytes` 被当字面量第二次使用：{offenders}"

    def testInboundVoiceTypeSetIsNotRestatedElsewhere(self):
        offenders = []
        for rel, tree in _channelTrees(exclude=("voice_ingress.py",)):
            hits = _setLiteralsMatching(tree, {"voice", "audio"})
            if hits:
                offenders.append(f"{rel}:{hits}")
        assert offenders == [], f"语音类型集合被各写一份：{offenders}"

    def testDownloadCapIsNotRestatedElsewhere(self):
        offenders = []
        for rel, tree in _channelTrees(exclude=("voice_ingress.py",)):
            hits = _intCapAssignments(tree)
            if hits:
                offenders.append(f"{rel}:{hits}")
        assert offenders == [], f"语音下载上限有两份：{offenders}"

    def testDetectorsHaveTeeth(self):
        """探测器自证：合成样本必须被点名，真邻接不得误报（否则上面三格是空转）。"""
        sample = ast.parse(
            'd = {}\nd["audio_bytes"] = b"x"\nvo = {"voice", "audio"}\n'
            'M = [1, 2]\nMAX_BYTES = 20 * 1024 * 1024\n'
        )
        assert _dataUsesOfStringLiteral(sample, "audio_bytes"), "下标写入没被抓到"
        assert _setLiteralsMatching(sample, {"voice", "audio"}), "类型集合没被抓到"
        assert _intCapAssignments(sample), "上限赋值没被抓到"

        benign = ast.parse(
            '"""audio_bytes 在说明文字里出现"""\n'
            'x = m.get("image_bytes")\nk = {"voice": 1}\nSIZE = 128\n'
        )
        assert _dataUsesOfStringLiteral(benign, "audio_bytes") == [], "docstring 被误判成使用"
        assert _setLiteralsMatching(benign, {"voice", "audio"}) == [], "单键 dict 被误判成集合"
        assert _intCapAssignments(benign) == [], "无关小整数被误判成上限"

    @pytest.mark.asyncio
    async def testPrecheckStillHandlesBothVoiceTagsAfterImportingTheSet(self, monkeypatch):
        """行为格：收口之后，预检对 voice/audio 都得真转写，对 text 一律不动。

        防止把集合换成常量时把成员换窄（"闭集守卫常驻红"那族的反面——这里窄了就是静默丢内容）。
        """
        from neurova.channels import voice_precheck
        from neurova.channels.base import ChannelMessage

        async def _transcriber(_data):
            return {"text": "转写出来的内容"}

        monkeypatch.setattr(voice_precheck, "_get_asr_transcriber", lambda: _transcriber)

        for tag in ("voice", "audio"):
            msg = ChannelMessage(
                channel_type="probe", message_id="m1", sender_id="u1", sender_name="u1",
                content="[语音]", chat_id="c1", chat_type="p2p", message_type=tag,
                metadata={"audio_bytes": b"WAVBYTES"},
            )
            out = await voice_precheck.transcribe_voice_message(msg)
            assert out.content == "转写出来的内容", f"{tag} 型没有被转写：{out.content!r}"

        textMsg = ChannelMessage(
            channel_type="probe", message_id="m2", sender_id="u1", sender_name="u1",
            content="就是文字", chat_id="c1", chat_type="p2p", message_type="text",
            metadata={"audio_bytes": b"WAVBYTES"},
        )
        out = await voice_precheck.transcribe_voice_message(textMsg)
        assert out.content == "就是文字", "非语音类型被预检改动了"


# --------------------------------------------------------------------------
# 靶子 3：入站→预检→回合→出站，一条链的常驻证据
# --------------------------------------------------------------------------

class _FeishuStub(BaseHTTPRequestHandler):
    """一个桩扮飞书：token / 语音下载 / 文件上传 / 发消息四形。"""

    captured = []
    voice_bytes = b"FEISHU-VOICE-BODY"
    upload_body = b""
    fileKey = "fk_in"

    def _json(self, payload: dict):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        type(self).captured.append({
            "method": "POST", "path": self.path,
            "content_type": self.headers.get("Content-Type") or "", "body": raw,
        })
        if "tenant_access_token" in self.path:
            return self._json({"code": 0, "tenant_access_token": "t-stub", "expire": 3600})
        if "/im/v1/files" in self.path:
            return self._json({"code": 0, "data": {"file_key": type(self).fileKey}})
        if "/im/v1/messages" in self.path:
            return self._json({"code": 0, "data": {"message_id": "om_out"}})
        return self._json({"code": 1, "msg": f"unexpected {self.path}"})

    def do_GET(self):  # noqa: N802
        type(self).captured.append({
            "method": "GET", "path": self.path,
            "content_type": self.headers.get("Content-Type") or "", "body": b"",
        })
        if "/resources/" in self.path:
            body = type(self).voice_bytes
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return self._json({"code": 1, "msg": f"unexpected {self.path}"})

    def log_message(self, *args):
        pass


@pytest.fixture()
def fsStub():
    _FeishuStub.captured = []
    _FeishuStub.upload_body = b""
    server = HTTPServer(("127.0.0.1", 0), _FeishuStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _EvtUserIds:
    """lark SDK 里 EventSender.sender_id 是"三种 id 的对象"，不是字符串。"""

    def __init__(self):
        self.user_id = ""
        self.open_id = "ou_kai"
        self.union_id = ""


class _EvtSender:
    def __init__(self):
        self.sender_id = _EvtUserIds()


class _EvtMessage:
    def __init__(self, **kw):
        self.message_id = kw.get("message_id", "om_in")
        self.chat_id = kw.get("chat_id", "oc_kai")
        self.chat_type = kw.get("chat_type", "p2p")
        self.message_type = kw.get("message_type", "audio")
        self.content = kw.get("content", "{}")
        self.mentions = kw.get("mentions", None)


class _EvtBody:
    def __init__(self, message):
        self.message = message
        self.sender = _EvtSender()


class _Evt:
    def __init__(self, message):
        self.event = _EvtBody(message)


class _FakeAgent:
    """只替"agent 回合"这一边界；键名按 `chat_pipeline.py:2931-2934` 的真实产物取。"""

    def __init__(self, resp):
        self._resp = dict(resp)
        self.seen = []
        self.config = type("C", (), {"show_thinking": False, "show_tool_messages": False})()
        self.current_reasoning = ""

    def get_tool_messages_snapshot(self):
        return []

    async def chat(self, user_input="", session_id="", metadata=None, **kw):
        self.seen.append(user_input)
        return dict(self._resp)


class TestVoiceInVoiceOutLoop:
    """一条格打通全链：飞书来一段语音，回来的是一封真音频。"""

    @pytest.mark.asyncio
    async def testFeishuVoiceInComesBackAsAudio(self, fsStub, tmp_path, monkeypatch):
        import wave

        from neurova.channels import voice_precheck
        from neurova.channels.channel_router import make_handler
        from neurova.channels.feishu import FeishuAdapter
        from neurova.channels.base import ChannelConfig
        from neurova.channels.manager import ChannelManager

        wav = tmp_path / "tts_loop_1.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x01\x00" * 400)

        async def _transcriber(_data):
            return {"text": "明天天气怎么样"}

        monkeypatch.setattr(voice_precheck, "_get_asr_transcriber", lambda: _transcriber)

        ChannelManager._instance = None
        mgr = ChannelManager()
        adapter = FeishuAdapter(ChannelConfig(
            channel_type="feishu", app_id="cli_stub", app_secret="sec_stub"))
        adapter.api_base = fsStub
        adapter.open_base = fsStub

        # 判据不许有任何通向外部的出口，包括它本不该走到的那条：manager 的发送路径见
        # `is_connected` 为假时会 `await adapter.connect()`，而飞书的 connect 会起一条真
        # lark WebSocket 会话（第一次跑本格时它真的拨出去了一次，"connect failed" 就是证据）。
        # 这里把状态摆成"已连"（这是前置条件，不是被测行为），并把 connect 钉成硬失败——
        # 将来若有改动让这条链又去调 connect，红会喊人，而不是悄悄打外网。
        async def _forbidConnect(*_a, **_kw):
            raise AssertionError("判据触发了真连接出口：适配器不应在测试里 connect")

        monkeypatch.setattr(FeishuAdapter, "connect", _forbidConnect)
        adapter._connected = True

        # 走生产装配口：它同时绑 agent_id 与事件回调（回调缺失时 _emit_event 静默什么都不做）
        mgr.register_adapter(adapter, agent_id="default")
        agent = _FakeAgent({"text": "明天晴", "audio_path": str(wav)})
        mgr._message_handlers = [(50, "loop-handler", make_handler(mgr, lambda _aid: agent))]

        adapter._main_loop = asyncio.get_running_loop()
        adapter._handle_message_event(_Evt(_EvtMessage(
            message_type="audio", content=json.dumps({"file_key": "fk_voice_in"}))))

        def _voiceUploads():
            return [c for c in _FeishuStub.captured if "/im/v1/files" in c["path"]]

        def _voiceSends():
            # 按内容认"语音那一跳"而不是按位置：文本回复走 lark SDK 路（路径带
            # /open-apis/ 前缀），语音走纯 HTTP 路，两跳先后随装配耗时变化——
            # 用 send[-1] 取会在慢的那次读成"没按 file 发"（本档实测飘过一次）。
            return [c for c in _FeishuStub.captured
                    if "/im/v1/messages" in c["path"] and b'"file"' in c["body"]]

        # 等到语音发送那一跳出现为止（上限 30s）：这一回合含真装配，实测首次可到十几秒；
        # 谓词命中就立刻退出，成功路径不花这份时间。
        for _ in range(600):
            if _voiceSends():
                break
            await asyncio.sleep(0.05)

        assert agent.seen, "语音消息没有到达回合（入站或预检断了）"
        assert agent.seen[0] == "明天天气怎么样", (
            f"回合拿到的是占位而不是转写文本：{agent.seen!r}")

        uploads = _voiceUploads()
        assert uploads, f"没有语音上传这一跳，全部请求：{[c['path'] for c in _FeishuStub.captured]}"
        assert wav.read_bytes() in uploads[0]["body"], "对岸收到的不是本轮那段音频字节"
        sends = _voiceSends()
        assert sends, "语音消息没按 file 类型发出去"
        assert b"fk_in" in sends[0]["body"], f"发送那一跳没带上传回来的 file_key：{sends[0]['body'][:120]}"
        paths = [c["path"] for c in _FeishuStub.captured]
        assert paths.index(uploads[0]["path"]) < paths.index(sends[0]["path"]), "先上传后发送没成立"
        assert any(b'"msg_type": "text"' in c["body"] or b'"text"' in c["body"]
                   for c in _FeishuStub.captured if c["method"] == "POST"), "文本回复不该因语音而丢失"

    @pytest.mark.asyncio
    async def testPlaceholderNeverReachesTheAgentWhenBytesArePresent(self, fsStub, monkeypatch):
        """反空转：如果入站没交字节，预检就只会把占位原样送进回合——这条格钉住"不该发生"。"""
        from neurova.channels import voice_precheck
        from neurova.channels.base import ChannelMessage

        called = []

        async def _transcriber(data):
            called.append(data)
            return {"text": "转写"}

        monkeypatch.setattr(voice_precheck, "_get_asr_transcriber", lambda: _transcriber)
        msg = ChannelMessage(
            channel_type="feishu", message_id="m", sender_id="u", sender_name="u",
            content="[语音]", chat_id="c", chat_type="p2p", message_type="audio",
            metadata={"audio_bytes": b"AUDIO-IN"})
        out = await voice_precheck.transcribe_voice_message(msg)

        assert called == [b"AUDIO-IN"], f"预检没把入站字节交给 ASR：{called}"
        assert out.content == "转写"

