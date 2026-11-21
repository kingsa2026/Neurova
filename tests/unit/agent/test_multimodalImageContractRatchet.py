# -*- coding: utf-8 -*-
"""多模态契约棘轮（批三 · M8）：图片附件进模型前的一道格式闸 + 工具图回灌。

四类契约（对齐 LobeHub MessageContent 全矩阵的**行为语义**，实现形态本仓自有）：

1. **SVG 拒发**：矢量图不进视觉通道——服务商（OpenAI/Anthropic/Gemini）不收
   `image/svg+xml`，原样发出去整轮必被拒。改为诚实留痕（与视频抽不到帧同款
   "本轮未能看到画面"形态），不静默丢、不发必被拒的原件。
2. **AVIF/非常规位图**：PIL 能解码就转码成服务商支持的 PNG/JPEG 再附
   （"媒体引用兜底"——模型真看得到画面）；解不开的字节诚实说明，不静默丢。
3. **图片 + 无 vision 候选模型**：装配层不丢图——切片照挂、覆盖不激活，
   请求带图交给 provider 诚实裁决（报错也是诚实形态），不悄悄剥图。
4. **工具产出图片回灌**：所有截图类工具的图汇入同一个轮级槽
   （`offerTurnPerceptionImage`），只经感知闸门（缺口 + vision 可用 + 一轮一张）
   进下一轮请求；工具结果体不带 base64，只留 `has_image` 痕。

判据都咬真字节：图片用 PIL 现造真图（AVIF/PNG/JPEG/GIF/WEBP），
不用假字节冒充媒体数据（假字节只会撞进异常分支，主路径没被走过）。
"""

from __future__ import annotations

import asyncio
import base64
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from neurova.agent.chat_pipeline import ChatPipeline
from neurova.core import turn_context as tc


def _imageBytes(fmt: str, color=(12, 34, 56)) -> bytes:
    """现造一张真图（Pillow 对 AVIF 的解码依赖本机 libavif，缺席时由调用方跳过）。"""
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, format=fmt)
    return buf.getvalue()


_SVG_BYTES = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'
    b'<rect width="16" height="16" fill="#0c2238"/></svg>'
)
_NOT_AN_IMAGE = b"\x00\x01\x02this-is-not-an-image"


def _pipeline(monkeypatch, fileBytes: bytes):
    """最小管线替身：只注入"磁盘上有什么字节"，其余走真装配逻辑。"""
    p = object.__new__(ChatPipeline)
    monkeypatch.setattr(p, "_read_attachment_bytes", lambda file_id: fileBytes)
    return p


def _imageAttachment(filename: str, mime: str, file_type: str = "image", size: int = 128) -> dict:
    return {
        "file_id": f"f-{filename}",
        "filename": filename,
        "file_type": file_type,
        "mime_type": mime,
        "size": size,
        "path": f"/tmp/{filename}",
    }


def _partsOfKind(parts: list, kind: str) -> list:
    return [p for p in parts if isinstance(p, dict) and p.get("type") == kind]


# ══════════════════════════════════════════════════════════════
# 契约 1：SVG 拒发（先红后绿）
# ══════════════════════════════════════════════════════════════


class TestSvgRefused:
    def test_svgAttachmentIsRefusedHonestlyAndNeverAttached(self, monkeypatch):
        """SVG 不产视觉切片：服务商不收 image/svg+xml，原样发=整轮被拒。"""
        p = _pipeline(monkeypatch, _SVG_BYTES)
        text, parts = p._inject_attachments_into_input(
            "这是什么", [_imageAttachment("logo.svg", "image/svg+xml")]
        )

        assert _partsOfKind(parts, "image_url") == [], \
            f"SVG 不得进视觉通道，实际产出了 {len(_partsOfKind(parts, 'image_url'))} 个切片"
        assert "logo.svg" in text, "拒发也要留痕：文件名必须进本轮文本"
        assert "未能看到画面" in text, "与视频同款诚实形态：明说模型这轮没看到画面"
        assert "data:image/svg" not in text, "SVG 字节不得借文本通道溜进请求"

    def test_svgByExtensionOnlyAlsoRefused(self, monkeypatch):
        """mime 缺失但扩展名是 .svg 时同样拒发（按扩展名识别矢量图）。"""
        p = _pipeline(monkeypatch, _SVG_BYTES)
        att = _imageAttachment("diagram.svg", "")
        text, parts = p._inject_attachments_into_input("看图", [att])

        assert _partsOfKind(parts, "image_url") == []
        assert "未能看到画面" in text


# ══════════════════════════════════════════════════════════════
# 契约 2：AVIF/非常规位图 → 转码兜底（先红后绿）
# ══════════════════════════════════════════════════════════════


def _avifSupported() -> bool:
    from PIL import features

    return features.check("avif")


class TestUnsupportedRasterFallback:
    @pytest.mark.skipif(not _avifSupported(), reason="本机 Pillow 无 AVIF 解码插件")
    def test_avifImageIsReencodedSoTheModelActuallySeesIt(self, monkeypatch):
        """AVIF 原样发必被服务商拒；转码成 PNG 后模型才真看得到（媒体引用兜底）。"""
        avif = _imageBytes("AVIF")
        p = _pipeline(monkeypatch, avif)
        text, parts = p._inject_attachments_into_input(
            "看这张图", [_imageAttachment("photo.avif", "image/avif")]
        )

        imageParts = _partsOfKind(parts, "image_url")
        assert len(imageParts) == 1, f"AVIF 应转码后附上，实际切片数 {len(imageParts)}"
        url = imageParts[0]["image_url"]["url"]
        assert url.startswith(("data:image/png;base64,", "data:image/jpeg;base64,")), \
            f"应转码为服务商支持的位图，不再是 image/avif：{url[:40]}"
        decoded = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
        assert decoded.format in ("PNG", "JPEG"), "转码产物必须真是一张能解开的位图"
        assert "photo.avif" in text, "中性标记仍在：历史知道用户传了图"

    def test_avifClassifiedAsFileStillReachesVisionByMime(self, monkeypatch):
        """服务端分类不认 .avif（落 "file"），注入面按 mime 兜住：转码后照附。"""
        avif = _imageBytes("AVIF")
        p = _pipeline(monkeypatch, avif)
        text, parts = p._inject_attachments_into_input(
            "看这张图", [_imageAttachment("photo.avif", "image/avif", file_type="file")]
        )

        assert len(_partsOfKind(parts, "image_url")) == 1, \
            "mime 说它是图就该走视觉兜底，不该落进'未能抽取文本'"
        assert "未能抽取文本" not in text, "把图片当坏文档报错是误报"

    def test_undecodableImageBytesDegradeHonestlyWithoutPart(self, monkeypatch):
        """解不开的"图片"不装切片：诚实说明原因，不静默丢、不发必被拒的原件。"""
        p = _pipeline(monkeypatch, _NOT_AN_IMAGE)
        text, parts = p._inject_attachments_into_input(
            "看图", [_imageAttachment("mystery.img", "image/x-vnd.custom")]
        )

        assert _partsOfKind(parts, "image_url") == []
        assert "mystery.img" in text
        assert "未能看到画面" in text
        assert "image/x-vnd.custom" in text, "原因要点名 mime，便于排查"

    @pytest.mark.parametrize("fmt,mime", [
        ("PNG", "image/png"),
        ("JPEG", "image/jpeg"),
        ("GIF", "image/gif"),
        ("WEBP", "image/webp"),
    ])
    def test_supportedFormatsAttachAsThemselves(self, monkeypatch, fmt, mime):
        """钉约：服务商支持集合内的格式直装直发，不多一道转码。"""
        raw = _imageBytes(fmt)
        p = _pipeline(monkeypatch, raw)
        _, parts = p._inject_attachments_into_input(
            "看图", [_imageAttachment(f"pic.{fmt.lower()}", mime)]
        )

        imageParts = _partsOfKind(parts, "image_url")
        assert len(imageParts) == 1
        assert imageParts[0]["image_url"]["url"].startswith(f"data:{mime};base64,"), \
            f"{mime} 应原样直装，不得被多余转码"


# ══════════════════════════════════════════════════════════════
# 契约 3：图片 + 无 vision 候选模型 → 装配层不丢图（钉约）
# ══════════════════════════════════════════════════════════════


class TestNoVisionCandidateKeepsImages:
    def test_imagesStayAttachedAndCurrentModelKeptWhenNoCandidate(self, monkeypatch):
        """全库无 vision 候选：不激活覆盖、也**不在装配层剥图**——请求带图
        交给 provider 诚实裁决。静默丢图会让"用户传了图"变成无凭据的谜。"""
        from neurova.llm import llm_routing_overlay

        monkeypatch.setattr(
            llm_routing_overlay, "resolve_vision_capable_model", lambda cur, **kw: None
        )
        p = object.__new__(ChatPipeline)
        monkeypatch.setattr(p, "_current_model_name", lambda: "text-only-model")
        monkeypatch.setattr(p, "_apply_image_retention", lambda ctx: None)  # 另卡在改，此处隔离

        imagePart = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}
        ctx = SimpleNamespace(
            context=[{"role": "user", "content": "[用户上传了图片: pic.png（图片已随本轮请求附上）]"}],
            _pending_vision_parts=[imagePart],
        )

        p._flush_vision_attachments(ctx)

        lastUser = ctx.context[-1]
        assert isinstance(lastUser["content"], list)
        kinds = [c.get("type") for c in lastUser["content"] if isinstance(c, dict)]
        assert "image_url" in kinds, "无 vision 候选也不得在装配层静默丢图"
        assert llm_routing_overlay.get_vision_model_override() is None, "无候选不得凭空造覆盖"

    def test_fullChain_imageAttachmentReachesRequestEvenWithoutVisionCandidate(
        self, monkeypatch
    ):
        """全链钉约：附件注入 → 视觉切片 → flush 挂载，无候选时图仍进本轮请求。"""
        from neurova.llm import llm_routing_overlay

        png = _imageBytes("PNG")
        p = object.__new__(ChatPipeline)
        monkeypatch.setattr(p, "_read_attachment_bytes", lambda file_id: png)
        monkeypatch.setattr(
            llm_routing_overlay, "resolve_vision_capable_model", lambda cur, **kw: None
        )
        monkeypatch.setattr(p, "_current_model_name", lambda: "text-only-model")
        monkeypatch.setattr(p, "_apply_image_retention", lambda ctx: None)

        ctx = SimpleNamespace(
            user_input="看这张图",
            metadata={"attachments": [_imageAttachment("pic.png", "image/png")]},
            context=None,
            _pending_vision_parts=None,
        )
        asyncio.run(p._step_inject_attachments(ctx))
        assert ctx._pending_vision_parts, "注入面应产出视觉切片"

        ctx.context = [{"role": "user", "content": ctx.user_input}]
        p._flush_vision_attachments(ctx)

        kinds = [c.get("type") for c in ctx.context[-1]["content"] if isinstance(c, dict)]
        assert "image_url" in kinds, "全链走完图必须还在请求上"


# ══════════════════════════════════════════════════════════════
# 契约 4：工具产出图片回灌（钉约）
# ══════════════════════════════════════════════════════════════


def _realPngB64() -> str:
    return base64.b64encode(_imageBytes("PNG", (1, 2, 3))).decode("ascii")


class _EventSink:
    def __init__(self) -> None:
        self.events: list = []

    def append_tool_event(self, event: dict) -> None:
        self.events.append(event)


def _openaiLoop():
    from neurova.agent.loops.openai_loop import OpenAILoop

    loop = OpenAILoop.__new__(OpenAILoop)
    loop.agent = _EventSink()
    return loop


@pytest.fixture(autouse=True)
def _freshPerceptionSlot():
    tc.resetTurnPerceptionImage()
    yield
    tc.resetTurnPerceptionImage()


class TestToolImageFeedback:
    @pytest.mark.parametrize("tool", [
        "computer_screenshot",
        "computer_som_snapshot",
        "browser_screenshot",
    ])
    def test_everyScreenshotToolFeedsTheSingleTurnSlot(self, tool):
        """三类截图工具的图都汇入同一个轮级槽（单源），不各开旁路。"""
        from neurova.tool_executor import ToolExecutor

        executor = ToolExecutor.__new__(ToolExecutor)
        executor._agent = object()  # 无 session_id：WS 旁路早退，模型侧槽必须照收

        asyncio.run(executor._emit_computer_event(
            tool, {}, {"success": True}, screenshot_base64=_realPngB64()))

        taken = tc.takeTurnPerceptionImage()
        assert taken is not None, f"{tool} 的截图没进轮级槽"
        assert taken["toolName"] == tool, f"槽里记的产出工具应是 {tool}"

    def test_screenshotReachesNextRequestOnlyThroughTheGapGate(self, monkeypatch):
        """全链：工具产图进槽 → 无缺口不进请求；具名快照失败标缺口后，
        同一张图经闸门进下一轮请求副本（原始 messages 不被改写）。"""
        from neurova.computer_use import capability_state
        from neurova.tool_executor import ToolExecutor

        monkeypatch.setattr(
            capability_state, "reading",
            lambda name, **kw: capability_state.CapabilityReading(
                "vision", capability_state.CAP_AVAILABLE,
                capability_state.OWNER_AGENT, "判据造的可用量"),
        )
        executor = ToolExecutor.__new__(ToolExecutor)
        executor._agent = object()

        # 成功截图（无缺口）→ 图在槽里但不进请求
        asyncio.run(executor._emit_computer_event(
            "browser_screenshot", {}, {"success": True}, screenshot_base64=_realPngB64()))
        params = {"messages": [{"role": "user", "content": "点一下登录按钮"}], "tools": []}
        before = [dict(m) for m in params["messages"]]
        sent = _openaiLoop()._attachPerceptionImage(params)
        assert not any(
            isinstance(c, dict) and c.get("type") == "image_url"
            for m in sent["messages"]
            for c in (m["content"] if isinstance(m.get("content"), list) else [])
        ), "没有感知缺口也附图 = 闸门失效"
        assert params["messages"] == before

        # 具名快照失败 → 缺口标记，同一张槽里的图进下一轮请求**副本**
        asyncio.run(executor._emit_computer_event(
            "browser_dom_snapshot", {}, {"success": False, "error": "snapshot-empty: 无结构"}))
        sent2 = _openaiLoop()._attachPerceptionImage(params)
        imageParts = [
            c for m in sent2["messages"]
            for c in (m["content"] if isinstance(m.get("content"), list) else [])
            if isinstance(c, dict) and c.get("type") == "image_url"
        ]
        assert len(imageParts) == 1, "缺口出现后，槽里的截图应恰好附一张"
        assert params["messages"] == before, "原始 messages 被改写 = base64 进历史"
        assert tc.turnPerceptionGivenCount() == 1
