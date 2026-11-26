from __future__ import annotations

"""
TOTP 两步验证端点（S8）

链路：
- POST /api/v1/auth/2fa/setup    （需登录）生成 base32 secret + otpauth URL，
  暂存 users.totp_secret，不启用
- POST /api/v1/auth/2fa/enable   （需登录）验 TOTP 码通过才置 two_factor_enabled=1，
  生成 10 条一次性恢复码——**明文仅本次响应返回**，库中只存 sha256 哈希
- POST /api/v1/auth/2fa/disable  （需登录）验码（TOTP 或恢复码）后关闭并清列
- POST /api/v1/auth/2fa/verify   （公开，白名单）{challenge_token, code}：
  校验登录链下发的短时挑战令牌 + TOTP 码（或单次恢复码）→ 发正式 token 对。
  挑战令牌一次性（成功即入全局黑名单），防重放；失败按 jti 限次防爆破。

TOTP 算法单源：neurova/security/totp.py（stdlib RFC 6238，HMAC-SHA1，窗口 ±1）。
"""

import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from neurova.api.auth import (
    blacklist_token,
    blacklistStateOr503,
    create_access_token,
    create_refresh_token,
    get_current_user,
    verify_2fa_challenge_token,
)
from neurova.core.logger import get_logger
from neurova.security.totp import generateTotpSecret, otpauthUrl, verifyTotp

logger = get_logger(__name__)

router = APIRouter()

RECOVERY_CODE_COUNT = 10

# verify 失败限次（按挑战令牌 jti）：挑战令牌 5 分钟 TTL，窗口内最多 5 次错码
_VERIFY_MAX_ATTEMPTS = 5
_verifyAttempts: Dict[str, List[float]] = {}
_verifyAttemptsLock = threading.RLock()
_VERIFY_WINDOW_SECONDS = 300


class TwoFactorCodeRequest(BaseModel):
    """setup 之外的 2FA 操作请求体（enable/disable 共用）"""

    code: str = Field(..., description="TOTP 码或恢复码")


class TwoFactorVerifyRequest(BaseModel):
    """登录挑战验证请求体"""

    challenge_token: str = Field(..., description="登录返回的短时挑战令牌")
    code: str = Field(..., description="TOTP 码或恢复码")


def _get_model():
    from neurova.api.endpoints.auth import _get_user_model

    return _get_user_model()


def _userFromIdentity(identity: Dict[str, Any]):
    """JWT 身份 → 账本 User；身份与账本对不上时显式 401（不静默）。"""
    model = _get_model()
    try:
        user = model.get_user_by_id(int(identity.get("user_id")))
    except (TypeError, ValueError):
        user = None
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在或已删除")
    return user


def _hashRecoveryCode(code: str) -> str:
    """恢复码哈希：归一（去分隔符、小写）后 sha256——明文不落库。"""
    normalized = code.strip().replace("-", "").replace(" ", "").lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _loadRecoveryHashes(user) -> List[str]:
    if not user.recovery_codes_hash:
        return []
    try:
        parsed = json.loads(user.recovery_codes_hash)
        return [str(h) for h in parsed] if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        logger.warning("恢复码哈希列解析失败，按空处理")
        return []


def _persistRecoveryHashes(model, userId: int, hashes: List[str]) -> None:
    model.update_user(userId, recovery_codes_hash=json.dumps(hashes) if hashes else None)


def _consumeRecoveryCode(model, user, code: str) -> bool:
    """恢复码单次消费：命中即从哈希表移除并落库。"""
    target = _hashRecoveryCode(code)
    hashes = _loadRecoveryHashes(user)
    for idx, entry in enumerate(hashes):
        if hmac.compare_digest(entry, target):
            hashes.pop(idx)
            _persistRecoveryHashes(model, user.id, hashes)
            return True
    return False


def _generateRecoveryCodes() -> List[str]:
    return [secrets.token_hex(4).upper() for _ in range(RECOVERY_CODE_COUNT)]


def _recordVerifyFailure(jti: str) -> int:
    now = time.time()
    with _verifyAttemptsLock:
        recent = [t for t in _verifyAttempts.get(jti, []) if now - t < _VERIFY_WINDOW_SECONDS]
        recent.append(now)
        _verifyAttempts[jti] = recent
        return len(recent)


def _clearVerifyAttempts(jti: str) -> None:
    with _verifyAttemptsLock:
        _verifyAttempts.pop(jti, None)


def _issueTokenPair(user) -> Dict[str, Any]:
    """正式 token 对（身份声明走 buildIdentityClaims 单源）。"""
    from neurova.api.endpoints.auth import buildIdentityClaims

    identityClaims = buildIdentityClaims({
        "id": user.id, "username": user.username, "auth_version": user.auth_version,
    })
    return {
        "access_token": create_access_token(data={**identityClaims, "role": user.role}),
        "refresh_token": create_refresh_token(data=identityClaims),
        "token_type": "bearer",
        "expires_in": 3600,
    }


@router.post("/setup")
async def setupTwoFactor(request: Request, identity: Dict[str, Any] = Depends(get_current_user)):
    """生成 TOTP secret 与 otpauth URL（暂存未启用；重复调用换新 secret）。"""
    _ = request
    user = _userFromIdentity(identity)
    if user.two_factor_enabled:
        raise HTTPException(status_code=400, detail="两步验证已启用；如需重置请先关闭")

    model = _get_model()
    secret = generateTotpSecret()
    model.update_user(user.id, totp_secret=secret)
    return {
        "secret": secret,
        "otpauth_url": otpauthUrl(secret, accountName=user.username),
    }


@router.post("/enable")
async def enableTwoFactor(request: Request, body: TwoFactorCodeRequest,
                          identity: Dict[str, Any] = Depends(get_current_user)):
    """验 TOTP 码通过才启用；返回一次性恢复码明文（库中只存哈希）。"""
    _ = request
    user = _userFromIdentity(identity)
    model = _get_model()
    if user.two_factor_enabled:
        raise HTTPException(status_code=400, detail="两步验证已启用")
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="请先调用 setup 生成二维码")

    if not verifyTotp(user.totp_secret, body.code):
        raise HTTPException(status_code=400, detail="验证码不正确，请确认认证器时间与当前码")

    recoveryCodes = _generateRecoveryCodes()
    model.update_user(
        user.id,
        two_factor_enabled=1,
        recovery_codes_hash=json.dumps([_hashRecoveryCode(c) for c in recoveryCodes]),
    )
    logger.info("2FA enabled for user %s (recovery codes hashed)", user.id)
    return {"recovery_codes": recoveryCodes}


@router.post("/disable")
async def disableTwoFactor(request: Request, body: TwoFactorCodeRequest,
                           identity: Dict[str, Any] = Depends(get_current_user)):
    """验码（TOTP 或恢复码）后关闭两步验证并清空相关列。"""
    _ = request
    user = _userFromIdentity(identity)
    model = _get_model()
    if not user.two_factor_enabled and not user.totp_secret:
        raise HTTPException(status_code=400, detail="两步验证未启用")

    codeOk = verifyTotp(user.totp_secret or "", body.code) or _consumeRecoveryCode(model, user, body.code)
    if not codeOk:
        raise HTTPException(status_code=400, detail="验证码不正确")

    model.update_user(
        user.id,
        totp_secret=None,
        two_factor_enabled=0,
        recovery_codes_hash=None,
    )
    logger.info("2FA disabled for user %s", user.id)
    return {"ok": True}


@router.post("/verify")
async def verifyTwoFactor(request: Request, body: TwoFactorVerifyRequest):
    """挑战验证（公开端点，白名单）：challenge_token + TOTP/恢复码 → 正式 token 对。

    - challenge_token 必须 type=2fa_challenge 且未过期（普通 token 一律 401）
    - challenge 一次性：验证成功即入全局黑名单，重放拒绝
    - 错码按挑战 jti 限次（窗口内 5 次），防 10^6 码空间爆破
    """
    challenge = (body.challenge_token or "").strip()
    if not challenge:
        raise HTTPException(status_code=401, detail="缺少挑战令牌")

    # 成功消费过的 challenge 再来 → 黑名单命中即拒（重放）。
    # API-03：判据面故障 fail-closed（blacklistStateOr503 显式 503），不吞异常放行。
    if blacklistStateOr503(challenge):
        raise HTTPException(status_code=401, detail="挑战令牌已使用")

    payload = verify_2fa_challenge_token(challenge)
    if not payload:
        raise HTTPException(status_code=401, detail="挑战令牌无效或已过期")

    jti = str(payload.get("jti") or "")
    if _recordVerifyFailure(jti) > _VERIFY_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="尝试次数过多，请重新登录")

    model = _get_model()
    try:
        user = model.get_user_by_id(int(payload.get("sub")))
    except (TypeError, ValueError):
        user = None
    if user is None or not user.two_factor_enabled or not user.totp_secret:
        raise HTTPException(status_code=401, detail="两步验证未启用或用户不存在")
    if user.auth_version != payload.get("auth_version"):
        raise HTTPException(status_code=401, detail="挑战令牌已撤销")

    code = (body.code or "").strip()
    codeOk = verifyTotp(user.totp_secret, code) or _consumeRecoveryCode(model, user, code)
    if not codeOk:
        logger.warning("2FA verify failed for user %s", user.id)
        raise HTTPException(status_code=401, detail="验证码不正确")

    # 挑战一次性：成功即撤销（challenge 令牌不可复用、也不可当普通 token）
    try:
        blacklist_token(challenge)
    except Exception as e:  # noqa: BLE001 - 撤销失败不得发 token（诚实 500）
        logger.error("2FA challenge 撤销失败: %s", e)
        raise HTTPException(status_code=500, detail="验证状态登记失败，请重试")
    _clearVerifyAttempts(jti)

    tokens = _issueTokenPair(user)
    try:
        model.log_login(
            user_id=user.id,
            username=user.username,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            success=True,
        )
    except Exception as e:  # noqa: BLE001 - 登录日志失败不阻断
        logger.warning("2FA 登录日志写入失败: %s", e)
    try:
        from neurova.api.endpoints.auth import _auditAuthLogin

        _auditAuthLogin(str(user.id), request, success=True, attempted_username=user.username)
    except Exception as e:  # noqa: BLE001 - 审计失败不阻断
        logger.warning("2FA 审计写入失败: %s", e)
    return tokens
