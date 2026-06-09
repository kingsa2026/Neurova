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

import collections
import datetime
import logging
import re
import time
import typing
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

# 模块级导入（避免重复导入）
from neurova.api.auth import create_access_token, create_refresh_token, decode_token


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
    user_id: str
    username: str
    email: str = ""
    role: str = "user"
    created_at: Optional[str] = None


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
    request_id = _get_request_id(request)

    try:
        # TODO: 实际的用户验证逻辑
        # 这里简化处理，实际应该查询数据库
        if body.username and body.password:
            user_id = str(uuid.uuid4())

            # 生成 token
            access_token = create_access_token(
                data={"sub": user_id, "username": body.username}
            )
            refresh_token = create_refresh_token(
                data={"sub": user_id, "username": body.username}
            )

            return TokenResponse(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in=3600,
            )
        else:
            raise HTTPException(status_code=401, detail="Invalid credentials")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: Request, body: RefreshRequest):
    """刷新 Token"""
    request_id = _get_request_id(request)

    try:
        # 解码 refresh token
        payload = decode_token(body.refresh_token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        user_id = payload.get("sub")
        username = payload.get("username", "")

        # 生成新 token
        access_token = create_access_token(
            data={"sub": user_id, "username": username}
        )
        refresh_token = create_refresh_token(
            data={"sub": user_id, "username": username}
        )

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
    request_id = _get_request_id(request)

    try:
        # 从请求中获取用户信息（由认证中间件设置）
        user = getattr(request.state, "user", None)
        if not user:
            # 尝试从 token 解析
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                payload = decode_token(token)
                if payload:
                    user = {
                        "user_id": payload.get("sub", "unknown"),
                        "username": payload.get("username", "unknown"),
                    }

        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")

        return UserInfo(
            user_id=user.get("user_id", "unknown"),
            username=user.get("username", "unknown"),
            email=user.get("email", ""),
            role=user.get("role", "user"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get user: {str(e)}")


@router.post("/register")
async def register(request: Request, body: RegisterRequest):
    """用户注册"""
    request_id = _get_request_id(request)

    try:
        # TODO: 实际的注册逻辑
        # 1. 验证邀请码（如果需要）
        # 2. 检查用户名是否已存在
        # 3. 创建用户
        # 4. 返回 token

        user_id = str(uuid.uuid4())

        access_token = create_access_token(
            data={"sub": user_id, "username": body.username}
        )
        refresh_token = create_refresh_token(
            data={"sub": user_id, "username": body.username}
        )

        return {
            "code": 0,
            "message": "Registration successful",
            "data": {
                "user_id": user_id,
                "username": body.username,
                "access_token": access_token,
                "refresh_token": refresh_token,
            },
        }

    except Exception as e:
        logger.error(f"Register error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")


@router.post("/register/send-code")
async def send_verification_code(request: Request, email: str = Query(...)):
    """发送注册验证码"""
    request_id = _get_request_id(request)

    # TODO: 实际发送验证码逻辑
    code = "123456"  # 测试用

    return {
        "code": 0,
        "message": "Verification code sent",
        "data": {"email": email},
    }


@router.post("/register/verify-code")
async def verify_code(request: Request, email: str = Query(...), code: str = Query(...)):
    """验证注册验证码"""
    request_id = _get_request_id(request)

    # TODO: 实际验证逻辑
    if code == "123456":
        return {
            "code": 0,
            "message": "Code verified",
            "data": {"email": email, "verified": True},
        }
    else:
        raise HTTPException(status_code=400, detail="Invalid verification code")


@router.post("/logout")
async def logout(request: Request):
    """用户登出"""
    request_id = _get_request_id(request)

    # TODO: 实际登出逻辑（如将 token 加入黑名单）

    return {
        "code": 0,
        "message": "Logged out successfully",
    }
