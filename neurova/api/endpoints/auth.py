from __future__ import annotations

"""
认证接口 - Auth Endpoint

功能:
1. 用户登录 (POST /api/v1/auth/login)
2. 刷新 Token (POST /api/v1/auth/refresh)
3. 获取当前用户信息 (GET /api/v1/auth/me)
4. 注册验证码发送 (POST /api/v1/auth/register/send-code)
5. 注册验证码验证 (POST /api/v1/auth/register/verify-code)
6. 完成注册 (POST /api/v1/auth/register)
7. 邀请注册 (POST /api/v1/auth/register/invite)
"""

from neurova.core.logger import get_logger
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter()

# 模块级导入（避免重复导入）
from neurova.api.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from neurova.api.auth import (
    hash_password,
)
from neurova.auth.invitation_code import InvitationCodeModel
from neurova.auth.user_model import UserModel
from neurova.auth.verification_code import VerificationCodeModel, VerificationType

# Token 黑名单（生产环境应使用 Redis 或数据库）
_token_blacklist: set = set()

# 用户模型实例（单例）
_user_model: Optional[UserModel] = None
_verification_code_model: Optional[VerificationCodeModel] = None
_invitation_code_model: Optional[InvitationCodeModel] = None


def _get_user_model() -> UserModel:
    """获取用户模型实例"""
    global _user_model
    if _user_model is None:
        _user_model = UserModel()
    return _user_model


def _get_verification_code_model() -> VerificationCodeModel:
    """获取验证码模型实例"""
    global _verification_code_model
    if _verification_code_model is None:
        _verification_code_model = VerificationCodeModel()
    return _verification_code_model


def _get_invitation_code_model() -> InvitationCodeModel:
    """获取邀请码模型实例"""
    global _invitation_code_model
    if _invitation_code_model is None:
        _invitation_code_model = InvitationCodeModel()
    return _invitation_code_model


class LoginRequest(BaseModel):
    """登录请求"""

    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class TokenResponse(BaseModel):
    """Token 响应"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 3600


class UserInfo(BaseModel):
    """用户信息"""

    id: str = ""
    user_id: str = ""
    username: str
    email: str = ""
    role: str = "user"
    created_at: Optional[str] = None

    def model_post_init(self, __context) -> None:
        # 确保 id 和 user_id 一致（向后兼容）
        if not self.id and self.user_id:
            self.id = self.user_id
        elif not self.user_id and self.id:
            self.user_id = self.id


class RegisterRequest(BaseModel):
    """注册请求"""

    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")
    email: Optional[str] = Field(default=None, description="邮箱")
    invite_code: Optional[str] = Field(default=None, description="邀请码")


class RefreshRequest(BaseModel):
    """刷新 Token 请求"""

    refresh_token: str = Field(..., description="刷新令牌")


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_token_manager():
    """获取 Token 管理器"""
    from neurova.api.endpoints import get_app_state

    state = get_app_state()
    if state:
        return state.get("token_manager")
    return None


@router.post("/login", response_model=TokenResponse)
async def login(request: Request, body: LoginRequest):
    """用户登录"""
    _get_request_id(request)

    try:
        # 获取用户模型
        user_model = _get_user_model()

        # 查找用户（用于记录失败尝试）
        user_obj = user_model.get_user_by_username(body.username)

        # 验证用户
        user = user_model.authenticate_user(body.username, body.password)
        if not user:
            logger.warning("Login failed for user: %s", body.username)

            # 如果用户存在，增加失败尝试次数
            if user_obj:
                user_model.increment_failed_attempts(user_obj.id)

            raise HTTPException(status_code=401, detail="Invalid credentials")

        # 检查用户状态
        if user.get("status") != "active":
            logger.warning("Login attempt for inactive user: %s", body.username)
            raise HTTPException(status_code=403, detail="Account is inactive")

        # 检查失败尝试次数（可选：如果超过5次则锁定账户）
        if user.get("failed_attempts", 0) >= 5:
            logger.warning("Login attempt for locked user: %s", body.username)
            raise HTTPException(status_code=403, detail="Account is locked due to too many failed attempts")

        # 生成 token
        # 审计修复 (P0-2): JWT 必须携带 neuser_id/user_id 身份声明,
        # 否则三层隔离第 2 层永远回退 "default", 事实上从未生效。
        # 语义: neuser_id = 账号 id (JWT sub); user_id = 对话身份, HTTP 路径同为账号 id。
        identity_claims = {
            "sub": str(user["id"]),
            "username": user["username"],
            "neuser_id": str(user["id"]),
            "user_id": str(user["id"]),
        }
        access_token = create_access_token(
            data={**identity_claims, "role": user.get("role", "user")}
        )
        refresh_token = create_refresh_token(data=identity_claims)

        # 记录登录日志
        user_model.log_login(
            user_id=user["id"],
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            success=True,
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=3600,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")


def is_token_blacklisted(token: str) -> bool:
    """检查token是否在黑名单中"""
    return token in _token_blacklist


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: Request, body: RefreshRequest):
    """刷新 Token"""
    _get_request_id(request)

    try:
        # 检查 token 是否在黑名单中
        if is_token_blacklisted(body.refresh_token):
            raise HTTPException(status_code=401, detail="Token has been revoked")

        # 解码 refresh token
        payload = decode_token(body.refresh_token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        # 验证 token 类型
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")

        user_id = payload.get("sub")
        username = payload.get("username", "")

        # 检查用户是否存在
        user_model = _get_user_model()
        user = user_model.get_user_by_id(int(user_id))
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        # 检查用户状态
        if user.status != "active":
            raise HTTPException(status_code=403, detail="Account is inactive")

        # 生成新 token (审计修复 P0-2: 补齐身份声明)
        identity_claims = {
            "sub": user_id,
            "username": username,
            "neuser_id": str(user.id),
            "user_id": str(user.id),
        }
        access_token = create_access_token(data={**identity_claims, "role": user.role})
        refresh_token = create_refresh_token(data=identity_claims)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=3600,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Refresh error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Refresh failed: {str(e)}")


@router.get("/me", response_model=UserInfo)
async def get_current_user(request: Request):
    """获取当前用户信息"""
    _get_request_id(request)

    try:
        # 从请求中获取用户信息（由认证中间件设置）
        user = getattr(request.state, "user", None)
        if not user:
            # 尝试从 token 解析
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

                # 检查 token 是否在黑名单中
                if is_token_blacklisted(token):
                    raise HTTPException(status_code=401, detail="Token has been revoked")

                payload = decode_token(token)
                if payload:
                    # 验证 token 类型
                    if payload.get("type") != "access":
                        raise HTTPException(status_code=401, detail="Invalid token type")

                    user = {
                        "user_id": payload.get("sub", "unknown"),
                        "username": payload.get("username", "unknown"),
                        "role": payload.get("role", "user"),
                    }

        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")

        user_id = user.get("user_id", "unknown")
        return UserInfo(
            id=user_id,
            user_id=user_id,
            username=user.get("username", "unknown"),
            email=user.get("email", ""),
            role=user.get("role", "user"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get user: {str(e)}")


@router.get("/setup-status")
async def setup_status():
    """首启初始化状态（公开端点）：系统中是否还没有任何用户。

    桌面壳首启向导据此决定是否展示"创建管理员账号"页。
    """
    try:
        user_model = _get_user_model()
        needs_setup = user_model.count_users() == 0
        return {"code": 0, "message": "ok", "data": {"needs_setup": needs_setup}}
    except Exception as e:
        logger.error(f"Setup status error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get setup status: {str(e)}")


@router.post("/register")
async def register(request: Request, body: RegisterRequest):
    """用户注册"""
    _get_request_id(request)

    try:
        # 获取模型实例
        user_model = _get_user_model()
        verification_model = _get_verification_code_model()

        # 检查注册限流
        ip_address = request.client.host if request.client else "unknown"
        rate_limit_info = verification_model.check_register_rate_limit(ip_address)
        if rate_limit_info.get("is_limited", False):
            logger.warning("Register rate limited for IP: %s", ip_address)
            raise HTTPException(status_code=429, detail="Too many registration attempts. Please try again later.")

        # 1. 检查用户名是否已存在
        existing_user = user_model.get_user_by_username(body.username)
        if existing_user:
            logger.warning("Username already exists: %s", body.username)
            # 记录注册尝试
            verification_model.record_register_attempt(ip_address, success=False)
            raise HTTPException(status_code=400, detail="Username already exists")

        # 3. 检查邮箱是否已存在（如果提供）
        if body.email:
            existing_email = user_model.get_user_by_email(body.email)
            if existing_email:
                logger.warning("Email already exists: %s", body.email)
                # 记录注册尝试
                verification_model.record_register_attempt(ip_address, success=False)
                raise HTTPException(status_code=400, detail="Email already exists")

        # 4. 创建用户（首启场景：系统中尚无任何用户时，注册者即为管理员）
        password_hash = hash_password(body.password)
        role = "admin" if user_model.count_users() == 0 else "user"
        user = user_model.create_user(
            username=body.username, password_hash=password_hash, email=body.email, role=role
        )

        # 5. 生成 token (审计修复 P0-2: 补齐身份声明)
        identity_claims = {
            "sub": str(user.id),
            "username": user.username,
            "neuser_id": str(user.id),
            "user_id": str(user.id),
        }
        access_token = create_access_token(data={**identity_claims, "role": user.role})
        refresh_token = create_refresh_token(data=identity_claims)

        # 记录成功的注册尝试
        verification_model.record_register_attempt(ip_address, success=True)

        return {
            "code": 0,
            "message": "Registration successful",
            "data": {
                "user_id": user.id,
                "username": user.username,
                "access_token": access_token,
                "refresh_token": refresh_token,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Register error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")


@router.post("/register/send-code")
async def send_verification_code(request: Request, email: str = Query(...)):
    """发送注册验证码"""
    _get_request_id(request)

    try:
        # 获取验证码模型
        verification_model = _get_verification_code_model()

        # 检查是否可以发送验证码（限流）
        can_send_info = verification_model.can_send_code(
            target=email, code_type=VerificationType.REGISTER, cooldown=60  # 60秒冷却期
        )

        if not can_send_info["can_send"]:
            raise HTTPException(status_code=429, detail=can_send_info["message"])

        # 生成验证码
        code = verification_model.create_code(
            target=email,
            code_type=VerificationType.REGISTER,
            expires_in=300,  # 5分钟过期
            max_attempts=3,  # 最多尝试3次
            length=6,  # 6位验证码
        )

        # 实际发送验证码（这里只是模拟，实际应该调用邮件服务）
        logger.info("Verification code generated for %s: %s", email, code)

        # TODO: 实际发送邮件逻辑
        # 例如：send_email(email, "Neurova 验证码", f"您的验证码是: {code}")

        return {
            "code": 0,
            "message": "Verification code sent",
            "data": {"email": email},
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Send verification code error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send verification code: {str(e)}")


@router.post("/register/verify-code")
async def verify_code(request: Request, email: str = Query(...), code: str = Query(...)):
    """验证注册验证码"""
    _get_request_id(request)

    try:
        # 获取验证码模型
        verification_model = _get_verification_code_model()

        # 验证验证码
        is_valid = verification_model.verify_code(
            target=email, code=code, code_type=VerificationType.REGISTER, mark_as_used=True  # 验证成功后标记为已使用
        )

        if is_valid:
            return {
                "code": 0,
                "message": "Code verified",
                "data": {"email": email, "verified": True},
            }
        else:
            # 获取尝试次数信息
            code_info = verification_model.get_code_info(target=email, code_type=VerificationType.REGISTER)

            if code_info and code_info.is_used_up:
                raise HTTPException(status_code=429, detail="Too many failed attempts. Please request a new code.")
            elif code_info and code_info.is_expired:
                raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new one.")
            else:
                raise HTTPException(status_code=400, detail="Invalid verification code")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Verify code error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to verify code: {str(e)}")


@router.post("/logout")
async def logout(request: Request):
    """用户登出"""
    _get_request_id(request)

    try:
        # 获取当前用户的 token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

            # 将 token 加入黑名单
            if token:
                _token_blacklist.add(token)
                logger.info("Token added to blacklist")

        return {
            "code": 0,
            "message": "Logged out successfully",
        }

    except Exception as e:
        logger.error(f"Logout error: {e}", exc_info=True)
        # 即使出错也返回成功，因为登出是幂等操作
        return {
            "code": 0,
            "message": "Logged out successfully",
        }


class InviteRegisterRequest(BaseModel):
    """邀请注册请求"""

    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")
    email: Optional[str] = Field(default=None, description="邮箱")
    invite_code: str = Field(..., description="邀请码")


@router.post("/register/invite")
async def register_with_invite(request: Request, body: InviteRegisterRequest):
    """邀请注册（暂未启用）"""
    raise HTTPException(status_code=501, detail="Invitation registration is not enabled yet")
