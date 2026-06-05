"""
微信认证 Mixin

包含:
1. 主认证入口 (authenticate)
2. 企业微信认证 (_authenticate_wecom, _refresh_wecom_token, _ensure_wecom_token)
3. iLink 协议认证 (_authenticate_ilink, _generate_qr_code, _wait_for_scan, _verify_ilink_token, _save_ilink_token)
4. 微信公众号认证 (_authenticate_official, _refresh_official_token, _ensure_official_token)
5. 统一 API 请求方法 (_api_request)

由 WeChatAdapter 通过多继承使用，所有属性都来自主类。
"""

import hashlib
import json
import logging
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

# 微信 API 基础 URL
WECHAT_API_BASE = "https://api.weixin.qq.com/cgi-bin"
WECOM_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"


class AuthMixin:
    """
    微信认证 Mixin

    提供:
    - 企业微信认证
    - 微信公众号认证
    - iLink 协议认证
    - 统一 API 请求
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    async def authenticate(self) -> bool:
        """
        主认证入口

        根据配置选择认证方式:
        - 企业微信: corpid + corpsecret
        - 公众号: appid + secret
        - iLink: 扫码认证
        """
        try:
            auth_type = self.config.extra.get("auth_type", "wecom")

            if auth_type == "wecom":
                return await self._authenticate_wecom()
            elif auth_type == "official":
                return await self._authenticate_official()
            elif auth_type == "ilink":
                return await self._authenticate_ilink()
            else:
                logger.error(f"Unknown auth type: {auth_type}")
                return False

        except Exception as e:
            logger.exception(f"Authentication error: {e}")
            return False

    async def _authenticate_wecom(self) -> bool:
        """企业微信认证"""
        try:
            corpid = self.config.app_id
            corpsecret = self.config.app_secret

            if not corpid or not corpsecret:
                logger.error("WeChat credentials not configured")
                return False

            # 获取 access_token
            response = requests.get(
                f"{WECOM_API_BASE}/gettoken",
                params={
                    "corpid": corpid,
                    "corpsecret": corpsecret,
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            if data.get("errcode") != 0:
                logger.error(f"WeCom auth failed: {data}")
                return False

            self._access_token = data["access_token"]
            expires_in = data.get("expires_in", 7200)
            self._token_expires_at = time.time() + expires_in - 300  # 提前5分钟刷新

            logger.info("WeCom authentication successful")
            return True

        except Exception as e:
            logger.exception(f"WeCom auth error: {e}")
            return False

    async def _refresh_wecom_token(self) -> bool:
        """刷新企业微信 access_token"""
        return await self._authenticate_wecom()

    async def _ensure_wecom_token(self) -> str:
        """确保企业微信 token 有效"""
        if not self._access_token or time.time() >= self._token_expires_at:
            await self._refresh_wecom_token()
        return self._access_token or ""

    async def _authenticate_official(self) -> bool:
        """微信公众号认证"""
        try:
            appid = self.config.app_id
            secret = self.config.app_secret

            if not appid or not secret:
                logger.error("WeChat official credentials not configured")
                return False

            # 获取 access_token
            response = requests.get(
                f"{WECHAT_API_BASE}/token",
                params={
                    "grant_type": "client_credential",
                    "appid": appid,
                    "secret": secret,
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            if "errcode" in data:
                logger.error(f"WeChat official auth failed: {data}")
                return False

            self._access_token = data["access_token"]
            expires_in = data.get("expires_in", 7200)
            self._token_expires_at = time.time() + expires_in - 300

            logger.info("WeChat official authentication successful")
            return True

        except Exception as e:
            logger.exception(f"WeChat official auth error: {e}")
            return False

    async def _refresh_official_token(self) -> bool:
        """刷新公众号 access_token"""
        return await self._authenticate_official()

    async def _ensure_official_token(self) -> str:
        """确保公众号 token 有效"""
        if not self._access_token or time.time() >= self._token_expires_at:
            await self._refresh_official_token()
        return self._access_token or ""

    async def _authenticate_ilink(self) -> bool:
        """iLink 协议认证 (扫码)"""
        try:
            # 生成二维码
            qr_code_url = await self._generate_qr_code()
            if not qr_code_url:
                return False

            # 等待扫码
            token = await self._wait_for_scan(qr_code_url)
            if not token:
                return False

            # 验证 token
            if await self._verify_ilink_token(token):
                await self._save_ilink_token(token)
                return True

            return False

        except Exception as e:
            logger.exception(f"iLink auth error: {e}")
            return False

    async def _generate_qr_code(self) -> Optional[str]:
        """生成 iLink 扫码二维码 URL"""
        # 实际实现需要调用 iLink API
        logger.warning("iLink QR code generation not implemented")
        return None

    async def _wait_for_scan(self, qr_code_url: str) -> Optional[str]:
        """等待用户扫码"""
        # 实际实现需要轮询扫码状态
        logger.warning("iLink scan waiting not implemented")
        return None

    async def _verify_ilink_token(self, token: str) -> bool:
        """验证 iLink token"""
        # 实际实现需要调用 iLink API 验证
        logger.warning("iLink token verification not implemented")
        return False

    async def _save_ilink_token(self, token: str):
        """保存 iLink token"""
        self._access_token = token
        # 设置较长的过期时间
        self._token_expires_at = time.time() + 86400 * 30  # 30天

    async def _api_request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        统一 API 请求方法

        参数:
            method: HTTP 方法
            path: API 路径
            data: 请求体
            params: 查询参数
            timeout: 超时时间

        返回:
            Dict: API 响应
        """
        # 确保 token 有效
        auth_type = self.config.extra.get("auth_type", "wecom")
        if auth_type == "wecom":
            token = await self._ensure_wecom_token()
            base_url = WECOM_API_BASE
        else:
            token = await self._ensure_official_token()
            base_url = WECHAT_API_BASE

        # 添加 access_token 到参数
        if params is None:
            params = {}
        params["access_token"] = token

        url = f"{base_url}{path}"

        try:
            response = requests.request(
                method=method,
                url=url,
                json=data,
                params=params,
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.exception(f"WeChat API request error: {e}")
            raise
