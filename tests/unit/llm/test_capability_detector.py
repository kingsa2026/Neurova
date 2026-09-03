"""
模型能力自动检测器测试（2026-09-03）

用户需求（模型管理）：自动检测模型能力（文本、推理、图片理解、视频理解、
图片生成、视频生成）作为标记并持久化。

能力词表（canonical，字符串值与 ProviderCapability/ModelCapability 对齐）：
- text             文本
- reasoning        推理
- vision           图片理解
- video            视频理解
- image_generation 图片生成
- video_generation 视频生成
（audio/tts/stt/tool_use 保持兼容，继续支持）

检测策略（诚实的自动检测，不伪造）：
1. 显式元数据（已持久化/发现链路写入）优先；
2. 已知模型目录（精确/前缀匹配）；
3. 名称关键词启发式兜底。
"""

import pytest

from neurova.llm.capability_detector import (
    CAPABILITY_ORDER,
    detect_model_capabilities,
    infer_capabilities,
)


class TestInferRules:
    """六类核心能力的名称推断规则。"""

    def test_known_reasoning_models(self):
        for m in ["deepseek-r1", "deepseek-reasoner", "o1-mini", "o3", "qwq-32b-preview", "glm-z1-air"]:
            caps = infer_capabilities(m)
            assert "reasoning" in caps, f"{m} 应检出推理能力"
            assert "text" in caps

    def test_thinking_suffix_means_reasoning(self):
        assert "reasoning" in infer_capabilities("gemini-2.5-pro-thinking")
        assert "reasoning" in infer_capabilities("qwen3-235b-a22b-thinking")

    def test_known_vision_models(self):
        for m in ["qwen-vl-max", "glm-4v-flash", "gpt-4o", "llava-13b", "internvl2-8b"]:
            assert "vision" in infer_capabilities(m), m

    def test_vision_keyword_patterns(self):
        assert "vision" in infer_capabilities("pixtral-12b-vision")
        assert "vision" in infer_capabilities("deepseek-vl2")

    def test_known_image_generation_models(self):
        for m in ["dall-e-3", "stable-diffusion-3.5-large", "flux.1-dev", "imagen-3.0-generate-002", "seedream-3.0", "cogview-3-plus"]:
            caps = infer_capabilities(m)
            assert "image_generation" in caps, f"{m} 应检出图片生成"

    def test_known_video_generation_models(self):
        for m in ["sora-2", "veo-3.1-generate-preview", "kling-v2-master", "cogvideox-5b", "wan2.2-t2v-a14b", "t2v-turbo"]:
            caps = infer_capabilities(m)
            assert "video_generation" in caps, f"{m} 应检出视频生成"

    def test_video_word_without_generation_signals_is_understanding(self):
        # "video" 命中但无生成信号（t2v/i2v/sora 等）→ 视频理解
        caps = infer_capabilities("video-llava-7b")
        assert "video" in caps
        assert "video_generation" not in caps

    def test_plain_chat_model_is_text_only(self):
        # deepseek-chat 已核准带 tool_use，纯文本样本改用无信号模型
        caps = infer_capabilities("some-plain-chat-7b")
        assert caps == ["text"] or set(caps) == {"text"}

    def test_generation_only_model_has_no_text(self):
        # 纯生成模型不应标记文本对话能力
        caps = infer_capabilities("dall-e-3")
        assert "text" not in caps
        assert "image_generation" in caps

    def test_audio_models(self):
        assert "audio" in infer_capabilities("whisper-large-v3")
        assert "stt" in infer_capabilities("whisper-large-v3")
        assert "tts" in infer_capabilities("cosyvoice-v2")

    def test_display_name_fallback(self):
        # id 无信号时用显示名兜底
        assert "vision" in infer_capabilities("some-internal-id-01", display_name="通义千问视觉理解版")
        assert "reasoning" in infer_capabilities("some-internal-id-02", display_name="DeepSeek 推理模型")

    def test_empty_name_gets_text_default(self):
        assert infer_capabilities("") == ["text"]

    def test_catalog_priority_over_keyword(self):
        # 已知目录优先：deepseek-r1 命中 reasoning 目录；不会因 "r1" 误判
        caps = infer_capabilities("deepseek-r1-distill-qwen-32b")
        assert "reasoning" in caps


class TestDetectWithExisting:
    """已有显式能力（持久化元数据/发现链路）优先于推断。"""

    def test_existing_metadata_wins(self):
        caps = detect_model_capabilities("deepseek-chat", existing=["text", "vision"])
        assert caps == ["text", "vision"]

    def test_existing_empty_falls_back_to_infer(self):
        caps = detect_model_capabilities("deepseek-r1", existing=[])
        assert "reasoning" in caps

    def test_existing_none_falls_back_to_infer(self):
        caps = detect_model_capabilities("qwen-vl-max", existing=None)
        assert "vision" in caps

    def test_order_canonical(self):
        caps = detect_model_capabilities("x", existing=["vision", "text", "reasoning"])
        assert caps == sorted(caps, key=CAPABILITY_ORDER.index)


class TestCapabilityOrder:
    """canonical 排序覆盖六类核心能力。"""

    def test_core_six_in_order(self):
        for cap in ["text", "reasoning", "vision", "video", "image_generation", "video_generation"]:
            assert cap in CAPABILITY_ORDER


# ===========================================================================
# 能力目录核准（2026-09-03 第二轮：用户点名误判 + 厂商全族补全 + 限额预埋）
# ===========================================================================

import pytest

from neurova.llm.capability_detector import (
    MODEL_PRESETS,
    apply_preset_defaults,
    lookup_model_preset,
)


class TestUserNamedModels:
    """用户实测点名的新代模型：现行检测误判，锁定修正后行为。"""

    def test_glm_5_3_flash(self):
        """GLM-5.3 系为混合思考模型：必须带推理+工具。"""
        caps = detect_model_capabilities("glm-5.3-flash")
        assert "reasoning" in caps
        assert "tool_use" in caps
        assert "text" in caps

    def test_deepseek_v4_flash_vision_exp(self):
        """deepseek-v4 系支持函数调用；vision 变体须带图片理解。"""
        caps = detect_model_capabilities("deepseek-v4-flash-vision-exp")
        assert "vision" in caps
        assert "tool_use" in caps
        assert "text" in caps


class TestVendorCatalog:
    """厂商全族覆盖核准：Kimi/MiniMax/Qwen/GLM/Gemini/商汤/美团/小米/豆包/百度/京东。"""

    # -- Kimi / Moonshot --
    def test_kimi_k2(self):
        assert "tool_use" in detect_model_capabilities("kimi-k2-0905-preview")

    def test_moonshot_v1_sizes(self):
        p = lookup_model_preset("moonshot-v1-128k")
        assert p and p.context_window == 131_072
        assert "tool_use" in detect_model_capabilities("moonshot-v1-8k")

    def test_kimi_vision_variants(self):
        assert "vision" in detect_model_capabilities("kimi-vl-a3b-thinking")
        assert "vision" in detect_model_capabilities("moonshot-v1-8k-vision-preview")

    # -- MiniMax --
    def test_minimax_m1(self):
        caps = detect_model_capabilities("MiniMax-M1-80k")
        assert "reasoning" in caps
        p = lookup_model_preset("minimax-m1-80k")
        assert p and p.context_window == 1_000_000 and p.max_tokens == 40_960

    def test_minimax_video_and_tts(self):
        assert "video_generation" in detect_model_capabilities("hailuo-02")
        assert "video_generation" in detect_model_capabilities("minimax-video-01")
        assert "tts" in detect_model_capabilities("speech-02-hd")

    # -- Qwen --
    def test_qwen_ctx_max(self):
        assert lookup_model_preset("qwen-long").context_window == 10_000_000
        p = lookup_model_preset("qwen-plus-latest")
        assert p and p.context_window == 131_072 and p.max_tokens == 8_192

    def test_qwen_specialists(self):
        assert "image_generation" in detect_model_capabilities("qwen-image")
        assert "audio" in detect_model_capabilities("qwen2.5-omni")
        assert "video" in detect_model_capabilities("qwen2.5-vl-72b-instruct")
        assert "reasoning" in detect_model_capabilities("qvq-max")

    # -- GLM --
    def test_glm_family(self):
        assert lookup_model_preset("glm-4-plus").context_window == 131_072
        assert lookup_model_preset("glm-4-plus").max_tokens == 4_095
        assert "reasoning" in detect_model_capabilities("glm-4.6")
        assert "vision" in detect_model_capabilities("glm-4.5v")
        assert "reasoning" in detect_model_capabilities("glm-4.5-flash")

    # -- Gemini --
    def test_gemini_3(self):
        caps = detect_model_capabilities("gemini-3-pro-preview")
        assert "vision" in caps and "audio" in caps and "video" in caps

    def test_gemini_25_limits(self):
        p = lookup_model_preset("gemini-2.5-pro")
        assert p and p.context_window == 1_048_576 and p.max_tokens == 65_536

    # -- 商汤 SenseNova --
    def test_sensenova(self):
        assert "tool_use" in detect_model_capabilities("sensechat-5")
        assert "vision" in detect_model_capabilities("sensechat-vision-5")

    # -- 美团 LongCat --
    def test_longcat(self):
        assert "tool_use" in detect_model_capabilities("LongCat-Flash-Chat")
        caps = detect_model_capabilities("LongCat-Video")
        assert "video_generation" in caps
        # 生成模型不得同时误标视频理解
        assert "video" not in caps

    # -- 小米 MiMo --
    def test_mimo(self):
        assert "reasoning" in detect_model_capabilities("MiMo-7B-RL")
        assert "vision" in detect_model_capabilities("MiMo-VL-7B-RL")

    # -- 豆包 / 字节 --
    def test_doubao(self):
        assert "reasoning" in detect_model_capabilities("doubao-seed-1.6")
        assert lookup_model_preset("doubao-pro-256k").context_window == 262_144
        assert "video_generation" in detect_model_capabilities("seedance-1-lite")

    # -- 百度 ERNIE --
    def test_ernie(self):
        assert "reasoning" in detect_model_capabilities("ernie-x1-turbo-32k")
        assert "tool_use" in detect_model_capabilities("ernie-4.5-turbo-128k")
        assert "vision" in detect_model_capabilities("ernie-4.5-vl-28b")

    # -- 京东 --
    def test_jd_joyai(self):
        # 京东 JoyAI/言犀：登记为已知族，能力不做虚假标注（文本基线）
        assert detect_model_capabilities("joyai-xl") == ["text"]
        assert detect_model_capabilities("yanxi-chat") == ["text"]

    # -- OpenAI 补全 --
    def test_gpt5_and_oss(self):
        caps = detect_model_capabilities("gpt-5")
        assert "reasoning" in caps and "vision" in caps and "tool_use" in caps
        assert "reasoning" in detect_model_capabilities("gpt-oss-120b")
        assert lookup_model_preset("gpt-5").context_window == 400_000

    # -- ASR 补全（项目本地 ASR 同源） --
    def test_asr_models(self):
        assert "stt" in detect_model_capabilities("sensevoice-small")
        assert "stt" in detect_model_capabilities("paraformer-zh")


class TestPresetDefaults:
    """预埋限额：服务商自有值首选，缺失才由 预埋目录/model_limits 兜底。"""

    def test_fills_missing_fields(self):
        entry = apply_preset_defaults("minimax-m1-80k", {"name": "MiniMax M1"})
        assert entry["context_window"] == 1_000_000
        assert entry["max_tokens"] == 40_960
        assert "reasoning" in entry["capabilities"]

    def test_provider_values_win(self):
        """服务商预设参数为首选：已有值一律不覆盖。"""
        entry = apply_preset_defaults(
            "minimax-m1-80k", {"context_window": 123_456, "max_tokens": 777}
        )
        assert entry["context_window"] == 123_456
        assert entry["max_tokens"] == 777

    def test_model_limits_exact_beats_family_preset(self):
        """model_limits.MODEL_MAX_TOKENS 精确表（服务商文档维护）优先于族级预埋。"""
        entry = apply_preset_defaults("deepseek-v4-flash", {})
        assert entry["max_tokens"] == 65_536  # 来自 model_limits 精确条目

    def test_4096_placeholder_treated_as_unset(self):
        """ModelInfo 默认值 4096 不是真实限额，视为未设置。"""
        entry = apply_preset_defaults("minimax-m1-80k", {"context_window": 4096})
        assert entry["context_window"] == 1_000_000

    def test_unknown_model_untouched(self):
        entry = apply_preset_defaults("totally-unknown-model", {"context_window": 8_000})
        assert entry["context_window"] == 8_000
        assert "context_window" not in apply_preset_defaults("totally-unknown-model", {})

    def test_presets_table_has_metadata_for_core_entries(self):
        for key in ["glm-5.3", "deepseek-v4", "kimi-k2", "minimax-m1", "doubao-seed-1.6"]:
            assert key in MODEL_PRESETS, f"{key} 应在预埋目录中"
