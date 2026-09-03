"""
LLM Router 单元测试

测试内容:
1. RequestType 枚举
2. ModelCapability 枚举
3. LLMRouter 单例类
4. select_model_for_request() 函数
5. detect_request_type() 函数
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from neurova.llm.llm_router import (
    RequestType,
    ModelCapability,
    ModelSelectionResult,
    LLMRouter,
    select_model_for_request,
    detect_request_type,
)


class TestRequestType:
    """RequestType 枚举测试"""
    
    def test_request_type_values(self):
        """测试 RequestType 枚举值"""
        assert RequestType.CHAT.value == "chat"
        assert RequestType.IMAGE_UNDERSTANDING.value == "image_understanding"
        assert RequestType.AUDIO_UNDERSTANDING.value == "audio_understanding"
        assert RequestType.VIDEO_UNDERSTANDING.value == "video_understanding"
        assert RequestType.TEXT_TO_IMAGE.value == "text_to_image"
        assert RequestType.IMAGE_TO_IMAGE.value == "image_to_image"
        assert RequestType.TEXT_TO_VIDEO.value == "text_to_video"
        assert RequestType.IMAGE_TO_VIDEO.value == "image_to_video"
        assert RequestType.TEXT_TO_SPEECH.value == "text_to_speech"
        assert RequestType.SPEECH_TO_TEXT.value == "speech_to_text"
    
    def test_request_type_members(self):
        """测试 RequestType 枚举成员数量"""
        assert len(RequestType) == 10


class TestModelCapability:
    """ModelCapability 枚举测试"""
    
    def test_capability_values(self):
        """测试 ModelCapability 枚举值"""
        assert ModelCapability.TEXT.value == "text"
        assert ModelCapability.VISION.value == "vision"
        assert ModelCapability.AUDIO.value == "audio"
        assert ModelCapability.VIDEO.value == "video"
        assert ModelCapability.IMAGE_GENERATION.value == "image_generation"
        assert ModelCapability.VIDEO_GENERATION.value == "video_generation"
        assert ModelCapability.TTS.value == "tts"
        assert ModelCapability.STT.value == "stt"
        assert ModelCapability.MULTIMODAL.value == "multimodal"
        assert ModelCapability.TOOL_USE.value == "tool_use"
    
    def test_capability_members(self):
        """测试 ModelCapability 枚举成员数量（2026-09-03 新增 REASONING）"""
        assert len(ModelCapability) == 11
        assert ModelCapability.REASONING.value == "reasoning"


class TestModelSelectionResult:
    """ModelSelectionResult 数据类测试"""
    
    def test_creation(self):
        """测试创建 ModelSelectionResult"""
        result = ModelSelectionResult(
            provider_id="openai",
            provider_name="OpenAI",
            model="gpt-4o",
            capabilities=[ModelCapability.TEXT, ModelCapability.VISION],
            priority=10,
            health_status="healthy",
            response_time=0.5,
            weight=1.0
        )
        
        assert result.provider_id == "openai"
        assert result.provider_name == "OpenAI"
        assert result.model == "gpt-4o"
        assert ModelCapability.TEXT in result.capabilities
        assert ModelCapability.VISION in result.capabilities
        assert result.priority == 10
        assert result.health_status == "healthy"
        assert result.response_time == 0.5
        assert result.weight == 1.0
    
    def test_default_values(self):
        """测试默认值"""
        result = ModelSelectionResult(
            provider_id="test",
            provider_name="Test",
            model="test-model"
        )
        
        assert result.capabilities == []
        assert result.priority == 0
        assert result.health_status == "unknown"
        assert result.response_time == 0.0
        assert result.weight == 1.0


class TestLLMRouter:
    """LLMRouter 单例类测试"""
    
    def setup_method(self):
        """测试前重置单例"""
        LLMRouter._instance = None
    
    def test_singleton(self):
        """测试单例模式"""
        router1 = LLMRouter()
        router2 = LLMRouter()
        assert router1 is router2
    
    def test_register_provider(self):
        """测试注册提供商"""
        router = LLMRouter()
        
        # 注册一个提供商
        router.register_provider(
            provider_id="openai",
            provider_name="OpenAI",
            models=[
                {
                    "name": "gpt-4o",
                    "capabilities": ["text", "vision"],
                    "priority": 10,
                    "health_status": "healthy",
                    "response_time": 0.5
                },
                {
                    "name": "gpt-3.5-turbo",
                    "capabilities": ["text"],
                    "priority": 5,
                    "health_status": "healthy",
                    "response_time": 0.2
                }
            ]
        )
        
        # 验证注册成功
        providers = router.list_providers()
        assert len(providers) == 1
        assert providers[0]["provider_id"] == "openai"
        assert len(providers[0]["models"]) == 2
    
    def test_select_model_for_chat(self):
        """测试为聊天请求选择模型"""
        router = LLMRouter()
        
        # 注册提供商
        router.register_provider(
            provider_id="openai",
            provider_name="OpenAI",
            models=[
                {
                    "name": "gpt-4o",
                    "capabilities": ["text", "vision"],
                    "priority": 10,
                    "health_status": "healthy",
                    "response_time": 0.5
                }
            ]
        )
        
        # 选择聊天模型
        result = router.select_model(RequestType.CHAT)
        
        assert result is not None
        assert result.model == "gpt-4o"
        assert result.provider_id == "openai"
        assert ModelCapability.TEXT in result.capabilities
    
    def test_select_model_for_image_understanding(self):
        """测试为图像理解选择模型"""
        router = LLMRouter()
        
        # 注册提供商
        router.register_provider(
            provider_id="openai",
            provider_name="OpenAI",
            models=[
                {
                    "name": "gpt-4o",
                    "capabilities": ["text", "vision"],
                    "priority": 10,
                    "health_status": "healthy",
                    "response_time": 0.5
                }
            ]
        )
        
        # 选择图像理解模型
        result = router.select_model(RequestType.IMAGE_UNDERSTANDING)
        
        assert result is not None
        assert result.model == "gpt-4o"
        assert ModelCapability.VISION in result.capabilities
    
    def test_select_model_with_no_providers(self):
        """测试没有提供商时的选择"""
        router = LLMRouter()
        
        result = router.select_model(RequestType.CHAT)
        assert result is None
    
    def test_select_model_with_unhealthy_provider(self):
        """测试不健康提供商的选择"""
        router = LLMRouter()
        
        # 注册不健康的提供商
        router.register_provider(
            provider_id="openai",
            provider_name="OpenAI",
            models=[
                {
                    "name": "gpt-4o",
                    "capabilities": ["text"],
                    "priority": 10,
                    "health_status": "unhealthy",
                    "response_time": 5.0
                }
            ]
        )
        
        # 应该跳过不健康的提供商
        result = router.select_model(RequestType.CHAT)
        assert result is None
    
    def test_select_model_with_priority(self):
        """测试优先级选择"""
        router = LLMRouter()
        
        # 注册多个提供商
        router.register_provider(
            provider_id="openai",
            provider_name="OpenAI",
            models=[
                {
                    "name": "gpt-3.5-turbo",
                    "capabilities": ["text"],
                    "priority": 5,
                    "health_status": "healthy",
                    "response_time": 0.2
                }
            ]
        )
        
        router.register_provider(
            provider_id="anthropic",
            provider_name="Anthropic",
            models=[
                {
                    "name": "claude-3-opus",
                    "capabilities": ["text", "vision"],
                    "priority": 20,
                    "health_status": "healthy",
                    "response_time": 0.8
                }
            ]
        )
        
        # 应该选择更高优先级的模型
        result = router.select_model(RequestType.CHAT)
        assert result.model == "claude-3-opus"
        assert result.priority == 20
    
    def test_unregister_provider(self):
        """测试注销提供商"""
        router = LLMRouter()
        
        # 注册提供商
        router.register_provider(
            provider_id="openai",
            provider_name="OpenAI",
            models=[{"name": "gpt-4o", "capabilities": ["text"]}]
        )
        
        # 注销提供商
        router.unregister_provider("openai")
        
        # 验证注销成功
        providers = router.list_providers()
        assert len(providers) == 0


class TestSelectModelForRequest:
    """select_model_for_request() 函数测试"""
    
    def setup_method(self):
        """测试前重置单例"""
        LLMRouter._instance = None
    
    def test_select_model_for_request(self):
        """测试便捷函数"""
        # 注册提供商
        router = LLMRouter()
        router.register_provider(
            provider_id="openai",
            provider_name="OpenAI",
            models=[
                {
                    "name": "gpt-4o",
                    "capabilities": ["text", "vision"],
                    "priority": 10,
                    "health_status": "healthy"
                }
            ]
        )
        
        # 使用便捷函数
        result = select_model_for_request(RequestType.IMAGE_UNDERSTANDING)
        
        assert result is not None
        assert result.model == "gpt-4o"
        assert ModelCapability.VISION in result.capabilities


class TestDetectRequestType:
    """detect_request_type() 函数测试"""
    
    def test_detect_text_only(self):
        """检测纯文本"""
        result = detect_request_type("Hello, how are you?")
        assert result == RequestType.CHAT
    
    def test_detect_image_description(self):
        """检测图像描述"""
        result = detect_request_type("[用户发送了一张图片: test.jpg] 告诉我这是什么")
        assert result == RequestType.IMAGE_UNDERSTANDING
    
    def test_detect_audio_description(self):
        """检测音频描述"""
        result = detect_request_type("[用户发送了一段语音消息] 请转录这段语音")
        assert result == RequestType.AUDIO_UNDERSTANDING
    
    def test_detect_video_description(self):
        """检测视频描述"""
        result = detect_request_type("[用户发送了一个视频] 分析这个视频内容")
        assert result == RequestType.VIDEO_UNDERSTANDING
    
    def test_detect_image_generation_request(self):
        """检测图像生成请求"""
        result = detect_request_type("生成一张猫的图片")
        assert result == RequestType.TEXT_TO_IMAGE
    
    def test_detect_video_generation_request(self):
        """检测视频生成请求"""
        result = detect_request_type("制作一个关于海洋的视频")
        assert result == RequestType.TEXT_TO_VIDEO
    
    def test_detect_speech_request(self):
        """检测语音合成请求"""
        result = detect_request_type("请用语音读出这段文字")
        assert result == RequestType.TEXT_TO_SPEECH