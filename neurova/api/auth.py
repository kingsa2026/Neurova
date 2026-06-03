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
import logging
import os
from pathlib import Path
import secrets
import time
import typing
import uuid
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

logger = logging.getLogger(__name__)

# JWT 配置
JWT_SECRET_KEY = os.getenv("NEUROVA_JWT_SECRET", "neurova-default-secret-key-change-in-production")
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
    env_key = os.getenv("NEUROVA_JWT_SECRET")
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
        logger.warning(f"Failed to save JWT secret: {e}")

    return secret


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

    to_encode.update({
        "exp": expire,
        "type": "access",
        "iat": datetime.datetime.now(datetime.timezone.utc),
        "jti": str(uuid.uuid4()),
    })

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

    to_encode.update({
        "exp": expire,
        "type": "refresh",
        "iat": datetime.datetime.now(datetime.timezone.utc),
        "jti": str(uuid.uuid4()),
    })

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
        logger.warning(f"Invalid token: {e}")
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
        logger.warning(f"Token type mismatch: expected {token_type}, got {payload.get('type')}")
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
    使用 bcrypt 安全哈希密码

    Args:
        password: 明文密码

    Returns:
        bcrypt 哈希字符串
    """
    try:
        import bcrypt
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")
    except ImportError:
        # 如果 bcrypt 不可用，使用简单哈希（不推荐用于生产）
        import hashlib
        return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    """
    验证密码是否匹配哈希值

    Args:
        password: 明文密码
        hashed: 哈希值

    Returns:
        是否匹配
    """
    try:
        import bcrypt
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ImportError:
        # 如果 bcrypt 不可用，使用简单哈希比较
        import hashlib
        return hashlib.sha256(password.encode("utf-8")).hexdigest() == hashed


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

    return {
        "user_id": payload.get("sub", "unknown"),
        "username": payload.get("username", "unknown"),
        "role": payload.get("role", "user"),
    }


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

    return {
        "user_id": payload.get("sub", "unknown"),
        "username": payload.get("username", "unknown"),
        "role": payload.get("role", "user"),
    }
