"""
飞书媒体文件 Mixin

提供媒体文件上传、下载和处理功能。
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 媒体类型映射
MEDIA_TYPE_MAP = {
    "image": {"type": "image", "suffix": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]},
    "audio": {"type": "audio", "suffix": [".mp3", ".wav", ".ogg", ".m4a"]},
    "video": {"type": "video", "suffix": [".mp4", ".avi", ".mov", ".wmv"]},
    "file": {"type": "file", "suffix": []},
}


class MediaMixin:
    """
    飞书媒体文件 Mixin

    提供:
    - 图片上传 (获取 image_key)
    - 文件上传 (获取 file_key)
    - 媒体文件下载
    """

    async def upload_image(
        self,
        image_path: str,
        image_type: str = "message",
    ) -> Optional[str]:
        """
        上传图片

        参数:
            image_path: 图片路径
            image_type: 图片类型 (message 或 avatar)

        返回:
            str: image_key
        """
        try:
            import os

            if not os.path.exists(image_path):
                logger.error("Image file not found: %s", image_path)
                return None

            # 确定 MIME 类型
            suffix = os.path.splitext(image_path)[1].lower()
            mime_type = "image/jpeg"
            if suffix == ".png":
                mime_type = "image/png"
            elif suffix == ".gif":
                mime_type = "image/gif"

            # 读取文件
            with open(image_path, "rb") as f:
                file_content = f.read()

            # 上传图片
            response = self._feishu_post(
                "/im/v1/images",
                data={"image_type": image_type},
                files={"image": (os.path.basename(image_path), file_content, mime_type)},
            )

            if response.get("code") == 0:
                image_key = response.get("data", {}).get("image_key")
                logger.info("Image uploaded: %s", image_key)
                return image_key
            else:
                logger.error("Image upload failed: %s", response)
                return None

        except Exception as e:
            logger.exception("Image upload error: %s", e)
            return None

    async def upload_file(
        self,
        file_path: str,
        file_type: str = "stream",
    ) -> Optional[str]:
        """
        上传文件

        参数:
            file_path: 文件路径
            file_type: 文件类型 (opus, mp4, pdf, doc, xls, ppt, stream)

        返回:
            str: file_key
        """
        try:
            import mimetypes
            import os

            if not os.path.exists(file_path):
                logger.error("File not found: %s", file_path)
                return None

            # 确定文件类型
            os.path.splitext(file_path)[1].lower()
            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type:
                mime_type = "application/octet-stream"

            # 读取文件
            with open(file_path, "rb") as f:
                file_content = f.read()

            # 上传文件
            response = self._feishu_post(
                "/im/v1/files",
                data={
                    "file_type": file_type,
                    "file_name": os.path.basename(file_path),
                },
                files={"file": (os.path.basename(file_path), file_content, mime_type)},
            )

            if response.get("code") == 0:
                file_key = response.get("data", {}).get("file_key")
                logger.info("File uploaded: %s", file_key)
                return file_key
            else:
                logger.error("File upload failed: %s", response)
                return None

        except Exception as e:
            logger.exception("File upload error: %s", e)
            return None

    async def download_media(
        self,
        message_id: str,
        file_key: str,
        save_path: str,
    ) -> bool:
        """
        下载媒体文件

        参数:
            message_id: 消息 ID
            file_key: 文件 key
            save_path: 保存路径

        返回:
            bool: 是否成功
        """
        try:
            response = self._feishu_get(
                f"/im/v1/messages/{message_id}/resources/{file_key}",
                params={"type": "file"},
            )

            if response.get("code") == 0:
                # 保存文件
                import os

                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(response.get("data", b""))
                logger.info("Media downloaded to %s", save_path)
                return True
            else:
                logger.error("Media download failed: %s", response)
                return False

        except Exception as e:
            logger.exception("Media download error: %s", e)
            return False

    def get_media_type(self, file_path: str) -> str:
        """
        根据文件扩展名判断媒体类型

        参数:
            file_path: 文件路径

        返回:
            str: 媒体类型 (image, audio, video, file)
        """
        import os

        suffix = os.path.splitext(file_path)[1].lower()

        for media_type, info in MEDIA_TYPE_MAP.items():
            if suffix in info["suffix"]:
                return media_type

        return "file"
