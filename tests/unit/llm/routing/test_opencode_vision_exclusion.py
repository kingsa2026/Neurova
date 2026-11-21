# -*- coding: utf-8 -*-
"""M4（多模态追平批一）：opencode 无 vision 声明 → 视觉轮路由候选必须排除。

现状核实：`opencode_provider.py` 的模型仅声明 TEXT+TOOL_USE（默认列表
显式如此；API 发现链路也不注入 vision）。本文件把「视觉请求类型的候选集
不含无 vision provider」钉成契约：

- REQUEST_TYPE_CAPABILITIES 映射：IMAGE_UNDERSTANDING 只认 VISION；
- LLMRouter.select_model：仅 TEXT+TOOL_USE 的 opencode 模型不进视觉候选；
- llm_routing_overlay.resolve_vision_capable_model：全库只有 opencode 时
  返回 None（不凭空造能力、不落到无 vision provider）。
"""

import pytest

from neurova.llm.llm_router import (
    LLMRouter,
    ModelCapability,
    RequestType,
    REQUEST_TYPE_CAPABILITIES,
)


@pytest.fixture(autouse=True)
def _isolatedRouter():
    """换掉全局单例，测试间互不污染（结束后恢复原单例）。"""
    original = LLMRouter._instance
    LLMRouter._instance = None
    yield
    LLMRouter._instance = original


def _registerOpencode(scope: str = "admin") -> None:
    """按 opencode_provider 的真实声明注册（TEXT+TOOL_USE，无 VISION）。"""
    router = LLMRouter()
    router.register_provider(
        "opencode",
        "OpenCode",
        [
            {
                "name": "mimo-v2.5-free",
                "capabilities": [ModelCapability.TEXT.value, ModelCapability.TOOL_USE.value],
                "priority": 10,  # 优先级最高：若过滤失效，它会赢下视觉轮选型
                "health_status": "healthy",
                "response_time": 0.0,
                "weight": 1.0,
            }
        ],
        scope=scope,
    )


class TestRequestTypeMapping:
    def test_imageUnderstandingRequiresVisionOnly(self):
        assert REQUEST_TYPE_CAPABILITIES[RequestType.IMAGE_UNDERSTANDING] == [
            ModelCapability.VISION
        ]


class TestRouterCandidateFiltering:
    def test_visionRound_skipsTextOnlyOpencode(self):
        _registerOpencode()

        selected = LLMRouter().select_model(RequestType.IMAGE_UNDERSTANDING, scope="admin")

        assert selected is None, f"视觉轮落到了无 vision 的 opencode：{selected}"

    def test_visionRound_candidateSetExcludesOpencode_evenWithHealthyHighPriority(self):
        """候选集断言：TEXT+TOOL_USE 模型无论优先级多高都不进视觉候选集。"""
        _registerOpencode()

        chat = LLMRouter().select_model(RequestType.CHAT, scope="admin")
        assert chat is not None and chat.provider_id == "opencode", "文本轮 opencode 应正常参选"
        vision = LLMRouter().select_model(RequestType.IMAGE_UNDERSTANDING, scope="admin")
        assert vision is None, "视觉轮必须排除 opencode（能力过滤，非健康/优先级问题）"

    def test_opencodeGainsVision_onlyThenEntersVisionCandidates(self):
        """对照：只有声明了 VISION 的模型才解禁——排除逻辑按能力位，不按 provider 名。"""
        router = LLMRouter()
        router.register_provider(
            "opencode",
            "OpenCode",
            [
                {
                    "name": "vision-variant-free",
                    "capabilities": [
                        ModelCapability.TEXT.value,
                        ModelCapability.TOOL_USE.value,
                        ModelCapability.VISION.value,
                    ],
                    "priority": 10,
                    "health_status": "healthy",
                    "response_time": 0.0,
                    "weight": 1.0,
                }
            ],
            scope="admin",
        )

        selected = router.select_model(RequestType.IMAGE_UNDERSTANDING, scope="admin")

        assert selected is not None and selected.provider_id == "opencode"


class TestVisionOverlay:
    def test_overlayFindsNothing_whenOnlyOpencodeExists(self, monkeypatch):
        from neurova.llm import llm_routing_overlay as overlay

        class _Provider:
            id = "opencode"
            priority = 10
            api_key = "k"
            encrypted_api_key = None
            models = ["mimo-v2.5-free"]
            default_model = "mimo-v2.5-free"
            model_metadata = {"mimo-v2.5-free": {"capabilities": ["text", "tool_use"]}}

        class _Manager:
            def list_providers(self, enabled_only=False):
                return [_Provider()]

        monkeypatch.setattr(overlay, "_get_provider_manager", lambda: _Manager())

        assert overlay.resolve_vision_capable_model("mimo-v2.5-free") is None, (
            "当前模型无 vision 且全库无候选：必须返回 None，不得落到 opencode 自己"
        )

    def test_overlay_skipsOpencode_whenAnotherVisionModelExists(self, monkeypatch):
        from neurova.llm import llm_routing_overlay as overlay

        class _Provider:
            id = "opencode"
            priority = 10
            api_key = "k"
            encrypted_api_key = None
            models = ["mimo-v2.5-free"]
            default_model = "mimo-v2.5-free"
            model_metadata = {"mimo-v2.5-free": {"capabilities": ["text", "tool_use"]}}

        class _VisionProvider:
            id = "openai"
            priority = 1
            api_key = "k"
            encrypted_api_key = None
            models = ["gpt-4o"]
            default_model = "gpt-4o"
            model_metadata = {"gpt-4o": {"capabilities": ["text", "vision"]}}

        class _Manager:
            def list_providers(self, enabled_only=False):
                return [_Provider(), _VisionProvider()]

        monkeypatch.setattr(overlay, "_get_provider_manager", lambda: _Manager())

        assert overlay.resolve_vision_capable_model("mimo-v2.5-free") == ("openai", "gpt-4o"), (
            "视觉轮应覆盖到有 vision 的 provider，而不是停在无 vision 的当前模型"
        )


class TestOpencodeDeclaration:
    def test_defaultModels_declareTextAndToolUseOnly(self):
        """声明核实（单一事实源）：opencode 默认模型能力位就地里核对。"""
        from neurova.llm.providers.opencode_provider import OpenCodeProvider

        models = OpenCodeProvider._FREE_DEFAULT_MODELS
        assert models, "默认列表不应为空"
        for model in models:
            names = [c.value if hasattr(c, "value") else str(c) for c in model.capabilities]
            assert "vision" not in names, f"{model.id} 意外声明了 vision"
            assert "text" in names and "tool_use" in names
