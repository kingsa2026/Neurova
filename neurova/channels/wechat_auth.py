"""
微信认证 Mixin

处理企业微信、iLink、微信公众号三种模式的认证逻辑。
"""
from __future__ import annotations

import hashlib
import json
from neurova.core.logger import get_logger
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class WeChatAuthMixin:
    """微信认证 Mixin — 企业微信 / iLink / 公众号"""

    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    # ============================================================
    # 企业微信认证
    # ============================================================

    def _authenticate_wecom(self, config: Dict[str, str]) -> bool:
        """认证企业微信"""
        a = self.adapter
        a.corpid = config.get("corpid", "")
        a.corpsecret = config.get("corpsecret", "")
        a.agentid = config.get("agentid", "")
        a.kf_mode = config.get("kf_mode", "false").lower() == "true"
        a.open_kfid = config.get("open_kfid", "")
        a.callback_token = config.get("token", "")
        a.encoding_aes_key = config.get("encoding_aes_key", "")

        if not a.corpid or not a.corpsecret:
            logger.error("企业微信认证失败: corpid 和 corpsecret 不能为空")
            return False

        if a.kf_mode and not a.open_kfid:
            logger.error("微信客服模式需要提供 open_kfid")
            return False

        return self._refresh_wecom_token()

    def _refresh_wecom_token(self) -> bool:
        """刷新企业微信 access_token"""
        a = self.adapter
        if not REQUESTS_AVAILABLE:
            a._wecom_initialized = True
            return True

        try:
            url = f"{a.WECOM_API_BASE}/cgi-bin/gettoken"
            params = {
                "corpid": a.corpid,
                "corpsecret": a.corpsecret,
            }
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()

            if data.get("errcode") == 0:
                a.access_token = data["access_token"]
                a.token_expire_time = int(time.time()) + data.get("expires_in", 7200) - 60
                a._wecom_initialized = True
                logger.info("企业微信认证成功")
                return True
            else:
                logger.error("企业微信认证失败: %s", data)
                return False
        except (requests.RequestException, json.JSONDecodeError) as e:
            logger.error("企业微信认证异常: %s", e)
            return False

    def _ensure_wecom_token(self) -> bool:
        """确保企业微信 token 有效"""
        a = self.adapter
        if not a._wecom_initialized:
            return self._refresh_wecom_token()
        if int(time.time()) >= a.token_expire_time:
            return self._refresh_wecom_token()
        return True

    # ============================================================
    # iLink 协议认证
    # ============================================================

    def _authenticate_ilink(self, config: Dict[str, str]) -> bool:
        """
        认证 iLink 协议

        流程:
        1. 如果提供了 bot_token，直接使用
        2. 如果没有 token，生成二维码URL，等待扫码
        3. 扫码成功后，token 保存到本地文件
        """
        a = self.adapter
        a.ilink_bot_token = config.get("bot_token", "")
        a.ilink_token_file = config.get("token_file", "~/.Neurova/weixin_bot_token")
        a.ilink_media_dir = config.get("media_directory", "")
        a.ilink_message_merge = config.get("message_merge", "false").lower() == "true"
        a.ilink_private_strategy = config.get("private_strategy", "open")
        a.ilink_group_strategy = config.get("group_strategy", "open")
        a.ilink_require_mention = config.get("require_mention", "false").lower() == "true"

        whitelist = config.get("whitelist_users", "")
        a.ilink_whitelist_users = [u.strip() for u in whitelist.split(",") if u.strip()] if whitelist else []

        # 扩展 token_file 路径
        if a.ilink_token_file.startswith("~"):
            a.ilink_token_file = str(Path(a.ilink_token_file).expanduser())

        # 如果已有 token，直接验证
        if a.ilink_bot_token:
            return self._verify_ilink_token()

        # 尝试从文件加载 token
        token_path = Path(a.ilink_token_file)
        if token_path.exists():
            try:
                with open(token_path, "r") as f:
                    a.ilink_bot_token = f.read().strip()
                if a.ilink_bot_token:
                    logger.info("从文件加载 iLink Token: %s", a.ilink_token_file)
                    return self._verify_ilink_token()
            except (OSError, IOError) as e:
                logger.warning("加载 Token 文件失败: %s", e)

        # 首次启动，需要扫码登录
        logger.info("iLink 协议首次启动，需要扫码登录")
        return self._generate_qr_code()

    def _generate_qr_code(self) -> bool:
        """
        生成登录二维码

        返回:
        如果请求成功返回 True (需要用户扫码)
        """
        a = self.adapter
        if not REQUESTS_AVAILABLE:
            logger.info("[iLink 模拟] 生成二维码链接: https://ilink.wechat.bot/qr/xxxxx")
            a._ilink_initialized = True
            return True

        try:
            url = f"{a.ILINK_API_BASE}/auth/qrcode"
            resp = requests.post(url, timeout=10)
            data = resp.json()

            if data.get("success"):
                qr_url = data.get("qr_code_url", "")
                qr_id = data.get("qr_id", "")
                logger.info("iLink 登录二维码: %s", qr_url)
                logger.info("请扫码登录，QR ID: %s", qr_id)

                # 轮询等待扫码
                return self._wait_for_scan(qr_id)
            else:
                logger.error("生成二维码失败: %s", data)
                return False
        except (requests.RequestException, json.JSONDecodeError) as e:
            logger.error("生成二维码异常: %s", e)
            return False

    def _wait_for_scan(self, qr_id: str, timeout: int = 300) -> bool:
        """
        等待用户扫码登录

        参数:
        qr_id: 二维码ID
        timeout: 超时时间 (秒)
        """
        a = self.adapter
        if not REQUESTS_AVAILABLE:
            a._ilink_initialized = True
            return True

        start_time = time.time()
        poll_interval = 3

        while time.time() - start_time < timeout:
            try:
                url = f"{a.ILINK_API_BASE}/auth/status"
                resp = requests.get(url, params={"qr_id": qr_id}, timeout=10)
                data = resp.json()

                status = data.get("status", "")
                if status == "scanned":
                    logger.info("二维码已扫描，等待确认...")
                elif status == "confirmed":
                    a.ilink_bot_token = data.get("bot_token", "")
                    self._save_ilink_token()
                    a._ilink_initialized = True
                    logger.info("iLink 登录成功!")
                    return True
                elif status == "expired":
                    logger.error("二维码已过期，请重新生成")
                    return False

                time.sleep(poll_interval)
            except (requests.RequestException, json.JSONDecodeError) as e:
                logger.error("轮询扫码状态异常: %s", e)
                time.sleep(poll_interval)

        logger.error("扫码登录超时")
        return False

    def _verify_ilink_token(self) -> bool:
        """验证 iLink Token 是否有效"""
        a = self.adapter
        if not REQUESTS_AVAILABLE:
            a._ilink_initialized = True
            return True

        try:
            url = f"{a.ILINK_API_BASE}/auth/verify"
            headers = {"Authorization": f"Bearer {a.ilink_bot_token}"}
            resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()

            if data.get("valid", False):
                a._ilink_initialized = True
                logger.info("iLink Token 验证成功")
                return True
            else:
                logger.error("iLink Token 无效，需要重新登录")
                a.ilink_bot_token = ""
                return False
        except (requests.RequestException, json.JSONDecodeError) as e:
            logger.error("验证 Token 异常: %s", e)
            return False

    def _save_ilink_token(self):
        """保存 iLink Token 到本地文件"""
        a = self.adapter
        if not a.ilink_token_file:
            return

        try:
            token_path = Path(a.ilink_token_file)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(token_path, "w") as f:
                f.write(a.ilink_bot_token)
            logger.info("iLink Token 已保存到: %s", a.ilink_token_file)
        except (OSError, IOError) as e:
            logger.error("保存 Token 失败: %s", e)

    # ============================================================
    # 微信公众号认证
    # ============================================================

    def _authenticate_official(self, config: Dict[str, str]) -> bool:
        """认证微信公众号"""
        a = self.adapter
        a.official_appid = config.get("appid", "")
        a.official_secret = config.get("secret", "")
        a.official_token = config.get("token", "")
        a.official_encoding_aes_key = config.get("encoding_aes_key", "")

        if not a.official_appid or not a.official_secret:
            logger.error("微信公众号认证失败: appid 和 secret 不能为空")
            return False

        return self._refresh_official_token()

    def _refresh_official_token(self) -> bool:
        """刷新微信公众号 access_token"""
        a = self.adapter
        if not REQUESTS_AVAILABLE:
            a._official_initialized = True
            return True

        try:
            url = f"{a.WECHAT_OA_API_BASE}/cgi-bin/token"
            params = {
                "grant_type": "client_credential",
                "appid": a.official_appid,
                "secret": a.official_secret,
            }
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()

            if "access_token" in data:
                a.official_access_token = data["access_token"]
                a.official_token_expire_time = int(time.time()) + data.get("expires_in", 7200) - 60
                a._official_initialized = True
                logger.info("微信公众号认证成功")
                return True
            else:
                logger.error("微信公众号认证失败: %s", data)
                return False
        except Exception as e:
            logger.error("微信公众号认证异常: %s", e)
            return False

    def _ensure_official_token(self) -> bool:
        """确保微信公众号 token 有效"""
        a = self.adapter
        if not a._official_initialized:
            return self._refresh_official_token()
        if int(time.time()) >= a.official_token_expire_time:
            return self._refresh_official_token()
        return True

    # ============================================================
    # 签名验证 (企业微信/公众号回调)
    # ============================================================

    def verify_signature(self, msg_signature: str, timestamp: str, nonce: str, echostr: str = "") -> Optional[str]:
        """
        验证企业微信/公众号回调签名

        返回 echostr 表示验证通过
        """
        a = self.adapter
        if not a.callback_token and not a.official_token:
            return None

        token = a.callback_token or a.official_token
        params = sorted([token, timestamp, nonce])
        sign_str = "".join(params)
        signature = hashlib.sha1(sign_str.encode("utf-8")).hexdigest()

        if signature == msg_signature:
            return echostr
        return None

    # ============================================================
    # 统一 API 请求方法
    # ============================================================

    def _api_request(self, base_url: str, method: str, path: str, params: Dict = None, **kwargs) -> Dict[str, Any]:
        """
        统一的 API 请求方法

        参数:
        base_url: API 基础 URL
        method: HTTP 方法
        path: API 路径
        params: URL 参数
        **kwargs: requests 的其他参数

        返回:
        API 响应数据
        """
        if not REQUESTS_AVAILABLE:
            return {"errcode": -1, "errmsg": "requests 库未安装"}

        url = f"{base_url}{path}"
        kwargs.setdefault("timeout", 10)

        try:
            resp = requests.request(method, url, params=params, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            logger.error("微信 API 请求超时: %s", url)
            return {"errcode": -1, "errmsg": "请求超时"}
        except requests.exceptions.HTTPError as e:
            logger.error("微信 API HTTP 错误: %s", e)
            return {"errcode": -1, "errmsg": f"HTTP 错误: {e.response.status_code}"}
        except Exception as e:
            logger.error("微信 API 请求异常: %s", e)
            return {"errcode": -1, "errmsg": str(e)}
