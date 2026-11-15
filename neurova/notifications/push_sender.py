# -*- coding: utf-8 -*-
"""移动端离线推送扇出（设计方案 §8.4 S-3，已裁 D2=做）。

设计要点：
- **只发信令**：payload 仅含 notificationId / notificationType，正文由 App 拉取
  /api/v1/notifications——敏感内容不过第三方推送通道。
- 平台映射：platform=android → FCM（HTTP v1，服务账号 JWT 换 OAuth token）；
  platform=harmony → 华为 Push Kit（client_credentials 换 token）。
  国内无 GMS 设备的厂商通道是后续扩展批（当前如实降级为"仅前台可达"）。
- 凭据：env 优先（NEUROVA_PUSH_FCM_SERVICE_ACCOUNT=服务账号 JSON 串、
  NEUROVA_PUSH_HARMONY_APP_ID、NEUROVA_PUSH_HARMONY_CLIENT_SECRET），
  回退 data/push_credentials.json（值经 secret_store 加密）。未配置 = 如实跳过并记日志，
  不影响站内通知/SSE 面。
- 扇出失败不抛出（通知主链路不受影响）；每次调用内对每设备最多重试 1 次。
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from neurova.core.data_root import dataPath
from neurova.core.logger import get_logger
from neurova.notifications.push_store import PushTokenRecord, list_tokens_for_user

logger = get_logger(__name__)

_FCM_TOKEN_URL = "https://oauth2.googleapis.com/token"
_FCM_SEND_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_HARMONY_TOKEN_URL = "https://oauth-login.cloud.huawei.com/oauth2/v3/token"
_HARMONY_SEND_URL = "https://push-api.cloud.huawei.com/v1/{app_id}/messages:send"

_CREDENTIAL_FILE = dataPath("push_credentials.json")

_tokenCache: Dict[str, Any] = {}
#: 测试注入口：非 None 时替代 httpx 发送（返回 (status, body)）
_posterOverride = None


def _readCredentialFile() -> Dict[str, str]:
    """读加密凭据文件（值经 secret_store 加密；缺文件/解密失败按未配置处理）。"""
    path = Path(_CREDENTIAL_FILE)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        from neurova.security.secret_store import decrypt_secret

        out: Dict[str, str] = {}
        for key, value in raw.items():
            try:
                out[key] = decrypt_secret(str(value))
            except Exception:  # noqa: BLE001 - 单字段解密失败按缺失处理
                out[key] = ""
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("push 凭据文件读取失败（按未配置处理）: %s", e)
        return {}


def loadCredentials() -> Dict[str, str]:
    """推送凭据：env 优先，回退加密文件。返回可能为部分/全空的字典。"""
    creds = {
        "fcm_service_account": os.environ.get("NEUROVA_PUSH_FCM_SERVICE_ACCOUNT", ""),
        "harmony_app_id": os.environ.get("NEUROVA_PUSH_HARMONY_APP_ID", ""),
        "harmony_client_secret": os.environ.get("NEUROVA_PUSH_HARMONY_CLIENT_SECRET", ""),
    }
    if all(creds.values()):
        return creds
    fileCreds = _readCredentialFile()
    for key, value in fileCreds.items():
        if key in creds and not creds[key]:
            creds[key] = value
    return creds


def credentialsStatus() -> Dict[str, bool]:
    """管理面只读状态（不回显凭据值）。"""
    creds = loadCredentials()
    return {
        "fcm_configured": bool(creds.get("fcm_service_account")),
        "harmony_configured": bool(creds.get("harmony_app_id") and creds.get("harmony_client_secret")),
    }


def buildSignalingPayload(notificationId: str, notificationType: str) -> Dict[str, str]:
    """推送信令（只带 id/类型，不带正文）。"""
    return {"notificationId": notificationId, "notificationType": notificationType}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _fcmAccessToken(serviceAccount: Dict[str, Any]) -> Optional[str]:
    """服务账号 JWT → OAuth2 access token（RS256，cryptography 签名；缓存 55 分钟）。"""
    cached = _tokenCache.get("fcm")
    if cached and cached["expires_at"] > time.time() + 30:
        return cached["token"]
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        now = int(time.time())
        header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode("utf-8"))
        claims = _b64url(json.dumps({
            "iss": serviceAccount["client_email"],
            "scope": _FCM_SCOPE,
            "aud": _FCM_TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        }).encode("utf-8"))
        signingInput = f"{header}.{claims}".encode("ascii")
        key = serialization.load_pem_private_key(
            serviceAccount["private_key"].encode("utf-8"), password=None)
        signature = key.sign(signingInput, padding.PKCS1v15(), hashes.SHA256())
        assertion = f"{header}.{claims}.{_b64url(signature)}"

        poster = _posterOverride or httpx.post
        resp = poster(
            _FCM_TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
            timeout=15.0,
        )
        if resp.status_code != 200:
            logger.warning("FCM OAuth 失败: %s %s", resp.status_code, resp.text[:200])
            return None
        token = resp.json().get("access_token")
        if token:
            _tokenCache["fcm"] = {"token": token, "expires_at": time.time() + 3300}
        return token
    except Exception as e:  # noqa: BLE001
        logger.warning("FCM access token 获取失败: %s", e)
        return None


def _harmonyAccessToken(appId: str, clientSecret: str) -> Optional[str]:
    """华为 Push Kit client_credentials 换 token（缓存 55 分钟）。"""
    cached = _tokenCache.get("harmony")
    if cached and cached["expires_at"] > time.time() + 30:
        return cached["token"]
    try:
        poster = _posterOverride or httpx.post
        resp = poster(
            _HARMONY_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": appId,
                "client_secret": clientSecret,
            },
            timeout=15.0,
        )
        if resp.status_code != 200:
            logger.warning("Push Kit OAuth 失败: %s %s", resp.status_code, resp.text[:200])
            return None
        token = resp.json().get("access_token")
        if token:
            _tokenCache["harmony"] = {"token": token, "expires_at": time.time() + 3300}
        return token
    except Exception as e:  # noqa: BLE001
        logger.warning("Push Kit access token 获取失败: %s", e)
        return None


def _postJson(url: str, headers: Dict[str, str], body: Dict[str, Any]) -> tuple:
    poster = _posterOverride or httpx.post
    resp = poster(url, headers=headers, json=body, timeout=15.0)
    return resp.status_code, resp.text[:300]


def _sendFcm(pushToken: str, signaling: Dict[str, str], creds: Dict[str, str]) -> bool:
    try:
        serviceAccount = json.loads(creds["fcm_service_account"])
    except Exception as e:  # noqa: BLE001
        logger.warning("FCM 服务账号 JSON 解析失败: %s", e)
        return False
    accessToken = _fcmAccessToken(serviceAccount)
    if not accessToken:
        return False
    projectId = serviceAccount.get("project_id", "")
    url = _FCM_SEND_URL.format(project_id=projectId)
    body = {"message": {"token": pushToken, "data": signaling, "android": {"priority": "HIGH"}}}
    last = ""
    for attempt in range(2):  # 失败重试 1 次
        status, text = _postJson(url, {"Authorization": f"Bearer {accessToken}"}, body)
        if status == 200:
            return True
        last = f"{status} {text}"
        time.sleep(0.5)
    logger.warning("FCM 推送失败（device token 尾 6 位 …%s）: %s", pushToken[-6:], last)
    return False


def _sendHarmony(pushToken: str, signaling: Dict[str, str], creds: Dict[str, str]) -> bool:
    appId = creds.get("harmony_app_id", "")
    accessToken = _harmonyAccessToken(appId, creds.get("harmony_client_secret", ""))
    if not accessToken:
        return False
    url = _HARMONY_SEND_URL.format(app_id=appId)
    body = {
        "validate_only": False,
        "message": {"data": json.dumps(signaling), "token": [pushToken]},
    }
    last = ""
    for attempt in range(2):
        status, text = _postJson(url, {"Authorization": f"Bearer {accessToken}"}, body)
        if status == 200:
            return True
        last = f"{status} {text}"
        time.sleep(0.5)
    logger.warning("Push Kit 推送失败（device token 尾 6 位 …%s）: %s", pushToken[-6:], last)
    return False


def pushNotificationToUser(user_id: str, notification: Any) -> Dict[str, int]:
    """把一条站内通知扇出到该用户全部已登记设备（信令-only）。

    返回 {sent, skipped, failed} 计数；任何异常都不上抛（通知主链路不受影响）。
    """
    signaling = buildSignalingPayload(
        str(getattr(notification, "notification_id", "")),
        str(getattr(notification, "notification_type", "info")),
    )
    try:
        records: List[PushTokenRecord] = list_tokens_for_user(str(user_id))
    except Exception as e:  # noqa: BLE001
        logger.warning("推送令牌查询失败（user=%s）: %s", user_id, e)
        return {"sent": 0, "skipped": 0, "failed": 0}
    if not records:
        return {"sent": 0, "skipped": 0, "failed": 0}

    creds = loadCredentials()
    sent = failed = 0
    for record in records:
        if record.platform == "android":
            ok = _sendFcm(record.push_token, signaling, creds) if creds.get("fcm_service_account") else False
        elif record.platform == "harmony":
            ok = _sendHarmony(record.push_token, signaling, creds) if (
                creds.get("harmony_app_id") and creds.get("harmony_client_secret")) else False
        else:
            ok = False
        if ok:
            sent += 1
        else:
            failed += 1
    if failed:
        logger.info("推送扇出 user=%s sent=%d failed=%d（未配置凭据或无 GMS 设备计入 failed，前台 SSE 不受影响）",
                    user_id, sent, failed)
    return {"sent": sent, "skipped": 0, "failed": failed}


def dispatchPushAsync(user_id: str, notification: Any) -> None:
    """异步扇出（后台线程，不阻塞通知落库主链路）。由 notify_user 门面调用。"""
    import threading

    thread = threading.Thread(
        target=_safeFanout, args=(user_id, notification), daemon=True, name="push-fanout")
    thread.start()


def _safeFanout(user_id: str, notification: Any) -> None:
    try:
        pushNotificationToUser(user_id, notification)
    except Exception as e:  # noqa: BLE001
        logger.warning("推送扇出异常（user=%s）: %s", user_id, e)
