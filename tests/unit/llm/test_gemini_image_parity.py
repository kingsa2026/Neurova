# -*- coding: utf-8 -*-
"""M3（多模态追平批一）：Gemini 原生视觉链路 parity。

对齐 `test_perception_image_anthropic_parity.py` 的形态：

- 管线侧只产 OpenAI `image_url` 切片（`visionImagePart` 单源）；
- 协议转换收口在 provider 层：`build_gemini_body` 必须把 `image_url`
  切片转成 Gemini 原生 `inline_data` part——不得把整个 content 列表
  `str()` 拍平成文本（改前形态：图片变 Python repr 噪声，模型看不到图）；
- 单次进入请求：一张图在整个请求体里只出现一次；
- 原始 messages 不被改写（base64 不进跨轮历史）；
- `ContextConverter` 增 Gemini 原生 content 形态并按模型分派。
"""
import base64
import io

import pytest
from PIL import Image

from neurova.llm.providers.gemini_client import build_gemini_body


def _makeRealPng() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (12, 34, 56)).save(buf, format="PNG")
    return buf.getvalue()


REAL_PNG = _makeRealPng()
FAKE_PNG_B64 = base64.b64encode(REAL_PNG).decode("ascii")


def _openaiVisionMessage() -> dict:
    """管线实际交出的形状：`_apply_vision_attachments` 挂好的 OpenAI 多模态 content。"""
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": "这张图的主色是什么？"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{FAKE_PNG_B64}"}},
        ],
    }


def _allParts(body: dict) -> list:
    parts = []
    for content in body.get("contents") or []:
        parts.extend(content.get("parts") or [])
    return parts


def _inlineDataParts(body: dict) -> list:
    return [p for p in _allParts(body) if isinstance(p, dict) and "inline_data" in p]


class TestGeminiBodyCarriesImage:
    def test_imageSlice_becomesGeminiInlineDataPart(self):
        """image_url 切片必须转成 inline_data（mime+base64），文本段原样保留。"""
        body = build_gemini_body([_openaiVisionMessage()])

        inlines = _inlineDataParts(body)
        assert inlines, "图片被 str() 拍平成文本，Gemini 原生链路收不到图"
        inline = inlines[0]["inline_data"]
        assert inline["mime_type"] == "image/png"
        assert inline["data"] == FAKE_PNG_B64
        texts = [p.get("text") for p in _allParts(body) if "text" in p]
        assert "这张图的主色是什么？" in texts, "文本段不得因图片转换丢失"

    def test_imageEntersRequestBodyExactlyOnce(self):
        """单次进入请求：一张图在整个请求体里只允许出现一次。"""
        body = build_gemini_body([_openaiVisionMessage()])

        assert len(_inlineDataParts(body)) == 1, "同一张图在请求体里重复出现"

    def test_visionImagePart_bytesDecodeBackToPng(self):
        """装配单源 `visionImagePart` 的产物经 Gemini 转换后仍是可解的 PNG。"""
        from neurova.agent.attachment_turn_injection import visionImagePart

        part = visionImagePart(REAL_PNG, "image/png")
        body = build_gemini_body([{"role": "user", "content": [part]}])

        inlines = _inlineDataParts(body)
        assert inlines, "visionImagePart 产物没能进 Gemini 请求体"
        raw = base64.b64decode(inlines[0]["inline_data"]["data"])
        assert Image.open(io.BytesIO(raw)).format == "PNG", "转换后字节解不开成 PNG"

    def test_remoteImageUrl_becomesFileDataReference(self):
        """非 data URL 走 Gemini 的 file_data 引用形态（不支持时由 API 诚实报错）。"""
        body = build_gemini_body(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "https://example.test/a.png"}}
                    ],
                }
            ]
        )

        file_refs = [p for p in _allParts(body) if "file_data" in p]
        assert file_refs, "远程 URL 应转 file_data 引用，而不是被拍平成文本"
        assert file_refs[0]["file_data"]["file_uri"] == "https://example.test/a.png"

    def test_originalMessagesStayUntouched(self):
        """转换只读入参：原 messages（跨轮活的那份）一字不改。"""
        msg = _openaiVisionMessage()
        before = repr(msg)

        build_gemini_body([msg])

        assert repr(msg) == before, "入参 messages 被改写——base64 会经此进历史"

    def test_plainTextPathUnchanged(self):
        """纯文本轮零变化：仍是单 text part（回归保护）。"""
        body = build_gemini_body([{"role": "user", "content": "hi"}])

        assert body["contents"] == [{"role": "user", "parts": [{"text": "hi"}]}]


class TestConverterGeminiForm:
    def _multimodalContext(self):
        from neurova.context.converter import ContextConverter
        from neurova.context.pool_models import ContextInput, ContextSource

        return (
            ContextConverter(),
            ContextInput(
                source=ContextSource.MULTIMODAL,
                content="看图",
                metadata={
                    "media_type": "image",
                    "media_url": f"data:image/png;base64,{FAKE_PNG_B64}",
                },
            ),
        )

    def test_toGeminiFormat_producesNativeParts(self):
        converter, ctx = self._multimodalContext()

        entry = converter.to_gemini_format(ctx)

        assert entry["role"] == "user"
        kinds = {key for part in entry["parts"] for key in part}
        assert "inline_data" in kinds, f"Gemini 形态缺 inline_data：{entry}"
        assert "text" in kinds

    def test_convertForModel_dispatchesGeminiByModelName(self):
        converter, ctx = self._multimodalContext()

        entry = converter.convert_for_model(ctx, "gemini-2.5-flash")

        assert "parts" in entry, "gemini 模型未分派到原生 parts 形态"
        assert any("inline_data" in p for p in entry["parts"])
