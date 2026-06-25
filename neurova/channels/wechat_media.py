"""
微信媒体上传/下载 Mixin

处理企业微信、iLink、微信公众号三种模式的媒体文件操作。
"""
from __future__ import annotations

import json
from neurova.core.logger import get_logger
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class WeChatMediaMixin:
    """微信媒体 Mixin — 上传 / 下载 / 临时文件"""

    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    # ============================================================
    # 媒体上传
    # ============================================================

    def upload_media(
        self, file_path: str, media_type: str = "image", title: str = "", description: str = ""
    ) -> Optional[str]:
        """
        上传媒体文件到微信服务器

        参数:
        file_path: 媒体文件路径
        media_type: 媒体类型 (image/voice/video/file)
        title: 视频标题 (仅视频类型需要)
        description: 视频描述 (仅视频类型需要)

        返回:
        成功返回 media_id，失败返回 None
        """
        if self.adapter.mode == "official":
            return self._upload_official_media(file_path, media_type)
        elif self.adapter.mode == "ilink":
            return self._upload_ilink_media(file_path, media_type)
        else:
            return self._upload_wecom_media(file_path, media_type, title, description)

    def _upload_wecom_media(
        self, file_path: str, media_type: str, title: str = "", description: str = ""
    ) -> Optional[str]:
        """上传媒体文件到企业微信"""
        if not self.adapter._ensure_wecom_token():
            logger.error("企业微信 Token 获取失败")
            return None

        if not REQUESTS_AVAILABLE:
            logger.info("[企微模拟] 上传媒体: %s, 类型: %s", file_path, media_type)
            return f"mock_media_id_{int(time.time())}"

        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            logger.error("媒体文件不存在: %s", file_path)
            return None

        try:
            a = self.adapter
            url = f"{a.WECOM_API_BASE}/cgi-bin/media/upload"
            params = {
                "access_token": a.access_token,
                "type": media_type,
            }

            with open(file_path_obj, "rb") as f:
                files = {"media": (file_path_obj.name, f)}

                if media_type == "video":
                    data = {
                        "description": json.dumps(
                            {
                                "title": title or file_path_obj.stem,
                                "introduction": description or "",
                            }
                        )
                    }
                    resp = requests.post(url, params=params, files=files, data=data, timeout=30)
                else:
                    resp = requests.post(url, params=params, files=files, timeout=30)

            result = resp.json()

            if result.get("errcode") == 0:
                media_id = result.get("media_id")
                logger.info("企业微信媒体上传成功: %s", media_id)
                return media_id
            else:
                logger.error("企业微信媒体上传失败: %s", result)
                return None
        except requests.exceptions.Timeout:
            logger.error("媒体上传超时: %s", file_path)
            return None
        except requests.exceptions.HTTPError as e:
            logger.error("媒体上传 HTTP 错误: %s", e)
            return None
        except IOError as e:
            logger.error("读取媒体文件失败: %s", e)
            return None
        except Exception as e:
            logger.error("媒体上传异常: %s", e)
            return None

    def _upload_official_media(self, file_path: str, media_type: str) -> Optional[str]:
        """上传媒体文件到微信公众号"""
        if not self.adapter._ensure_official_token():
            logger.error("微信公众号 Token 获取失败")
            return None

        if not REQUESTS_AVAILABLE:
            logger.info("[公众号模拟] 上传媒体: %s, 类型: %s", file_path, media_type)
            return f"mock_official_media_id_{int(time.time())}"

        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            logger.error("媒体文件不存在: %s", file_path)
            return None

        try:
            a = self.adapter
            url = f"{a.WECHAT_OA_API_BASE}/cgi-bin/media/upload"
            params = {
                "access_token": a.official_access_token,
                "type": media_type,
            }

            with open(file_path_obj, "rb") as f:
                files = {"media": (file_path_obj.name, f)}
                resp = requests.post(url, params=params, files=files, timeout=30)

            result = resp.json()

            if result.get("errcode") == 0:
                media_id = result.get("media_id")
                logger.info("微信公众号媒体上传成功: %s", media_id)
                return media_id
            else:
                logger.error("微信公众号媒体上传失败: %s", result)
                return None
        except Exception as e:
            logger.error("微信公众号媒体上传异常: %s", e)
            return None

    def _upload_ilink_media(self, file_path: str, media_type: str) -> Optional[str]:
        """上传媒体文件到 iLink"""
        a = self.adapter
        if not a._ilink_initialized:
            logger.error("iLink 未初始化")
            return None

        if not REQUESTS_AVAILABLE:
            logger.info("[iLink 模拟] 上传媒体: %s, 类型: %s", file_path, media_type)
            return f"mock_ilink_media_id_{int(time.time())}"

        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            logger.error("媒体文件不存在: %s", file_path)
            return None

        try:
            url = f"{a.ILINK_API_BASE}/media/upload"
            headers = {"Authorization": f"Bearer {a.ilink_bot_token}"}

            with open(file_path_obj, "rb") as f:
                files = {"file": (file_path_obj.name, f)}
                data = {"type": media_type}
                resp = requests.post(url, headers=headers, data=data, files=files, timeout=30)

            result = resp.json()

            if result.get("success"):
                media_id = result.get("media_id")
                logger.info("iLink 媒体上传成功: %s", media_id)
                return media_id
            else:
                logger.error("iLink 媒体上传失败: %s", result)
                return None
        except Exception as e:
            logger.error("iLink 媒体上传异常: %s", e)
            return None

    # ============================================================
    # 媒体下载
    # ============================================================

    def download_media(self, media_id: str, save_path: str = "") -> Optional[bytes]:
        """
        从微信服务器下载媒体文件

        参数:
        media_id: 媒体文件 ID
        save_path: 保存路径 (为空则返回二进制数据)

        返回:
        成功返回二进制数据 (或保存后返回数据)，失败返回 None
        """
        if self.adapter.mode == "official":
            return self._download_official_media(media_id, save_path)
        elif self.adapter.mode == "ilink":
            return self._download_ilink_media(media_id, save_path)
        else:
            return self._download_wecom_media(media_id, save_path)

    def _download_wecom_media(self, media_id: str, save_path: str = "") -> Optional[bytes]:
        """从企业微信下载媒体文件"""
        if not self.adapter._ensure_wecom_token():
            logger.error("企业微信 Token 获取失败")
            return None

        if not REQUESTS_AVAILABLE:
            logger.info("[企微模拟] 下载媒体: %s", media_id)
            return b"mock_media_data"

        try:
            a = self.adapter
            url = f"{a.WECOM_API_BASE}/cgi-bin/media/get"
            params = {
                "access_token": a.access_token,
                "media_id": media_id,
            }

            resp = requests.get(url, params=params, timeout=30, stream=True)

            content_type = resp.headers.get("Content-Type", "")

            if "application/json" in content_type:
                result = resp.json()
                logger.error("企业微信媒体下载失败: %s", result)
                return None

            media_data = resp.content

            if save_path:
                save_path_obj = Path(save_path)
                save_path_obj.parent.mkdir(parents=True, exist_ok=True)
                with open(save_path_obj, "wb") as f:
                    f.write(media_data)
                logger.info("企业微信媒体已保存: %s", save_path)

            return media_data
        except requests.exceptions.Timeout:
            logger.error("媒体下载超时: %s", media_id)
            return None
        except requests.exceptions.HTTPError as e:
            logger.error("媒体下载 HTTP 错误: %s", e)
            return None
        except IOError as e:
            logger.error("保存媒体文件失败: %s", e)
            return None
        except Exception as e:
            logger.error("媒体下载异常: %s", e)
            return None

    def _download_official_media(self, media_id: str, save_path: str = "") -> Optional[bytes]:
        """从微信公众号下载媒体文件"""
        if not self.adapter._ensure_official_token():
            logger.error("微信公众号 Token 获取失败")
            return None

        if not REQUESTS_AVAILABLE:
            logger.info("[公众号模拟] 下载媒体: %s", media_id)
            return b"mock_official_media_data"

        try:
            a = self.adapter
            url = f"{a.WECHAT_OA_API_BASE}/cgi-bin/media/get"
            params = {
                "access_token": a.official_access_token,
                "media_id": media_id,
            }

            resp = requests.get(url, params=params, timeout=30, stream=True)

            content_type = resp.headers.get("Content-Type", "")

            if "application/json" in content_type:
                result = resp.json()
                logger.error("微信公众号媒体下载失败: %s", result)
                return None

            media_data = resp.content

            if save_path:
                save_path_obj = Path(save_path)
                save_path_obj.parent.mkdir(parents=True, exist_ok=True)
                with open(save_path_obj, "wb") as f:
                    f.write(media_data)
                logger.info("微信公众号媒体已保存: %s", save_path)

            return media_data
        except Exception as e:
            logger.error("微信公众号媒体下载异常: %s", e)
            return None

    def _download_ilink_media(self, media_id: str, save_path: str = "") -> Optional[bytes]:
        """从 iLink 下载媒体文件"""
        a = self.adapter
        if not a._ilink_initialized:
            logger.error("iLink 未初始化")
            return None

        if not REQUESTS_AVAILABLE:
            logger.info("[iLink 模拟] 下载媒体: %s", media_id)
            return b"mock_ilink_media_data"

        try:
            url = f"{a.ILINK_API_BASE}/media/get"
            headers = {"Authorization": f"Bearer {a.ilink_bot_token}"}
            params = {"media_id": media_id}

            resp = requests.get(url, headers=headers, params=params, timeout=30, stream=True)
            result = resp.json()

            if not result.get("success"):
                logger.error("iLink 媒体下载失败: %s", result)
                return None

            media_url = result.get("url")
            if not media_url:
                logger.error("iLink 媒体 URL 为空")
                return None

            media_resp = requests.get(media_url, timeout=30, stream=True)
            media_data = media_resp.content

            if save_path:
                save_path_obj = Path(save_path)
                save_path_obj.parent.mkdir(parents=True, exist_ok=True)
                with open(save_path_obj, "wb") as f:
                    f.write(media_data)
                logger.info("iLink 媒体已保存: %s", save_path)

            return media_data
        except Exception as e:
            logger.error("iLink 媒体下载异常: %s", e)
            return None

    # ============================================================
    # 辅助方法
    # ============================================================

    async def _download_url(self, url: str, timeout: int = 60) -> Optional[bytes]:
        """下载URL内容

        参数:
            url: 目标URL
            timeout: 超时时间（秒）

        返回:
            成功返回二进制数据，失败返回 None
        """
        if HTTPX_AVAILABLE:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(url)
                    if response.status_code == 200:
                        return response.content
                    else:
                        logger.error("下载失败 HTTP %s: %s", response.status_code, url)
                        return None
            except Exception as e:
                logger.error("httpx下载异常: %s", e)
                return None
        elif REQUESTS_AVAILABLE:
            try:
                response = requests.get(url, timeout=timeout)
                if response.status_code == 200:
                    return response.content
                else:
                    logger.error("下载失败 HTTP %s: %s", response.status_code, url)
                    return None
            except Exception as e:
                logger.error("requests下载异常: %s", e)
                return None
        else:
            logger.error("无可用的HTTP客户端")
            return None

    async def _save_temp_file(self, data: bytes, extension: str) -> Optional[str]:
        """保存临时文件

        参数:
            data: 文件数据
            extension: 文件扩展名

        返回:
            成功返回文件路径，失败返回 None
        """
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{extension}") as f:
                f.write(data)
                temp_path = f.name
            logger.info("临时文件已保存: %s", temp_path)
            return temp_path
        except Exception as e:
            logger.error("保存临时文件失败: %s", e)
            return None
