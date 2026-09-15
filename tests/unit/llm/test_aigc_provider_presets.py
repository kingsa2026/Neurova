# -*- coding: utf-8 -*-
"""AIGC 服务商预置链路测试（先红后绿）：种子 → 能力检测 → 下拉数据源。"""
from neurova.llm.provider_manager import (
    LLMProviderManager,
    ProviderConfig,
    _BUILTIN_PROVIDER_DEFS,
)

_SEEDS = {d["id"]: d for d in _BUILTIN_PROVIDER_DEFS}


def test_agnes_gateways_seeded():
    assert "agnes-intl" in _SEEDS and _SEEDS["agnes-intl"]["base_url"] == "https://apihub.agnes-ai.com/v1"
    assert "agnes-cn" in _SEEDS and _SEEDS["agnes-cn"]["base_url"] == "https://api.agnes-ai.cn/v1"


def test_agnes_verified_image_models_present():
    for pid in ("agnes-intl", "agnes-cn"):
        models = _SEEDS[pid]["models"]
        assert "agnes-image-2.1-flash" in models and "agnes-image-2.0-flashv" in models


def test_agnes_verified_video_model_present():
    """2026-09-14 官方仓实核 agnes-video-v2.0 端点契约（/v1/videos +
    agnesapi?video_id 轮询）后解锁预置；能力检测须标 video_generation。"""
    from neurova.llm.capability_detector import infer_capabilities
    for pid in ("agnes-intl", "agnes-cn"):
        assert "agnes-video-v2.0" in _SEEDS[pid]["models"]
    assert "video_generation" in infer_capabilities("agnes-video-v2.0")


def test_volcengine_aigc_models_present():
    models = _SEEDS["volcengine"]["models"]
    assert "doubao-seedream-5-0-pro-260628" in models
    assert "doubao-seedance-2-5-260628" in models


def test_preset_models_carry_generation_capabilities():
    """预置模型必须被能力检测标成生成能力（否则 AIGC 下拉过滤后不可见）。"""
    from neurova.llm.capability_detector import infer_capabilities
    for pid in ("volcengine", "agnes-intl"):
        for m in _SEEDS[pid]["models"]:
            if "seedream" in m or "image" in m:
                assert "image_generation" in infer_capabilities(m), m
            if "seedance" in m:
                assert "video_generation" in infer_capabilities(m), m


def test_seed_merge_does_not_override_user(tmp_path):
    """用户已配 agnes-intl（自定义 base_url）时，种子只补缺失的 agnes-cn，不覆盖已有项。"""
    pm = LLMProviderManager.__new__(LLMProviderManager)
    pm._providers = {
        "agnes-intl": ProviderConfig(
            id="agnes-intl", name="用户自建", provider="openai",
            base_url="https://evil.example/v1", api_key="sk-user", models=[],
        )
    }
    pm._load_builtin_providers()
    assert pm._providers["agnes-intl"].base_url == "https://evil.example/v1"
    assert "agnes-cn" in pm._providers  # 缺失才补
