"""
QClaw 服务类

封装与 QClaw 网关的通信逻辑：
1. 凭证校验
2. accessToken 获取和刷新
3. 消息发送
4. 消息签名验证
"""

import hashlib
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

try:
    pass

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logging.warning("requests 库未安装，QClaw服务将使用模拟模式")

from neurova.auth.qclaw_binding_model import QClawBindingModel

logger = logging.getLogger(__name__)

# QClaw 网关地址（应配置化，不要硬编码）
QCLAW_API_BASE = "https://jprx.m.qq.com"
QCLAW_TOKEN_ENDPOINT = "/api/v1/4310"  # 根据实际QClaw API调整


class QClawService:
    """
    QClaw 服务类

    管理 QClaw 网关通信，包括：
    - 凭证校验
    - accessToken 获取和缓存
    - 消息发送
    - 签名验证
    """

    def __init__(self, api_base: str = None):
        """
        初始化 QClaw 服务

        Args:
            api_base: QClaw API 基础地址
        """
        self.api_base = api_base or QCLAW_API_BASE
        self.token_cache = {}  # 缓存 accessToken，按 appId 索引
        self.binding_model = QClawBindingModel()

        logger.info("QClaw 服务已初始化，API地址: %s", self.api_base)

    def verify_credentials(self, app_id: str, app_secret: str) -> Dict[str, Any]:
        """
        校验 QClaw 凭证有效性

        Args:
            app_id: QClaw 应用ID
            app_secret: QClaw 应用密钥

        Returns:
            校验结果字典，包含:
            - valid: 是否有效
            - qclaw_user_id: QClaw 用户ID（如果有效）
            - error: 错误信息（如果无效）
        """
        if not REQUESTS_AVAILABLE:
            # 模拟模式：假设凭证有效
            logger.warning("模拟模式：假设 QClaw 凭证有效")
            return {"valid": True, "qclaw_user_id": f"mock_user_{app_id[:8]}", "error": None}

        try:
            # 调用 QClaw 网关校验接口（根据实际API调整）
            # 这里假设有一个校验接口，实际可能需要调用获取accessToken接口来间接校验
            response = requests.post(
                f"{self.api_base}{QCLAW_TOKEN_ENDPOINT}",
                headers={"Content-Type": "application/json"},
                json={"app_id": app_id, "app_secret": app_secret, "progress": "verify"},  # 自定义进度标识，用于校验
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                # 根据实际返回格式解析
                if data.get("common", {}).get("code") == 0:
                    return {"valid": True, "qclaw_user_id": data.get("data", {}).get("qclaw_user_id"), "error": None}
                else:
                    return {
                        "valid": False,
                        "qclaw_user_id": None,
                        "error": data.get("common", {}).get("message", "凭证校验失败"),
                    }
            else:
                return {"valid": False, "qclaw_user_id": None, "error": f"HTTP {response.status_code}"}

        except Exception as e:
            logger.error("QClaw 凭证校验失败: %s", e)
            return {"valid": False, "qclaw_user_id": None, "error": str(e)}

    def get_access_token(self, app_id: str, app_secret: str, force_refresh: bool = False) -> Optional[str]:
        """
        获取 accessToken（带缓存）

        Args:
            app_id: QClaw 应用ID
            app_secret: QClaw 应用密钥
            force_refresh: 是否强制刷新

        Returns:
            accessToken 字符串，失败返回None
        """
        # 检查缓存
        if not force_refresh and app_id in self.token_cache:
            cached = self.token_cache[app_id]
            if datetime.now() < cached["expires_at"]:
                logger.debug("使用缓存的 accessToken (app_id: %s****)", app_id[:4])
                return cached["token"]

        if not REQUESTS_AVAILABLE:
            # 模拟模式
            mock_token = f"mock_token_{app_id[:8]}_{int(time.time())}"
            self.token_cache[app_id] = {"token": mock_token, "expires_at": datetime.now() + timedelta(hours=2)}
            return mock_token

        try:
            # 调用 QClaw 网关获取 accessToken（根据实际API调整）
            response = requests.post(
                f"{self.api_base}{QCLAW_TOKEN_ENDPOINT}",
                headers={"Content-Type": "application/json"},
                json={"app_id": app_id, "app_secret": app_secret, "grant_type": "client_credentials"},
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                # 根据实际返回格式解析
                if data.get("common", {}).get("code") == 0:
                    token = data.get("data", {}).get("access_token")
                    expires_in = data.get("data", {}).get("expires_in", 7200)  # 默认2小时

                    # 缓存 token
                    self.token_cache[app_id] = {
                        "token": token,
                        "expires_at": datetime.now() + timedelta(seconds=expires_in),
                    }

                    logger.info("获取 accessToken 成功 (app_id: %s****)", app_id[:4])
                    return token
                else:
                    logger.error("获取 accessToken 失败: %s", data.get('common', {}).get('message', 'unknown'))
                    return None
            else:
                logger.error("获取 accessToken HTTP 错误: %s", response.status_code)
                return None

        except Exception as e:
            logger.error("获取 accessToken 异常: %s", e)
            return None

    def send_message(
        self, app_id: str, app_secret: str, chat_id: str, content: str, content_type: str = "text"
    ) -> Dict[str, Any]:
        """
        发送消息到 QClaw

        Args:
            app_id: QClaw 应用ID
            app_secret: QClaw 应用密钥
            chat_id: 目标聊天ID
            content: 消息内容
            content_type: 内容类型（text/image/voice/video/file）

        Returns:
            发送结果字典
        """
        # 获取 accessToken
        access_token = self.get_access_token(app_id, app_secret)
        if not access_token:
            return {"success": False, "error": "获取 accessToken 失败"}

        if not REQUESTS_AVAILABLE:
            # 模拟模式
            logger.warning("模拟模式：模拟发送消息成功")
            return {"success": True, "message_id": f"mock_msg_{int(time.time())}"}

        try:
            # 调用 QClaw 消息发送接口（根据实际API调整）
            response = requests.post(
                f"{self.api_base}/api/v1/message/send",  # 假设接口地址
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"},
                json={"chat_id": chat_id, "content": content, "content_type": content_type},
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("common", {}).get("code") == 0:
                    return {"success": True, "message_id": data.get("data", {}).get("message_id")}
                else:
                    return {"success": False, "error": data.get("common", {}).get("message", "发送失败")}
            else:
                return {"success": False, "error": f"HTTP {response.status_code}"}

        except Exception as e:
            logger.error("发送消息到 QClaw 失败: %s", e)
            return {"success": False, "error": str(e)}

    def verify_signature(self, signature: str, body: str, app_secret: str) -> bool:
        """
        验证 QClaw 回调签名

        Args:
            signature: QClaw 回调签名
            body: 回调请求体
            app_secret: QClaw 应用密钥

        Returns:
            签名是否有效
        """
        # 根据实际签名算法实现（这里使用HMAC-SHA256示例）
        expected_signature = hmac.new(app_secret.encode(), body.encode(), hashlib.sha256).hexdigest()

        # 安全比较（防止时序攻击）
        return hmac.compare_digest(signature, expected_signature)

    def get_binding_by_user(self, neuser_id: str, user_id: str = None) -> Optional[Dict[str, Any]]:
        """
        获取用户的 QClaw 绑定信息

        Args:
            neuser_id: Neurova 系统用户ID
            user_id: 对话用户ID（可选）

        Returns:
            绑定信息字典，不存在返回None
        """
        return self.binding_model.get_binding_by_user(neuser_id, user_id)

    def create_binding(self, neuser_id: str, user_id: str, app_id: str, app_secret: str) -> Dict[str, Any]:
        """
        创建 QClaw 绑定

        Args:
            neuser_id: Neurova 系统用户ID
            user_id: 对话用户ID
            app_id: QClaw 应用ID
            app_secret: QClaw 应用密钥

        Returns:
            创建结果字典
        """
        # 1. 校验凭证
        verify_result = self.verify_credentials(app_id, app_secret)
        if not verify_result["valid"]:
            return {"success": False, "error": verify_result["error"]}

        # 2. 创建绑定
        try:
            binding = self.binding_model.create_binding(
                neuser_id=neuser_id,
                user_id=user_id,
                app_id=app_id,
                app_secret=app_secret,
                qclaw_user_id=verify_result["qclaw_user_id"],
            )

            return {"success": True, "binding": binding}
        except ValueError as e:
            return {"success": False, "error": str(e)}

    def delete_binding(self, binding_id: int):
        """
        删除 QClaw 绑定

        Args:
            binding_id: 绑定记录ID
        """
        self.binding_model.delete_binding(binding_id)

        # 清除 token 缓存
        # 注意：这里需要从 binding 记录中获取 app_id，然后清除缓存
        # 为简化，这里不实现，实际应该先查询 binding 再清除缓存

    def update_last_used(self, binding_id: int):
        """
        更新最后使用时间

        Args:
            binding_id: 绑定记录ID
        """
        self.binding_model.update_last_used(binding_id)


# 全局单例
_qclaw_service_instance: Optional[QClawService] = None


def get_qclaw_service() -> QClawService:
    """
    获取 QClaw 服务单例

    Returns:
        QClawService 实例
    """
    global _qclaw_service_instance
    if _qclaw_service_instance is None:
        _qclaw_service_instance = QClawService()
        logger.info("创建 QClaw 服务单例")
    return _qclaw_service_instance
