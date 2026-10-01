"""多模态探测图必须是**真能解码的 PNG**（U-01 卡在这儿的实测根因）。

## 为什么会红

2026-10-01 为跑 U-01（把 `capabilities.vision` 顶到 available）对商汤网关真探一次，
回的是：

```
HTTP 400: invalid image base64 content      →  probe_source = "inconclusive"
```

网关嫌的是**我们发出去的探测图**：`OpenAIProvider._IMAGE_PROBE_PNG_BASE64` 那段内联
base64 解出来 208 字节，PNG 签名是对的，但 chunk 结构坏掉——`PIL.Image.open()` 直接
`UnidentifiedImageError: cannot identify image file`。后果不是"某次探测失败"：
凡是严格校验媒体的网关都永远给出不了结论的错，于是 **vision 能力实测不出**，
`_probeVision` 的实测档（§30 刚接上的那条）拿不到东西，T-09 的附图闸门开不了。

## 判据口径

- 图自己过一遍解码器（PIL verify + load + 取中心像素），不断言 base64 文本；
- 线上形状：把 `aiohttp` 那层替掉（外部慢操作），断言**生产代码发出去的** data URL
  解码后仍是那张可开的红图——不是断言替身被怎么调。
"""
import base64
import io

import pytest

from neurova.llm.providers.openai_provider import OpenAIProvider


def _decode(b64: str) -> bytes:
    return base64.b64decode(b64)


def test_probeImageFixtureIsADecodableRedSquare():
    raw = _decode(OpenAIProvider._IMAGE_PROBE_PNG_BASE64)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "连 PNG 签名都不对"
    assert b"IEND" in raw[-12:], f"尾部缺 IEND（最后 12 字节 {raw[-12:]!r}）——这样的 PNG 谁都解不开"

    from PIL import Image

    img = Image.open(io.BytesIO(raw))
    assert img.format == "PNG"
    img.verify()
    reopened = Image.open(io.BytesIO(raw))
    reopened.load()
    assert reopened.size == (32, 32), f"探测图尺寸漂了：{reopened.size}"
    red, green, blue = reopened.convert("RGB").getpixel((16, 16))
    assert red > 200 and green < 40 and blue < 40, \
        f"探测图必须纯红（判据靠'答红色系'确认真看了图），实得 {(red, green, blue)}"


def test_probeRequestPutsADecodableImageOnTheWire(monkeypatch):
    """发出去的 data URL 必须自己解得开——坏图在严格网关那里只会换回一句 400。"""
    import asyncio

    captured: dict = {}

    class _Response:
        status = 200

        async def json(self):
            return {"choices": [{"message": {"content": "red"}}]}

    class _PostCtx:
        async def __aenter__(self):
            return _Response()

        async def __aexit__(self, *exc):
            return False

    class _Session:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def post(self, url, **kwargs):
            captured["url"] = url
            captured["payload"] = kwargs.get("json")
            return _PostCtx()

    class _AiohttpStub:
        ClientSession = _Session

        @staticmethod
        def ClientTimeout(total=None):  # noqa: N805 - 生产码用 hasattr 探这个符号
            return ("timeout", total)

    monkeypatch.setattr("neurova.llm.providers.openai_provider.aiohttp", _AiohttpStub)

    provider = OpenAIProvider(api_key="probe-key", base_url="https://probe.test/v1")
    asyncio.run(provider._image_probe_request("some-vision-model"))

    url = captured["payload"]["messages"][0]["content"][0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    body = url.split("base64,", 1)[1]
    raw = _decode(body)

    from PIL import Image

    img = Image.open(io.BytesIO(raw))
    img.load()
    assert img.size == (32, 32)
    assert captured["payload"]["messages"][0]["content"][1]["text"] == \
        OpenAIProvider._IMAGE_PROBE_PROMPT, "图文不同源：问的不是这张图"
