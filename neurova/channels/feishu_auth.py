"""
飞书认证与 API 请求 Mixin

提供统一的 API 请求方法、Token 管理和认证功能。
"""

import json
import logging
import threading
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

# 飞书 API 基础 URL
FEISHU_API_BASE = "https://open.feishu.cn/open-apis"

# Token 缓存过期时间（秒）
TOKEN_CACHE_TTL = 7000  # 约 2 小时（实际有效期 2 小时，提前刷新）


class AuthMixin:
    """
    飞书认证 Mixin

    提供:
    - tenant_access_token 获取与缓存
    - API 请求封装
    - 自动刷新 Token
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._token_lock = threading.Lock()
        self._tenant_access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def _get_tenant_access_token(self) -> str:
        """
        获取 tenant_access_token

        使用 app_id 和 app_secret 获取，并自动缓存。
        """
        with self._token_lock:
            # 检查缓存是否有效
            if self._tenant_access_token and time.time() < self._token_expires_at:
                return self._tenant_access_token

            # 请求新 token
            try:
                response = requests.post(
                    f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal",
                    json={
                        "app_id": self.config.app_id,
                        "app_secret": self.config.app_secret,
                    },
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()

                if data.get("code") != 0:
                    logger.error(f"Failed to get tenant_access_token: {data}")
                    raise ValueError(f"Feishu auth error: {data.get('msg')}")

                self._tenant_access_token = data["tenant_access_token"]
                expire = data.get("expire", 7200)
                self._token_expires_at = time.time() + expire - 300  # 提前5分钟刷新

                logger.info("Tenant access token refreshed")
                return self._tenant_access_token

            except Exception as e:
                logger.exception(f"Error getting tenant_access_token: {e}")
                raise

    def _feishu_request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        发送飞书 API 请求

        参数:
            method: HTTP 方法 (GET, POST, PUT, DELETE)
            path: API 路径 (例如: /im/v1/messages)
            data: 请求体 (JSON)
            params: 查询参数
            timeout: 超时时间

        返回:
            Dict: API 响应
        """
        token = self._get_tenant_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        url = f"{FEISHU_API_BASE}{path}"

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=data,
                params=params,
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.exception(f"Feishu API request error: {e}")
            raise

    def _feishu_get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """发送 GET 请求"""
        return self._feishu_request("GET", path, params=params, **kwargs)

    def _feishu_post(
        self,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """发送 POST 请求"""
        return self._feishu_request("POST", path, data=data, **kwargs)

    def _feishu_put(
        self,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """发送 PUT 请求"""
        return self._feishu_request("PUT", path, data=data, **kwargs)

    def _feishu_delete(
        self,
        path: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """发送 DELETE 请求"""
        return self._feishu_request("DELETE", path, **kwargs)
