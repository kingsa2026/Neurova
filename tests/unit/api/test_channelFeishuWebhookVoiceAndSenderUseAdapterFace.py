# -*- coding: utf-8 -*-
"""飞书 webhook 入站：语音、外部发送者、@提及 三件在端点里被手抄漏掉了（§6-185 批 26）。

复核实状（三处命中点，各自现量）：
- **同一平台的入站解析有两份**：`channels/feishu.py:_handle_message_event`（Stream 路）对 audio
  退 `INBOUND_VOICE_PLACEHOLDER`、按 `file_key` 取字节写进 `AUDIO_BYTES_KEY`、`sender_id` 取
  `user_id or open_id or union_id`、mentions 结构化并把 "@_user_N" 换成 "@昵称"；
  而 `api/endpoints/channels.py:_handle_feishu_webhook`（Webhook 路）**只认 `msg_type == "text"`**，
  其余类型一律 `content=""`，sender 只取 `sender_id.user_id`，mentions 完全不做。
   ⇒ 飞书配成 webhook 模式的用户发一条语音，进回合的正文是**空串**；外部用户（user_id 常为 null）
  的 `sender_id` 是**空串**——而 §6-123/§6-163 立的身份口径读的正是它，Stream 那段注释写明了后果：
  "sender_id 空 → ChannelRouter 的 user_id 落到带冒号的回退值，且记忆隔离失效"。
- **这不是设计取舍，是"逐平台加分支时各写各的"漏出来的**：wecom 那支委托 `adapter.handle_callback`
  （§6-184 刚补上语音读取），飞书这支却在端点里自己拼消息——同一条入站两种形状。

修法（教义第 6/7 条：比后合，不是再补一份）：把"事件体 → ChannelMessage"收成 `FeishuAdapter` 上的
**一个**入口，Stream 与 Webhook 两条路都改指它；端点只负责验签与投递。Webhook 那支的下载含同步 HTTP，
必须在**事件循环外**跑（否则一次 15 秒的下载把整个进程的入站都拖住），所以投递侧走线程池。

本批不做的两件事（写了就有人当已做）：
1. **钉钉 webhook 的非文本类型**同样落空正文，但仓内拿不到钉钉"接收语音"的协议形状实据
   （`channels/dingtalk.py` 全仓无 `downloadCode`/素材下载实现）⇒ 不给没证到的形状立门（形态集同族），
   登记在台账由下一批带协议事实源来做。
2. 端点 `manager.get_adapter(channel_type)` 不带 agent 维度（实例表主键本是 `(agent_id, channel_type)`）
   ⇒ 那是 §6-180 已记的一族，与本批的入站内容口径不同根因，不顺手动。
"""

import ast
import asyncio
import json
import pathlib
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

REPO = pathlib.Path(__file__).resolve().parents[3]
ENDPOINTS_SRC = (REPO / "neurova" / "api" / "endpoints" / "channels.py").read_text(encoding="utf-8")

from neurova.api.app import create_app  # noqa: E402
from neurova.channels.base import ChannelConfig  # noqa: E402
from neurova.channels.feishu import FeishuAdapter  # noqa: E402
from neurova.channels.manager import ChannelManager, get_channel_manager  # noqa: E402
from neurova.channels.voice_ingress import (  # noqa: E402
    AUDIO_BYTES_KEY,
    INBOUND_VOICE_PLACEHOLDER,
)

WEBHOOK = "/api/v1/channel-adapters/feishu/webhook"
VERIFY_TOKEN = "fs-verification-token-batch26"

AUDIO_FILE_KEY = "fk_batch26"
MESSAGE_ID = "om_batch26"


def _fsEventBody(messageType="audio", content='{"file_key":"fk_batch26","duration_ms":1800}',
                 userId="ou_internal", openId="ou_open", mentions=None, chatType="p2p"):
    """按飞书 v2 事件信封拼一条回调体（字段形状取自仓内 Stream 路那半区，同一平台同一事件体）。"""
    senderId = {"user_id": userId, "open_id": openId, "union_id": "on_union"}
    message = {
        "message_id": MESSAGE_ID,
        "chat_id": "oc_batch26",
        "chat_type": chatType,
        "message_type": messageType,
        "content": content,
    }
    if mentions is not None:
        message["mentions"] = mentions
    return {
        "schema": "2.0",
        "header": {"event_type": "im.message.receive_v1", "token": VERIFY_TOKEN},
        "event": {"sender": {"sender_id": senderId}, "message": message},
    }


def _streamEventOf(body: dict):
    """把同一份 webhook 事件体折成 lark SDK 那种属性访问对象——同形对照的另一侧。"""
    ev = body["event"]
    msg = ev["message"]
    sid = ev["sender"]["sender_id"]
    sender = SimpleNamespace(sender_id=SimpleNamespace(
        user_id=sid["user_id"], open_id=sid["open_id"], union_id=sid["union_id"]))
    messageObj = SimpleNamespace(
        message_type=msg["message_type"], message_id=msg["message_id"],
        chat_id=msg["chat_id"], chat_type=msg["chat_type"], content=msg["content"],
        mentions=msg.get("mentions") or [])
    return SimpleNamespace(event=SimpleNamespace(message=messageObj, sender=sender))


@pytest.fixture()
def webhookFace(tmp_path):
    """真 app + 真分派链；事件回调换 recorder（不起 agent、不调模型、不开外网、不花配额）。"""
    ChannelManager._instance = None
    events: list = []

    async def _record(_eventType, message):
        events.append(message)

    adapter = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="cli_b26",
                                          app_secret="sec_b26", verification_token=VERIFY_TOKEN))
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        get_channel_manager().register_adapter(adapter)
        adapter._event_callback = _record
        yield client, events, adapter
    ChannelManager._instance = None


class TestWebhookVoiceIsNotEmptied:
    def testVoiceWithoutBytesFallsBackToThePlaceholder(self, webhookFace):
        """下载拿不到字节时也不能交空串——空正文进回合等于用户说了句不存在的话。"""
        client, events, adapter = webhookFace
        with patch.object(FeishuAdapter, "_download_media_bytes", return_value=None):
            r = client.post(WEBHOOK, json=_fsEventBody())

        assert r.status_code == 200, f"合法回调被拒：{r.status_code} {r.text[:120]}"
        assert len(events) == 1, f"投递条数不对：{len(events)}"
        assert events[0].content == INBOUND_VOICE_PLACEHOLDER, (
            f"语音正文被留成空串（实得 {events[0].content!r}）")

    def testVoiceCarriesFetchedBytesIntoTheDocumentedKey(self, webhookFace):
        """file_key → 字节 → `voice_ingress.AUDIO_BYTES_KEY`，与 Stream 路同一个键、同一份下载器。"""
        client, events, adapter = webhookFace
        with patch.object(FeishuAdapter, "_download_media_bytes",
                          return_value=b"FS_OPUS_BYTES") as dl:
            client.post(WEBHOOK, json=_fsEventBody())

        assert len(events) == 1, "事件根本没投出来"
        assert events[0].metadata.get(AUDIO_BYTES_KEY) == b"FS_OPUS_BYTES", (
            f"字节没进预检读的那个键（metadata={sorted(events[0].metadata)}）")
        dl.assert_called_once_with(MESSAGE_ID, AUDIO_FILE_KEY)

    def testDownloadNeverRunsOnTheEventLoopThread(self, webhookFace):
        """同步 HTTP 一旦跑在事件循环线程上，一次 15s 下载会拖住整个进程的入站。

        探针在下载器里问"这个线程当前有没有在跑的 loop"：有 ⇒ 就是在循环里阻塞；
        同时必须证下载**真发生了**——否则"关掉下载"也能让这一格变绿。
        """
        client, events, adapter = webhookFace
        probe = {"called": False, "loopInThread": None}

        def _stub(message_id, file_key):
            probe["called"] = True
            try:
                asyncio.get_running_loop()
                probe["loopInThread"] = True
            except RuntimeError:
                probe["loopInThread"] = False
            return b"X"

        with patch.object(FeishuAdapter, "_download_media_bytes", side_effect=_stub):
            client.post(WEBHOOK, json=_fsEventBody())

        assert probe["called"], "下载根本没被调用（关掉它等于把这一格改成假绿）"
        assert probe["loopInThread"] is False, (
            "语音字节在事件循环线程上做同步 HTTP——一次慢下载把所有渠道的入站一起拖住")

    def testTextTurnIsStillUntouched(self, webhookFace):
        """对照组：收口不能把文本支一起改掉。"""
        client, events, _ = webhookFace
        client.post(WEBHOOK, json=_fsEventBody(messageType="text",
                                               content='{"text":"普通文字"}'))

        assert len(events) == 1 and events[0].content == "普通文字"


class TestSenderIdentityAndMentionsReachWebhookToo:
    def testExternalSenderFallsBackToOpenId(self, webhookFace):
        """外部用户 user_id 常为 null：只取 user_id 会得到空 sender_id，身份口径当场失效。"""
        client, events, _ = webhookFace
        with patch.object(FeishuAdapter, "_download_media_bytes", return_value=None):
            client.post(WEBHOOK, json=_fsEventBody(userId="", openId="ou_external_only"))

        assert len(events) == 1
        assert events[0].sender_id == "ou_external_only", (
            f"sender_id 落空（实得 {events[0].sender_id!r}）——按 Stream 那半区注释，"
            "空 sender_id 会让回合身份落到回退值、记忆隔离失效")

    def testMentionsAreStructuredAndSubstituted(self, webhookFace):
        """@提及：require_mention 判定读 metadata.mentions，正文里的 "@_user_1" 要被换成可读昵称。"""
        client, events, _ = webhookFace
        client.post(WEBHOOK, json=_fsEventBody(
            messageType="text",
            content='{"text":"@_user_1 帮我看下这份报表"}',
            mentions=[{"key": "@_user_1", "id": {"open_id": "ou_open"}, "name": "小明"}]))

        assert len(events) == 1
        msg = events[0]
        assert msg.metadata.get("mentions"), "mentions 没结构化进 metadata——群内 require_mention 判不到"
        assert "@_user_1" not in msg.content and "小明" in msg.content, (
            f"占位符没换成昵称（实得 {msg.content!r}）")


class TestStreamAndWebhookAreTheSameFaceOnce:
    def testBothPathsBuildTheSameMessage(self, webhookFace):
        """教义第 6 条：一条入站两种形状就是两个事实源。同一事件体过两条路，读数必须相等。"""
        client, webhookEvents, adapter = webhookFace
        body = _fsEventBody(userId="", openId="ou_external_only")

        with patch.object(FeishuAdapter, "_download_media_bytes", return_value=b"SAME_BYTES"):
            client.post(WEBHOOK, json=body)

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        while not loop.is_running():
            time.sleep(0.01)
        streamEvents: list = []

        async def _capture(_eventType, message):
            streamEvents.append(message)

        adapter._main_loop = loop
        adapter._event_callback = _capture
        try:
            with patch.object(FeishuAdapter, "_download_media_bytes", return_value=b"SAME_BYTES"):
                adapter._handle_message_event(_streamEventOf(body))
            for _ in range(150):
                if streamEvents:
                    break
                time.sleep(0.02)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2)
            adapter._main_loop = None

        assert len(webhookEvents) == 1 and len(streamEvents) == 1, (
            f"两条路各投了几条：webhook={len(webhookEvents)} stream={len(streamEvents)}")
        w, s = webhookEvents[0], streamEvents[0]
        assert (w.content, w.message_type, w.sender_id, w.chat_id) == (
            s.content, s.message_type, s.sender_id, s.chat_id), (
            f"两条路形状不同：webhook={(w.content, w.message_type, w.sender_id)!r} "
            f"stream={(s.content, s.message_type, s.sender_id)!r}")
        assert w.metadata.get(AUDIO_BYTES_KEY) == s.metadata.get(AUDIO_BYTES_KEY) == b"SAME_BYTES"


def _bannedShapesIn(src: str, funcName: str) -> list:
    """端点里"自己解析事件内容"的两形（AST 口径，按**用途**取而不是按函数名取）。

    禁的是内容面手抄：`json.loads(<带 "content` 字面量的式子>)` 与 `== "text"` 的类型分派。
    **不禁** `json.loads(body)`——那是 HTTP 信封的传输面，端点本来就该做（把两者混为一谈的
    排除型断言会把合法代码一起报掉，本仓记过这一族）。
    """
    found = []
    tree = ast.parse(src)
    target = next((n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == funcName),
                  None)
    assert target is not None, f"函数 {funcName} 不在了——扫描口径失效"
    for node in ast.walk(target):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "loads":
            mentionsContent = any(isinstance(lit, ast.Constant) and lit.value == "content"
                                  for arg in node.args for lit in ast.walk(arg))
            if mentionsContent:
                found.append(f":{node.lineno} 内容面 json.loads")
        elif isinstance(node, ast.Compare):
            for op, comparator in zip(node.ops, node.comparators):
                if isinstance(op, ast.Eq) and isinstance(comparator, ast.Constant) \
                        and comparator.value == "text":
                    found.append(f":{node.lineno} == 'text' 类型分派")
    return found


class TestEndpointStopsHandCopyingTheEventBody:
    def testFeishuBranchNoLongerParsesThePayloadItself(self):
        hits = _bannedShapesIn(ENDPOINTS_SRC, "_handle_feishu_webhook")
        assert hits == [], f"端点里还留着手抄的事件体解析：{hits}"

    def testDetectorHasTeethOnTheDingTalkBranch(self):
        """变异对照：同一探测器打在**仍然手抄**的钉钉支上必须报东西——否则上一格是假绿。"""
        hits = _bannedShapesIn(ENDPOINTS_SRC, "_handle_dingtalk_webhook")
        assert hits, "探测器对现成的手抄形状零命中——那它对手抄的消失也不会红"

    def testDetectorSeparatesTransportFaceFromContentFace(self):
        """探测器自己也要审穿：合法的信封解析必须放过，内容面手抄必须抓到。"""
        sample = (
            "async def probe(body):\n"
            "    envelope = json.loads(body)\n"                     # 传输面：放过
            "    inner = json.loads(msg.get('content', '{}'))\n"    # 内容面：抓
            "    if msg.get('message_type') == 'text':\n"           # 类型分派：抓
            "        return inner\n"
        )
        hits = _bannedShapesIn(sample, "probe")
        assert len(hits) == 2, f"探测器口径不准（实得 {hits}）"
        assert any("内容面" in h for h in hits) and any("类型分派" in h for h in hits)
