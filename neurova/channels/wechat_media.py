"""
微信媒体与用户 Mixin

包含:
1. 用户管理 (get_user_info, _get_wecom_user_info, _get_official_user_info)
2. 媒体上传与下载 (upload_media, _upload_wecom_media, _upload_official_media, _upload_ilink_media,
   download_media, _download_wecom_media, _download_official_media, _download_ilink_media)

由 WeChatAdapter 通过多继承使用，所有属性都来自主类。
"""

import logging
import os
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

# 媒体类型映射
MEDIA_TYPE_MAP = {
    "image": {"type": "image", "suffix": [".jpg", ".jpeg", ".png", ".gif"]},
    "voice": {"type": "voice", "suffix": [".amr", ".mp3"]},
    "video": {"type": "video", "suffix": [".mp4"]},
    "file": {"type": "file", "suffix": []},
}


class MediaMixin:
    """
    微信媒体与用户 Mixin

    提供:
    - 用户信息获取
    - 媒体文件上传
    - 媒体文件下载
    """

    async def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        获取用户信息

        参数:
            user_id: 用户 ID (openid 或 userid)

        返回:
            Dict: 用户信息
        """
        auth_type = self.config.extra.get("auth_type", "wecom")

        if auth_type == "wecom":
            return await self._get_wecom_user_info(user_id)
        elif auth_type == "official":
            return await self._get_official_user_info(user_id)
        else:
            logger.error("Unknown auth type for get_user_info: %s", auth_type)
            return None

    async def _get_wecom_user_info(self, userid: str) -> Optional[Dict[str, Any]]:
        """获取企业微信用户信息"""
        try:
            response = await self._api_request(
                "GET",
                f"/user/get",
                params={"userid": userid},
            )

            if response.get("errcode") == 0:
                return {
                    "userid": response.get("userid"),
                    "name": response.get("name"),
                    "department": response.get("department"),
                    "position": response.get("position"),
                    "mobile": response.get("mobile"),
                    "email": response.get("email"),
                    "avatar": response.get("avatar"),
                    "status": response.get("status"),
                }
            else:
                logger.error("Get WeCom user info failed: %s", response)
                return None

        except Exception as e:
            logger.exception("Get WeCom user info error: %s", e)
            return None

    async def _get_official_user_info(self, openid: str) -> Optional[Dict[str, Any]]:
        """获取公众号用户信息"""
        try:
            response = await self._api_request(
                "GET",
                "/user/info",
                params={"openid": openid, "lang": "zh_CN"},
            )

            if "errcode" not in response:
                return {
                    "openid": response.get("openid"),
                    "nickname": response.get("nickname"),
                    "sex": response.get("sex"),
                    "province": response.get("province"),
                    "city": response.get("city"),
                    "country": response.get("country"),
                    "headimgurl": response.get("headimgurl"),
                    "subscribe_time": response.get("subscribe_time"),
                    "unionid": response.get("unionid"),
                }
            else:
                logger.error("Get official user info failed: %s", response)
                return None

        except Exception as e:
            logger.exception("Get official user info error: %s", e)
            return None

    async def upload_media(
        self,
        file_path: str,
        media_type: str = "image",
    ) -> Optional[str]:
        """
        上传媒体文件

        参数:
            file_path: 文件路径
            media_type: 媒体类型 (image, voice, video, file)

        返回:
            str: media_id
        """
        auth_type = self.config.extra.get("auth_type", "wecom")

        if auth_type == "wecom":
            return await self._upload_wecom_media(file_path, media_type)
        elif auth_type == "official":
            return await self._upload_official_media(file_path, media_type)
        elif auth_type == "ilink":
            return await self._upload_ilink_media(file_path, media_type)
        else:
            logger.error("Unknown auth type for upload_media: %s", auth_type)
            return None

    async def _upload_wecom_media(
        self,
        file_path: str,
        media_type: str,
    ) -> Optional[str]:
        """企业微信媒体上传"""
        try:
            if not os.path.exists(file_path):
                logger.error("File not found: %s", file_path)
                return None

            # 获取 access_token
            token = await self._ensure_wecom_token()

            # 上传文件
            url = f"{WECOM_API_BASE}/media/upload"
            params = {"access_token": token, "type": media_type}

            with open(file_path, "rb") as f:
                files = {"media": (os.path.basename(file_path), f)}
                response = requests.post(url, params=params, files=files, timeout=30)

            response.raise_for_status()
            data = response.json()

            if data.get("errcode") == 0:
                media_id = data.get("media_id")
                logger.info("Media uploaded: %s", media_id)
                return media_id
            else:
                logger.error("Media upload failed: %s", data)
                return None

        except Exception as e:
            logger.exception("WeCom media upload error: %s", e)
            return None

    async def _upload_official_media(
        self,
        file_path: str,
        media_type: str,
    ) -> Optional[str]:
        """公众号媒体上传"""
        try:
            if not os.path.exists(file_path):
                logger.error("File not found: %s", file_path)
                return None

            # 获取 access_token
            token = await self._ensure_official_token()

            # 上传文件
            url = f"{WECHAT_API_BASE}/media/upload"
            params = {"access_token": token, "type": media_type}

            with open(file_path, "rb") as f:
                files = {"media": (os.path.basename(file_path), f)}
                response = requests.post(url, params=params, files=files, timeout=30)

            response.raise_for_status()
            data = response.json()

            if "errcode" not in data:
                media_id = data.get("media_id")
                logger.info("Media uploaded: %s", media_id)
                return media_id
            else:
                logger.error("Media upload failed: %s", data)
                return None

        except Exception as e:
            logger.exception("Official media upload error: %s", e)
            return None

    async def _upload_ilink_media(
        self,
        file_path: str,
        media_type: str,
    ) -> Optional[str]:
        """iLink 媒体上传"""
        # iLink 媒体上传实现
        logger.warning("iLink media upload not implemented")
        return None

    async def download_media(
        self,
        media_id: str,
        save_path: str,
    ) -> bool:
        """
        下载媒体文件

        参数:
            media_id: 媒体 ID
            save_path: 保存路径

        返回:
            bool: 是否成功
        """
        auth_type = self.config.extra.get("auth_type", "wecom")

        if auth_type == "wecom":
            return await self._download_wecom_media(media_id, save_path)
        elif auth_type == "official":
            return await self._download_official_media(media_id, save_path)
        elif auth_type == "ilink":
            return await self._download_ilink_media(media_id, save_path)
        else:
            logger.error("Unknown auth type for download_media: %s", auth_type)
            return False

    async def _download_wecom_media(
        self,
        media_id: str,
        save_path: str,
    ) -> bool:
        """企业微信媒体下载"""
        try:
            # 获取 access_token
            token = await self._ensure_wecom_token()

            # 下载文件
            url = f"{WECOM_API_BASE}/media/get"
            params = {"access_token": token, "media_id": media_id}

            response = requests.get(url, params=params, timeout=30, stream=True)
            response.raise_for_status()

            # 保存文件
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info("Media downloaded to %s", save_path)
            return True

        except Exception as e:
            logger.exception("WeCom media download error: %s", e)
            return False

    async def _download_official_media(
        self,
        media_id: str,
        save_path: str,
    ) -> bool:
        """公众号媒体下载"""
        try:
            # 获取 access_token
            token = await self._ensure_official_token()

            # 下载文件
            url = f"{WECHAT_API_BASE}/media/get"
            params = {"access_token": token, "media_id": media_id}

            response = requests.get(url, params=params, timeout=30, stream=True)
            response.raise_for_status()

            # 保存文件
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info("Media downloaded to %s", save_path)
            return True

        except Exception as e:
            logger.exception("Official media download error: %s", e)
            return False

    async def _download_ilink_media(
        self,
        media_id: str,
        save_path: str,
    ) -> bool:
        """iLink 媒体下载"""
        # iLink 媒体下载实现
        logger.warning("iLink media download not implemented")
        return False

    def get_media_type(self, file_path: str) -> str:
        """
        根据文件扩展名判断媒体类型

        参数:
            file_path: 文件路径

        返回:
            str: 媒体类型 (image, voice, video, file)
        """
        suffix = os.path.splitext(file_path)[1].lower()

        for media_type, info in MEDIA_TYPE_MAP.items():
            if suffix in info["suffix"]:
                return media_type

        return "file"
