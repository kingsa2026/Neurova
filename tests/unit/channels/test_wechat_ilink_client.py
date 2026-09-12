# -*- coding: utf-8 -*-
"""iLink Bot HTTP client 协议契约测试（QwenPaw wechat/client.py + utils.py 照搬移植）。

钉死真实官方协议语义（HTTP/JSON @ ilinkai.weixin.qq.com）：
- make_headers：X-WECHAT-UIN（base64 随机 uint32 防重放）/ AuthorizationType /
  有 token 才带 Bearer。
- getupdates：body 含 get_updates_buf cursor + base_info.channel_version。
- send_text：item_list type=1 + context_token（平台要求必填，≤10 回复/轮）。
- AES-128-ECB：encrypt→decrypt 回环 + 三种 key 格式自动识别（hex/base64(raw)/
  base64(hex)）——cryptography 实现（不引 pycryptodome）。
- download_media：encrypt_query_param → novac2c CDN URL + 解密。
- upload_media：getuploadurl→CDN POST→X-Encrypted-Param 回传（缺参诚实抛错）。
"""

from __future__ import annotations

import base64
import json

import pytest


class _Resp:
    def __init__(self, payload=None, content=b"", headers=None, status=200):
        self._payload = payload if payload is not None else {}
        self.content = content
        self.headers = headers or {}
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttpx:
    """记录调用并按 (method, url 前缀) 路由 httpx.AsyncClient 替身。"""

    def __init__(self, routes=None):
        self.routes = routes or []
        self.calls = []
        self._usage = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False

    async def aclose(self):
        pass

    def _match(self, method, url):
        for r in self.routes:
            if r["method"] != method or not url.startswith(r["url_startswith"]):
                continue
            used = self._usage.get(id(r), 0)
            if r.get("times", 1) <= used:
                continue
            self._usage[id(r)] = used + 1
            return r
        raise AssertionError(f"unrouted {method} {url}")

    async def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("GET", url, params, headers))
        r = self._match("GET", url)
        return r["resp"]

    async def post(self, url, json=None, content=None, headers=None, timeout=None):
        self.calls.append(("POST", url, json, content, headers))
        r = self._match("POST", url)
        return r["resp"]


@pytest.fixture
def client_with(monkeypatch):
    from neurova.channels import wechat_ilink_client as mod

    def _make(bot_token="tok-1", routes=None, **kw):
        c = mod.ILinkClient(bot_token=bot_token, **kw)
        fake = FakeHttpx(routes or [])
        c._client = fake  # 直注替身，绕开 start()
        return c, fake

    return _make


# ------------------------------------------------------------------
# headers / utils
# ------------------------------------------------------------------


def test_make_headers_shape():
    from neurova.channels.wechat_ilink_client import make_headers

    h = make_headers("abc")
    assert h["AuthorizationType"] == "ilink_bot_token"
    assert h["Authorization"] == "Bearer abc"
    # X-WECHAT-UIN = base64(十进制随机 uint32)
    decoded = base64.b64decode(h["X-WECHAT-UIN"]).decode()
    assert decoded.isdigit() and 0 <= int(decoded) < 0xFFFFFFFF


def test_make_headers_without_token_no_bearer():
    from neurova.channels.wechat_ilink_client import make_headers

    assert "Authorization" not in make_headers("")


def test_aes_ecb_roundtrip_three_key_formats():
    from neurova.channels.wechat_ilink_client import aes_ecb_decrypt, aes_ecb_encrypt

    raw = bytes(range(16))
    key_b64 = base64.b64encode(raw).decode()          # Format A：base64(16 字节)
    key_hex = raw.hex()                                 # 32 位 hex
    key_b64hex = base64.b64encode(key_hex.encode()).decode()  # Format B：base64(hex)
    data = b"hello wechat iLink media" * 7

    enc = aes_ecb_encrypt(data, key_b64)
    assert enc != data and len(enc) % 16 == 0
    # 三种格式都能解同一密文
    assert aes_ecb_decrypt(enc, key_b64) == data
    assert aes_ecb_decrypt(enc, key_hex) == data
    assert aes_ecb_decrypt(enc, key_b64hex) == data


# ------------------------------------------------------------------
# auth + messaging 请求体规范
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_getupdates_body_official_shape(client_with):
    routes = [{"method": "POST", "url_startswith": "https://ilinkai.weixin.qq.com/ilink/bot/getupdates",
               "resp": _Resp({"ret": 0, "msgs": [], "get_updates_buf": "cur-2"})}]
    c, fake = client_with(routes=routes)
    data = await c.getupdates("cur-1")
    assert data["get_updates_buf"] == "cur-2"
    call = fake.calls[0]
    assert call[1].endswith("/ilink/bot/getupdates")
    body = call[2]
    assert body["get_updates_buf"] == "cur-1"
    assert body["base_info"]["channel_version"]


@pytest.mark.asyncio
async def test_send_text_item_list_shape(client_with):
    routes = [{"method": "POST", "url_startswith": "https://ilinkai.weixin.qq.com/ilink/bot/sendmessage",
               "resp": _Resp({"ret": 0})}]
    c, fake = client_with(routes=routes)
    await c.send_text("u@im.wechat", "你好", "ctx-9")
    body = fake.calls[0][2]
    msg = body["msg"]
    assert msg["to_user_id"] == "u@im.wechat"
    assert msg["context_token"] == "ctx-9"
    assert msg["message_type"] == 2 and msg["message_state"] == 2
    assert msg["item_list"] == [{"type": 1, "text_item": {"text": "你好"}}]
    assert msg["client_id"]  # uuid 幂等键必填


@pytest.mark.asyncio
async def test_get_bot_qrcode_and_status_paths(client_with):
    routes = [
        {"method": "GET", "url_startswith": "https://gw.example/ilink/bot/get_bot_qrcode",
         "resp": _Resp({"qrcode": "qr-1", "qrcode_img_content": ""})},
        {"method": "GET", "url_startswith": "https://gw.example/ilink/bot/get_qrcode_status",
         "resp": _Resp({"status": "confirmed", "bot_token": "t2", "baseurl": "https://gw2.example"})},
    ]
    c, fake = client_with(bot_token="", base_url="https://gw.example/", routes=routes)
    d = await c.get_bot_qrcode()
    assert d["qrcode"] == "qr-1"
    assert fake.calls[0][1].startswith("https://gw.example/ilink/")  # base_url 尾斜杠已剥
    s = await c.get_qrcode_status("qr-1")
    assert s["status"] == "confirmed" and s["baseurl"] == "https://gw2.example"


@pytest.mark.asyncio
async def test_not_started_client_raises():
    from neurova.channels.wechat_ilink_client import ILinkClient, ILinkError

    c = ILinkClient("t")
    with pytest.raises(ILinkError):
        await c.getupdates("")


# ------------------------------------------------------------------
# media：下载解密 / 上传取回传参
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_media_cdn_url_and_decrypt(client_with):
    from neurova.channels.wechat_ilink_client import aes_ecb_encrypt

    raw_key = bytes(range(16))
    key_b64 = base64.b64encode(raw_key).decode()
    plain = b"PNGDATA" * 10
    enc = aes_ecb_encrypt(plain, key_b64)
    routes = [{"method": "GET", "url_startswith": "https://novac2c.cdn.weixin.qq.com/c2c/download",
               "resp": _Resp(content=enc)}]
    c, fake = client_with(routes=routes)
    got = await c.download_media("", aes_key_b64=key_b64,
                                 encrypt_query_param="abc?x=1")
    url = fake.calls[0][1]
    assert "encrypted_query_param=abc%3Fx%3D1" in url  # quote(safe="")
    assert got == plain


@pytest.mark.asyncio
async def test_upload_media_flow(client_with, tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"x" * 40)
    routes = [
        {"method": "POST", "url_startswith": "https://ilinkai.weixin.qq.com/ilink/bot/getuploadurl",
         "resp": _Resp({"upload_full_url": "https://novac2c.cdn.weixin.qq.com/c2c/upload?p=1"})},
        {"method": "POST", "url_startswith": "https://novac2c.cdn.weixin.qq.com/c2c/upload",
         "resp": _Resp(headers={"x-encrypted-param": "eqp-99"}, status=200)},
    ]
    c, fake = client_with(routes=routes)
    out = await c.upload_media(str(f), 3, "u@im.wechat")
    assert out["encrypt_query_param"] == "eqp-99"
    assert out["filesize"] % 16 == 0 and out["filesize"] >= 40
    # 消息用 aes_key = base64(hex 字符串)（picoclaw encodeWeixinOutboundAESKey 同构）
    assert base64.b64decode(out["aes_key_b64"]).decode().strip() in ("",) or \
        bytes.fromhex(base64.b64decode(out["aes_key_b64"]).decode())
    # getuploadurl body 齐备官方字段
    body = fake.calls[0][2]
    for k in ("filekey", "media_type", "to_user_id", "rawsize", "rawfilemd5", "filesize", "aeskey"):
        assert k in body
    assert body["media_type"] == 3


@pytest.mark.asyncio
async def test_upload_media_missing_param_honest_error(client_with, tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"y" * 20)
    routes = [
        {"method": "POST", "url_startswith": "https://ilinkai.weixin.qq.com/ilink/bot/getuploadurl",
         "resp": _Resp({"upload_full_url": "https://cdn.example/u"})},
        {"method": "POST", "url_startswith": "https://cdn.example/u",
         "resp": _Resp(headers={})},  # CDN 未回传 x-encrypted-param
    ]
    c, _ = client_with(routes=routes)
    with pytest.raises(ValueError, match="encrypt_query_param"):
        await c.upload_media(str(f), 1, "u@im.wechat")


@pytest.mark.asyncio
async def test_send_file_wraps_upload_and_item_shape(client_with, tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"z" * 33)
    routes = [
        {"method": "POST", "url_startswith": "https://ilinkai.weixin.qq.com/ilink/bot/getuploadurl",
         "resp": _Resp({"upload_full_url": "https://cdn.example/u"})},
        {"method": "POST", "url_startswith": "https://cdn.example/u",
         "resp": _Resp(headers={"x-encrypted-param": "eqp-1"})},
        {"method": "POST", "url_startswith": "https://ilinkai.weixin.qq.com/ilink/bot/sendmessage",
         "resp": _Resp({"ret": 0})},
    ]
    c, fake = client_with(routes=routes)
    await c.send_file("u@im.wechat", str(f), "doc.pdf", "ctx-1")
    body = fake.calls[2][2]
    item = body["msg"]["item_list"][0]
    assert item["type"] == 4
    assert item["file_item"]["file_name"] == "doc.pdf"
    assert item["file_item"]["media"]["encrypt_query_param"] == "eqp-1"
    assert item["file_item"]["media"]["encrypt_type"] == 1
