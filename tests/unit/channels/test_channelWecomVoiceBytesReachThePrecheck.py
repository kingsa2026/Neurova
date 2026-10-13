# -*- coding: utf-8 -*-
"""企业微信语音的素材字节：从 `<MediaId>` 走到 `AUDIO_BYTES_KEY`，且全仓只有一份取字节的实装（§6-187 批 27 · 缺口① 后半）。

复核实状（逐处自己命中）：
- **活路缺的是"把引用换成字节"**：§6-184 让平台已转写的 `<Recognition>` 进了正文，但企业没开通
  语音识别时回调只给 `<MediaId>`——那条语音在本仓仍然没有任何东西能转写它（预检读的是
  `voice_ingress.AUDIO_BYTES_KEY`，而适配器从不写它）。
- **仓内已有一份 wecom 素材下载，但它在死路上且没有大小上限**：`wechat_media.py:WeChatMediaMixin._download_wecom_media`
  自己发一次媒体 GET，依赖 `WeChatAdapter` 才有的同步 `_ensure_wecom_token()`；它的入口 `download_media`
  全仓**零调用者**（只有 `test_wechat_split.py` 断 `hasattr` 那种形状守卫）。
  ⇒ 按教义第 7 条不许再写第二份：HTTP 那一层收成 `wecom.py` 里的一份单源（与
  `_wecom_callback_signature` 同族＝平台协议面），两侧都改指它——旧同步面保留自己的 token 检查与
  `save_path` 落盘语义（**不因此丢能力**），只把手抄的请求删掉。
- **`handle_callback` 是同步的且跑在事件循环线程上**（它用 `run_coroutine_threadsafe` 投事件），
  所以取字节必须发生在循环之外——§6-185 刚为同一件事踩过一次，判据照那条**成对**口径写。
- **顺手扫出第二套占位词汇**（同根因属 §6-184）：`wechat_ilink.py` 与 `wecom_aibot.py` 在
  "没有平台转写"时写的是内部标记 `[voice:` + `no transcription]`，而**同一个文件的另一条分支**用的
  是 `INBOUND_VOICE_PLACEHOLDER`——一条入站两种词汇。本批把这两处取回共享占位。

刻意不做的一件事：aibot 的语音帧只给平台 ASR 文本、没有素材 URL（`_on_message` 的 voice 分支只读
`body["voice"]["content"]`），所以它**没有字节可取**，本批不给它编一条下载路。
"""

import asyncio
import pathlib
import re
import threading
import time
from unittest.mock import patch

REPO = pathlib.Path(__file__).resolve().parents[3]
NEUROVA = REPO / "neurova"

import neurova.channels.wechat_media as mediaModule  # noqa: E402
import neurova.channels.wecom as wecomModule  # noqa: E402
from neurova.channels.base import ChannelConfig  # noqa: E402
from neurova.channels.voice_ingress import (  # noqa: E402
    AUDIO_BYTES_KEY,
    INBOUND_VOICE_PLACEHOLDER,
    VOICE_DOWNLOAD_MAX_BYTES,
)
from neurova.channels.wechat_media import WeChatMediaMixin  # noqa: E402
from neurova.channels.wecom import WeComAdapter, _wecom_callback_signature  # noqa: E402


def _singleSource():
    """按属性现取单源：本批落地前这一格要红在"这份实装不存在"这条事实上，而不是 collection error。"""
    fetch = getattr(wecomModule, "fetchWecomMediaBytes", None)
    assert callable(fetch), "`wecom.py` 里还没有那份单源的素材取字节实装"
    return fetch


def _mediaGetPath() -> str:
    path = getattr(wecomModule, "MEDIA_GET_PATH", None)
    assert isinstance(path, str) and path, "`wecom.py` 里还没有那份单源的接口路径常量"
    return path


CALLBACK_TOKEN = "wecom-callback-token-b27"
MEDIA_ID = "MEDIA_VOICE_B27"
FAKE_BYTES = b"FAKE-WECOM-VOICE-BYTES"
SECOND_VOCAB = "[voice: " + "no transcription]"


def _adapter() -> WeComAdapter:
    return WeComAdapter(ChannelConfig(
        channel_type="wecom", app_id="ww_corp_b27", app_secret="sec",
        webhook_token=CALLBACK_TOKEN, extra={"corpid": "ww_corp_b27", "agentid": "100"}))


def _xml(msgType: str, extra: str) -> str:
    return ("<xml><ToUserName><![CDATA[ww_corp_b27]]></ToUserName>"
            "<FromUserName><![CDATA[manager_user_b27]]></FromUserName>"
            "<CreateTime>1700000000</CreateTime><MsgType><![CDATA[" + msgType + "]]></MsgType>"
            + extra + "<MsgId>88</MsgId><AgentID>100</AgentID></xml>")


def _deliver(adapter: WeComAdapter, xml: str, sink: list, timeout: float = 3.0) -> None:
    """喂一条真回调进 `handle_callback`，捕获它投出来的消息（要一个真在跑的循环）。"""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    while not loop.is_running():
        time.sleep(0.01)

    async def _record(_eventType, message):
        sink.append(message)

    adapter._main_loop = loop
    adapter._event_callback = _record
    adapter._access_token = "tok-b27"          # 生产里由 `_refresh_access_token` 填
    adapter._token_expires_at = time.time() + 600
    signature = _wecom_callback_signature(CALLBACK_TOKEN, "1700000000", "n1", "")
    adapter.handle_callback(signature, "1700000000", "n1", xml)

    deadline = time.time() + timeout
    while time.time() < deadline and not sink:
        time.sleep(0.02)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)


def _patchFetch(spy):
    """把单源换掉——打在模块属性上，生产调用点按全局名解析，所以打的正是活的那一处。"""
    return patch.object(wecomModule, "fetchWecomMediaBytes", spy)


class TestMediaBytesReachThePrecheckKey:
    def testVoiceWithMediaIdCarriesBytesWhenNoPlatformTranscript(self):
        calls: list = []

        def _spy(accessToken, mediaId, **kwargs):
            calls.append((accessToken, mediaId))
            return FAKE_BYTES

        sink: list = []
        with _patchFetch(_spy):
            _deliver(_adapter(), _xml("voice", f"<MediaId><![CDATA[{MEDIA_ID}]]></MediaId>"), sink)

        assert sink, "语音回调根本没投出消息"
        assert len(sink) == 1, f"投了 {len(sink)} 条——同一句话进两次回合"
        assert calls == [("tok-b27", MEDIA_ID)], f"没走到单源取字节（调用记录 {calls}）"
        assert sink[0].metadata.get(AUDIO_BYTES_KEY) == FAKE_BYTES, (
            f"字节没落进预检读的那个键（metadata={sorted(sink[0].metadata)}）")

    def testPlatformTranscriptSkipsTheDownload(self):
        """平台已经转写过了就别再出站一次：省一次请求，也别把没人读的字节挂上消息。"""
        calls: list = []
        sink: list = []

        def _spy(*args, **kwargs):
            calls.append(args)
            return FAKE_BYTES

        with _patchFetch(_spy):
            _deliver(_adapter(), _xml("voice", "<Recognition><![CDATA[今天天气]]></Recognition>"
                                               f"<MediaId><![CDATA[{MEDIA_ID}]]></MediaId>"), sink)

        assert sink and sink[0].content == "今天天气"
        assert calls == [], f"平台已给转写还去下载了（{len(calls)} 次）"
        assert AUDIO_BYTES_KEY not in (sink[0].metadata or {})

    def testFetchFailureStillEmitsThePlaceholder(self):
        """下载失败/缺依赖 ⇒ 退共享占位并照常投递一条：绝不丢消息，也不谎报有内容。"""
        sink: list = []
        with _patchFetch(lambda *a, **k: None):
            _deliver(_adapter(), _xml("voice", f"<MediaId><![CDATA[{MEDIA_ID}]]></MediaId>"), sink)

        assert len(sink) == 1, f"下载失败把消息弄丢了（投了 {len(sink)} 条）"
        assert sink[0].content == INBOUND_VOICE_PLACEHOLDER
        assert AUDIO_BYTES_KEY not in (sink[0].metadata or {})

    def testDownloadDoesNotRunOnTheEventLoopThread(self):
        """成对探针：既要证「真下载过」，也要证「不在循环线程上」——只写后半会被『关掉下载』骗绿。"""
        probe = {"called": False, "loopInThread": None}

        def _spy(accessToken, mediaId, **kwargs):
            probe["called"] = True
            try:
                asyncio.get_running_loop()
                probe["loopInThread"] = True
            except RuntimeError:
                probe["loopInThread"] = False
            return FAKE_BYTES

        with _patchFetch(_spy):
            _deliver(_adapter(), _xml("voice", f"<MediaId><![CDATA[{MEDIA_ID}]]></MediaId>"), [])

        assert probe["called"], "根本没下载——这一格不能靠『什么都没发生』变绿"
        assert probe["loopInThread"] is False, "在事件循环线程上做同步 HTTP＝一次慢下载拖住全进程入站"


class TestSingleSourceForTheMediaGet:
    """媒体 GET 全仓只许有一处 HTTP 实装（教义第 6 条），旧同步面改指它。"""

    @staticmethod
    def _wecomMediaGetFaces(src: str | None = None) -> list:
        """数"向企业微信发起素材 GET"的落点。

        口径两条，都是被现成的坑教出来的：① `/cgi-bin/media/get` 这条路径**公众号也在用**
        （`WECHAT_OA_API_BASE` + 另一套 token），按裸路径扫就会把另一条平台通道报成"第二份手抄"
        （本仓里正好有这一行可作负样本）；② 单源那档既声明路径常量又用它拼 URL，两处都算同一份实装。
        """
        needle = _mediaGetPath()
        otherPlatform = ("WECHAT_OA_API_BASE", "api.weixin.qq.com")
        hits = []
        sources = [(REPO / "synthetic.py", src)] if src is not None else [
            (p, None) for p in sorted(NEUROVA.rglob("*.py")) if "__pycache__" not in p.parts
        ]
        for path, override in sources:
            text = override if override is not None else path.read_text(
                encoding="utf-8", errors="replace")
            for lineNo, line in enumerate(text.splitlines(), start=1):
                if (needle in line or "MEDIA_GET_PATH" in line) \
                        and not any(mark in line for mark in otherPlatform):
                    hits.append(f"{path.relative_to(REPO).as_posix()}:{lineNo}")
        return hits

    def testOnlyOneFaceFetchesWecomMedia(self):
        hits = self._wecomMediaGetFaces()
        assert hits, "探测器零命中——单源那档也不见了（口径失效）"
        offenders = [h for h in hits if not h.startswith("neurova/channels/wecom.py")]
        assert offenders == [], f"企业微信素材 GET 有第二份手抄实装：{offenders}"

    def testDetectorHasTeethAndSeparatesTheOtherPlatform(self):
        """自证：手抄的第二份要抓到，公众号那条同名路径不能误报（排除型断言两头都要钉）。"""
        copied = 'a = 1\nurl = f"{a.WECOM_API_BASE}' + _mediaGetPath() + '"\n'
        assert len(self._wecomMediaGetFaces(copied)) == 1, "第二份手抄没被抓到"
        official = 'url = f"{a.WECHAT_OA_API_BASE}' + _mediaGetPath() + '"\n'
        assert self._wecomMediaGetFaces(official) == [], "公众号那条同名路径被误报成企微的第二份"
        assert self._wecomMediaGetFaces('x = 1\n') == []

    def testLegacySyncFaceDelegatesAndKeepsSavePath(self, tmp_path):
        """旧同步面必须走同一份单源，且自己的 token 检查与 `save_path` 落盘语义都没丢。"""
        calls: list = []

        def _spy(accessToken, mediaId, **kwargs):
            calls.append((accessToken, mediaId))
            return FAKE_BYTES

        class _Host(WeChatMediaMixin):
            mode = "wecom"
            access_token = "tok-legacy"

            def __init__(self):
                self.adapter = self

            def _ensure_wecom_token(self):
                return True

        host = _Host()
        dest = tmp_path / "voice.bin"
        with patch.object(mediaModule, "fetchWecomMediaBytes", _spy):
            got = host._download_wecom_media(MEDIA_ID, str(dest))

        assert calls == [("tok-legacy", MEDIA_ID)], f"旧面没走单源（调用记录 {calls}）"
        assert got == FAKE_BYTES
        assert dest.read_bytes() == FAKE_BYTES, "save_path 落盘语义在合并时被弄丢了"

    def testCapIsSourcedOnceNotRestatedByCallers(self):
        """上限只许在单源的缺省里定义一次——调用方各自补一个数就是第二个事实源。"""
        import inspect

        fetch = _singleSource()
        param = inspect.signature(fetch).parameters.get("maxBytes")
        assert param is not None and param.default == VOICE_DOWNLOAD_MAX_BYTES, (
            f"单源没有把上限取自 voice_ingress（实得 {param and param.default!r}）")
        assert VOICE_DOWNLOAD_MAX_BYTES > 0

    def testSingleSourceRefusesOversizedInBothWays(self):
        """上限两道：声明长度超限就不读 body；没有声明时按实际字节拒（照 `voice_ingress` 口径）。"""
        reads = {"n": 0}
        fetch = _singleSource()

        class _Resp:
            def __init__(self, headers):
                self.headers = headers

            @property
            def content(self):
                reads["n"] += 1
                return b"x" * (VOICE_DOWNLOAD_MAX_BYTES + 1)

        declaredTooBig = _Resp({"Content-Length": str(VOICE_DOWNLOAD_MAX_BYTES + 1000),
                                "Content-Type": "application/octet-stream"})
        with patch("requests.get", return_value=declaredTooBig):
            assert fetch("tok", MEDIA_ID) is None, "声明超限没拒"
        assert reads["n"] == 0, "声明已超限还去读 body——白等一个大响应"

        noDeclaration = _Resp({"Content-Type": "application/octet-stream"})
        with patch("requests.get", return_value=noDeclaration):
            assert fetch("tok", MEDIA_ID) is None, "实际超限没拒（没有 Content-Length 时）"
        assert reads["n"] == 1, f"没声明时应当读一次再判（实读 {reads['n']} 次）"

    def testSingleSourceNormalByteAndJsonErrorBody(self):
        """正常尺寸要给出字节；错误响应回的是 JSON，不能把错误体当音频交给预检去转写。"""
        fetch = _singleSource()

        class _Resp:
            def __init__(self, body, contentType):
                self.headers = {"Content-Length": str(len(body)), "Content-Type": contentType}
                self.content = body

        with patch("requests.get", return_value=_Resp(FAKE_BYTES, "application/octet-stream")):
            assert fetch("tok", MEDIA_ID) == FAKE_BYTES
        with patch("requests.get", return_value=_Resp(
                b'{"errcode":40008,"errmsg":"invalid media id"}', "application/json")):
            assert fetch("tok", MEDIA_ID) is None


class TestNoSecondPlaceholderVocabulary:
    """`SECONDVOCAB` 是第二套语音占位词汇；同一文件的另一条分支用的是共享占位。"""

    @staticmethod
    def _markerSites() -> list:
        hits = []
        pattern = re.compile(r"\[voice:\s*no transcription\]")
        for path in sorted(NEUROVA.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for lineNo, line in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                if pattern.search(line):
                    hits.append(f"{path.relative_to(REPO).as_posix()}:{lineNo}")
        return hits

    def testNoEnglishInternalMarkerInInboundPaths(self):
        assert self._markerSites() == [], f"还留着第二套语音占位词汇：{self._markerSites()}"

    def testDetectorHasTeeth(self):
        assert re.search(r"\[voice:\s*no transcription\]", 'x = "' + SECOND_VOCAB + '"')
        assert not re.search(r"\[voice:\s*no transcription\]", 'x = "' + INBOUND_VOICE_PLACEHOLDER + '"')


class TestTextPathIsUntouched:
    def testTextCallbackStillPassesThrough(self):
        """对照文本支：它不下载、也不该被本批的分支波及。

        这一格刻意不 patch 单源——否则在生产件还没单源的形状上它会因夹具而红（假差异），
        把"文本支未受波及"这条读数一起弄脏。
        """
        sink: list = []
        _deliver(_adapter(), _xml("text", "<Content><![CDATA[普通文字]]></Content>"), sink)
        assert sink and sink[0].content == "普通文字" and sink[0].message_type == "text"
