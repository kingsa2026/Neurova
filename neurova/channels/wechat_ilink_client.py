# -*- coding: utf-8 -*-
"""iLink Bot HTTP client —— 微信个人号 Bot 协议（QwenPaw wechat/client.py+utils.py 照搬移植）。

真实端点全部在 https://ilinkai.weixin.qq.com 下，HTTP/JSON 协议，无第三方 SDK。

认证流：
1. GET /ilink/bot/get_bot_qrcode?bot_type=3 → qrcode + qrcode_img_content
2. 轮询 GET /ilink/bot/get_qrcode_status?qrcode= 直到 confirmed
3. confirmed 回包携带 bot_token + baseurl（后续请求的 Bearer 与网关）
4. 收消息 = POST /ilink/bot/getupdates 长轮询（服务端最长挂 ~35s）
5. 发消息 = POST /ilink/bot/sendmessage（必带 inbound 的 context_token，
   平台限制每个 context_token 最多回复 10 条）
媒体：CDN novac2c.cdn.weixin.qq.com/c2c，AES-128-ECB+PKCS7 加密
（下载解密 / 上传取 x-encrypted-param 回传参数）。

与 QwenPaw 的差异仅两处（均为依赖纪律）：
- AES 用已声明的 cryptography 实现（不新增 pycryptodome）；
- ChannelError → 本模块 ILinkError。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import uuid
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
_CHANNEL_VERSION = "2.0.1"
# 长轮询服务端挂起最长 ~35s，传输超时留余量
_GETUPDATES_TIMEOUT = 45.0
_DEFAULT_TIMEOUT = 15.0
# QR 状态轮询服务端可挂 ~30s
_QRCODE_STATUS_TIMEOUT = 60.0
_CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"


class ILinkError(RuntimeError):
    """iLink 协议层错误（未启动/被拒/返回异常）。"""


# ---------------------------------------------------------------------------
# 请求头与 AES 工具（QwenPaw wechat/utils.py 照搬）
# ---------------------------------------------------------------------------


def make_headers(bot_token: str = "") -> Dict[str, str]:
    """iLink API 请求头。

    X-WECHAT-UIN: base64(str(随机 uint32))——逐请求防重放；
    Authorization: Bearer <bot_token>——仅在有 token 时携带。
    """
    uin_val = secrets.randbelow(0xFFFFFFFF)
    uin_b64 = base64.b64encode(str(uin_val).encode()).decode()
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": uin_b64,
    }
    if bot_token:
        headers["Authorization"] = f"Bearer {bot_token}"
    return headers


def _parse_aes_key(key_b64: str) -> bytes:
    """AES key 三格式自动识别（对齐官方 TypeScript parseAesKey 逻辑）。

    - 32/48/64 位纯 hex 字符串（image_item.aeskey）→ bytes.fromhex
    - base64(16 字节原始 key)（图片）
    - base64(hex 字符串)（文件/语音/视频）
    """
    raw = key_b64.strip()
    if len(raw) in (32, 48, 64) and all(c in "0123456789abcdefABCDEF" for c in raw):
        return bytes.fromhex(raw)
    try:
        decoded = base64.b64decode(raw + "==")
    except Exception:
        decoded = raw.encode()
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32 and all(c in b"0123456789abcdefABCDEF" for c in decoded):
        return bytes.fromhex(decoded.decode("ascii"))
    return decoded


def aes_ecb_decrypt(data: bytes, key_b64: str) -> bytes:
    """AES-128-ECB 解密（PKCS7 去填充）。"""
    key = _parse_aes_key(key_b64)
    if len(key) not in (16, 24, 32):
        raise ValueError(f"Invalid AES key length: {len(key)} (from key_b64={key_b64[:20]!r})")
    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    padded = decryptor.update(data) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def aes_ecb_encrypt(data: bytes, key_b64: str) -> bytes:
    """AES-128-ECB 加密（PKCS7 填充）；key_b64 为 base64(16 字节)。"""
    key = base64.b64decode(key_b64)
    padder = PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


# ---------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------


class ILinkClient:
    """微信 iLink Bot API 异步 HTTP 客户端。

    Args:
        bot_token: 扫码登录后取得的 Bearer token。
        base_url: iLink API 基址（缺省 ilinkai.weixin.qq.com；
            QR confirmed 回包的 baseurl 优先）。
    """

    def __init__(self, bot_token: str = "", base_url: str = DEFAULT_BASE_URL) -> None:
        self.bot_token = bot_token
        self.base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(_GETUPDATES_TIMEOUT))

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # -- 内部 --------------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _require_client(self) -> None:
        if self._client is None:
            raise ILinkError("ILinkClient not started")

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None,
                   *, timeout: float = _DEFAULT_TIMEOUT) -> Any:
        self._require_client()
        resp = await self._client.get(self._url(path), params=params or {},
                                      headers=make_headers(self.bot_token), timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, body: Dict[str, Any],
                    timeout: float = _DEFAULT_TIMEOUT) -> Any:
        self._require_client()
        resp = await self._client.post(self._url(path), json=body,
                                       headers=make_headers(self.bot_token), timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    # -- 认证 --------------------------------------------------------------

    async def get_bot_qrcode(self) -> Dict[str, Any]:
        """取登录二维码：{qrcode, qrcode_img_content(base64 PNG)}。"""
        return await self._get("ilink/bot/get_bot_qrcode", {"bot_type": 3})

    async def get_qrcode_status(self, qrcode: str) -> Dict[str, Any]:
        """单次轮询扫码状态：waiting|scanned|confirmed|expired；
        confirmed 时带 bot_token + baseurl。"""
        return await self._get("ilink/bot/get_qrcode_status", {"qrcode": qrcode},
                               timeout=_QRCODE_STATUS_TIMEOUT)

    async def wait_for_login(self, qrcode: str, poll_interval: float = 1.5,
                             max_wait: float = 300.0) -> Tuple[str, str]:
        """阻塞至扫码 confirmed，返回 (bot_token, base_url)。"""
        elapsed = 0.0
        while elapsed < max_wait:
            try:
                data = await self.get_qrcode_status(qrcode)
            except httpx.ReadTimeout:
                logger.warning("wechat: QR status poll timed out, retrying…")
                elapsed += poll_interval
                continue
            status = data.get("status", "")
            if status == "confirmed":
                return data.get("bot_token", ""), data.get("baseurl", self.base_url)
            if status == "expired":
                raise ILinkError("WeChat QR code expired, please retry login")
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        raise TimeoutError(f"WeChat QR code not scanned within {max_wait}s")

    # -- 消息 --------------------------------------------------------------

    async def getupdates(self, cursor: str = "") -> Dict[str, Any]:
        """长轮询收消息（服务端最长挂 ~35s）。

        返回：ret(0=成功) / msgs[] / get_updates_buf(下轮 cursor) /
        longpolling_timeout_ms。
        """
        return await self._post(
            "ilink/bot/getupdates",
            {"get_updates_buf": cursor, "base_info": {"channel_version": _CHANNEL_VERSION}},
            timeout=_GETUPDATES_TIMEOUT,
        )

    async def sendmessage(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """发送消息（msg 必带 to_user_id/context_token/item_list 等）。"""
        return await self._post("ilink/bot/sendmessage",
                                {"msg": msg, "base_info": {"channel_version": _CHANNEL_VERSION}})

    async def send_text(self, to_user_id: str, text: str, context_token: str) -> Dict[str, Any]:
        return await self.sendmessage({
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": str(uuid.uuid4()),
            "message_type": 2,
            "message_state": 2,
            "context_token": context_token,
            "item_list": [{"type": 1, "text_item": {"text": text}}],
        })

    async def getconfig(self, ilink_user_id: str = "", context_token: str = "") -> Dict[str, Any]:
        """取 bot 配置（typing_ticket 等；亦作 token 有效性轻校验）。"""
        body: Dict[str, Any] = {}
        if ilink_user_id:
            body["ilink_user_id"] = ilink_user_id
        if context_token:
            body["context_token"] = context_token
        body["base_info"] = {"channel_version": _CHANNEL_VERSION}
        return await self._post("ilink/bot/getconfig", body)

    async def sendtyping(self, to_user_id: str, typing_ticket: str, status: int = 1) -> Dict[str, Any]:
        """输入中提示：1=开始，2=停止。"""
        return await self._post("ilink/bot/sendtyping", {
            "ilink_user_id": to_user_id,
            "typing_ticket": typing_ticket,
            "status": status,
            "base_info": {"channel_version": _CHANNEL_VERSION},
        })

    # -- 媒体 --------------------------------------------------------------

    async def download_media(self, url: str, aes_key_b64: str = "",
                             encrypt_query_param: str = "") -> bytes:
        """下载 CDN 媒体并（可选）AES 解密。

        item 里的 url 字段是十六进制媒体 ID（非 HTTP）；真实下载地址由
        encrypt_query_param 拼 CDN base。
        """
        self._require_client()
        if encrypt_query_param:
            enc = quote(encrypt_query_param, safe="")
            download_url = f"{_CDN_BASE}/download?encrypted_query_param={enc}"
        elif url.startswith("http"):
            download_url = url
        else:
            raise ValueError(
                f"Cannot download media: no valid HTTP URL. url={url[:40]!r}, "
                "encrypt_query_param empty."
            )
        resp = await self._client.get(download_url, timeout=60.0)
        resp.raise_for_status()
        data = resp.content
        if aes_key_b64:
            data = aes_ecb_decrypt(data, aes_key_b64)
        return data

    async def getuploadurl(self, filekey: str, media_type: int, to_user_id: str,
                           rawsize: int, rawfilemd5: str, filesize: int,
                           aeskey: str, no_need_thumb: bool = True) -> Dict[str, Any]:
        """换取上传地址。media_type: 1=图 2=视频 3=文件 4=语音。"""
        return await self._post("ilink/bot/getuploadurl", {
            "filekey": filekey,
            "media_type": media_type,
            "to_user_id": to_user_id,
            "rawsize": rawsize,
            "rawfilemd5": rawfilemd5,
            "filesize": filesize,
            "aeskey": aeskey,
            "no_need_thumb": no_need_thumb,
            "base_info": {"channel_version": _CHANNEL_VERSION},
        })

    async def upload_media(self, file_path: str, media_type: int, to_user_id: str) -> Dict[str, Any]:
        """AES-128-ECB 加密文件→CDN 上传，回传 sendmessage 所需的下载参数。

        返回 {encrypt_query_param, aes_key_b64(=base64(hex key)，
        picoclaw encodeWeixinOutboundAESKey 同构), filesize(加密后大小)}。
        """
        self._require_client()
        with open(file_path, "rb") as f:
            raw_data = f.read()
        rawsize = len(raw_data)
        rawfilemd5 = hashlib.md5(raw_data).hexdigest()

        aes_key_raw = secrets.token_bytes(16)
        aes_key_hex = aes_key_raw.hex()
        aes_key_for_msg = base64.b64encode(aes_key_hex.encode()).decode()
        aes_key_b64_for_encrypt = base64.b64encode(aes_key_raw).decode()
        filekey = secrets.token_hex(16)

        encrypted_data = aes_ecb_encrypt(raw_data, aes_key_b64_for_encrypt)
        filesize = len(encrypted_data)

        upload_resp = await self.getuploadurl(
            filekey=filekey, media_type=media_type, to_user_id=to_user_id,
            rawsize=rawsize, rawfilemd5=rawfilemd5, filesize=filesize,
            aeskey=aes_key_hex,
        )
        upload_url = upload_resp.get("upload_full_url", "")
        if not upload_url:
            upload_param = upload_resp.get("upload_param", "")
            if upload_param:
                enc_param = quote(upload_param, safe="")
                upload_url = f"{_CDN_BASE}/upload?encrypted_query_param={enc_param}&filekey={filekey}"
            else:
                raise ValueError(
                    "No upload_full_url or upload_param in getuploadurl response: "
                    f"{upload_resp}"
                )

        # upload_param 本身已含鉴权信息，CDN 上传不带 auth 头
        resp = await self._client.post(upload_url, content=encrypted_data,
                                        headers={"Content-Type": "application/octet-stream"},
                                        timeout=120.0)
        resp.raise_for_status()
        encrypt_query_param = resp.headers.get("x-encrypted-param", "")
        if not encrypt_query_param:
            logger.error(
                "upload_media: encrypt_query_param is empty! Sent files would "
                "appear blank on receiver side. headers=%s", dict(resp.headers))
            raise ValueError(
                "upload_media failed: CDN did not return encrypt_query_param "
                "in response headers. Files cannot be sent without this parameter.")
        return {"encrypt_query_param": encrypt_query_param,
                "aes_key_b64": aes_key_for_msg,
                "filesize": filesize}

    def _media_item(self, media_type: int, upload: Dict[str, Any]) -> Dict[str, Any]:
        return {"encrypt_query_param": upload["encrypt_query_param"],
                "aes_key": upload["aes_key_b64"], "encrypt_type": 1}

    async def send_file(self, to_user_id: str, file_path: str, filename: str,
                        context_token: str) -> Dict[str, Any]:
        upload = await self.upload_media(file_path, 3, to_user_id)
        return await self.sendmessage({
            "to_user_id": to_user_id, "client_id": str(uuid.uuid4()),
            "message_type": 2, "message_state": 2, "context_token": context_token,
            "item_list": [{"type": 4, "file_item": {
                "media": self._media_item(3, upload),
                "file_name": filename, "len": str(upload["filesize"])}}],
        })

    async def send_image(self, to_user_id: str, image_path: str,
                         context_token: str) -> Dict[str, Any]:
        upload = await self.upload_media(image_path, 1, to_user_id)
        return await self.sendmessage({
            "to_user_id": to_user_id, "client_id": str(uuid.uuid4()),
            "message_type": 2, "message_state": 2, "context_token": context_token,
            "item_list": [{"type": 2, "image_item": {
                "media": self._media_item(1, upload),
                "mid_size": upload["filesize"]}}],
        })

    async def send_video(self, to_user_id: str, video_path: str,
                         context_token: str) -> Dict[str, Any]:
        upload = await self.upload_media(video_path, 2, to_user_id)
        return await self.sendmessage({
            "to_user_id": to_user_id, "client_id": str(uuid.uuid4()),
            "message_type": 2, "message_state": 2, "context_token": context_token,
            "item_list": [{"type": 5, "video_item": {
                "media": self._media_item(2, upload)}}],
        })
