"""
Image-to-Image Generator
Supports Stable Diffusion Img2Img, DALL-E Variations, Wanx Style Transfer, ControlNet, Midjourney Vary
"""

import base64
from neurova.core.logger import get_logger
import time
from typing import Any, Dict

try:
    import aiohttp
except ImportError:
    aiohttp = None

from neurova.llm.generators.base import BaseGenerator, GenerationConfig, GenerationResult, GeneratorType

logger = get_logger(__name__)


class ImageToImageGenerator(BaseGenerator):
    """
    图生图生成器

    支持多种图生图服务商：
    - Stable Diffusion Img2Img
    - DALL-E Variations
    - 通义万相风格迁移
    - ControlNet
    - Midjourney Vary
    """

    # 支持的服务商列表
    _SUPPORTED_PROVIDERS = {
        "stable-diffusion": {
            "name": "Stable Diffusion Img2Img",
            "default_model": "stable-diffusion-xl-1024-v1-0",
            "requires_image": True,
        },
        "dalle": {
            "name": "DALL-E Variations",
            "default_model": "dall-e-2",
            "requires_image": True,
        },
        "wanx": {
            "name": "通义万相风格迁移",
            "default_model": "wanx-style-v1",
            "requires_image": True,
        },
        "controlnet": {
            "name": "ControlNet",
            "default_model": "controlnet-v1.1",
            "requires_image": True,
        },
        "midjourney": {
            "name": "Midjourney Vary",
            "default_model": "midjourney-v6",
            "requires_image": True,
        },
        "generic": {
            "name": "通用 API",
            "default_model": "generic",
            "requires_image": True,
        },
    }

    def __init__(
        self,
        generator_id: str = "image_to_image",
        api_key: str = "",
        base_url: str = "",
        provider: str = "generic",
        **kwargs,
    ):
        """初始化图生图生成器

        Args:
            generator_id: 生成器唯一标识符
            api_key: API 密钥
            base_url: API 基础 URL
            provider: 服务商类型
            **kwargs: 其他配置参数
        """
        super().__init__(generator_id=generator_id, generator_type=GeneratorType.IMAGE_TO_IMAGE, **kwargs)
        self.api_key = api_key
        self.base_url = base_url
        self.provider = provider
        self._initialized = True

        self.logger.info("ImageToImageGenerator 初始化完成: provider=%s", provider)

    def supports(self, config: GenerationConfig) -> bool:
        """检查是否支持指定的生成配置

        Args:
            config: 生成配置

        Returns:
            是否支持
        """
        # 检查是否为图生图类型
        if config.type != GeneratorType.IMAGE_TO_IMAGE:
            return False

        # 检查服务商是否支持
        if config.extra_params.get("provider") in self._SUPPORTED_PROVIDERS:
            return True

        # 默认支持
        return True

    async def generate(self, config: GenerationConfig) -> GenerationResult:
        """执行图生图生成

        Args:
            config: 生成配置

        Returns:
            生成结果
        """
        start_time = time.time()

        try:
            # 检查是否提供了输入图片
            input_image = config.extra_params.get("input_image")
            if not input_image:
                return self._create_error_result(
                    error="未提供输入图片",
                    duration=time.time() - start_time,
                )

            # 确定服务商
            provider = config.extra_params.get("provider", self.provider)

            # 根据服务商选择生成方法
            if provider == "stable-diffusion":
                result = await self._generate_sd_img2img(config)
            elif provider == "dalle":
                result = await self._generate_dalle_variations(config)
            elif provider == "wanx":
                result = await self._generate_wanx_style_transfer(config)
            elif provider == "controlnet":
                result = await self._generate_controlnet(config)
            elif provider == "midjourney":
                result = await self._generate_midjourney_vary(config)
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
            self.logger.error("图生图生成失败: %s", e)
            return self._create_error_result(
                error=str(e),
                duration=duration,
            )

    async def _generate_sd_img2img(self, config: GenerationConfig) -> GenerationResult:
        """Stable Diffusion Img2Img 生成

        Args:
            config: 生成配置

        Returns:
            生成结果
        """
        if not aiohttp:
            raise ImportError("aiohttp 未安装，无法调用 Stable Diffusion API")

        if not self.api_key:
            raise ValueError("API 密钥未配置")

        # 获取输入图片
        input_image = config.extra_params.get("input_image")
        if isinstance(input_image, bytes):
            input_image_b64 = base64.b64encode(input_image).decode("utf-8")
        elif isinstance(input_image, str):
            input_image_b64 = input_image
        else:
            raise ValueError("输入图片格式不支持")

        # 构建请求数据
        request_data = {
            "text_prompts": [
                {"text": config.prompt, "weight": 1.0},
            ],
            "init_image": input_image_b64,
            "init_image_mode": "IMAGE_STRENGTH",
            "image_strength": config.extra_params.get("image_strength", 0.35),
            "cfg_scale": config.guidance_scale,
            "samples": 1,
            "steps": config.num_inference_steps,
        }

        if config.negative_prompt:
            request_data["text_prompts"].append(
                {
                    "text": config.negative_prompt,
                    "weight": -1.0,
                }
            )

        if config.seed is not None:
            request_data["seed"] = config.seed

        # 发送请求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v1/generation/image-to-image",
                json=request_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120),
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

    async def _generate_dalle_variations(self, config: GenerationConfig) -> GenerationResult:
        """DALL-E Variations 生成

        Args:
            config: 生成配置

        Returns:
            生成结果
        """
        if not aiohttp:
            raise ImportError("aiohttp 未安装，无法调用 DALL-E API")

        if not self.api_key:
            raise ValueError("API 密钥未配置")

        # 获取输入图片
        input_image = config.extra_params.get("input_image")
        if isinstance(input_image, bytes):
            input_image_b64 = base64.b64encode(input_image).decode("utf-8")
        elif isinstance(input_image, str):
            input_image_b64 = input_image
        else:
            raise ValueError("输入图片格式不支持")

        # 构建请求数据
        request_data = {
            "model": config.extra_params.get("model", "dall-e-2"),
            "image": input_image_b64,
            "n": 1,
            "size": f"{config.width}x{config.height}",
            "response_format": "b64_json",
        }

        # 发送请求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v1/images/variations",
                json=request_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
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

    async def _generate_wanx_style_transfer(self, config: GenerationConfig) -> GenerationResult:
        """通义万相风格迁移

        Args:
            config: 生成配置

        Returns:
            生成结果
        """
        if not aiohttp:
            raise ImportError("aiohttp 未安装，无法调用通义万相 API")

        if not self.api_key:
            raise ValueError("API 密钥未配置")

        # 获取输入图片
        input_image = config.extra_params.get("input_image")
        if isinstance(input_image, bytes):
            input_image_b64 = base64.b64encode(input_image).decode("utf-8")
        elif isinstance(input_image, str):
            input_image_b64 = input_image
        else:
            raise ValueError("输入图片格式不支持")

        # 构建请求数据
        request_data = {
            "model": config.extra_params.get("model", "wanx-style-v1"),
            "input": {
                "image_url": f"data:image/png;base64,{input_image_b64}",
                "style": config.extra_params.get("style", "auto"),
            },
            "parameters": {
                "strength": config.extra_params.get("strength", 0.7),
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
                f"{self.base_url}/api/v1/services/aigc/image2image/image-synthesis",
                json=request_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
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
                                        "style": request_data["input"]["style"],
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

    async def _generate_controlnet(self, config: GenerationConfig) -> GenerationResult:
        """ControlNet 生成

        Args:
            config: 生成配置

        Returns:
            生成结果
        """
        if not aiohttp:
            raise ImportError("aiohttp 未安装，无法调用 ControlNet API")

        if not self.api_key:
            raise ValueError("API 密钥未配置")

        # 获取输入图片
        input_image = config.extra_params.get("input_image")
        if isinstance(input_image, bytes):
            input_image_b64 = base64.b64encode(input_image).decode("utf-8")
        elif isinstance(input_image, str):
            input_image_b64 = input_image
        else:
            raise ValueError("输入图片格式不支持")

        # 构建请求数据
        request_data = {
            "prompt": config.prompt,
            "negative_prompt": config.negative_prompt,
            "image": input_image_b64,
            "model": config.extra_params.get("model", "controlnet-v1.1"),
            "control_type": config.extra_params.get("control_type", "canny"),
            "control_strength": config.extra_params.get("control_strength", 1.0),
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
                timeout=aiohttp.ClientTimeout(total=120),
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
                                "model": request_data["model"],
                                "control_type": request_data["control_type"],
                                "control_strength": request_data["control_strength"],
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

    async def _generate_midjourney_vary(self, config: GenerationConfig) -> GenerationResult:
        """Midjourney Vary 生成

        Args:
            config: 生成配置

        Returns:
            生成结果
        """
        # Midjourney 通常通过 Discord Bot 或第三方 API 调用
        # 这里提供一个通用的实现框架

        if not aiohttp:
            raise ImportError("aiohttp 未安装，无法调用 Midjourney API")

        if not self.api_key:
            raise ValueError("API 密钥未配置")

        # 获取输入图片
        input_image = config.extra_params.get("input_image")
        if isinstance(input_image, bytes):
            input_image_b64 = base64.b64encode(input_image).decode("utf-8")
        elif isinstance(input_image, str):
            input_image_b64 = input_image
        else:
            raise ValueError("输入图片格式不支持")

        # 构建请求数据（Midjourney API 格式）
        request_data = {
            "prompt": config.prompt,
            "image": input_image_b64,
            "action": "vary",
            "strength": config.extra_params.get("strength", 0.7),
        }

        # 发送请求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v1/generations",
                json=request_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120),
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
                                "model": config.extra_params.get("model", "midjourney-v6"),
                                "action": "vary",
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

        # 获取输入图片
        input_image = config.extra_params.get("input_image")
        if isinstance(input_image, bytes):
            input_image_b64 = base64.b64encode(input_image).decode("utf-8")
        elif isinstance(input_image, str):
            input_image_b64 = input_image
        else:
            raise ValueError("输入图片格式不支持")

        # 构建请求数据
        request_data = {
            "prompt": config.prompt,
            "negative_prompt": config.negative_prompt,
            "image": input_image_b64,
            "width": config.width,
            "height": config.height,
            "num_inference_steps": config.num_inference_steps,
            "guidance_scale": config.guidance_scale,
            "strength": config.extra_params.get("strength", 0.75),
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
                timeout=aiohttp.ClientTimeout(total=120),
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
                                "strength": request_data["strength"],
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


# 工厂函数
def create_image_to_image_generator(
    api_key: str = "", base_url: str = "", provider: str = "generic", **kwargs
) -> ImageToImageGenerator:
    """创建图生图生成器实例

    Args:
        api_key: API 密钥
        base_url: API 基础 URL
        provider: 服务商类型
        **kwargs: 其他配置参数

    Returns:
        ImageToImageGenerator 实例
    """
    return ImageToImageGenerator(
        generator_id="image_to_image", api_key=api_key, base_url=base_url, provider=provider, **kwargs
    )
