"""
微信 AI 生成 Mixin

处理文本/图片生成图片、视频等 AI 生成能力。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WeChatAIGenerationMixin:
    """微信 AI 生成 Mixin — 文生图/图生图/文生视频/图生视频/首尾帧生视频/视频生视频"""

    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    async def generate_text_to_image(self, prompt: str, **kwargs) -> Optional[bytes]:
        """生成AI图片

        参数:
            prompt: 图片描述文本
            **kwargs: 其他生成参数

        返回:
            成功返回图片二进制数据，失败返回 None
        """
        try:
            from neurova.llm.generators import GenerationConfig, GeneratorType, get_generator_manager

            manager = get_generator_manager()
            generator = manager.get_generator("text_to_image", kwargs.get("model"))
            if not generator:
                logger.error("未找到文本生成图片的生成器")
                return None

            config = GenerationConfig(
                type=GeneratorType.TEXT_TO_IMAGE,
                model=kwargs.get("model", "wanx-v1"),
                prompt=prompt,
                width=kwargs.get("width", 1024),
                height=kwargs.get("height", 1024),
                num_outputs=kwargs.get("num_outputs", 1),
                negative_prompt=kwargs.get("negative_prompt", ""),
                style=kwargs.get("style", ""),
            )

            result = await generator.generate(config)

            if result.success and result.urls:
                return await self.adapter._download_url(result.urls[0])
            else:
                logger.error(
                    f"图片生成失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}"
                )
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("AI图片生成异常: %s", e)
            return None

    async def generate_image_to_image(self, image_url: str, prompt: str, **kwargs) -> Optional[bytes]:
        """图生图 - 基于参考图片生成新图片

        参数:
            image_url: 参考图片URL
            prompt: 图片描述文本
            **kwargs: 其他生成参数

        返回:
            成功返回图片二进制数据，失败返回 None
        """
        try:
            from neurova.llm.generators import GenerationConfig, GeneratorType, get_generator_manager

            manager = get_generator_manager()
            generator = manager.get_generator("image_to_image", kwargs.get("model"))
            if not generator:
                logger.error("未找到图生图的生成器")
                return None

            image_data = await self.adapter._download_url(image_url)
            if not image_data:
                logger.error("下载参考图片失败: %s", image_url)
                return None

            config = GenerationConfig(
                type=GeneratorType.IMAGE_TO_IMAGE,
                model=kwargs.get("model", "sd-img2img-xl"),
                prompt=prompt,
                image_url=image_url,
                width=kwargs.get("width", 1024),
                height=kwargs.get("height", 1024),
                strength=kwargs.get("strength", 0.7),
                guidance_scale=kwargs.get("guidance_scale", 7.5),
                num_outputs=kwargs.get("num_outputs", 1),
                negative_prompt=kwargs.get("negative_prompt", ""),
                style=kwargs.get("style", ""),
            )

            result = await generator.generate(config)

            if result.success and result.urls:
                return await self.adapter._download_url(result.urls[0])
            else:
                logger.error(
                    f"图生图生成失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}"
                )
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("图生图生成异常: %s", e)
            return None

    async def generate_text_to_video(self, prompt: str, **kwargs) -> Optional[bytes]:
        """生成AI视频

        参数:
            prompt: 视频描述文本
            **kwargs: 其他生成参数

        返回:
            成功返回视频二进制数据，失败返回 None
        """
        try:
            from neurova.llm.generators import GenerationConfig, GeneratorType, get_generator_manager

            manager = get_generator_manager()
            generator = manager.get_generator("text_to_video", kwargs.get("model"))
            if not generator:
                logger.error("未找到文本生成视频的生成器")
                return None

            config = GenerationConfig(
                type=GeneratorType.TEXT_TO_VIDEO,
                model=kwargs.get("model", "kling-v1"),
                prompt=prompt,
                width=kwargs.get("width", 1280),
                height=kwargs.get("height", 720),
                duration=kwargs.get("duration", 5),
                fps=kwargs.get("fps", 30),
                num_outputs=kwargs.get("num_outputs", 1),
                negative_prompt=kwargs.get("negative_prompt", ""),
            )

            result = await generator.generate(config)

            if result.success and result.urls:
                return await self.adapter._download_url(result.urls[0])
            else:
                logger.error(
                    f"视频生成失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}"
                )
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("AI视频生成异常: %s", e)
            return None

    async def generate_image_to_video(self, image_url: str, prompt: str, **kwargs) -> Optional[bytes]:
        """图生视频 - 基于图片生成视频

        参数:
            image_url: 参考图片URL
            prompt: 视频描述文本
            **kwargs: 其他生成参数

        返回:
            成功返回视频二进制数据，失败返回 None
        """
        try:
            from neurova.llm.generators import GenerationConfig, GeneratorType, get_generator_manager

            manager = get_generator_manager()
            generator = manager.get_generator("image_to_video", kwargs.get("model"))
            if not generator:
                logger.error("未找到图生视频的生成器")
                return None

            image_data = await self.adapter._download_url(image_url)
            if not image_data:
                logger.error("下载参考图片失败: %s", image_url)
                return None

            config = GenerationConfig(
                type=GeneratorType.IMAGE_TO_VIDEO,
                model=kwargs.get("model", "kling-v1-video"),
                prompt=prompt,
                image_url=image_url,
                width=kwargs.get("width", 1280),
                height=kwargs.get("height", 720),
                duration=kwargs.get("duration", 5),
                fps=kwargs.get("fps", 30),
                num_outputs=kwargs.get("num_outputs", 1),
                negative_prompt=kwargs.get("negative_prompt", ""),
            )

            result = await generator.generate(config)

            if result.success and result.urls:
                return await self.adapter._download_url(result.urls[0])
            else:
                logger.error(
                    f"图生视频生成失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}"
                )
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("图生视频生成异常: %s", e)
            return None

    async def generate_keyframe_to_video(self, start_url: str, end_url: str, **kwargs) -> Optional[bytes]:
        """首尾帧生视频 - 基于起始和结束帧生成视频

        参数:
            start_url: 起始帧图片URL
            end_url: 结束帧图片URL
            **kwargs: 其他生成参数

        返回:
            成功返回视频二进制数据，失败返回 None
        """
        try:
            from neurova.llm.generators import GenerationConfig, GeneratorType, get_generator_manager

            manager = get_generator_manager()
            generator = manager.get_generator("keyframe_to_video", kwargs.get("model"))
            if not generator:
                logger.error("未找到首尾帧生成视频的生成器")
                return None

            start_data = await self.adapter._download_url(start_url)
            end_data = await self.adapter._download_url(end_url)
            if not start_data or not end_data:
                logger.error("下载首尾帧失败")
                return None

            config = GenerationConfig(
                type=GeneratorType.KEYFRAME_TO_VIDEO,
                model=kwargs.get("model", "kling-v1-keyframe"),
                prompt=kwargs.get("prompt", ""),
                start_image_url=start_url,
                end_image_url=end_url,
                width=kwargs.get("width", 1280),
                height=kwargs.get("height", 720),
                duration=kwargs.get("duration", 5),
                fps=kwargs.get("fps", 30),
                num_outputs=kwargs.get("num_outputs", 1),
                negative_prompt=kwargs.get("negative_prompt", ""),
            )

            result = await generator.generate(config)

            if result.success and result.urls:
                return await self.adapter._download_url(result.urls[0])
            else:
                logger.error(
                    f"首尾帧生成视频失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}"
                )
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("首尾帧生成视频异常: %s", e)
            return None

    async def generate_video_to_video(self, video_url: str, prompt: str, **kwargs) -> Optional[bytes]:
        """视频生视频 - 基于参考视频生成新视频

        参数:
            video_url: 参考视频URL
            prompt: 视频描述文本
            **kwargs: 其他生成参数

        返回:
            成功返回视频二进制数据，失败返回 None
        """
        try:
            from neurova.llm.generators import GenerationConfig, GeneratorType, get_generator_manager

            manager = get_generator_manager()
            generator = manager.get_generator("video_to_video", kwargs.get("model"))
            if not generator:
                logger.error("未找到视频生成视频的生成器")
                return None

            video_data = await self.adapter._download_url(video_url)
            if not video_data:
                logger.error("下载参考视频失败: %s", video_url)
                return None

            config = GenerationConfig(
                type=GeneratorType.VIDEO_TO_VIDEO,
                model=kwargs.get("model", "kling-v1-v2v"),
                prompt=prompt,
                video_url=video_url,
                width=kwargs.get("width", 1280),
                height=kwargs.get("height", 720),
                duration=kwargs.get("duration", 5),
                fps=kwargs.get("fps", 30),
                strength=kwargs.get("strength", 0.75),
                guidance_scale=kwargs.get("guidance_scale", 7.5),
                num_outputs=kwargs.get("num_outputs", 1),
                negative_prompt=kwargs.get("negative_prompt", ""),
                style=kwargs.get("style", "realistic"),
            )

            result = await generator.generate(config)

            if result.success and result.urls:
                return await self.adapter._download_url(result.urls[0])
            else:
                logger.error(
                    f"视频生成失败: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}"
                )
                return None

        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("视频生成异常: %s", e)
            return None
