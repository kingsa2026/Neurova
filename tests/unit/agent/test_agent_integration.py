"""
Agent 集成测试 - LLMRouter + ContextPool 集成

测试内容:
1. _infer_capabilities_from_name - 模型名能力推断逻辑
2. Provider → LLMRouter 注册逻辑
3. _convert_history_for_model - 模型切换时上下文格式转换

注意: neurova.agent_core 存在循环导入问题（agent_core → agent/__init__ → agent_core），
因此本测试直接测试核心逻辑，不导入 Agent 类。
"""

import pytest
from unittest.mock import Mock, MagicMock
from neurova.llm.llm_router import LLMRouter, ModelCapability, RequestType
from neurova.context_pool import ContextConverter, ContextInput, ContextSource


# ===== 等价于 Agent._infer_capabilities_from_name 的独立函数 =====
def infer_capabilities_from_name(model_name: str) -> list:
    """根据模型名称推断其能力列表（与 Agent 中实现一致）"""
    name_lower = model_name.lower()
    caps = [ModelCapability.TEXT, ModelCapability.TOOL_USE]

    vision_keywords = ["vision", "vl", "multimodal", "gpt-4o", "gpt-4v",
                       "claude-3", "gemini", "qwen-vl", "internvl", "deepseek-vl"]
    if any(kw in name_lower for kw in vision_keywords):
        caps.append(ModelCapability.VISION)
        caps.append(ModelCapability.MULTIMODAL)

    audio_keywords = ["whisper", "audio", "speech", "tts", "stt"]
    if any(kw in name_lower for kw in audio_keywords):
        caps.append(ModelCapability.AUDIO)

    img_gen_keywords = ["dall-e", "stable-diffusion", "midjourney", "flux",
                        "image-generation", "img2img"]
    if any(kw in name_lower for kw in img_gen_keywords):
        caps.append(ModelCapability.IMAGE_GENERATION)

    vid_gen_keywords = ["video", "sora", "kling", "cogvideo", "runway"]
    if any(kw in name_lower for kw in vid_gen_keywords):
        caps.append(ModelCapability.VIDEO_GENERATION)

    return caps


# ===== 等价于 Agent._convert_history_for_model 的独立函数 =====
def convert_history_for_model(
    conversation_history: list,
    model_name: str,
    previous_model_anthropic: bool = False,
) -> tuple:
    """
    模型热切换时，将对话历史转换为新模型格式。
    
    返回: (converted_history, new_previous_model_anthropic)
    """
    if not conversation_history:
        return conversation_history, previous_model_anthropic

    converter = ContextConverter()
    is_anthropic = "claude" in model_name.lower() or "anthropic" in model_name.lower()
    was_anthropic = previous_model_anthropic

    if is_anthropic == was_anthropic:
        return conversation_history, is_anthropic

    converted_history = []
    for msg in conversation_history:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if is_anthropic and isinstance(content, list):
            converted_history.append(msg)
            continue
        if not is_anthropic and isinstance(content, str):
            converted_history.append(msg)
            continue

        source_map = {
            "system": ContextSource.SYSTEM_INSTRUCTION,
            "user": ContextSource.USER_INPUT,
            "assistant": ContextSource.CONVERSATION,
            "tool": ContextSource.TOOL_CALL,
        }
        source = source_map.get(role, ContextSource.CONVERSATION)

        # 从 Anthropic 列表格式中提取纯文本
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
                elif isinstance(part, str):
                    text_parts.append(part)
            text_content = "\n".join(text_parts) if text_parts else str(content)
        else:
            text_content = content

        ctx_input = ContextInput(
            source=source,
            content=text_content,
        )

        if is_anthropic:
            converted = converter.to_anthropic_format(ctx_input)
        else:
            converted = converter.to_openai_format(ctx_input)

        converted_history.append(converted)

    return converted_history, is_anthropic


class TestInferCapabilitiesFromName:
    """模型名能力推断测试"""

    def test_text_model(self):
        """纯文本模型"""
        caps = infer_capabilities_from_name("gpt-3.5-turbo")
        assert ModelCapability.TEXT in caps
        assert ModelCapability.TOOL_USE in caps
        assert ModelCapability.VISION not in caps

    def test_vision_model(self):
        """视觉模型"""
        caps = infer_capabilities_from_name("gpt-4o")
        assert ModelCapability.VISION in caps
        assert ModelCapability.MULTIMODAL in caps

    def test_claude_model(self):
        """Claude 模型"""
        caps = infer_capabilities_from_name("claude-3-opus-20240229")
        assert ModelCapability.VISION in caps
        assert ModelCapability.MULTIMODAL in caps

    def test_audio_model(self):
        """音频模型"""
        caps = infer_capabilities_from_name("whisper-large-v3")
        assert ModelCapability.AUDIO in caps

    def test_image_generation_model(self):
        """图像生成模型"""
        caps = infer_capabilities_from_name("dall-e-3")
        assert ModelCapability.IMAGE_GENERATION in caps

    def test_video_generation_model(self):
        """视频生成模型"""
        caps = infer_capabilities_from_name("sora-preview")
        assert ModelCapability.VIDEO_GENERATION in caps

    def test_qwen_vl(self):
        """通义千问视觉模型"""
        caps = infer_capabilities_from_name("Qwen2.5-VL-72B-Instruct")
        assert ModelCapability.VISION in caps
        assert ModelCapability.MULTIMODAL in caps

    def test_internvl(self):
        """InternVL 模型"""
        caps = infer_capabilities_from_name("InternVL2-8B")
        assert ModelCapability.VISION in caps

    def test_deepseek_coder(self):
        """DeepSeek Coder（不应有视觉能力）"""
        caps = infer_capabilities_from_name("deepseek-coder-33b-instruct")
        assert ModelCapability.TEXT in caps
        assert ModelCapability.VISION not in caps

    def test_all_models_have_text(self):
        """所有模型都应有 TEXT 和 TOOL_USE"""
        for name in ["gpt-4o", "whisper-large", "dall-e-3", "sora-preview", "random-model"]:
            caps = infer_capabilities_from_name(name)
            assert ModelCapability.TEXT in caps
            assert ModelCapability.TOOL_USE in caps


class TestProviderRegistration:
    """Provider → LLMRouter 注册逻辑测试"""

    def setup_method(self):
        LLMRouter._instance = None

    def _register_provider(
        self,
        provider_id: str,
        provider_name: str,
        main_model: str,
        extra_models: list = None,
    ):
        """模拟 Agent._sync_provider_to_llm_router 的注册逻辑"""
        router = LLMRouter()
        models = []

        caps = infer_capabilities_from_name(main_model)
        models.append({
            "name": main_model,
            "capabilities": [c.value for c in caps],
            "priority": 10,
            "health_status": "healthy",
            "response_time": 0.5,
        })

        extra_models = extra_models or []
        for em in extra_models:
            model_name = em.get("name", "") if isinstance(em, dict) else str(em)
            if model_name and model_name != main_model:
                caps = infer_capabilities_from_name(model_name)
                models.append({
                    "name": model_name,
                    "capabilities": [c.value for c in caps],
                    "priority": em.get("priority", 5) if isinstance(em, dict) else 5,
                    "health_status": "healthy",
                    "response_time": 0.5,
                })

        router.register_provider(
            provider_id=provider_id,
            provider_name=provider_name,
            models=models,
        )

    def test_register_main_model(self):
        """注册主模型"""
        self._register_provider("openai", "OpenAI", "gpt-4o")

        router = LLMRouter()
        providers = router.list_providers()
        assert len(providers) == 1
        assert providers[0]["provider_id"] == "openai"
        assert len(providers[0]["models"]) == 1
        assert providers[0]["models"][0]["name"] == "gpt-4o"

    def test_register_with_extra_models(self):
        """注册主模型 + 额外模型"""
        self._register_provider(
            "siliconflow", "SiliconFlow", "deepseek-ai/DeepSeek-V3",
            extra_models=[
                {"name": "Qwen/Qwen2.5-VL-72B-Instruct", "priority": 7},
            ],
        )

        router = LLMRouter()
        providers = router.list_providers()
        models = providers[0]["models"]
        assert len(models) == 2
        model_names = [m["name"] for m in models]
        assert "deepseek-ai/DeepSeek-V3" in model_names
        assert "Qwen/Qwen2.5-VL-72B-Instruct" in model_names

    def test_router_selects_after_sync(self):
        """注册后 LLMRouter 能正确选择模型"""
        self._register_provider("openai", "OpenAI", "gpt-4o")

        router = LLMRouter()
        result = router.select_model(RequestType.IMAGE_UNDERSTANDING)
        assert result is not None
        assert result.model == "gpt-4o"
        assert ModelCapability.VISION in result.capabilities

    def test_priority_affects_selection(self):
        """高优先级模型优先被选中"""
        router = LLMRouter()
        router.register_provider("low", "LowPri", [{
            "name": "cheap-model",
            "capabilities": ["text"],
            "priority": 5,
            "health_status": "healthy",
        }])
        router.register_provider("high", "HighPri", [{
            "name": "premium-model",
            "capabilities": ["text", "vision"],
            "priority": 20,
            "health_status": "healthy",
        }])

        result = router.select_model(RequestType.IMAGE_UNDERSTANDING)
        assert result.model == "premium-model"
        assert result.priority == 20


class TestConvertHistoryForModel:
    """模型切换时上下文格式转换测试"""

    def test_openai_to_anthropic(self):
        """OpenAI → Anthropic 格式转换"""
        history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！有什么可以帮你的？"},
        ]

        converted, is_anthropic = convert_history_for_model(history, "claude-3-opus")

        assert is_anthropic is True
        assert isinstance(converted[0]["content"], list)
        assert isinstance(converted[1]["content"], list)
        assert converted[0]["content"][0]["type"] == "text"
        assert converted[0]["content"][0]["text"] == "你好"

    def test_anthropic_to_openai(self):
        """Anthropic → OpenAI 格式转换"""
        history = [
            {"role": "user", "content": [{"type": "text", "text": "你好"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "你好！"}]},
        ]

        converted, is_anthropic = convert_history_for_model(
            history, "gpt-4o", previous_model_anthropic=True
        )

        assert is_anthropic is False
        assert isinstance(converted[0]["content"], str)
        assert isinstance(converted[1]["content"], str)
        assert converted[0]["content"] == "你好"

    def test_no_conversion_same_type(self):
        """同类型模型不需要转换"""
        history = [{"role": "user", "content": "你好"}]

        converted, _ = convert_history_for_model(history, "gpt-3.5-turbo")

        assert isinstance(converted[0]["content"], str)
        assert converted[0]["content"] == "你好"

    def test_empty_history(self):
        """空历史不报错"""
        converted, _ = convert_history_for_model([], "claude-3-opus")
        assert converted == []

    def test_system_role_preserved(self):
        """system 角色消息正确转换"""
        history = [
            {"role": "system", "content": "你是一个助手"},
            {"role": "user", "content": "你好"},
        ]

        converted, _ = convert_history_for_model(history, "claude-3-opus")

        # system 消息也应转换为列表格式
        assert isinstance(converted[0]["content"], list)
        assert converted[0]["content"][0]["text"] == "你是一个助手"

    def test_convert_then_convert_back(self):
        """来回转换保持一致性"""
        original = [
            {"role": "user", "content": "测试消息"},
            {"role": "assistant", "content": "回复内容"},
        ]

        # OpenAI → Anthropic
        step1, _ = convert_history_for_model(original, "claude-3-opus")
        assert isinstance(step1[0]["content"], list)

        # Anthropic → OpenAI
        step2, _ = convert_history_for_model(step1, "gpt-4o", previous_model_anthropic=True)
        assert isinstance(step2[0]["content"], str)
        assert step2[0]["content"] == "测试消息"

    def test_mixed_content_types(self):
        """混合内容类型（str + list）的处理"""
        history = [
            {"role": "user", "content": "文本消息"},
            {"role": "assistant", "content": [{"type": "text", "text": "已经是列表格式"}]},
        ]

        converted, _ = convert_history_for_model(history, "claude-3-opus")

        # str 应转换为 list
        assert isinstance(converted[0]["content"], list)
        # list 保持不变
        assert isinstance(converted[1]["content"], list)
