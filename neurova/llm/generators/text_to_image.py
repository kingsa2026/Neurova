"""
文生图生成器
支持通义万相、Stable Diffusion等服务商
"""

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


class TextToImageGenerator(BaseGenerator):
    """
    文生图生成器
    
    支持多种文生图服务商：
    - 通义万相 (Wanx)
    - DALL-E (OpenAI)
    - Stable Diffusion
    - 通用 API
    """
    
    # 支持的服务商列表
    _SUPPORTED_PROVIDERS = {
        "wanx": {
            "name": "通义万相",
            "default_model": "wanx-v1",
            "supported_sizes": ["512x512", "768x768", "1024x1024"],
        },
        "dalle": {
            "name": "DALL-E",
            "default_model": "dall-e-3",
            "supported_sizes": ["1024x1024", "1024x1792", "1792x1024"],
        },
        "stable-diffusion": {
            "name": "Stable Diffusion",
            "default_model": "stable-diffusion-xl-1024-v1-0",
            "supported_sizes": ["512x512", "768x768", "1024x1024"],
        },
        "generic": {
            "name": "通用 API",
            "default_model": "generic",
            "supported_sizes": ["512x512", "1024x1024"],
        },
    }
    
    def __init__(
        self,
        generator_id: str = "text_to_image",
        api_key: str = "",
        base_url: str = "",
        provider: str = "generic",
        **kwargs
    ):
        """初始化文生图生成器
        
        Args:
            generator_id: 生成器唯一标识符
            api_key: API 密钥
            base_url: API 基础 URL
            provider: 服务商类型
            **kwargs: 其他配置参数
        """
        super().__init__(
            generator_id=generator_id,
            generator_type=GeneratorType.TEXT_TO_IMAGE,
            **kwargs
        )
        self.api_key = api_key
        self.base_url = base_url
        self.provider = provider
        self._initialized = True
        
        self.logger.info(f"TextToImageGenerator 初始化完成: provider={provider}")
    
    def supports(self, config: GenerationConfig) -> bool:
        """检查是否支持指定的生成配置
        
        Args:
            config: 生成配置
            
        Returns:
            是否支持
        """
        # 检查是否为文生图类型
        if config.type != GeneratorType.TEXT_TO_IMAGE:
            return False
        
        # 检查服务商是否支持
        if config.extra_params.get("provider") in self._SUPPORTED_PROVIDERS:
            return True
        
        # 默认支持
        return True
    
    async def generate(self, config: GenerationConfig) -> GenerationResult:
        """执行文生图生成
        
        Args:
            config: 生成配置
            
        Returns:
            生成结果
        """
        start_time = time.time()
        
        try:
            # 确定服务商
            provider = config.extra_params.get("provider", self.provider)
            
            # 根据服务商选择生成方法
            if provider == "wanx":
                result = await self._generate_wanx(config)
            elif provider == "dalle":
                result = await self._generate_dalle(config)
            elif provider == "stable-diffusion":
                result = await self._generate_sd(config)
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
            self.logger.error(f"文生图生成失败: {e}")
            return self._create_error_result(
                error=str(e),
                duration=duration,
            )
    
    async def _generate_wanx(self, config: GenerationConfig) -> GenerationResult:
        """通义万相生成
        
        Args:
            config: 生成配置
            
        Returns:
            生成结果
        """
        if not aiohttp:
            raise ImportError("aiohttp 未安装，无法调用通义万相 API")
        
        if not self.api_key:
            raise ValueError("API 密钥未配置")
        
        # 构建请求数据
        request_data = {
            "model": config.extra_params.get("model", "wanx-v1"),
            "input": {
                "prompt": config.prompt,
                "negative_prompt": config.negative_prompt,
            },
            "parameters": {
                "size": f"{config.width}x{config.height}",
                "n": 1,
                "seed": config.seed,
            },
        }
        
        # 发送请求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/api/v1/services/aigc/text2image/image-synthesis",
                json=request_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # 获取图片 URL
                    image_url = data.get("output", {}).get("results", [{}])[0].get("url", "")
                    
                    if image_url:
                        # 下载图片
                        async with session.get(image_url) as img_response:
                            if img_response.status == 200:
                                image_data = await img_response.read()
                                return self._create_success_result(
                                    output_data=image_data,
                                    metadata={
                                        "model": request_data["model"],
                                        "size": request_data["parameters"]["size"],
                                        "image_url": image_url,
                                    },
                                )
                    
                    return self._create_error_result(
                        error="未获取到图片数据",
                        metadata={"response": data},
                    )
                else:
                    error_text = await response.text()
                    return self._create_error_result(
                        error=f"API 请求失败: HTTP {response.status}",
                        metadata={"response": error_text},
                    )
    
    async def _generate_dalle(self, config: GenerationConfig) -> GenerationResult:
        """DALL-E 生成
        
        Args:
            config: 生成配置
            
        Returns:
            生成结果
        """
        if not aiohttp:
            raise ImportError("aiohttp 未安装，无法调用 DALL-E API")
        
        if not self.api_key:
            raise ValueError("API 密钥未配置")
        
        # 构建请求数据
        request_data = {
            "model": config.extra_params.get("model", "dall-e-3"),
            "prompt": config.prompt,
            "n": 1,
            "size": f"{config.width}x{config.height}",
            "quality": config.extra_params.get("quality", "standard"),
            "response_format": "b64_json",
        }
        
        # 发送请求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v1/images/generations",
                json=request_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # 获取图片数据
                    image_data_b64 = data.get("data", [{}])[0].get("b64_json", "")
                    
                    if image_data_b64:
                        image_data = base64.b64decode(image_data_b64)
                        return self._create_success_result(
                            output_data=image_data,
                            metadata={
                                "model": request_data["model"],
                                "size": request_data["size"],
                                "quality": request_data["quality"],
                            },
                        )
                    
                    return self._create_error_result(
                        error="未获取到图片数据",
                        metadata={"response": data},
                    )
                else:
                    error_text = await response.text()
                    return self._create_error_result(
                        error=f"API 请求失败: HTTP {response.status}",
                        metadata={"response": error_text},
                    )
    
    async def _generate_sd(self, config: GenerationConfig) -> GenerationResult:
        """Stable Diffusion 生成
        
        Args:
            config: 生成配置
            
        Returns:
            生成结果
        """
        if not aiohttp:
            raise ImportError("aiohttp 未安装，无法调用 Stable Diffusion API")
        
        if not self.api_key:
            raise ValueError("API 密钥未配置")
        
        # 构建请求数据
        request_data = {
            "text_prompts": [
                {"text": config.prompt, "weight": 1.0},
            ],
            "cfg_scale": config.guidance_scale,
            "height": config.height,
            "width": config.width,
            "samples": 1,
            "steps": config.num_inference_steps,
        }
        
        if config.negative_prompt:
            request_data["text_prompts"].append({
                "text": config.negative_prompt,
                "weight": -1.0,
            })
        
        if config.seed is not None:
            request_data["seed"] = config.seed
        
        # 发送请求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v1/generation/text-to-image",
                json=request_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # 获取图片数据
                    artifacts = data.get("artifacts", [])
                    if artifacts:
                        image_data_b64 = artifacts[0].get("base64", "")
                        if image_data_b64:
                            image_data = base64.b64decode(image_data_b64)
                            return self._create_success_result(
                                output_data=image_data,
                                metadata={
                                    "model": config.extra_params.get("model", "stable-diffusion-xl-1024-v1-0"),
                                    "seed": artifacts[0].get("seed"),
                                    "finish_reason": artifacts[0].get("finishReason"),
                                },
                            )
                    
                    return self._create_error_result(
                        error="未获取到图片数据",
                        metadata={"response": data},
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
        
        # 构建请求数据
        request_data = {
            "prompt": config.prompt,
            "negative_prompt": config.negative_prompt,
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
            async with session.post(
                f"{self.base_url}/generate",
                json=request_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # 尝试获取图片数据
                    image_data = None
                    
                    # 尝试不同的响应格式
                    if "image" in data:
                        image_data = base64.b64decode(data["image"])
                    elif "output" in data:
                        if isinstance(data["output"], str):
                            image_data = base64.b64decode(data["output"])
                        elif isinstance(data["output"], dict) and "image" in data["output"]:
                            image_data = base64.b64decode(data["output"]["image"])
                    
                    if image_data:
                        return self._create_success_result(
                            output_data=image_data,
                            metadata={
                                "model": config.extra_params.get("model", "generic"),
                                "response_keys": list(data.keys()),
                            },
                        )
                    
                    return self._create_error_result(
                        error="未获取到图片数据",
                        metadata={"response": data},
                    )
                else:
                    error_text = await response.text()
                    return self._create_error_result(
                        error=f"API 请求失败: HTTP {response.status}",
                        metadata={"response": error_text},
                    )
    
    def get_supported_providers(self) -> Dict[str, Dict[str, Any]]:
        """获取支持的服务商列表
        
        Returns:
            服务商信息字典
        """
        return self._SUPPORTED_PROVIDERS.copy()
    
    def get_supported_sizes(self, provider: str) -> list:
        """获取指定服务商支持的图片尺寸
        
        Args:
            provider: 服务商名称
            
        Returns:
            支持的尺寸列表
        """
        provider_info = self._SUPPORTED_PROVIDERS.get(provider, {})
        return provider_info.get("supported_sizes", ["512x512", "1024x1024"])


# 工厂函数
def create_text_to_image_generator(
    api_key: str = "",
    base_url: str = "",
    provider: str = "generic",
    **kwargs
) -> TextToImageGenerator:
    """创建文生图生成器实例
    
    Args:
        api_key: API 密钥
        base_url: API 基础 URL
        provider: 服务商类型
        **kwargs: 其他配置参数
        
    Returns:
        TextToImageGenerator 实例
    """
    return TextToImageGenerator(
        generator_id="text_to_image",
        api_key=api_key,
        base_url=base_url,
        provider=provider,
        **kwargs
    )
