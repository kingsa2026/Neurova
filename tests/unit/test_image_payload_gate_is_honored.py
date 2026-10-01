# -*- coding: utf-8 -*-
"""413 闸门必须**兑现**：归一化的返回值要真的进得了载荷上限。

## 为什么值得常驻

`normalize_image_for_llm` 是 2026-09-09 那次 413 之后立的唯一一道防线，被两处消费
（附件注入 `chat_pipeline` 与感知截图 `perception_gate`）。它此前的判据是零——
所以「超阈值就降采样重编码，直到载荷进限」这句 docstring 一直没被检验过。

实测把它证伪了（工单集 §37，纯本地取值，无服务商参与）：

| 输入（逐字节随机噪声 = 编码最坏情况） | 归一化后 | 闸门 3MB |
|---|---|---|
| RGB 2048×2048 PNG，13,276,976 B | **JPEG 3,169,960 B** | **仍超** |
| RGBA 2600×1700 PNG，18,474,182 B | **PNG 9,045,543 B** | **仍超** |

两个形状都撞在同一条缺陷上：**只缩放一次、只编码一趟**。长边恰好等于尺寸帽时
`scale < 1` 不成立，尺寸没动；无 alpha 分支的 JPEG 在高熵内容上仍可能压不进限；
带 alpha 分支保透明的 PNG 更是基本按像素数线性膨胀。闸门没兑现，就等于
「防线是装饰」——超限的图照旧发给服务商，413 照旧整轮失败。

判据口径：给定**闸门要求的是返回值**，不是"努力过"。所以每条都用最坏情况夹具
（随机噪声）而不是好看的照片，且断言 `len(out) <= 闸门`。
"""
from __future__ import annotations

import io
import os

from neurova.attachment_parser import (
    LLM_IMAGE_MAX_DIMENSION,
    LLM_IMAGE_MAX_PAYLOAD_BYTES,
    normalize_image_for_llm,
)


def _noisePng(mode: str, width: int, height: int) -> bytes:
    """编码最坏情况的真图：逐像素随机字节，存成 PNG。

    不用 `Image.new(...)` 的纯色/渐变——那种内容 JPEG 能压到几十 KB，
    正好绕开这条缺陷，绿灯会是假的。
    """
    from PIL import Image

    channels = 4 if mode == "RGBA" else 3
    img = Image.frombytes(mode, (width, height), os.urandom(width * height * channels))
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def _assertEntersGate(data: bytes, mime: str) -> None:
    assert len(data) <= LLM_IMAGE_MAX_PAYLOAD_BYTES, (
        f"归一化后仍超闸门：{len(data)} B > {LLM_IMAGE_MAX_PAYLOAD_BYTES} B"
    )
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    img.load()
    assert max(img.size) <= LLM_IMAGE_MAX_DIMENSION, "长边没进尺寸帽"


class TestPayloadGateIsHonored:
    def test_jpegBranchEntersGateOnWorstCaseNoise(self):
        """无 alpha：尺寸帽本身不缩小（长边=2048）时，JPEG 一趟仍压不进 3MB。"""
        raw = _noisePng("RGB", 2048, 2048)
        assert len(raw) > LLM_IMAGE_MAX_PAYLOAD_BYTES, "夹具必须真的超闸门"

        out, mime = normalize_image_for_llm(raw, "image/png")

        _assertEntersGate(out, mime)

    def test_alphaBranchEntersGateAndKeepsTransparency(self):
        """带 alpha：保透明的 PNG 分支最容易漏——但透明不许被悄悄丢掉换体积。"""
        raw = _noisePng("RGBA", 1000, 800)
        assert len(raw) > LLM_IMAGE_MAX_PAYLOAD_BYTES, "夹具必须真的超闸门"

        out, mime = normalize_image_for_llm(raw, "image/png")

        _assertEntersGate(out, mime)
        from PIL import Image

        assert Image.open(io.BytesIO(out)).mode in ("RGBA", "LA", "PA", "P"), (
            "超闸门就改投 JPEG 会抹掉透明通道——前端拿到的图与用户看到的不是同一张"
        )

    def test_underGatePayloadIsPassedThroughUntouched(self):
        """闸门只该管超限的图：没超限就重编码 = 白白掉画质，也掩盖回归。"""
        raw = _noisePng("RGB", 64, 64)
        assert len(raw) <= LLM_IMAGE_MAX_PAYLOAD_BYTES

        out, mime = normalize_image_for_llm(raw, "image/png")

        assert out == raw
        assert mime == "image/png"

    def test_undecodableBytesFallBackAsIs(self):
        """解码失败原样返回（与模块整体降级语义一致），不许抛。"""
        junk = b"\x89PNG\r\n\x1a\n" + os.urandom(LLM_IMAGE_MAX_PAYLOAD_BYTES + 1024)

        out, mime = normalize_image_for_llm(junk, "image/png")

        assert out == junk
        assert mime == "image/png"
