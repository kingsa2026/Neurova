# -*- coding: utf-8 -*-
"""渠道入站媒体落 into 附件单点批（红灯）。

复核实状（逐处自己命中）：

- 唯一必经的回合装配点在 `channels/channel_router.py:make_handler`：它先做准入判定，
  再由 `UserIdentityManager().resolveTurnIdentity()`（第 189-191 行）算出**这一轮的属主**。
  属主只在这一层拿得到——上游 `manager._on_channel_event` 只有 sender_id/chat_id。
- 纯媒体轮在**任何处理之前**就被丢：`channel_router.py:131-133` 的
  `if not content: return None`。ilink 解析出的图片消息正文为空（`wechat_ilink.py:245-250` 只往
  metadata 挂 `image_path`），于是这类回合物料齐了却连回合都不进。
- 素材今天已经有，只是没人接：`wechat_ilink.py` 挂 `image_path`/`video_path`/`file_path`（本地
  路径字符串，过入站队列安全）、`wecom_aibot.py` 挂 `image_path`/`file_path`、
  `wechat_kf.py:185` 挂 `media_bytes`（字节，过 `channel_ingress_queue.py:153-167` 的
  `default=str` JSON 化会变形 ⇒ 必须在入队前 staging 成路径）。
- **语音刻意不合流**：`voice_precheck` 跑在入队之前，已把 ASR 真产物写进 `VOICE_CONTEXT_KEY`，
  那条读侧刚被证明活着。再把同一份字节落成音频附件＝同一句语音转写两遍、历史里同时留
  「转写文本」与「音频附件」两种形态——本批用一条反向判据把这条界线钉住。
- 落盘规则只许有一份：`files_api.upload_file` 里的净化／危险扩展名拒绝／越根二次校验／登记
  是 P0 安全面的唯一实现。渠道入站必须与它**共用同一份 helper**，不是抄第二份。

判据形态：断「真 handler 交出去的 metadata 里带 attachments」「同 filename 的落点两处一致」
「危险扩展名被拒不留残留」「语音不被二次落地」。DB 写穿由在册档 `test_files_store_persistence.py`
负责，本档只替 `persist_file` 记账，避免单元跑测写真库——落盘字节、内存表、属主读回全走生产码。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from neurova.channels.base import ChannelMessage

REPO = pathlib.Path(__file__).resolve().parents[3]
from tests.ast_scan import parseSource  # noqa: E402


def _pngBytes() -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (20, 20), (30, 90, 150)).save(buf, format="PNG")
    return buf.getvalue()


class _CapturingAgent:
    """只替 agent 本体，把生产交给它的 metadata 原样收下来。"""

    def __init__(self):
        self.seenMetadata = []
        self.seenInput = []
        self.config = type("C", (), {"show_thinking": False, "show_tool_messages": False})()
        self.current_reasoning = ""

    def get_tool_messages_snapshot(self):
        return []

    async def chat(self, user_input="", session_id="", metadata=None, **kw):
        self.seenInput.append(user_input)
        self.seenMetadata.append(metadata or {})
        return {"text": "看到了"}


@pytest.fixture()
def isolatedFilesStore(monkeypatch, tmp_path):
    """把上传根与写穿落点挪出仓内；内存表按原样回填（不只回填引用）。"""
    from neurova.api.endpoints import files_api

    root = tmp_path / "storage" / "users"
    monkeypatch.setattr(files_api, "STORAGE_ROOT", root)
    saved = dict(files_api._files_store)
    files_api._files_store.clear()
    written: list = []
    monkeypatch.setattr(files_api, "persist_file",
                        lambda file_id, info, db_path=None: written.append((file_id, dict(info))))
    yield files_api, root, written
    files_api._files_store.clear()
    files_api._files_store.update(saved)


def _manager():
    from neurova.channels.manager import ChannelManager

    ChannelManager._instance = None
    return ChannelManager()


def _mediaMessage(tmp_path, key: str, suffix: str, *, content: str, message_type: str) -> ChannelMessage:
    target = tmp_path / f"素材样本{suffix}"
    target.write_bytes(_pngBytes() if suffix == ".png" else b"raw-bytes-content")
    return ChannelMessage(
        channel_type="wechat_ilink", message_id=f"m_{key}", sender_id="wx_u1", sender_name="wx_u1",
        content=content, chat_id="wx_chat", chat_type="p2p", message_type=message_type,
        metadata={key: str(target)},
    )


class TestChannelMediaLandsAsAttachments:
    @pytest.mark.asyncio
    async def testPureImageTurnReachesTheTurnWithAttachments(self, tmp_path, isolatedFilesStore):
        """正文为空的纯图片轮：不再被丢弃，且素材变成属主名下的 attachments 进回合。"""
        from neurova.channels.channel_router import make_handler

        files_api, root, _ = isolatedFilesStore
        agent = _CapturingAgent()
        msg = _mediaMessage(tmp_path, "image_path", ".png", content="", message_type="image")

        await make_handler(_manager(), lambda _aid: agent)(msg)

        assert agent.seenMetadata, "纯媒体轮仍被『正文为空』丢掉，回合根本没被调用"
        attachments = agent.seenMetadata[0].get("attachments") or []
        assert len(attachments) == 1, f"素材没变成附件：{attachments!r}"
        assert attachments[0]["file_type"] == "image", attachments[0]
        landed = root.rglob("*.png")
        assert any(True for _ in landed), "字节没落到用户上传根之下"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key,suffix,message_type,expected", [
        ("video_path", ".mp4", "video", "video"),
        ("file_path", ".pdf", "file", "document"),
    ])
    async def testVideoAndDocumentSourcesLandWithServerSideTypes(
        self, tmp_path, isolatedFilesStore, key, suffix, message_type, expected
    ):
        """视频/文件素材同样进附件单点；类型由服务端判定，不采信客户端自报。"""
        from neurova.channels.channel_router import make_handler

        _files_api, _root, _ = isolatedFilesStore
        agent = _CapturingAgent()
        msg = _mediaMessage(tmp_path, key, suffix, content="看下这个", message_type=message_type)

        await make_handler(_manager(), lambda _aid: agent)(msg)

        attachments = (agent.seenMetadata[0] if agent.seenMetadata else {}).get("attachments") or []
        assert len(attachments) == 1, f"{key} 没落成附件：{attachments!r}"
        assert attachments[0]["file_type"] == expected, attachments[0]

    @pytest.mark.asyncio
    async def testChannelVoiceIsNotLandedAsSecondTranscription(self, tmp_path, isolatedFilesStore):
        """反向判据（今天就该绿）：语音走预检那条已在役的路，不再被落成音频附件。

        同一句语音转写两遍会在历史里同时留下「转写文本」与「音频附件」两种形态。
        """
        from neurova.channels.channel_router import make_handler

        _files_api, _root, _ = isolatedFilesStore
        agent = _CapturingAgent()
        msg = ChannelMessage(
            channel_type="feishu", message_id="m_v", sender_id="ou_v", sender_name="ou_v",
            content="帮我看下明天的排程", chat_id="oc_v", chat_type="p2p", message_type="voice",
            metadata={"audio_bytes": b"WAV-BYTES"},
        )

        await make_handler(_manager(), lambda _aid: agent)(msg)

        handed = agent.seenMetadata[0] if agent.seenMetadata else {}
        assert not handed.get("attachments"), f"语音被第二条路落成了附件：{handed.get('attachments')!r}"


class TestStorageRulesAreNotCopiedTwice:
    def testPersistBytesUsesTheEndpointRuleSet(self, isolatedFilesStore):
        """纯字节入口与上传端点共用同一份落点规则（同 filename 同 file_type 同目录形态）。"""
        files_api, root, written = isolatedFilesStore

        info = files_api.persistBytes(
            user_id="u1", agent_id="a1", session_id="s1",
            filename="发布会.mp4", data=b"abcdefgh",
        )

        assert info["file_type"] == "video", info
        assert info["size"] == 8, info
        assert info["user_id"] == "u1" and info["file_id"]
        onDisk = pathlib.Path(info["path"])
        assert onDisk.is_file() and onDisk.read_bytes() == b"abcdefgh"
        assert onDisk.parent == root / "u1" / "agents" / "a1" / "sessions" / "s1" / "video", onDisk.parent
        # 属主读回：按 user_id 限属主的现读面必须拿得到
        assert files_api.get_attachment_info(info["file_id"], "u1"), "登记后属主读不到"
        assert files_api.get_attachment_info(info["file_id"], "u2") is None, "非属主也能读到"
        assert written, "写穿没被调用（内存表与库会漂）"

    def testDangerousExtensionRejectedWithoutResidue(self, isolatedFilesStore):
        """危险扩展名拒绝，且不在盘上留半截文件。"""
        files_api, root, _ = isolatedFilesStore

        with pytest.raises(ValueError):
            files_api.persistBytes(user_id="u1", agent_id="a1", session_id="s1",
                                   filename="setup.exe", data=b"MZ....")
        assert not list(root.rglob("*.exe")), "被拒绝的落点留下了残留文件"

    def testUploadEndpointDoesNotReimplementThePathRule(self):
        """单源正检：拼用户落点那条路径表达式只许出现在共享 helper 里。

        钉的是代码形态（谁在拼 STORAGE_ROOT/.../agents/...），不是文档里的说法；
        端点若留一份、渠道入站再抄一份，两处的净化与越根校验就会各漂各的。
        """
        source = (REPO / "neurova" / "api" / "endpoints" / "files_api.py").read_text(encoding="utf-8")
        tree = parseSource(source)
        offenders = []
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for node in ast.walk(fn):
                dump = ast.dump(node)
                if isinstance(node, ast.BinOp) and "STORAGE_ROOT" in dump and "agents" in dump:
                    offenders.append(fn.name)
                    break
        assert set(offenders) == {"_resolveTargetPath"}, f"落点规则出现在这些函数里: {sorted(set(offenders))}"

class TestChannelIdentityCannotEscapeTheStorageRoot:
    """我为了让渠道身份能落地，在 P0 校验旁边加了一层目录段转义——那必须钉住它转不出穿越。

    转义只换目录写法；记录里的属主仍存原值，`get_attachment_info` 的属主比对不受影响。
    """

    @pytest.mark.parametrize("hostile", [
        "ch:wechat_ilink:wx_u1",            # 渠道未绑定身份的真形态（带冒号）
        "../../etc/passwd",
        "a/b" + chr(92) + "c",
        "",
        "dotted.name.ok",
    ])
    def testSegmentAlwaysPassesTheP0Validator(self, hostile):
        import re

        from neurova.api.endpoints import files_api
        from neurova.channels.mediaIngress import _pathSegment

        segment = _pathSegment(hostile)
        assert segment and ".." not in segment
        assert "/" not in segment and "\\" not in segment
        assert re.match(files_api._PATH_SEGMENT_RE, segment), segment

    def testOwnerIdKeepsItsExactValue(self, isolatedFilesStore):
        """目录段被转义，但属主字段必须是原值——否则跨渠道同人两身份读不回自己的文件。"""
        from neurova.channels import mediaIngress

        files_api, _root, _ = isolatedFilesStore
        info = files_api.persistBytes(
            user_id="ch_wechat_ilink_wx_u1", agent_id="default", session_id="s1",
            filename="a.png", data=b"x", ownerId="ch:wechat_ilink:wx_u1",
        )
        assert info["user_id"] == "ch:wechat_ilink:wx_u1", info
        assert files_api.get_attachment_info(info["file_id"], "ch:wechat_ilink:wx_u1"), "原值读不回"

        attachments = mediaIngress.landInboundMedia(
            metadata={"image_path": "/nope/missing.png"},
            user_id="ch:feishu:ou_x", agent_id="default", session_id="oc:x",
        )
        assert attachments == [], "素材不在盘上却伪造出一条附件"
