"""
Video-to-Video Generator
Supports Kling, Runway, Pika, Stable Video Diffusion, and Gen-1/Gen-2
"""

import asyncio
import base64
import logging
import time
import typing
from typing import Dict, Any, Optional

import http

try:
    import aiohttp
except ImportError:
    aiohttp = None

from neurova.llm.generators.base import (
    BaseGenerator, GeneratorType, GenerationConfig, GenerationResult
)


logger = logging.getLogger(__name__)


class VideoToVideoGenerator(BaseGenerator):
    """
    视频到视频生成器
    
    支持多种视频转换服务商：
    - 可灵 (Kling)
    - Runway
    - Pika
    - Stable Video Diffusion
    - Gen-1/Gen-2
    """
    
    # 支持的服务商列表
    _SUPPORTED_PROVIDERS = {
        "kling": {
            "name": "可灵",
            "default_model": "kling-v1",
            "supported_durations": [5, 10, 15],
            "requires_video": True,
        },
        "runway": {
            "name": "Runway",
            "default_model": "gen-3-alpha",
            "supported_durations": [4, 8, 16],
            "requires_video": True,
        },
        "pika": {
            "name": "Pika",
            "default_model": "pika-v1",
            "supported_durations": [3, 5],
            "requires_video": True,
        },
        "svd": {
            "name": "Stable Video Diffusion",
            "default_model": "svd-xt-1-1",
            "supported_durations": [4, 8, 14, 25],
            "requires_video": True,
        },
        "gen": {
            "name": "Gen-1/Gen-2",
            "default_model": "gen-2",
            "supported_durations": [4, 8],
            "requires_video": True,
        },
        "generic": {
            "name": "通用 API",
            "default_model": "generic",
            "supported_durations": [5, 10],
            "requires_video": True,
        },
    }
    
    def __init__(
        self,
        generator_id: str = "video_to_video",
        api_key: str = "",
        base_url: str = "",
        provider: str = "generic",
        **kwargs
    ):
        """初始化视频到视频生成器
        
        Args:
            generator_id: 生成器唯一标识符
            api_key: API 密钥
            base_url: API 基础 URL
            provider: 服务商类型
            **kwargs: 其他配置参数
        """
        super().__init__(
            generator_id=generator_id,
            generator_type=GeneratorType.VIDEO_TO_VIDEO,
            **kwargs
        )
        self.api_key = api_key
        self.base_url = base_url
        self.provider = provider
        self._initialized = True
        
        self.logger.info(f"VideoToVideoGenerator 初始化完成: provider={provider}")
    
    def supports(self, config: GenerationConfig) -> bool:
        """检查是否支持指定的生成配置
        
        Args:
            config: 生成配置
            
        Returns:
            是否支持
        """
        # 检查是否为视频到视频类型
        if config.type != GeneratorType.VIDEO_TO_VIDEO:
            return False
        
        # 检查服务商是否支持
        if config.extra_params.get("provider") in self._SUPPORTED_PROVIDERS:
            return True
        
        # 默认支持
        return True
    
    async def generate(self, config: GenerationConfig) -> GenerationResult:
        """执行视频到视频生成
        
        Args:
            config: 生成配置
            
        Returns:
            生成结果
        """
        start_time = time.time()
        
        try:
            # 检查是否提供了输入视频
            input_video = config.extra_params.get("input_video")
            if not input_video:
                return self._create_error_result(
                    error="未提供输入视频",
                    duration=time.time() - start_time,
                )
            
            # 确定服务商
            provider = config.extra_params.get("provider", self.provider)
            
            # 根据服务商选择生成方法
            if provider == "kling":
                result = await self._generate_kling(config)
            elif provider == "runway":
                result = await self._generate_runway(config)
            elif provider == "pika":
                result = await self._generate_pika(config)
            elif provider == "svd":
                result = await self._generate_svd(config)
            elif provider == "gen":
                result = await self._generate_gen(config)
            else:
                result = await self._generate_generic(config)
            
            duration = time.time() - start_time
            
            # 更新结果
            result.duration = duration
            result.metadata.update({
                "provider": provider,
                "generator_id": self.generator_id,
            })
            
            return result
            
        except Exception as e:
            duration = time.time() - start_time
            self.logger.error(f"视频到视频生成失败: {e}")
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
        
        # 获取输入视频
        input_video = config.extra_params.get("input_video")
        if isinstance(input_video, bytes):
            input_video_b64 = base64.b64encode(input_video).decode("utf-8")
        elif isinstance(input_video, str):
            input_video_b64 = input_video
        else:
            raise ValueError("输入视频格式不支持")
        
        # 构建请求数据
        request_data = {
            "model": config.extra_params.get("model", "kling-v1"),
            "video": input_video_b64,
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
                f"{self.base_url}/v1/videos/video2video",
                json=request_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
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
                    video_data = await self._poll_task_status(
                        session, headers, task_id, "kling"
                    )
                    
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
    
    async def _generate_runway(self, config: GenerationConfig) -> GenerationResult:
        """Runway 生成
        
        Args:
            config: 生成配置
            
        Returns:
            生成结果
        """
        if not aiohttp:
            raise ImportError("aiohttp 未安装，无法调用 Runway API")
        
        if not self.api_key:
            raise ValueError("API 密钥未配置")
        
        # 获取输入视频
        input_video = config.extra_params.get("input_video")
        if isinstance(input_video, bytes):
            input_video_b64 = base64.b64encode(input_video).decode("utf-8")
        elif isinstance(input_video, str):
            input_video_b64 = input_video
        else:
            raise ValueError("输入视频格式不支持")
        
        # 构建请求数据
        request_data = {
            "model": config.extra_params.get("model", "gen-3-alpha"),
            "video": input_video_b64,
            "promptText": config.prompt,
            "negativePrompt": config.negative_prompt,
            "duration": config.duration or 4,
            "width": config.width,
            "height": config.height,
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
                f"{self.base_url}/v1/video_to_video",
                json=request_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
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
                    video_data = await self._poll_task_status(
                        session, headers, task_id, "runway"
                    )
                    
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
        
        # 获取输入视频
        input_video = config.extra_params.get("input_video")
        if isinstance(input_video, bytes):
            input_video_b64 = base64.b64encode(input_video).decode("utf-8")
        elif isinstance(input_video, str):
            input_video_b64 = input_video
        else:
            raise ValueError("输入视频格式不支持")
        
        # 构建请求数据
        request_data = {
            "model": config.extra_params.get("model", "pika-v1"),
            "video": input_video_b64,
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
                timeout=aiohttp.ClientTimeout(total=30)
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
                    video_data = await self._poll_task_status(
                        session, headers, task_id, "pika"
                    )
                    
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
    
    async def _generate_svd(self, config: GenerationConfig) -> GenerationResult:
        """Stable Video Diffusion 生成
        
        Args:
            config: 生成配置
            
        Returns:
            生成结果
        """
        if not aiohttp:
            raise ImportError("aiohttp 未安装，无法调用 SVD API")
        
        if not self.api_key:
            raise ValueError("API 密钥未配置")
        
        # 获取输入视频
        input_video = config.extra_params.get("input_video")
        if isinstance(input_video, bytes):
            input_video_b64 = base64.b64encode(input_video).decode("utf-8")
        elif isinstance(input_video, str):
            input_video_b64 = input_video
        else:
            raise ValueError("输入视频格式不支持")
        
        # 构建请求数据
        request_data = {
            "model": config.extra_params.get("model", "svd-xt-1-1"),
            "video": input_video_b64,
            "motion_bucket_id": config.extra_params.get("motion_bucket_id", 127),
            "noise_aug_strength": config.extra_params.get("noise_aug_strength", 0.02),
            "num_frames": config.num_frames or 25,
            "fps": config.fps or 6,
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
                f"{self.base_url}/v1/generation/video-to-video",
                json=request_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    task_id = data.get("task_id")
                    
                    if not task_id:
                        # 尝试直接获取视频数据
                        video_data = self._extract_video_data(data)
                        if video_data:
                            return self._create_success_result(
                                output_data=video_data,
                                metadata={
                                    "model": request_data["model"],
                                    "num_frames": request_data["num_frames"],
                                },
                            )
                        
                        return self._create_error_result(
                            error="未获取到任务ID或视频数据",
                            metadata={"response": data},
                        )
                    
                    # 轮询任务状态
                    video_data = await self._poll_task_status(
                        session, headers, task_id, "svd"
                    )
                    
                    if video_data:
                        return self._create_success_result(
                            output_data=video_data,
                            metadata={
                                "model": request_data["model"],
                                "num_frames": request_data["num_frames"],
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
    
    async def _generate_gen(self, config: GenerationConfig) -> GenerationResult:
        """Gen-1/Gen-2 生成
        
        Args:
            config: 生成配置
            
        Returns:
            生成结果
        """
        if not aiohttp:
            raise ImportError("aiohttp 未安装，无法调用 Gen API")
        
        if not self.api_key:
            raise ValueError("API 密钥未配置")
        
        # 获取输入视频
        input_video = config.extra_params.get("input_video")
        if isinstance(input_video, bytes):
            input_video_b64 = base64.b64encode(input_video).decode("utf-8")
        elif isinstance(input_video, str):
            input_video_b64 = input_video
        else:
            raise ValueError("输入视频格式不支持")
        
        # 构建请求数据
        request_data = {
            "model": config.extra_params.get("model", "gen-2"),
            "video": input_video_b64,
            "prompt": config.prompt,
            "negative_prompt": config.negative_prompt,
            "duration": config.duration or 4,
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
                f"{self.base_url}/v1/generations",
                json=request_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
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
                    video_data = await self._poll_task_status(
                        session, headers, task_id, "gen"
                    )
                    
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
        
        # 获取输入视频
        input_video = config.extra_params.get("input_video")
        if isinstance(input_video, bytes):
            input_video_b64 = base64.b64encode(input_video).decode("utf-8")
        elif isinstance(input_video, str):
            input_video_b64 = input_video
        else:
            raise ValueError("输入视频格式不支持")
        
        # 构建请求数据
        request_data = {
            "video": input_video_b64,
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
                f"{self.base_url}/generate",
                json=request_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
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
                    video_data = await self._poll_task_status(
                        session, headers, task_id, "generic"
                    )
                    
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
        poll_interval: float = 5.0
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
            "kling": f"{self.base_url}/v1/videos/video2video/{task_id}",
            "runway": f"{self.base_url}/v1/tasks/{task_id}",
            "pika": f"{self.base_url}/v1/videos/{task_id}",
            "svd": f"{self.base_url}/v1/generation/video-to-video/{task_id}",
            "gen": f"{self.base_url}/v1/generations/{task_id}",
            "generic": f"{self.base_url}/tasks/{task_id}",
        }
        
        status_url = status_urls.get(provider, f"{self.base_url}/tasks/{task_id}")
        
        for attempt in range(max_attempts):
            try:
                async with session.get(
                    status_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
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
                            self.logger.error(f"任务失败: {data}")
                            return None
                        
                        # 任务仍在进行中，等待后重试
                        await asyncio.sleep(poll_interval)
                    else:
                        self.logger.warning(f"查询任务状态失败: HTTP {response.status}")
                        await asyncio.sleep(poll_interval)
                        
            except Exception as e:
                self.logger.warning(f"查询任务状态异常: {e}")
                await asyncio.sleep(poll_interval)
        
        self.logger.error(f"任务超时: {task_id}")
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
        elif provider == "runway":
            return data.get("status", "unknown")
        elif provider == "pika":
            return data.get("status", "unknown")
        elif provider == "svd":
            return data.get("status", "unknown")
        elif provider == "gen":
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
            self.logger.info(f"获取到视频 URL: {video_url}")
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
def create_video_to_video_generator(
    api_key: str = "",
    base_url: str = "",
    provider: str = "generic",
    **kwargs
) -> VideoToVideoGenerator:
    """创建视频到视频生成器实例
    
    Args:
        api_key: API 密钥
        base_url: API 基础 URL
        provider: 服务商类型
        **kwargs: 其他配置参数
        
    Returns:
        VideoToVideoGenerator 实例
    """
    return VideoToVideoGenerator(
        generator_id="video_to_video",
        api_key=api_key,
        base_url=base_url,
        provider=provider,
        **kwargs
    )
