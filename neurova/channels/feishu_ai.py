"""
飞书 AI 生成 Mixin

提供文生图、图生图、视频生成等 AI 能力。
"""

import logging
import os
import tempfile
from typing import Generator, Optional

logger = logging.getLogger(__name__)


class AIMixin:
    """
    飞书 AI 生成 Mixin

    提供:
    - 文生图 (Text-to-Image)
    - 图生图 (Image-to-Image)
    - 视频生成 (Text-to-Video)
    - AI 对话 (Chat)
    """

    async def generate_image(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        num_images: int = 1,
        **kwargs,
    ) -> Optional[str]:
        """
        文生图

        参数:
            prompt: 正向提示词
            negative_prompt: 负向提示词
            width: 图片宽度
            height: 图片高度
            num_images: 生成数量

        返回:
            str: image_key (上传到飞书后的 key)
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
                # 上传到飞书
                image_key = await self.upload_image(temp_path)
                return image_key
            finally:
                # 清理临时文件
                os.unlink(temp_path)

        except Exception as e:
            logger.exception("Image generation error: %s", e)
            return None

    async def generate_video(
        self,
        prompt: str,
        duration: int = 5,
        fps: int = 24,
        **kwargs,
    ) -> Optional[str]:
        """
        视频生成

        参数:
            prompt: 提示词
            duration: 视频时长 (秒)
            fps: 帧率

        返回:
            str: file_key (上传到飞书后的 key)
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
                logger.error("Video generation failed")
                return None

            # 保存到临时文件并上传
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                f.write(video_data)
                temp_path = f.name

            try:
                # 上传到飞书
                file_key = await self.upload_file(temp_path, file_type="mp4")
                return file_key
            finally:
                # 清理临时文件
                os.unlink(temp_path)

        except Exception as e:
            logger.exception("Video generation error: %s", e)
            return None

    async def ai_chat(
        self,
        messages: list,
        model: str = "gpt-3.5-turbo",
        stream: bool = False,
        **kwargs,
    ) -> Optional[str]:
        """
        AI 对话

        参数:
            messages: 消息列表
            model: 模型名称
            stream: 是否流式

        返回:
            str: 回复内容
        """
        try:
            from neurova.llm.multi_model_client import get_multi_model_client

            client = get_multi_model_client()
            if not client:
                logger.error("LLM client not available")
                return None

            # 调用 LLM
            response = await client.generate(
                messages=messages,
                model=model,
                stream=stream,
                **kwargs,
            )

            if stream:
                # 流式返回
                return response
            else:
                # 非流式返回
                return response.get("content", "")

        except Exception as e:
            logger.exception("AI chat error: %s", e)
            return None

    async def ai_chat_stream(
        self,
        messages: list,
        model: str = "gpt-3.5-turbo",
        **kwargs,
    ) -> Generator[str, None, None]:
        """
        AI 流式对话

        参数:
            messages: 消息列表
            model: 模型名称

        生成:
            str: 流式内容片段
        """
        try:
            from neurova.llm.multi_model_client import get_multi_model_client

            client = get_multi_model_client()
            if not client:
                logger.error("LLM client not available")
                return

            # 流式调用 LLM
            async for chunk in client.generate_stream(
                messages=messages,
                model=model,
                **kwargs,
            ):
                yield chunk

        except Exception as e:
            logger.exception("AI chat stream error: %s", e)
