"""
首尾帧生成视频生成器
支持使用首帧和尾帧生成中间过渡视频
"""

import asyncio
import base64
from neurova.core.logger import get_logger
import time
from typing import Any, Dict, Optional

try:
    import aiohttp
except ImportError:
    aiohttp = None

from neurova.llm.generators.base import BaseGenerator, GenerationConfig, GenerationResult, GeneratorType

logger = get_logger(__name__)


class KeyframeToVideoGenerator(BaseGenerator):
    """
    首尾帧生成视频生成器

    支持使用首帧和尾帧生成中间过渡视频：
    - 可灵 (Kling)
    - Pika
    - 通用 API
    """

    # 支持的服务商列表
    _SUPPORTED_PROVIDERS = {
        "kling": {
            "name": "可灵",
            "default_model": "kling-v1",
            "supported_durations": [5, 10, 15],
            "requires_start_image": True,
            "requires_end_image": True,
        },
        "pika": {
            "name": "Pika",
            "default_model": "pika-v1",
            "supported_durations": [3, 5],
            "requires_start_image": True,
            "requires_end_image": True,
        },
        "generic": {
            "name": "通用 API",
            "default_model": "generic",
            "supported_durations": [5, 10],
            "requires_start_image": True,
            "requires_end_image": True,
        },
    }

    def __init__(
        self,
        generator_id: str = "keyframe_to_video",
        api_key: str = "",
        base_url: str = "",
        provider: str = "generic",
        **kwargs,
    ):
        """初始化首尾帧生成视频生成器

        Args:
            generator_id: 生成器唯一标识符
            api_key: API 密钥
            base_url: API 基础 URL
            provider: 服务商类型
            **kwargs: 其他配置参数
        """
        super().__init__(generator_id=generator_id, generator_type=GeneratorType.KEYFRAME_TO_VIDEO, **kwargs)
        self.api_key = api_key
        self.base_url = base_url
        self.provider = provider
        self._initialized = True

        self.logger.info("KeyframeToVideoGenerator 初始化完成: provider=%s", provider)

    def supports(self, config: GenerationConfig) -> bool:
        """检查是否支持指定的生成配置

        Args:
            config: 生成配置

        Returns:
            是否支持
        """
        # 检查是否为首尾帧生成视频类型
        if config.type != GeneratorType.KEYFRAME_TO_VIDEO:
            return False

        # 检查服务商是否支持
        if config.extra_params.get("provider") in self._SUPPORTED_PROVIDERS:
            return True

        # 默认支持
        return True

    async def generate(self, config: GenerationConfig) -> GenerationResult:
        """执行首尾帧生成视频

        Args:
            config: 生成配置

        Returns:
            生成结果
        """
        start_time = time.time()

        try:
            # 检查是否提供了首帧和尾帧
            start_image = config.extra_params.get("start_image")
            end_image = config.extra_params.get("end_image")

            if not start_image:
                return self._create_error_result(
                    error="未提供首帧图片",
                    duration=time.time() - start_time,
                )

            if not end_image:
                return self._create_error_result(
                    error="未提供尾帧图片",
                    duration=time.time() - start_time,
                )

            # 确定服务商
            provider = config.extra_params.get("provider", self.provider)

            # 根据服务商选择生成方法
            if provider == "kling":
                result = await self._generate_kling(config)
            elif provider == "pika":
                result = await self._generate_pika(config)
            else:
                result = await self._generate_generic(config)

            duration = time.time() - start_time

            # 更新结果
            result.duration = duration
            result.metadata.update(
                {
                    "provider": provider,
                    "generator_id": self.generator_id,
                }
            )

            return result

        except Exception as e:
            duration = time.time() - start_time
            self.logger.error("首尾帧生成视频失败: %s", e)
            return self._create_error_result(
                error=str(e),
                duration=duration,
            )

    async def _generate_kling(self, config: GenerationConfig) -> GenerationResult:
        """可灵生成

        Args:
            config: 生成配置

        Returns:
            生成结果
        """
        if not aiohttp:
            raise ImportError("aiohttp 未安装，无法调用可灵 API")

        if not self.api_key:
            raise ValueError("API 密钥未配置")

        # 获取首帧和尾帧
        start_image = config.extra_params.get("start_image")
        end_image = config.extra_params.get("end_image")

        if isinstance(start_image, bytes):
            start_image_b64 = base64.b64encode(start_image).decode("utf-8")
        elif isinstance(start_image, str):
            start_image_b64 = start_image
        else:
            raise ValueError("首帧图片格式不支持")

        if isinstance(end_image, bytes):
            end_image_b64 = base64.b64encode(end_image).decode("utf-8")
        elif isinstance(end_image, str):
            end_image_b64 = end_image
        else:
            raise ValueError("尾帧图片格式不支持")

        # 构建请求数据
        request_data = {
            "model": config.extra_params.get("model", "kling-v1"),
            "start_image": start_image_b64,
            "end_image": end_image_b64,
            "prompt": config.prompt,
            "negative_prompt": config.negative_prompt,
            "duration": config.duration or 5,
            "fps": config.fps,
            "seed": config.seed,
        }

        # 发送请求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            # 提交任务
            async with session.post(
                f"{self.base_url}/v1/videos/keyframe",
                json=request_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    task_id = data.get("task_id")

                    if not task_id:
                        return self._create_error_result(
                            error="未获取到任务ID",
                            metadata={"response": data},
                        )

                    # 轮询任务状态
                    video_data = await self._poll_task_status(session, headers, task_id, "kling")

                    if video_data:
                        return self._create_success_result(
                            output_data=video_data,
                            metadata={
                                "model": request_data["model"],
                                "duration": request_data["duration"],
                                "task_id": task_id,
                            },
                        )

                    return self._create_error_result(
                        error="任务执行失败或超时",
                        metadata={"task_id": task_id},
                    )
                else:
                    error_text = await response.text()
                    return self._create_error_result(
                        error=f"API 请求失败: HTTP {response.status}",
                        metadata={"response": error_text},
                    )

    async def _generate_pika(self, config: GenerationConfig) -> GenerationResult:
        """Pika 生成

        Args:
            config: 生成配置

        Returns:
            生成结果
        """
        if not aiohttp:
            raise ImportError("aiohttp 未安装，无法调用 Pika API")

        if not self.api_key:
            raise ValueError("API 密钥未配置")

        # 获取首帧和尾帧
        start_image = config.extra_params.get("start_image")
        end_image = config.extra_params.get("end_image")

        if isinstance(start_image, bytes):
            start_image_b64 = base64.b64encode(start_image).decode("utf-8")
        elif isinstance(start_image, str):
            start_image_b64 = start_image
        else:
            raise ValueError("首帧图片格式不支持")

        if isinstance(end_image, bytes):
            end_image_b64 = base64.b64encode(end_image).decode("utf-8")
        elif isinstance(end_image, str):
            end_image_b64 = end_image
        else:
            raise ValueError("尾帧图片格式不支持")

        # 构建请求数据
        request_data = {
            "model": config.extra_params.get("model", "pika-v1"),
            "start_image": start_image_b64,
            "end_image": end_image_b64,
            "prompt": config.prompt,
            "negative_prompt": config.negative_prompt,
            "duration": config.duration or 3,
            "fps": config.fps,
            "seed": config.seed,
        }

        # 发送请求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            # 提交任务
            async with session.post(
                f"{self.base_url}/v1/videos",
                json=request_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    task_id = data.get("id")

                    if not task_id:
                        return self._create_error_result(
                            error="未获取到任务ID",
                            metadata={"response": data},
                        )

                    # 轮询任务状态
                    video_data = await self._poll_task_status(session, headers, task_id, "pika")

                    if video_data:
                        return self._create_success_result(
                            output_data=video_data,
                            metadata={
                                "model": request_data["model"],
                                "duration": request_data["duration"],
                                "task_id": task_id,
                            },
                        )

                    return self._create_error_result(
                        error="任务执行失败或超时",
                        metadata={"task_id": task_id},
                    )
                else:
                    error_text = await response.text()
                    return self._create_error_result(
                        error=f"API 请求失败: HTTP {response.status}",
                        metadata={"response": error_text},
                    )

    async def _generate_generic(self, config: GenerationConfig) -> GenerationResult:
        """通用 API 生成

        Args:
            config: 生成配置

        Returns:
            生成结果
        """
        if not aiohttp:
            raise ImportError("aiohttp 未安装，无法调用通用 API")

        if not self.api_key:
            raise ValueError("API 密钥未配置")

        # 获取首帧和尾帧
        start_image = config.extra_params.get("start_image")
        end_image = config.extra_params.get("end_image")

        if isinstance(start_image, bytes):
            start_image_b64 = base64.b64encode(start_image).decode("utf-8")
        elif isinstance(start_image, str):
            start_image_b64 = start_image
        else:
            raise ValueError("首帧图片格式不支持")

        if isinstance(end_image, bytes):
            end_image_b64 = base64.b64encode(end_image).decode("utf-8")
        elif isinstance(end_image, str):
            end_image_b64 = end_image
        else:
            raise ValueError("尾帧图片格式不支持")

        # 构建请求数据
        request_data = {
            "start_image": start_image_b64,
            "end_image": end_image_b64,
            "prompt": config.prompt,
            "negative_prompt": config.negative_prompt,
            "duration": config.duration or 5,
            "fps": config.fps,
            "width": config.width,
            "height": config.height,
            "num_inference_steps": config.num_inference_steps,
            "guidance_scale": config.guidance_scale,
            "seed": config.seed,
        }

        # 发送请求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            # 提交任务
            async with session.post(
                f"{self.base_url}/generate", json=request_data, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    task_id = data.get("task_id") or data.get("id")

                    if not task_id:
                        # 尝试直接获取视频数据
                        video_data = self._extract_video_data(data)
                        if video_data:
                            return self._create_success_result(
                                output_data=video_data,
                                metadata={
                                    "model": config.extra_params.get("model", "generic"),
                                    "duration": request_data["duration"],
                                },
                            )

                        return self._create_error_result(
                            error="未获取到任务ID或视频数据",
                            metadata={"response": data},
                        )

                    # 轮询任务状态
                    video_data = await self._poll_task_status(session, headers, task_id, "generic")

                    if video_data:
                        return self._create_success_result(
                            output_data=video_data,
                            metadata={
                                "model": config.extra_params.get("model", "generic"),
                                "duration": request_data["duration"],
                                "task_id": task_id,
                            },
                        )

                    return self._create_error_result(
                        error="任务执行失败或超时",
                        metadata={"task_id": task_id},
                    )
                else:
                    error_text = await response.text()
                    return self._create_error_result(
                        error=f"API 请求失败: HTTP {response.status}",
                        metadata={"response": error_text},
                    )

    async def _poll_task_status(
        self,
        session: aiohttp.ClientSession,
        headers: Dict[str, str],
        task_id: str,
        provider: str,
        max_attempts: int = 60,
        poll_interval: float = 5.0,
    ) -> Optional[bytes]:
        """轮询任务状态

        Args:
            session: HTTP 会话
            headers: 请求头
            task_id: 任务ID
            provider: 服务商类型
            max_attempts: 最大尝试次数
            poll_interval: 轮询间隔（秒）

        Returns:
            视频数据，失败返回 None
        """
        # 根据服务商选择状态查询端点
        status_urls = {
            "kling": f"{self.base_url}/v1/videos/keyframe/{task_id}",
            "pika": f"{self.base_url}/v1/videos/{task_id}",
            "generic": f"{self.base_url}/tasks/{task_id}",
        }

        status_url = status_urls.get(provider, f"{self.base_url}/tasks/{task_id}")

        for attempt in range(max_attempts):
            try:
                async with session.get(
                    status_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()

                        # 检查任务状态
                        status = self._get_task_status(data, provider)

                        if status == "completed" or status == "success":
                            # 获取视频数据
                            video_data = self._extract_video_data(data)
                            if video_data:
                                return video_data
                        elif status == "failed" or status == "error":
                            self.logger.error("任务失败: %s", data)
                            return None

                        # 任务仍在进行中，等待后重试
                        await asyncio.sleep(poll_interval)
                    else:
                        self.logger.warning("查询任务状态失败: HTTP %s", response.status)
                        await asyncio.sleep(poll_interval)

            except Exception as e:
                self.logger.warning("查询任务状态异常: %s", e)
                await asyncio.sleep(poll_interval)

        self.logger.error("任务超时: %s", task_id)
        return None

    def _get_task_status(self, data: Dict[str, Any], provider: str) -> str:
        """获取任务状态

        Args:
            data: 响应数据
            provider: 服务商类型

        Returns:
            任务状态
        """
        # 根据服务商解析状态
        if provider == "kling":
            return data.get("task_status", "unknown")
        elif provider == "pika":
            return data.get("status", "unknown")
        else:
            # 通用格式
            return data.get("status") or data.get("task_status") or "unknown"

    def _extract_video_data(self, data: Dict[str, Any]) -> Optional[bytes]:
        """提取视频数据

        Args:
            data: 响应数据

        Returns:
            视频数据，失败返回 None
        """
        # 尝试不同的响应格式
        video_url = None

        # 尝试从 output 获取
        if "output" in data:
            output = data["output"]
            if isinstance(output, dict):
                video_url = output.get("video_url") or output.get("url")
            elif isinstance(output, str):
                video_url = output

        # 尝试从 data 获取
        if not video_url and "data" in data:
            video_data = data["data"]
            if isinstance(video_data, dict):
                video_url = video_data.get("video_url") or video_data.get("url")
            elif isinstance(video_data, list) and video_data:
                video_url = video_data[0].get("url") if isinstance(video_data[0], dict) else None

        # 尝试直接获取 base64 数据
        if not video_url:
            video_b64 = data.get("video") or data.get("video_base64")
            if video_b64:
                try:
                    return base64.b64decode(video_b64)
                except Exception:
                    pass

        # 如果有 URL，下载视频
        if video_url:
            # 注意：这里需要同步下载，因为是在异步函数中
            # 实际实现中可能需要使用 aiohttp 下载
            self.logger.info("获取到视频 URL: %s", video_url)
            # 返回 URL 作为元数据，实际下载由调用者处理
            return None

        return None

    def get_supported_providers(self) -> Dict[str, Dict[str, Any]]:
        """获取支持的服务商列表

        Returns:
            服务商信息字典
        """
        return self._SUPPORTED_PROVIDERS.copy()

    def get_supported_durations(self, provider: str) -> list:
        """获取指定服务商支持的视频时长

        Args:
            provider: 服务商名称

        Returns:
            支持的时长列表（秒）
        """
        provider_info = self._SUPPORTED_PROVIDERS.get(provider, {})
        return provider_info.get("supported_durations", [5, 10])


# 工厂函数
def create_keyframe_to_video_generator(
    api_key: str = "", base_url: str = "", provider: str = "generic", **kwargs
) -> KeyframeToVideoGenerator:
    """创建首尾帧生成视频生成器实例

    Args:
        api_key: API 密钥
        base_url: API 基础 URL
        provider: 服务商类型
        **kwargs: 其他配置参数

    Returns:
        KeyframeToVideoGenerator 实例
    """
    return KeyframeToVideoGenerator(
        generator_id="keyframe_to_video", api_key=api_key, base_url=base_url, provider=provider, **kwargs
    )
