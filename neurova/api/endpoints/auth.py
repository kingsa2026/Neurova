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
import hmac
import os
import uuid
import time
from typing import Dict, List, Optional

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
# BUG AUDIT S-21: 原 set 只增不减、无界增长 → 改为 token -> 过期时间戳 dict，
# token 本身过期后黑名单项即失去意义，惰性清理过期项。
_token_blacklist: Dict[str, float] = {}
_TOKEN_BLACKLIST_TTL_FALLBACK = 7 * 24 * 3600  # decode 失败时的兜底保留期


def _blacklist_token_local(token: str) -> None:
    """登记黑名单项，保留期与 token 自身 exp 对齐（无 exp 时用兜底 TTL）。"""
    payload = decode_token(token)
    exp = payload.get("exp") if payload else None
    _token_blacklist[token] = (
        float(exp) if exp else time.time() + _TOKEN_BLACKLIST_TTL_FALLBACK
    )


def _purge_expired_blacklist() -> None:
    now = time.time()
    expired = [t for t, exp in _token_blacklist.items() if exp <= now]
    for t in expired:
        _token_blacklist.pop(t, None)

# 忘记密码/取回密码：最高权重恢复密码（写死常量）。
# 校验只允许发生在服务端（前端仅做 UX 即时校验）；双条件缺一不可：
# 1) username 是系统内角色为 admin 的管理员账号；2) master_password == 此常量。
# 根因修复 2026-09-07：硬编码恢复密码随源码/打包分发=后门；改为环境变量，
# 未配置则恢复功能整体禁用（403）。
MASTER_RECOVERY_PASSWORD = os.environ.get("NEUROVA_MASTER_RECOVERY_PASSWORD", "")

# recover-password 简易限流：key=(username|ip) -> 尝试时间戳列表
_recover_attempts: Dict[str, list] = {}
_RECOVER_LIMIT = 5  # 窗口内最大尝试次数
_RECOVER_WINDOW = 900  # 15 分钟

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
    # 用户组功能模块白名单（所属组并集）。空列表 = 不限制（不在任何组/组未配置）。
    allowed_modules: List[str] = []
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
    # BUG AUDIT S-04: 非首启注册必须携带邮箱验证码，否则任意访客可无验证注册
    verification_code: Optional[str] = Field(default=None, description="邮箱验证码（非首启注册必填）")
    # BUG AUDIT S-04 残余: 服务端部署首账号抢注防护——配置了引导令牌时必填
    bootstrap_token: Optional[str] = Field(default=None, description="首账号引导令牌（部署加固）")


class RecoverPasswordRequest(BaseModel):
    """忘记密码/取回密码请求

    双条件缺一不可（必须都对上）：
    1. username：系统中存在且角色为 admin 的管理员账号
    2. master_password：最高权重恢复密码（写死常量）
    """

    username: str = Field(..., description="管理员账号")
    master_password: str = Field(..., description="最高权重恢复密码")
    new_password: str = Field(..., description="新密码")
    confirm_password: str = Field(..., description="确认新密码")


class RefreshRequest(BaseModel):
    """刷新 Token 请求"""

    refresh_token: str = Field(..., description="刷新令牌")


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


# BUG AUDIT S-04 残余: 首账号注册引导令牌（部署加固; 环境门控, 未配置=行为不变）
_BOOTSTRAP_ADMIN_TOKEN_ENV = "NEUROVA_BOOTSTRAP_ADMIN_TOKEN"


def _resolve_bootstrap_admin_token() -> str:
    """解析首账号注册引导令牌（仅 count_users()==0 时消费）。

    优先级:
    1. 环境变量 NEUROVA_BOOTSTRAP_ADMIN_TOKEN
    2. data/bootstrap_admin.ini 的 [bootstrap] token 键（安装包向导约定文件的
       扩展; 旧格式仅 username/password 无 token 键 → 视为未配置, 保持兼容）
    两者均未配置 → 返回空串（桌面首启默认行为: 首账号即管理员, 不要求令牌）。
    """
    token = (os.environ.get(_BOOTSTRAP_ADMIN_TOKEN_ENV) or "").strip()
    if token:
        return token

    import neurova.api.bootstrap_user as _bootstrap_user

    ini_path = _bootstrap_user.BOOTSTRAP_ADMIN_FILE
    if os.path.exists(ini_path):
        try:
            parser = _bootstrap_user._read_ini_text(ini_path)
            if parser is not None and parser.has_section("bootstrap"):
                return (parser.get("bootstrap", "token", fallback="") or "").strip()
        except Exception as e:
            logger.warning("bootstrap_admin.ini 令牌读取失败: %s", e)
    return ""


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
        # BUG AUDIT S-11: 不得把内部异常原文回传给客户端（信息泄露）
        raise HTTPException(status_code=500, detail="Login failed")


def _check_recover_rate_limit(key: str) -> bool:
    """recover-password 限流：窗口内达到上限返回 True。"""
    now = time.time()
    records = [t for t in _recover_attempts.get(key, []) if now - t < _RECOVER_WINDOW]
    _recover_attempts[key] = records
    return len(records) >= _RECOVER_LIMIT


def _record_recover_attempt(key: str) -> None:
    _recover_attempts.setdefault(key, []).append(time.time())


@router.post("/recover-password")
async def recover_password(request: Request, body: RecoverPasswordRequest):
    """忘记密码/取回密码（管理员账号 + 最高权重密码，双条件缺一不可）。

    - username 必须是系统中角色为 admin 的管理员账号
    - master_password 必须等于 MASTER_RECOVERY_PASSWORD（服务端校验）
    - 错误统一文案（不泄露账号是否存在/角色），防用户名探测
    """
    _get_request_id(request)

    ip_address = request.client.host if request.client else "unknown"
    rate_key = f"{body.username}|{ip_address}"

    try:
        if _check_recover_rate_limit(rate_key):
            raise HTTPException(status_code=429, detail="尝试次数过多，请 15 分钟后再试")

        user_model = _get_user_model()
        user = user_model.get_user_by_username(body.username)

        if not MASTER_RECOVERY_PASSWORD:
            raise HTTPException(status_code=403, detail="密码恢复功能未配置（NEUROVA_MASTER_RECOVERY_PASSWORD），已禁用")
        # S-20: 恒定时间比较，防时序攻击探测恢复密码
        master_ok = hmac.compare_digest(
            body.master_password.encode("utf-8", "ignore"),
            MASTER_RECOVERY_PASSWORD.encode("utf-8"),
        )
        user_ok = bool(user) and user.role == "admin"
        if not (user_ok and master_ok):
            _record_recover_attempt(rate_key)
            logger.warning(
                "recover-password 验证失败: username=%s (admin=%s, master=%s) ip=%s",
                body.username, bool(user) and user.role == "admin", bool(master_ok), ip_address,
            )
            raise HTTPException(status_code=400, detail="管理员账号或最高权重密码不正确，请核对后重试")

        if not body.new_password or not body.confirm_password:
            raise HTTPException(status_code=400, detail="请填写新密码")
        if body.new_password != body.confirm_password:
            raise HTTPException(status_code=400, detail="两次输入的新密码不一致")

        # 双条件对上 → 重置密码（同时清除历史失败计数）
        updated = user_model.update_user(
            user.id,
            password_hash=hash_password(body.new_password),
            failed_attempts=0,
        )
        if not updated:
            raise HTTPException(status_code=500, detail="密码重置失败，请稍后重试")

        logger.warning("Password recovered (最高权重密码): username=%s ip=%s", body.username, ip_address)
        return {
            "code": 0,
            "message": "密码已重置，请使用新密码登录",
            "data": {"username": body.username},
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Recover password error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Recover password failed: {str(e)}")


def is_token_blacklisted(token: str) -> bool:
    """检查token是否在黑名单中（含全局单源黑名单）。"""
    from neurova.api.auth import is_token_blacklisted_global

    _purge_expired_blacklist()
    return token in _token_blacklist or is_token_blacklisted_global(token)


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


def _get_user_allowed_modules(username: str) -> list:
    """计算用户可用功能模块（所属用户组并集）。

    fail-open：用户组服务异常时返回空列表（不限制），不影响登录本身。
    """
    try:
        from neurova.auth.user_group_model import get_user_group_manager

        return get_user_group_manager().get_allowed_modules_for_user(username)
    except Exception as e:
        logger.warning("Failed to compute allowed_modules for %s: %s", username, e)
        return []


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
        username = user.get("username", "unknown")
        role = user.get("role", "user")
        # admin 恒全模块可见；普通用户取所属组并集
        allowed_modules = [] if role == "admin" else _get_user_allowed_modules(username)
        return UserInfo(
            id=user_id,
            user_id=user_id,
            username=username,
            email=user.get("email", ""),
            role=role,
            allowed_modules=allowed_modules,
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

        # BUG AUDIT S-04: 注册流程此前完全跳过邮件验证码校验，任意访客可无验证
        # 注册账号。系统已存在用户（非首启引导）时，强制要求邮箱验证码。
        is_bootstrap = user_model.count_users() == 0
        if not is_bootstrap:
            if not body.email:
                raise HTTPException(status_code=400, detail="注册需提供邮箱")
            if not body.verification_code:
                raise HTTPException(status_code=400, detail="请先获取并填写邮箱验证码")
            code_ok = verification_model.verify_code(
                target=body.email,
                code=body.verification_code,
                code_type=VerificationType.REGISTER,
                mark_as_used=True,
            )
            if not code_ok:
                logger.warning("邮箱验证码校验失败: %s", body.email)
                verification_model.record_register_attempt(ip_address, success=False)
                raise HTTPException(status_code=400, detail="邮箱验证码无效或已过期")
        else:
            # BUG AUDIT S-04 残余: 服务端部署场景下首账号即管理员, 可被任意访客
            # 抢注。部署方配置引导令牌（NEUROVA_BOOTSTRAP_ADMIN_TOKEN 或
            # data/bootstrap_admin.ini [bootstrap] token）后, 首账号注册必须
            # 出示匹配令牌; 两处均未配置 → 保持桌面默认行为（注册即管理员）。
            expected_token = _resolve_bootstrap_admin_token()
            if expected_token:
                provided_token = (body.bootstrap_token or "").encode("utf-8")
                if not hmac.compare_digest(provided_token, expected_token.encode("utf-8")):
                    logger.warning("首账号注册引导令牌校验失败: %s", body.username)
                    verification_model.record_register_attempt(ip_address, success=False)
                    raise HTTPException(status_code=403, detail="Invalid bootstrap token")
            else:
                logger.warning(
                    "首账号注册未配置引导令牌（NEUROVA_BOOTSTRAP_ADMIN_TOKEN / "
                    "bootstrap_admin.ini）: 服务端部署存在管理员抢注风险"
                )

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

            # 将 token 加入黑名单（双源：本模块 set + api/auth 全局单源，
            # verify_access_token 只查后者——否则登出对受保护端点无效）
            if token:
                _blacklist_token_local(token)
                try:
                    from neurova.api.auth import blacklist_token

                    blacklist_token(token)
                except Exception as e:  # noqa: BLE001
                    logger.warning("全局黑名单注册失败: %s", e)
                    # BUG AUDIT S-12: 黑名单写入失败时不得谎报"登出成功"，否则
                    # token 实际仍有效，客户端误以为已登出。显式返回错误让客户端重试。
                    raise HTTPException(
                        status_code=500, detail="Logout failed: unable to invalidate token"
                    )
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
