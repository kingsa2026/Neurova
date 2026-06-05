"""
生成器基础模块
定义统一的生成器接口和数据结构
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import enum
import logging
import typing

from abc import ABC
from enum import Enum
from abc import abstractmethod

from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time

class GeneratorType(str, Enum):
    """生成器类型"""
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_TO_IMAGE = "image_to_image"
    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_VIDEO = "image_to_video"
    KEYFRAME_TO_VIDEO = "keyframe_to_video"
    VIDEO_TO_VIDEO = "video_to_video"
    TEXT_TO_SPEECH = "text_to_speech"
    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_GENERATION = "text_generation"
    CODE_GENERATION = "code_generation"

@dataclass
class GenerationConfig:
    """生成配置"""
    type: GeneratorType = GeneratorType.TEXT_GENERATION
    prompt: str = ""
    negative_prompt: str = ""
    model_id: str = ""
    width: int = 512
    height: int = 512
    num_frames: int = 1
    duration: float = 0.0
    fps: int = 24
    num_inference_steps: int = 50
    guidance_scale: float = 7.5
    seed: Optional[int] = None
    extra_params: Dict[str, Any] = field(default_factory=dict)

@dataclass
class GenerationResult:
    """生成结果"""
    success: bool = False
    output_path: str = ""
    output_data: Optional[bytes] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration: float = 0.0
    seed_used: Optional[int] = None

class BaseGenerator(ABC):
    """
    生成器抽象基类
    
    定义统一的生成器接口，用于与不同的生成服务进行交互。
    所有具体的生成器实现都必须继承此类。
    """
    
    def __init__(self, generator_id: str, generator_type: GeneratorType, **kwargs):
        """初始化生成器
        
        Args:
            generator_id: 生成器唯一标识符
            generator_type: 生成器类型
            **kwargs: 其他配置参数
        """
        self.generator_id = generator_id
        self.generator_type = generator_type
        self.logger = logging.getLogger(f"{__name__}.{generator_id}")
        self._config = kwargs
        self._initialized = False
    
    def configure(self, **kwargs) -> None:
        """配置生成器
        
        Args:
            **kwargs: 配置参数
        """
        self._config.update(kwargs)
        self._initialized = True
    
    @abstractmethod
    def supports(self, config: GenerationConfig) -> bool:
        """检查是否支持指定的生成配置
        
        Args:
            config: 生成配置
            
        Returns:
            是否支持
        """
        pass
    
    @abstractmethod
    async def generate(self, config: GenerationConfig) -> GenerationResult:
        """执行生成
        
        Args:
            config: 生成配置
            
        Returns:
            生成结果
        """
        pass
    
    def _create_success_result(
        self,
        output_path: str = "",
        output_data: Optional[bytes] = None,
        metadata: Optional[Dict[str, Any]] = None,
        duration: float = 0.0,
        seed_used: Optional[int] = None,
    ) -> GenerationResult:
        """创建成功结果
        
        Args:
            output_path: 输出路径
            output_data: 输出数据
            metadata: 元数据
            duration: 耗时
            seed_used: 使用的种子
            
        Returns:
            生成结果
        """
        return GenerationResult(
            success=True,
            output_path=output_path,
            output_data=output_data,
            metadata=metadata or {},
            duration=duration,
            seed_used=seed_used,
        )
    
    def _create_error_result(
        self,
        error: str,
        metadata: Optional[Dict[str, Any]] = None,
        duration: float = 0.0,
    ) -> GenerationResult:
        """创建错误结果
        
        Args:
            error: 错误信息
            metadata: 元数据
            duration: 耗时
            
        Returns:
            生成结果
        """
        return GenerationResult(
            success=False,
            error=error,
            metadata=metadata or {},
            duration=duration,
        )
