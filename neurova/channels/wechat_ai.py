"""
微信 AI 生成 Mixin

包含:
1. 文本生成图片 (generate_text_to_image)
2. 图生图 (generate_image_to_image)
3. 文本生成视频 (generate_text_to_video)
4. 图生视频 (generate_image_to_video)
5. 首尾帧生成视频 (generate_keyframe_to_video)
6. 视频生视频 (generate_video_to_video)
7. 工具方法 (_download_url, _save_temp_file, _extract_prompt)
...
"""

import logging
import os
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)


class AIMixin:
    """
    微信 AI 生成 Mixin

    提供:
    - 文生图
    - 图生图
    - 文生视频
    - 图生视频
    - 首尾帧生成视频
    - 视频生视频
    """

    async def generate_text_to_image(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        num_images: int = 1,
        **kwargs,
    ) -> Optional[str]:
        """
        文本生成图片

        参数:
            prompt: 正向提示词
            negative_prompt: 负向提示词
            width: 图片宽度
            height: 图片高度
            num_images: 生成数量

        返回:
            str: media_id (上传到微信后的 ID)
        """
        try:
            # 使用 LLM 生成器
            from neurova.llm.generators import get_image_generator

            generator = get_image_generator()
            if not generator:
                logger.error("Image generator not available")
                return None

            # 生成图片
            image_data = await generator.generate(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                num_images=num_images,
                **kwargs,
            )

            if not image_data:
                logger.error("Image generation failed")
                return None

            # 保存到临时文件并上传
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(image_data)
                temp_path = f.name

            try:
                # 上传到微信
                media_id = await self.upload_media(temp_path, media_type="image")
                return media_id
            finally:
                # 清理临时文件
                os.unlink(temp_path)

        except Exception as e:
            logger.exception("Text-to-image generation error: %s", e)
            return None

    async def generate_image_to_image(
        self,
        image_path: str,
        prompt: str,
        strength: float = 0.75,
        **kwargs,
    ) -> Optional[str]:
        """
        图生图

        参数:
            image_path: 输入图片路径
            prompt: 提示词
            strength: 变化强度 (0-1)

        返回:
            str: media_id
        """
        try:
            # 使用 LLM 生成器
            from neurova.llm.generators import get_image_generator

            generator = get_image_generator()
            if not generator:
                logger.error("Image generator not available")
                return None

            # 读取输入图片
            with open(image_path, "rb") as f:
                image_data = f.read()

            # 生成图片
            result_data = await generator.generate(
                image=image_data,
                prompt=prompt,
                strength=strength,
                **kwargs,
            )

            if not result_data:
                logger.error("Image-to-image generation failed")
                return None

            # 保存到临时文件并上传
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(result_data)
                temp_path = f.name

            try:
                # 上传到微信
                media_id = await self.upload_media(temp_path, media_type="image")
                return media_id
            finally:
                # 清理临时文件
                os.unlink(temp_path)

        except Exception as e:
            logger.exception("Image-to-image generation error: %s", e)
            return None

    async def generate_text_to_video(
        self,
        prompt: str,
        duration: int = 5,
        fps: int = 24,
        **kwargs,
    ) -> Optional[str]:
        """
        文本生成视频

        参数:
            prompt: 提示词
            duration: 视频时长 (秒)
            fps: 帧率

        返回:
            str: media_id
        """
        try:
            # 使用 LLM 生成器
            from neurova.llm.generators import get_video_generator

            generator = get_video_generator()
            if not generator:
                logger.error("Video generator not available")
                return None

            # 生成视频
            video_data = await generator.generate(
                prompt=prompt,
                duration=duration,
                fps=fps,
                **kwargs,
            )

            if not video_data:
                logger.error("Text-to-video generation failed")
                return None

            # 保存到临时文件并上传
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                f.write(video_data)
                temp_path = f.name

            try:
                # 上传到微信
                media_id = await self.upload_media(temp_path, media_type="video")
                return media_id
            finally:
                # 清理临时文件
                os.unlink(temp_path)

        except Exception as e:
            logger.exception("Text-to-video generation error: %s", e)
            return None

    async def generate_image_to_video(
        self,
        image_path: str,
        prompt: str = "",
        duration: int = 5,
        fps: int = 24,
        **kwargs,
    ) -> Optional[str]:
        """
        图生视频

        参数:
            image_path: 输入图片路径
            prompt: 提示词
            duration: 视频时长 (秒)
            fps: 帧率

        返回:
            str: media_id
        """
        try:
            # 使用 LLM 生成器
            from neurova.llm.generators import get_video_generator

            generator = get_video_generator()
            if not generator:
                logger.error("Video generator not available")
                return None

            # 读取输入图片
            with open(image_path, "rb") as f:
                image_data = f.read()

            # 生成视频
            video_data = await generator.generate(
                image=image_data,
                prompt=prompt,
                duration=duration,
                fps=fps,
                **kwargs,
            )

            if not video_data:
                logger.error("Image-to-video generation failed")
                return None

            # 保存到临时文件并上传
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                f.write(video_data)
                temp_path = f.name

            try:
                # 上传到微信
                media_id = await self.upload_media(temp_path, media_type="video")
                return media_id
            finally:
                # 清理临时文件
                os.unlink(temp_path)

        except Exception as e:
            logger.exception("Image-to-video generation error: %s", e)
            return None

    async def generate_keyframe_to_video(
        self,
        start_image_path: str,
        end_image_path: str,
        prompt: str = "",
        duration: int = 5,
        fps: int = 24,
        **kwargs,
    ) -> Optional[str]:
        """
        首尾帧生成视频

        参数:
            start_image_path: 首帧图片路径
            end_image_path: 尾帧图片路径
            prompt: 提示词
            duration: 视频时长 (秒)
            fps: 帧率

        返回:
            str: media_id
        """
        try:
            # 使用 LLM 生成器
            from neurova.llm.generators import get_video_generator

            generator = get_video_generator()
            if not generator:
                logger.error("Video generator not available")
                return None

            # 读取首尾帧图片
            with open(start_image_path, "rb") as f:
                start_image_data = f.read()
            with open(end_image_path, "rb") as f:
                end_image_data = f.read()

            # 生成视频
            video_data = await generator.generate(
                start_image=start_image_data,
                end_image=end_image_data,
                prompt=prompt,
                duration=duration,
                fps=fps,
                **kwargs,
            )

            if not video_data:
                logger.error("Keyframe-to-video generation failed")
                return None

            # 保存到临时文件并上传
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                f.write(video_data)
                temp_path = f.name

            try:
                # 上传到微信
                media_id = await self.upload_media(temp_path, media_type="video")
                return media_id
            finally:
                # 清理临时文件
                os.unlink(temp_path)

        except Exception as e:
            logger.exception("Keyframe-to-video generation error: %s", e)
            return None

    async def generate_video_to_video(
        self,
        video_path: str,
        prompt: str = "",
        duration: int = 5,
        fps: int = 24,
        **kwargs,
    ) -> Optional[str]:
        """
        视频生视频

        参数:
            video_path: 输入视频路径
            prompt: 提示词
            duration: 输出视频时长 (秒)
            fps: 帧率

        返回:
            str: media_id
        """
        try:
            # 使用 LLM 生成器
            from neurova.llm.generators import get_video_generator

            generator = get_video_generator()
            if not generator:
                logger.error("Video generator not available")
                return None

            # 读取输入视频
            with open(video_path, "rb") as f:
                video_data = f.read()

            # 生成视频
            result_data = await generator.generate(
                video=video_data,
                prompt=prompt,
                duration=duration,
                fps=fps,
                **kwargs,
            )

            if not result_data:
                logger.error("Video-to-video generation failed")
                return None

            # 保存到临时文件并上传
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                f.write(result_data)
                temp_path = f.name

            try:
                # 上传到微信
                media_id = await self.upload_media(temp_path, media_type="video")
                return media_id
            finally:
                # 清理临时文件
                os.unlink(temp_path)

        except Exception as e:
            logger.exception("Video-to-video generation error: %s", e)
            return None

    def _download_url(self, url: str) -> Optional[bytes]:
        """
        下载 URL 内容

        参数:
            url: URL 地址

        返回:
            bytes: 文件内容
        """
        try:
            import requests

            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.content
        except Exception as e:
            logger.exception("Download URL error: %s", e)
            return None

    def _save_temp_file(self, data: bytes, suffix: str = ".tmp") -> Optional[str]:
        """
        保存到临时文件

        参数:
            data: 文件数据
            suffix: 文件后缀

        返回:
            str: 临时文件路径
        """
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(data)
                return f.name
        except Exception as e:
            logger.exception("Save temp file error: %s", e)
            return None

    def _extract_prompt(self, text: str) -> str:
        """
        从文本中提取提示词

        参数:
            text: 输入文本

        返回:
            str: 提示词
        """
        # 移除指令前缀
        prefixes = ["画", "生成", "创建", "制作", "画一个", "生成一个"]
        for prefix in prefixes:
            if text.startswith(prefix):
                text = text[len(prefix) :]
                break

        return text.strip()
