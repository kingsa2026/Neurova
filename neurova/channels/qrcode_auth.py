# -*- coding: utf-8 -*-
"""渠道二维码授权处理器（对齐 QwenPaw qrcode_auth_handler，2026-09-13 照搬移植）。

每个支持"扫码授权/扫码建号"的渠道实现一个具体 ``QRCodeAuthHandler`` 并注册进
``QRCODE_AUTH_HANDLERS``；channel_config.py 暴露两个通用端点按 ``{channel}`` 委派：

1. ``GET /channel-configs/{channel}/qrcode``
   → ``handler.fetch_qrcode(request)``
   → ``{"qrcode_img": "<base64 PNG>", "poll_token": "..."}``

2. ``GET /channel-configs/{channel}/qrcode/status?token=...``
   → ``handler.poll_status(token, request)``
   → ``{"status": "...", "credentials": {...}}``

成功后 credentials 由前端自动回填表单（feishu/dingtalk 回填 app_id|client_id+secret、
qq 回填 app_id+client_secret+user_openid、wecom 回填 bot_id+secret、
wechat 回填 bot_token+base_url），用户点保存即完成配置——替代"手抄开放平台参数"。

真实官方协议端点（全部来自 QwenPaw v2.2.1 实现，非虚构）：
- feishu   : OAuth 2.0 Device Grant (RFC 8628) @ accounts.feishu.cn/accounts.larksuite.com
- dingtalk : /app/registration init→begin→poll @ oapi.dingtalk.com
- qq       : /lite/create_bind_task + poll_bind_result @ q.qq.com（AES-256-GCM 解 bot secret）
- wecom    : /ai/qc/gen 抓 window.settings + /ai/qc/query_result @ work.weixin.qq.com
- wechat   : ilinkai.weixin.qq.com get_bot_qrcode/get_qrcode_status +
             liteapp.weixin.qq.com 扫码跳转 URL（根修 NV 旧虚构端点 ilink.wechat.bot）
"""

from __future__ import annotations

import base64
import io
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Tuple

import segno
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

PROJECT_NAME = "NEUROVA"


@dataclass
class QRCodeResult:
    """``fetch_qrcode`` 返回值：扫码 URL + 后续轮询用 token。"""

    scan_url: str
    poll_token: str


@dataclass
class PollResult:
    """``poll_status`` 返回值：waiting/success/confirmed/expired/fail + 凭据。"""

    status: str
    credentials: Dict[str, Any]


class QRCodeAuthHandler(ABC):
    """渠道二维码授权抽象基类。"""

    @abstractmethod
    async def fetch_qrcode(self, request: Request) -> QRCodeResult:
        """获取扫码 URL 与轮询 token。"""

    @abstractmethod
    async def poll_status(self, token: str, request: Request) -> PollResult:
        """查询用户是否已扫码并确认授权。"""


def generate_qrcode_image(scan_url: str) -> str:
    """把 scan_url 渲染为 base64 PNG 二维码图片。"""
    try:
        qr_code = segno.make(scan_url, error="M")
        buf = io.BytesIO()
        qr_code.save(buf, kind="png", scale=6, border=2)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"QR code image generation failed: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# WeChat (iLink) handler — 真实端点 ilinkai.weixin.qq.com
# ---------------------------------------------------------------------------

# 与 QwenPaw channels/wechat/client.py _DEFAULT_BASE_URL 同源
ILINK_DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"


class WeChatQRCodeAuthHandler(QRCodeAuthHandler):
    """微信 iLink Bot 扫码登录（GET 二维码 → 轮询 confirmed 取 bot_token+baseurl）。"""

    async def _get_base_url(self, request: Request) -> str:
        base_url = request.query_params.get("base_url", "")
        if base_url:
            return base_url.rstrip("/")
        # 回落到已保存配置的 extra.base_url（default agent 视图）
        try:
            from neurova.api.endpoints.channel_config import _load_configs

            cfg = _load_configs().get("wechat", {}) or {}
            saved = ((cfg.get("extra") or {}) or {}).get("base_url", "")
            if saved:
                return str(saved).rstrip("/")
        except Exception:
            pass
        return ILINK_DEFAULT_BASE_URL

    async def fetch_qrcode(self, request: Request) -> QRCodeResult:
        import httpx

        base_url = await self._get_base_url(request)
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(
                    f"{base_url}/ilink/bot/get_bot_qrcode", params={"bot_type": 3}
                )
                resp.raise_for_status()
                qr_data = resp.json()
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"WeChat QR code fetch failed: {exc}",
            ) from exc

        qrcode = qr_data.get("qrcode", "")
        qrcode_img_content = qr_data.get("qrcode_img_content", "")

        if not qrcode and not qrcode_img_content:
            raise HTTPException(
                status_code=502,
                detail="WeChat returned empty QR code data",
            )

        if qrcode_img_content.startswith("http"):
            scan_url = qrcode_img_content
        else:
            scan_url = (
                f"https://liteapp.weixin.qq.com/q/7GiQu1"
                f"?qrcode={qrcode}&bot_type=3"
            )

        return QRCodeResult(scan_url=scan_url, poll_token=qrcode)

    async def poll_status(self, token: str, request: Request) -> PollResult:
        import httpx

        base_url = await self._get_base_url(request)
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(
                    f"{base_url}/ilink/bot/get_qrcode_status",
                    params={"qrcode": token},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"WeChat status check failed: {exc}",
            ) from exc

        return PollResult(
            status=data.get("status", "waiting"),
            credentials={
                "bot_token": data.get("bot_token", ""),
                "base_url": data.get("baseurl", ""),
            },
        )


# ---------------------------------------------------------------------------
# WeCom (Enterprise WeChat) handler
# ---------------------------------------------------------------------------

_WECOM_AUTH_ORIGIN = "https://work.weixin.qq.com"
_WECOM_SOURCE = PROJECT_NAME.lower()


class WecomQRCodeAuthHandler(QRCodeAuthHandler):
    """企业微信智能机器人扫码授权（auth 页 window.settings 取 scode）。"""

    async def fetch_qrcode(self, request: Request) -> QRCodeResult:
        import json
        import re
        import secrets
        import time
        import httpx

        state = secrets.token_urlsafe(16)
        gen_url = (
            f"{_WECOM_AUTH_ORIGIN}/ai/qc/gen"
            f"?source={_WECOM_SOURCE}&state={state}"
            f"&timestamp={int(time.time() * 1000)}"
        )

        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(gen_url)
                resp.raise_for_status()
                html = resp.text
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"WeCom auth page fetch failed: {exc}",
            ) from exc

        settings_match = re.search(
            r"window\.settings\s*=\s*(\{[^<]+\})",
            html,
        )
        if not settings_match:
            raise HTTPException(
                status_code=502,
                detail="Failed to parse WeCom auth page settings",
            )

        try:
            settings = json.loads(settings_match.group(1))
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to parse WeCom settings JSON: {exc}",
            ) from exc

        scode = settings.get("scode", "")
        auth_url = settings.get("auth_url", "")

        if not scode or not auth_url:
            raise HTTPException(
                status_code=502,
                detail="WeCom returned empty scode or auth_url",
            )

        return QRCodeResult(scan_url=auth_url, poll_token=scode)

    async def poll_status(self, token: str, request: Request) -> PollResult:
        from urllib.parse import quote
        import httpx

        query_url = f"{_WECOM_AUTH_ORIGIN}/ai/qc/query_result?scode={quote(token)}"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(query_url)
                resp.raise_for_status()
                result = resp.json()
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"WeCom status check failed: {exc}",
            ) from exc

        data = result.get("data", {})
        bot_info = data.get("bot_info", {})

        return PollResult(
            status=data.get("status", "waiting"),
            credentials={
                "bot_id": bot_info.get("botid", ""),
                "secret": bot_info.get("secret", ""),
            },
        )


# ---------------------------------------------------------------------------
# DingTalk (Device Flow) handler
# ---------------------------------------------------------------------------

_DINGTALK_API_BASE = "https://oapi.dingtalk.com"
_DINGTALK_SOURCE = PROJECT_NAME
# 尚未签发凭据的中间态（钉钉会持续新增中间步骤，未知状态一律继续轮询并记日志）
_DINGTALK_PENDING_STATUSES = (
    "WAITING",
    "CREATING",
    "PUBLISHING",
    "APPROVING",
)
_DINGTALK_FAILED_STATUSES = ("FAIL", "EXPIRED")


def _clean_str(value: Any) -> str:
    """只对真正的字符串返回值；JSON null/其他类型视为缺省。

    防止 ``client_id: null`` 变成字面量 "None" 误判成功（QwenPaw 同款根修）。
    """
    return value.strip() if isinstance(value, str) else ""


class DingtalkQRCodeAuthHandler(QRCodeAuthHandler):
    """钉钉机器人注册设备流：init→nonce，begin→device_code+二维码，poll→凭据。

    poll 观测序列：WAITING→CREATING→PUBLISHING→SUCCESS（开审批则停在 APPROVING，
    但凭据在 APPROVING 时已签发）——成功与否以 client_id+client_secret 齐备为准。
    """

    async def fetch_qrcode(self, request: Request) -> QRCodeResult:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                init_resp = await client.post(
                    f"{_DINGTALK_API_BASE}/app/registration/init",
                    json={"source": _DINGTALK_SOURCE},
                )
                init_resp.raise_for_status()
                init_data = init_resp.json()

                if init_data.get("errcode", -1) != 0:
                    raise HTTPException(
                        status_code=502,
                        detail=f"DingTalk init failed: {init_data.get('errmsg', 'unknown error')}",
                    )

                nonce = init_data.get("nonce", "")
                if not nonce:
                    raise HTTPException(status_code=502, detail="DingTalk returned empty nonce")

                begin_resp = await client.post(
                    f"{_DINGTALK_API_BASE}/app/registration/begin",
                    json={"nonce": nonce},
                )
                begin_resp.raise_for_status()
                begin_data = begin_resp.json()

                if begin_data.get("errcode", -1) != 0:
                    raise HTTPException(
                        status_code=502,
                        detail=f"DingTalk begin failed: {begin_data.get('errmsg', 'unknown error')}",
                    )

                device_code = begin_data.get("device_code", "")
                scan_url = begin_data.get("verification_uri_complete", "")

                if not device_code or not scan_url:
                    raise HTTPException(
                        status_code=502,
                        detail="DingTalk returned empty device_code or URI",
                    )

                return QRCodeResult(scan_url=scan_url, poll_token=device_code)

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"DingTalk QR code fetch failed: {exc}",
            ) from exc

    async def poll_status(self, token: str, request: Request) -> PollResult:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{_DINGTALK_API_BASE}/app/registration/poll",
                    json={"device_code": token},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"DingTalk status check failed: {exc}",
            ) from exc

        status = _clean_str(data.get("status")).upper()
        client_id = _clean_str(data.get("client_id"))
        client_secret = _clean_str(data.get("client_secret"))

        if client_id and client_secret:
            return PollResult(
                status="success",
                credentials={"client_id": client_id, "client_secret": client_secret},
            )

        if status in _DINGTALK_FAILED_STATUSES:
            return PollResult(
                status="expired" if status == "EXPIRED" else "fail",
                credentials={"fail_reason": _clean_str(data.get("fail_reason"))},
            )

        if status not in _DINGTALK_PENDING_STATUSES:
            logger.warning("dingtalk poll: unknown status=%r errcode=%s", status, data.get("errcode"))
        return PollResult(status="waiting", credentials={})


# ---------------------------------------------------------------------------
# Feishu/Lark (Device Authorization Grant - RFC 8628) handler
# ---------------------------------------------------------------------------

_FEISHU_ACCOUNTS_DOMAIN = "https://accounts.feishu.cn"
_LARK_ACCOUNTS_DOMAIN = "https://accounts.larksuite.com"
_FEISHU_REGISTER_ENDPOINT = "/oauth/v1/app/registration"


class FeishuQRCodeAuthHandler(QRCodeAuthHandler):
    """飞书/Lark 扫码一键建应用（RFC 8628 设备授权码模式）。

    无状态：init（探测认证方式）→ begin（device_code+扫码 URL）→ poll（凭据）。
    domain 优先取查询参数（配置未落盘时前端即传），回落已存配置，再回落 feishu。
    """

    async def _get_domain(self, request: Request) -> str:
        qp_domain = request.query_params.get("domain", "")
        if qp_domain in ("feishu", "lark"):
            return qp_domain
        try:
            from neurova.api.endpoints.channel_config import _load_configs

            cfg = _load_configs().get("feishu", {}) or {}
            domain = str(((cfg.get("extra") or {}) or {}).get("domain", "feishu"))
            return domain if domain in ("feishu", "lark") else "feishu"
        except Exception:
            return "feishu"

    def _get_accounts_domain(self, domain: str) -> str:
        return _LARK_ACCOUNTS_DOMAIN if domain == "lark" else _FEISHU_ACCOUNTS_DOMAIN

    async def fetch_qrcode(self, request: Request) -> QRCodeResult:
        import httpx
        from urllib.parse import urlencode

        domain = await self._get_domain(request)
        base_url = self._get_accounts_domain(domain)
        endpoint = base_url + _FEISHU_REGISTER_ENDPOINT
        form_headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                init_resp = await client.post(
                    endpoint, content=urlencode({"action": "init"}), headers=form_headers
                )
                init_resp.raise_for_status()
                init_data = init_resp.json()

                methods = init_data.get("supported_auth_methods", [])
                if "client_secret" not in methods:
                    raise HTTPException(status_code=502, detail="Feishu: unsupported auth methods")

                begin_resp = await client.post(
                    endpoint,
                    content=urlencode(
                        {
                            "action": "begin",
                            "archetype": "PersonalAgent",
                            "auth_method": "client_secret",
                            "request_user_info": "open_id",
                        }
                    ),
                    headers=form_headers,
                )
                begin_resp.raise_for_status()
                begin_data = begin_resp.json()

                device_code = begin_data.get("device_code", "")
                verification_uri = begin_data.get("verification_uri_complete", "")

                if not device_code or not verification_uri:
                    raise HTTPException(
                        status_code=502, detail="Feishu: missing device_code or QR URL"
                    )

                sep = "&" if "?" in verification_uri else "?"
                scan_url = f"{verification_uri}{sep}source={PROJECT_NAME}"

                return QRCodeResult(scan_url=scan_url, poll_token=device_code)

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Feishu QR code fetch failed: {exc}",
            ) from exc

    async def poll_status(self, token: str, request: Request) -> PollResult:
        import httpx
        from urllib.parse import urlencode

        domain = await self._get_domain(request)
        base_url = self._get_accounts_domain(domain)
        endpoint = base_url + _FEISHU_REGISTER_ENDPOINT

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    endpoint,
                    content=urlencode({"action": "poll", "device_code": token}),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                data = resp.json()
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Feishu status check failed: {exc}",
            ) from exc

        if data.get("client_id") and data.get("client_secret"):
            user_info = data.get("user_info", {})
            return PollResult(
                status="success",
                credentials={
                    "app_id": data["client_id"],
                    "app_secret": data["client_secret"],
                    "open_id": user_info.get("open_id", ""),
                    "tenant_brand": user_info.get("tenant_brand", "feishu"),
                },
            )

        error = data.get("error", "")
        if error in ("expired_token", "invalid_grant"):
            return PollResult(status="expired", credentials={"fail_reason": "QR code expired"})
        elif error == "access_denied":
            return PollResult(status="fail", credentials={"fail_reason": "User denied authorization"})
        elif error and error not in ("authorization_pending", "slow_down"):
            return PollResult(status="fail", credentials={"fail_reason": error})

        return PollResult(status="waiting", credentials={})


# ---------------------------------------------------------------------------
# 加密辅助（QQ 绑定任务）
# ---------------------------------------------------------------------------

_AES_KEY_LENGTH = 32  # 256 bits


def _generate_bind_key() -> str:
    """base64 编码的 256-bit AES key。"""
    return base64.b64encode(os.urandom(_AES_KEY_LENGTH)).decode()


def _decrypt_secret(
    encrypted_base64: str,
    key_base64: str,
    associated_data: bytes | None = None,
) -> str:
    """解密 AES-256-GCM 密文（base64，iv=前 12 字节）。"""
    key = base64.b64decode(key_base64)
    raw = base64.b64decode(encrypted_base64)

    if len(raw) < 28:  # 12-byte IV + 至少 16 字节 (ciphertext+tag)
        raise ValueError(f"Ciphertext too short: {len(raw)} bytes (min 28)")

    iv = raw[:12]
    ciphertext_with_tag = raw[12:]
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, ciphertext_with_tag, associated_data)
    return plaintext.decode("utf-8")


def encode_poll_token(task_id: str, aes_key: str) -> str:
    """把 task_id+AES key 合成无状态轮询 token。"""
    import json

    payload = json.dumps({"task_id": task_id, "key": aes_key}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode()


# QwenPaw 原名下划线别名（同物）
_encode_poll_token = encode_poll_token


def decode_poll_token(token: str) -> Tuple[str, str]:
    """轮询 token 解回 (task_id, aes_key)。"""
    import json

    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        data = json.loads(decoded)
        return data["task_id"], data["key"]
    except Exception as exc:
        raise ValueError(f"Invalid poll token: {exc}") from exc


# ---------------------------------------------------------------------------
# QQ handler：Portal 绑定任务
# ---------------------------------------------------------------------------


class QQQRCodeAuthHandler(QRCodeAuthHandler):
    """QQ 机器人扫码授权：create_bind_task 下发 AES key，poll 拿加密 bot secret。"""

    _PORTAL_HOST: str = os.getenv("QQ_PORTAL_HOST", "q.qq.com")
    _CREATE_PATH: str = "/lite/create_bind_task"
    _POLL_PATH: str = "/lite/poll_bind_result"
    _FRONTEND_PATH: str = "/qqbot/openclaw/connect.html"

    async def fetch_qrcode(self, request: Request) -> QRCodeResult:
        import httpx
        from urllib.parse import urlencode

        aes_key = _generate_bind_key()
        url = f"https://{self._PORTAL_HOST}{self._CREATE_PATH}"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json={"key": aes_key}, headers={"Content-Type": "application/json"})
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"QQ create_bind_task failed: {exc}") from exc

        if data.get("retcode") != 0:
            raise HTTPException(
                status_code=502,
                detail=f"QQ create_bind_task error: {data.get('msg', '')}",
            )

        task_id = data.get("data", {}).get("task_id")
        if not task_id:
            raise HTTPException(status_code=502, detail="QQ create_bind_task returned empty task_id")

        params = urlencode({"task_id": task_id, "_wv": "2", "source": PROJECT_NAME})
        scan_url = f"https://{self._PORTAL_HOST}{self._FRONTEND_PATH}?{params}"
        poll_token = encode_poll_token(task_id, aes_key)
        return QRCodeResult(scan_url=scan_url, poll_token=poll_token)

    async def poll_status(self, token: str, request: Request) -> PollResult:
        import httpx

        try:
            task_id, aes_key = decode_poll_token(token)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid poll token") from exc

        url = f"https://{self._PORTAL_HOST}{self._POLL_PATH}"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={"task_id": task_id}, headers={"Content-Type": "application/json"})
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"QQ poll_bind_result failed: {exc}") from exc

        retcode = data.get("retcode")
        if retcode != 0:
            return PollResult(status="fail", credentials={"fail_reason": data.get("msg", "unknown")})

        result_data = data.get("data", {})
        status = result_data.get("status", -1)

        if status == 2:
            raw_appid = result_data.get("bot_appid")
            encrypted_secret = result_data.get("bot_encrypt_secret", "")
            if not raw_appid or not encrypted_secret:
                return PollResult(
                    status="fail", credentials={"fail_reason": "Missing app_id or secret"}
                )
            try:
                client_secret = _decrypt_secret(encrypted_secret, aes_key)
            except Exception:
                return PollResult(
                    status="fail", credentials={"fail_reason": "Secret decryption failed"}
                )
            return PollResult(
                status="success",
                credentials={
                    "app_id": str(raw_appid),
                    "client_secret": client_secret,
                    "user_openid": str(result_data.get("user_openid", "")),
                },
            )
        elif status == 3:
            return PollResult(status="expired", credentials={})
        else:
            return PollResult(status="waiting", credentials={})


# ---------------------------------------------------------------------------
# 注册表 — 新渠道在此追加
# ---------------------------------------------------------------------------

QRCODE_AUTH_HANDLERS: Dict[str, QRCodeAuthHandler] = {
    "wechat": WeChatQRCodeAuthHandler(),
    "wecom": WecomQRCodeAuthHandler(),
    "dingtalk": DingtalkQRCodeAuthHandler(),
    "feishu": FeishuQRCodeAuthHandler(),
    "qq": QQQRCodeAuthHandler(),
}
