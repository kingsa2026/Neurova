from __future__ import annotations

"""
移动端推送令牌与凭据状态端点（设计方案 §8.4 S-3）。

- PUT  /api/v1/mobile/push/push-tokens          上报/更新设备推送令牌（登录态）
- DELETE /api/v1/mobile/push/push-tokens/{device_id}  注销设备令牌（登录态）
- GET  /api/v1/mobile/push/credentials/status   推送凭据配置状态（只回是否配置，不回显值）

App 语义：启动/登录后上报；登出时注销。平台取值 android|harmony。
推送只发信令（notificationId/type），正文由 App 拉取 /api/v1/notifications。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user
from neurova.core.logger import get_logger
from neurova.notifications import push_store
from neurova.notifications.push_sender import credentialsStatus

logger = get_logger(__name__)

router = APIRouter()

_VALID_PLATFORMS = ("android", "harmony")


class PushTokenUpsert(BaseModel):
    platform: str = Field(..., description="android | harmony")
    push_token: str = Field(..., min_length=8, max_length=4096)
    device_id: str = Field(..., min_length=1, max_length=128)


@router.put("/push-tokens")
async def upsertPushToken(
    body: PushTokenUpsert,
    current_user: dict = Depends(get_current_user),
):
    if body.platform not in _VALID_PLATFORMS:
        raise HTTPException(status_code=422, detail=f"platform 必须是 {'|'.join(_VALID_PLATFORMS)}")
    user_id = str(current_user.get("id") or current_user.get("user_id") or current_user.get("sub") or "")
    if user_id in ("", "default"):
        raise HTTPException(status_code=401, detail="推送令牌须绑定真实登录身份")
    if not user_id:
        raise HTTPException(status_code=401, detail="无法识别登录身份")
    push_store.upsert_token(
        user_id=user_id,
        platform=body.platform,
        push_token=body.push_token,
        device_id=body.device_id,
    )
    logger.info("push token 上报 user=%s platform=%s device=%s", user_id, body.platform, body.device_id)
    return {"code": 0, "message": "ok", "data": {"device_id": body.device_id, "platform": body.platform}}


@router.delete("/push-tokens/{device_id}")
async def deletePushToken(
    device_id: str,
    current_user: dict = Depends(get_current_user),
):
    # 审计 §3.1-9：只凭 device_id 任何登录用户都能注销他人设备推送——
    # 删除按"设备 + 属主"双键收口；非属主与不存在同形 404（防枚举）。
    user_id = str(current_user.get("id") or current_user.get("user_id") or current_user.get("sub") or "")
    removed = push_store.remove_token_for_user(device_id, user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="设备令牌不存在或不属于当前用户")
    return {"code": 0, "message": "ok", "data": {"device_id": device_id, "removed": removed}}


@router.get("/push-credentials/status")
async def pushCredentialsStatus(current_user: dict = Depends(get_current_user)):
    return {"code": 0, "message": "ok", "data": credentialsStatus()}
