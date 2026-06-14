from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

from neurova.channels import ContentType, UnifiedMessage

logger = logging.getLogger(__name__)


class TelegramAIGenerationMixin:
    """Telegram AI generation mixin — text/image → image/video."""

    async def generate_text_to_image(self: Any, prompt: str, **kwargs) -> Optional[bytes]:
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
                return await self._download_url(result.urls[0])
            logger.error("图片生成失败: %s", getattr(result, "error_message", "Unknown error"))
            return None
        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("AI图片生成异常: %s", e)
            return None

    async def generate_image_to_image(self: Any, image_url: str, prompt: str, **kwargs) -> Optional[bytes]:
        try:
            from neurova.llm.generators import GenerationConfig, GeneratorType, get_generator_manager
            manager = get_generator_manager()
            generator = manager.get_generator("image_to_image", kwargs.get("model"))
            if not generator:
                logger.error("未找到图生图的生成器")
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
                return await self._download_url(result.urls[0])
            logger.error("图生图生成失败: %s", getattr(result, "error_message", "Unknown error"))
            return None
        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("图生图生成异常: %s", e)
            return None

    async def generate_text_to_video(self: Any, prompt: str, **kwargs) -> Optional[bytes]:
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
                return await self._download_url(result.urls[0])
            logger.error("视频生成失败: %s", getattr(result, "error_message", "Unknown error"))
            return None
        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("AI视频生成异常: %s", e)
            return None

    async def generate_image_to_video(self: Any, image_url: str, prompt: str, **kwargs) -> Optional[bytes]:
        try:
            from neurova.llm.generators import GenerationConfig, GeneratorType, get_generator_manager
            manager = get_generator_manager()
            generator = manager.get_generator("image_to_video", kwargs.get("model"))
            if not generator:
                logger.error("未找到图生视频的生成器")
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
                return await self._download_url(result.urls[0])
            logger.error("图生视频生成失败: %s", getattr(result, "error_message", "Unknown error"))
            return None
        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("图生视频生成异常: %s", e)
            return None

    async def generate_keyframe_to_video(self: Any, start_url: str, end_url: str, **kwargs) -> Optional[bytes]:
        try:
            from neurova.llm.generators import GenerationConfig, GeneratorType, get_generator_manager
            manager = get_generator_manager()
            generator = manager.get_generator("keyframe_to_video", kwargs.get("model"))
            if not generator:
                logger.error("未找到首尾帧生成视频的生成器")
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
                return await self._download_url(result.urls[0])
            logger.error("首尾帧生成视频失败: %s", getattr(result, "error_message", "Unknown error"))
            return None
        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("首尾帧生成视频异常: %s", e)
            return None

    async def generate_video_to_video(self: Any, video_url: str, prompt: str, **kwargs) -> Optional[bytes]:
        try:
            from neurova.llm.generators import GenerationConfig, GeneratorType, get_generator_manager
            manager = get_generator_manager()
            generator = manager.get_generator("video_to_video", kwargs.get("model"))
            if not generator:
                logger.error("未找到视频生成视频的生成器")
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
                return await self._download_url(result.urls[0])
            logger.error("视频生成失败: %s", getattr(result, "error_message", "Unknown error"))
            return None
        except ImportError:
            logger.error("GeneratorManager 模块不可用")
            return None
        except Exception as e:
            logger.exception("视频生成异常: %s", e)
            return None

    def _extract_prompt(self: Any, content: str) -> str:
        patterns = [
            r"生成?\s*(?:一张|个)?\s*(?:图片?|画).*?[:：]?\s*(.+)",
            r"画.*?[:：]?\s*(.+)",
            r"生成?\s*(?:一段|个)?\s*视频.*?[:：]?\s*(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return content

    async def handle_ai_generation(self: Any, message: UnifiedMessage) -> bool:
        content = message.content.lower()
        has_image = message.content_type == ContentType.IMAGE
        has_video = message.content_type == ContentType.VIDEO
        image_url = message.file_url or message.metadata.get("file_url", "")
        video_url = message.file_url or message.metadata.get("file_url", "")

        if "生成图片" in content or "画一张" in content or "生成一张图片" in content:
            if has_image:
                prompt = self._extract_prompt(message.content) or ""
                if image_url:
                    self._send_text_message(message.chat_id, "正在生成图片，请稍候...")
                    gen_image_data = await self.generate_image_to_image(image_url, prompt)
                    if gen_image_data:
                        temp_path = await self._save_temp_file(gen_image_data, "png")
                        if temp_path:
                            if self._send_photo(message.chat_id, temp_path):
                                os.unlink(temp_path)
                                return True
                            os.unlink(temp_path)
                    self._send_text_message(message.chat_id, "图片生成失败")
                    return False
            else:
                prompt = self._extract_prompt(message.content)
                if prompt:
                    self._send_text_message(message.chat_id, "正在生成图片，请稍候...")
                    image_data = await self.generate_text_to_image(prompt)
                    if image_data:
                        temp_path = await self._save_temp_file(image_data, "png")
                        if temp_path:
                            if self._send_photo(message.chat_id, temp_path):
                                os.unlink(temp_path)
                                return True
                            os.unlink(temp_path)
                    self._send_text_message(message.chat_id, "图片生成失败")
                    return False

        elif has_image and (
            "图生图" in content or "以图生图" in content or "生成相似图片" in content or "生成新图片" in content
        ):
            prompt = self._extract_prompt(message.content) or ""
            if image_url:
                self._send_text_message(message.chat_id, "正在生成图片，请稍候...")
                image_data = await self.generate_image_to_image(image_url, prompt)
                if image_data:
                    temp_path = await self._save_temp_file(image_data, "png")
                    if temp_path:
                        if self._send_photo(message.chat_id, temp_path):
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                self._send_text_message(message.chat_id, "图片生成失败")
                return False

        elif has_image and (
            "图生视频" in content or "图片转视频" in content or "让图片动起来" in content or "图片生成视频" in content
        ):
            prompt = self._extract_prompt(message.content) or ""
            if image_url:
                self._send_text_message(message.chat_id, "正在生成视频，请稍候...")
                video_data = await self.generate_image_to_video(image_url, prompt)
                if video_data:
                    temp_path = await self._save_temp_file(video_data, "mp4")
                    if temp_path:
                        if self._send_video(message.chat_id, temp_path):
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                self._send_text_message(message.chat_id, "视频生成失败")
                return False

        elif ("首尾帧" in content or "首帧到尾帧" in content or "首尾帧生成视频" in content) and message.metadata.get(
            "images_count", 0
        ) >= 2:
            start_url = message.metadata.get("first_image_url", "")
            end_url = message.metadata.get("last_image_url", "")
            if start_url and end_url:
                self._send_text_message(message.chat_id, "正在生成视频，请稍候...")
                video_data = await self.generate_keyframe_to_video(start_url, end_url)
                if video_data:
                    temp_path = await self._save_temp_file(video_data, "mp4")
                    if temp_path:
                        if self._send_video(message.chat_id, temp_path):
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                self._send_text_message(message.chat_id, "视频生成失败")
                return False

        elif has_video and (
            "视频生成" in content or "视频风格" in content or "修改视频" in content or "视频转视频" in content
        ):
            prompt = self._extract_prompt(message.content) or ""
            if video_url:
                self._send_text_message(message.chat_id, "正在生成视频，请稍候...")
                video_data = await self.generate_video_to_video(video_url, prompt)
                if video_data:
                    temp_path = await self._save_temp_file(video_data, "mp4")
                    if temp_path:
                        if self._send_video(message.chat_id, temp_path):
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                self._send_text_message(message.chat_id, "视频生成失败")
                return False

        elif "生成视频" in content or "生成一段视频" in content:
            prompt = self._extract_prompt(message.content)
            if prompt:
                self._send_text_message(message.chat_id, "正在生成视频，请稍候...")
                video_data = await self.generate_text_to_video(prompt)
                if video_data:
                    temp_path = await self._save_temp_file(video_data, "mp4")
                    if temp_path:
                        if self._send_video(message.chat_id, temp_path):
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                self._send_text_message(message.chat_id, "视频生成失败")
                return False

        return False
