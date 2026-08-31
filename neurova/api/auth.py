from __future__ import annotations

"""
Neurova JWT 认证模块

功能:
1. JWT Token 生成 (Access Token + Refresh Token)
2. Token 验证
3. Token 刷新
4. 用户登录验证
"""

import datetime
from neurova.core import config
from neurova.core.logger import get_logger
import secrets
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = get_logger(__name__)

# JWT 配置
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7

# HTTP Bearer scheme
security = HTTPBearer(auto_error=False)


class AuthError(Exception):
    """认证错误"""

    def __init__(self, message: str, code: int = 401):
        self.message = message
        self.code = code
        super().__init__(message)


def _load_or_create_secret_key() -> str:
    """
    加载或创建持久化 JWT Secret Key

    优先级:
    1. 环境变量 NEUROVA_JWT_SECRET
    2. 配置文件 .jwt_secret
    3. 自动生成并保存
    """
    # 1. 环境变量
    env_key = config.get("NEUROVA_JWT_SECRET")
    if env_key:
        return env_key

    # 2. 配置文件
    secret_file = Path(".jwt_secret")
    if secret_file.exists():
        try:
            return secret_file.read_text().strip()
        except Exception:
            pass

    # 3. 自动生成
    secret = secrets.token_hex(32)
    try:
        secret_file.write_text(secret)
    except Exception as e:
        logger.warning("Failed to save JWT secret: %s", e)

    return secret


# JWT Secret Key — 从环境变量或自动生成的文件加载
# 优先级: 环境变量 NEUROVA_JWT_SECRET > .jwt_secret 文件 > 自动生成
JWT_SECRET_KEY = _load_or_create_secret_key()


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[datetime.timedelta] = None,
) -> str:
    """
    创建 Access Token

    Args:
        data: Token 数据
        expires_delta: 过期时间增量

    Returns:
        JWT Token 字符串
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.datetime.now(datetime.timezone.utc) + expires_delta
    else:
        expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update(
        {
            "exp": expire,
            "type": "access",
            "iat": datetime.datetime.now(datetime.timezone.utc),
            "jti": str(uuid.uuid4()),
        }
    )

    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(
    data: Dict[str, Any],
    expires_delta: Optional[datetime.timedelta] = None,
) -> str:
    """
    创建 Refresh Token

    Args:
        data: Token 数据
        expires_delta: 过期时间增量

    Returns:
        JWT Token 字符串
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.datetime.now(datetime.timezone.utc) + expires_delta
    else:
        expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode.update(
        {
            "exp": expire,
            "type": "refresh",
            "iat": datetime.datetime.now(datetime.timezone.utc),
            "jti": str(uuid.uuid4()),
        }
    )

    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_token_pair(
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    创建 Token 对 (Access + Refresh)

    Args:
        data: Token 数据

    Returns:
        包含 access_token 和 refresh_token 的字典
    """
    access_token = create_access_token(data)
    refresh_token = create_refresh_token(data)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """
    解码 JWT Token

    Args:
        token: JWT Token 字符串

    Returns:
        Token 数据字典，失败返回 None
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid token: %s", e)
        return None


def verify_token(token: str, token_type: str = "access") -> Optional[Dict[str, Any]]:
    """
    验证 JWT Token

    Args:
        token: JWT Token 字符串
        token_type: Token 类型 ("access" 或 "refresh")

    Returns:
        Token 数据字典，失败返回 None
    """
    payload = decode_token(token)
    if not payload:
        return None

    # 检查 token 类型
    if payload.get("type") != token_type:
        logger.warning("Token type mismatch: expected %s, got %s", token_type, payload.get('type'))
        return None

    return payload


def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    """验证 Access Token"""
    return verify_token(token, "access")


def verify_refresh_token(token: str) -> Optional[Dict[str, Any]]:
    """验证 Refresh Token"""
    return verify_token(token, "refresh")


def get_token_subject(token: str) -> Optional[str]:
    """
    从 Token 中获取 subject (用户标识)

    Args:
        token: JWT Token 字符串

    Returns:
        用户标识，失败返回 None
    """
    payload = decode_token(token)
    if payload:
        return payload.get("sub")
    return None


def hash_password(password: str) -> str:
    """
    安全哈希密码

    优先使用 bcrypt，回退到 PBKDF2-SHA256（带随机盐）。
    绝不使用无盐哈希。

    Args:
        password: 明文密码

    Returns:
        哈希字符串（bcrypt 或 PBKDF2 格式）
    """
    try:
        import bcrypt

        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")
    except ImportError:
        # bcrypt 不可用时，使用 PBKDF2-SHA256（NIST 推荐的 KDF）
        import base64
        import hashlib

        salt = secrets.token_bytes(16)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations=260000)
        # 格式: pbkdf2:sha256:260000:<salt_b64>:<dk_b64>
        return f"pbkdf2:sha256:260000:{base64.b64encode(salt).decode()}:{base64.b64encode(dk).decode()}"


def verify_password(password: str, hashed: str) -> bool:
    """
    验证密码是否匹配哈希值

    Args:
        password: 明文密码
        hashed: 哈希值（bcrypt 或 PBKDF2-SHA256 格式）

    Returns:
        是否匹配

    安全说明:
        不再接受无盐 SHA-256 哈希（彩虹表攻击风险）。
        仅支持 bcrypt 和 PBKDF2-SHA256 两种带盐算法。
    """
    if not hashed:
        return False
    try:
        import bcrypt

        try:
            return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        except ValueError:
            # 不是 bcrypt 哈希格式，继续尝试 PBKDF2
            pass
    except ImportError:
        pass

    # bcrypt 不可用或哈希不是 bcrypt 格式时，使用 PBKDF2-SHA256 验证
    import base64
    import hashlib

    if not hashed.startswith("pbkdf2:sha256:"):
        # 拒绝无盐 SHA-256 及任何未知格式（安全：不再回退到弱哈希）
        return False
    parts = hashed.split(":")
    if len(parts) != 5:
        return False
    _, _, iterations_b64, salt_b64, dk_b64 = parts
    salt = base64.b64decode(salt_b64)
    iterations = int(iterations_b64)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations=iterations)
    return base64.b64encode(dk).decode() == dk_b64


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """
    FastAPI 依赖：获取当前认证用户

    Args:
        credentials: HTTP Bearer 凭证

    Returns:
        用户信息字典

    Raises:
        HTTPException: 认证失败
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = verify_access_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _user_identity(payload)


_SERVICE_TOKEN_HEADER = "X-Service-Token"


async def get_current_user_or_service(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """FastAPI 依赖：JWT 优先，无 JWT 时接受服务令牌（遗留修复 ④）。

    面向无 JWT 的机器调用方（渠道后端、n8n、运维脚本等）访问知识条目 API：
    - 仅当环境变量 NEUROVA_SERVICE_TOKEN 已配置时启用（未配置=功能关闭，无后门）
    - 头 X-Service-Token 与配置值做常量时间比较（hmac.compare_digest）
    - 匹配 → role="admin" 的受信机器身份（user_id="system"）
    - 服务令牌不匹配时回落 JWT 校验，两者都失败 → 401
    """
    import hmac as _hmac
    import os as _os

    expected = (_os.environ.get("NEUROVA_SERVICE_TOKEN") or "").strip()
    provided = str(getattr(request, "headers", {}).get(_SERVICE_TOKEN_HEADER, "") or "").strip()
    if expected and provided and _hmac.compare_digest(provided, expected):
        return {
            "user_id": "system",
            "username": "service",
            "role": "admin",
            "neuser_id": "system",
            "auth_source": "service_token",
        }
    return await get_current_user(credentials)


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[Dict[str, Any]]:
    """
    FastAPI 依赖：获取可选的认证用户

    Args:
        credentials: HTTP Bearer 凭证

    Returns:
        用户信息字典，未认证返回 None
    """
    if not credentials:
        return None

    token = credentials.credentials
    payload = verify_access_token(token)

    if not payload:
        return None

    return _user_identity(payload)


_DEFAULT_USER = {"user_id": "default", "username": "default", "role": "user", "neuser_id": "default"}


def _user_identity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """从 JWT payload 提取用户身份字典 (含 neuser_id)。

    审计修复 (P0-2): get_current_user 系列必须暴露 neuser_id,
    否则三层隔离第 2 层永远回退 "default"。存量 Token 无声明时
    回退 sub (即账号 id), 与新签发的 Token 语义一致。
    """
    sub = payload.get("sub", "unknown")
    return {
        "user_id": sub,
        "username": payload.get("username", "unknown"),
        "role": payload.get("role", "user"),
        "neuser_id": payload.get("neuser_id") or sub,
    }


async def get_current_user_or_default(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """
    FastAPI 依赖：获取认证用户，未认证时返回默认用户

    用于不需要严格认证但仍然想识别已登录用户的端点。
    """
    if not credentials:
        return _DEFAULT_USER.copy()

    token = credentials.credentials
    payload = verify_access_token(token)

    if not payload:
        return _DEFAULT_USER.copy()

    return _user_identity(payload)
