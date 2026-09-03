from __future__ import annotations

"""
模型能力自动检测器

用户需求：模型管理中自动检测模型能力（文本、推理、图片理解、视频理解、
图片生成、视频生成）作为标记（持久化），供 AIGC 页面下拉过滤与 LLMRouter
自动路由消费。

能力词表（canonical，字符串值与 ProviderCapability/ModelCapability 对齐）：
    text / reasoning / vision / video / image_generation / video_generation
    （audio / tts / stt / tool_use 兼容保留）

检测策略（三层，诚实的自动检测，不伪造）：
1. 显式元数据（provider.model_metadata 持久化 / OpenRouter 发现链路写入）优先；
2. 已知模型目录（前缀精确段匹配，覆盖主流视觉/推理/生成模型族）；
3. 名称关键词启发式兜底。

生成类信号判定：名称含 t2v/i2v/sora/veo/kling 等生成信号才算 video_generation，
仅有 "video" 字样视为视频理解 —— 避免把 video-llava 误标成视频生成。
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

# canonical 能力排序（前端标签与下拉按此序展示）
CAPABILITY_ORDER: List[str] = [
    "text",
    "reasoning",
    "vision",
    "video",
    "image_generation",
    "video_generation",
    "audio",
    "tts",
    "stt",
    "tool_use",
    "multimodal",
]

_KNOWN_CAPS = frozenset(CAPABILITY_ORDER)

# ---------------------------------------------------------------------------
# 已知模型预埋目录（2026-09-03 核准扩充）
#
# 每条 = 能力 + 上下文窗口 + 最大输出 token 三元组。取值顺序（用户契约）：
#   服务商发现/配置的真实值（首选） > model_limits.MODEL_MAX_TOKENS 精确表
#   > 本目录族级预埋（兜底）。预埋值仅在后两者缺位时落库。
#
# 依据：各服务商官方文档 + HuggingFace 模型卡；后于知识截止的新模型
# （glm-5.x / deepseek-v4 等）按命名族规约推断能力，限额留空不杜撰。
# 键为族前缀，段边界匹配（"deepseek-r1" 不误吃 "deepseek-r2"）。
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ModelPreset:
    """模型预埋档案：能力 + 限额兜底值（None = 未知，不落库）。"""

    capabilities: Tuple[str, ...] = ()
    context_window: Optional[int] = None
    max_tokens: Optional[int] = None


MODEL_PRESETS: dict[str, ModelPreset] = {
    # --- OpenAI ---
    "gpt-5": ModelPreset(("reasoning", "vision", "tool_use"), 400_000, 128_000),
    "gpt-4o": ModelPreset(("vision", "tool_use"), 128_000, 16_384),
    "gpt-4.1": ModelPreset(("vision", "tool_use"), 1_047_576, 32_768),
    "gpt-4-turbo": ModelPreset(("vision", "tool_use"), 131_072, 4_096),
    "gpt-4": ModelPreset(("tool_use",), 8_192, 8_192),
    "gpt-3.5-turbo": ModelPreset(("tool_use",), 16_385, 4_096),
    "gpt-oss": ModelPreset(("reasoning", "tool_use"), 131_072),
    "o1": ModelPreset(("reasoning",), 204_800, 100_000),
    "o3": ModelPreset(("reasoning",), 204_800, 100_000),
    "o4-mini": ModelPreset(("reasoning",), 204_800, 100_000),
    # --- Anthropic ---
    "claude-3-5": ModelPreset(("vision", "tool_use"), 200_000, 8_192),
    "claude-3": ModelPreset(("vision", "tool_use"), 200_000, 4_096),
    "claude-sonnet-4": ModelPreset(("vision", "tool_use"), 200_000, 64_000),
    "claude-opus-4": ModelPreset(("vision", "tool_use"), 200_000, 32_000),
    # --- Google Gemini ---
    "gemini-3": ModelPreset(("vision", "audio", "video", "tool_use"), 1_048_576, 65_536),
    "gemini-2.5": ModelPreset(("vision", "audio", "video", "tool_use"), 1_048_576, 65_536),
    "gemini-2.0": ModelPreset(("vision", "audio", "video", "tool_use"), 1_048_576, 8_192),
    "gemini-1.5": ModelPreset(("vision", "audio", "video", "tool_use"), 1_048_576, 8_192),
    # --- DeepSeek ---
    "deepseek-r1": ModelPreset(("reasoning",), 65_536, 8_192),
    "deepseek-reasoner": ModelPreset(("reasoning",), 65_536, 8_192),
    "deepseek-v4": ModelPreset(("tool_use",)),          # vision/think 变体由名称信号补
    "deepseek-v3.1": ModelPreset(("reasoning", "tool_use")),  # 3.1 起混合思考
    "deepseek-v3": ModelPreset(("tool_use",)),
    "deepseek-chat": ModelPreset(("tool_use",), 65_536, 8_192),
    "janus-pro": ModelPreset(("vision", "image_generation")),
    # --- 智谱 GLM ---
    "glm-5.3": ModelPreset(("reasoning", "tool_use")),  # GLM-5 系混合思考（含 flash）
    "glm-5": ModelPreset(("reasoning", "tool_use")),
    "glm-4.6": ModelPreset(("reasoning", "tool_use"), 204_800, 131_072),
    "glm-4.5v": ModelPreset(("vision",), 65_536),
    "glm-4.5": ModelPreset(("reasoning", "tool_use"), 131_072, 98_304),
    "glm-4v": ModelPreset(("vision",), 131_072),
    "glm-4": ModelPreset(("tool_use",), 131_072, 4_095),
    "glm-3-turbo": ModelPreset(("tool_use",), 131_072, 2_048),
    "glm-z1": ModelPreset(("reasoning",)),
    # --- 通义 Qwen ---
    "qwen-long": ModelPreset(("tool_use",), 10_000_000),
    "qvq": ModelPreset(("vision", "reasoning")),
    "qwen-vl": ModelPreset(("vision", "video")),        # qwen-vl 系支持视频输入
    "qwen2.5-vl": ModelPreset(("vision", "video"), 131_072),
    "qwen3-vl": ModelPreset(("vision", "video")),
    "qwen2.5-omni": ModelPreset(("vision", "audio", "tts"), 131_072),
    "qwen-omni": ModelPreset(("vision", "audio", "tts")),
    "qwen-audio": ModelPreset(("audio",)),
    "qwen-image": ModelPreset(("image_generation",)),
    "qwen-turbo": ModelPreset(("tool_use",), 1_000_000),
    "qwen-plus": ModelPreset(("tool_use",), 131_072, 8_192),
    "qwen-max": ModelPreset(("tool_use",), 32_768, 8_192),
    "qwen3": ModelPreset(("tool_use",)),                # 混合思考，-thinking 变体由信号补
    "qwq": ModelPreset(("reasoning",), 131_072),
    # --- Kimi / Moonshot ---
    "kimi-k2": ModelPreset(("tool_use",), 262_144),
    "kimi-latest": ModelPreset(("vision",)),
    "kimi-vl": ModelPreset(("vision",)),
    "moonshot-v1-8k-vision-preview": ModelPreset(("vision",), 8_192),
    "moonshot-v1-128k": ModelPreset(("tool_use",), 131_072, 4_096),
    "moonshot-v1-32k": ModelPreset(("tool_use",), 32_768, 4_096),
    "moonshot-v1-8k": ModelPreset(("tool_use",), 8_192, 4_096),
    # --- MiniMax ---
    "minimax-m1": ModelPreset(("reasoning", "tool_use"), 1_000_000, 40_960),
    "minimax-m2": ModelPreset(("reasoning", "tool_use")),
    "minimax-video": ModelPreset(("video_generation",)),
    "hailuo": ModelPreset(("video_generation",)),
    "video-01": ModelPreset(("video_generation",)),
    "speech-01": ModelPreset(("tts",)),
    "speech-02": ModelPreset(("tts",)),
    "abab": ModelPreset(("tool_use",)),
    # --- 豆包 / 字节 ---
    "doubao-seed-1.6": ModelPreset(("vision", "reasoning", "tool_use")),  # 1.6 混合思考+视觉
    "doubao-pro-256k": ModelPreset(("tool_use",), 262_144),
    "doubao-pro-128k": ModelPreset(("tool_use",), 131_072),
    "doubao-pro-32k": ModelPreset(("tool_use",), 32_768),
    "doubao-pro": ModelPreset(("tool_use",)),
    "seedance": ModelPreset(("video_generation",)),
    "seededit": ModelPreset(("image_generation",)),
    "ui-tars": ModelPreset(("vision", "tool_use")),
    # --- 百度 ERNIE ---
    "ernie-x1": ModelPreset(("reasoning", "tool_use")),
    "ernie-4.5": ModelPreset(("tool_use",)),            # -vl 变体由名称信号补 vision
    "ernie": ModelPreset(("tool_use",)),
    # --- 商汤 SenseNova ---
    "sensechat-vision": ModelPreset(("vision",)),
    "sensechat": ModelPreset(("tool_use",)),
    "sensenova": ModelPreset(("tool_use",)),
    # --- 美团 LongCat ---
    "longcat-video": ModelPreset(("video_generation",)),  # 显式优先于 "video"=理解 信号
    "longcat": ModelPreset(("tool_use",)),
    # --- 小米 MiMo ---
    "mimo": ModelPreset(("reasoning",)),                # -vl 变体由名称信号补 vision
    # --- 京东 JoyAI/言犀（已知族，能力不虚假标注） ---
    "joyai": ModelPreset(()),
    "yanxi": ModelPreset(()),
    # --- 视觉理解（开源） ---
    "internvl": ModelPreset(("vision",)),
    "llava": ModelPreset(("vision",)),
    "pixtral": ModelPreset(("vision",)),
    "mistral-small-3": ModelPreset(("vision",)),
    "magistral": ModelPreset(("reasoning",)),
    # --- 图片生成 ---
    "dall-e": ModelPreset(("image_generation",)),
    "stable-diffusion": ModelPreset(("image_generation",)),
    "flux": ModelPreset(("image_generation",)),
    "flux.1": ModelPreset(("image_generation",)),
    "imagen": ModelPreset(("image_generation",)),
    "seedream": ModelPreset(("image_generation",)),
    "cogview": ModelPreset(("image_generation",)),
    "wanx": ModelPreset(("image_generation",)),
    "hidream": ModelPreset(("image_generation",)),
    "ideogram": ModelPreset(("image_generation",)),
    "recraft": ModelPreset(("image_generation",)),
    "hunyuan-image": ModelPreset(("image_generation",)),
    # --- 视频生成 ---
    "sora": ModelPreset(("video_generation",)),
    "veo": ModelPreset(("video_generation",)),
    "kling": ModelPreset(("video_generation",)),
    "cogvideox": ModelPreset(("video_generation",)),
    "wan2": ModelPreset(("video_generation",)),
    "hunyuan-video": ModelPreset(("video_generation",)),
    "ltx-video": ModelPreset(("video_generation",)),
    "t2v": ModelPreset(("video_generation",)),
    "pika": ModelPreset(("video_generation",)),
    "luma": ModelPreset(("video_generation",)),
    "runway": ModelPreset(("video_generation",)),
    "pixverse": ModelPreset(("video_generation",)),
    # --- 音频 ---
    "whisper": ModelPreset(("audio", "stt")),
    "sensevoice": ModelPreset(("audio", "stt")),
    "paraformer": ModelPreset(("stt",)),
    "cosyvoice": ModelPreset(("tts",)),
    "fish-speech": ModelPreset(("tts",)),
    "parler-tts": ModelPreset(("tts",)),
    "chat-tts": ModelPreset(("tts",)),
    "bark": ModelPreset(("tts",)),
    "kokoro": ModelPreset(("tts",)),
    "moss": ModelPreset(("tts", "audio")),
}

# 前缀匹配用（长键优先，防 "o1" 抢先吃掉 "o1-mini" 之外的无关项）
_KNOWN_MODEL_KEYS = sorted(MODEL_PRESETS.keys(), key=len, reverse=True)

# --- 关键词启发式 ---
_REASONING_PAT = re.compile(
    r"(reasoner|reasoning|-r1|qwq|thinking|think-|o1-|o3-|o4-|z1|deep-think|推理)", re.IGNORECASE
)
_VISION_PAT = re.compile(
    r"(vision|vlm|vl[\d_-]|vl$|multimodal|multi-modal|internvl|image[-_]understand|视觉|看图|多模态)", re.IGNORECASE
)
_IMAGE_GEN_PAT = re.compile(
    r"(dall|stable[-_]diffusion|sd3|sd-|sdxl|flux|imagen|seedream|cogview|wanx|hidream|text[-_]to[-_]image|t2i|生图|绘画|文生图)", re.IGNORECASE
)
_VIDEO_GEN_PAT = re.compile(
    r"(sora|veo[-_]|kling|cogvideox|t2v|i2v|text[-_]to[-_]video|image[-_]to[-_]video|文生视频|图生视频)", re.IGNORECASE
)
_VIDEO_UNDERSTAND_PAT = re.compile(r"(video|视频)", re.IGNORECASE)
_AUDIO_PAT = re.compile(r"(audio|asr|whisper|语音识别|listen)", re.IGNORECASE)
_TTS_PAT = re.compile(r"(tts|语音合成|cosyvoice|speech[-_]synth)", re.IGNORECASE)

# 纯生成模型（命中图片/视频生成即不再标记文本对话）
_GENERATION_ONLY_CAPS = {"image_generation", "video_generation"}


def _catalog_caps(model_lower: str) -> Optional[List[str]]:
    """已知模型目录匹配：族前缀 + 完整段边界（`deepseek-r1` 不误吃 `deepseek-r2`）。"""
    for key in _KNOWN_MODEL_KEYS:
        if model_lower == key or model_lower.startswith(key + "-") or model_lower.startswith(key + "."):
            return list(MODEL_PRESETS[key].capabilities)
    return None


def lookup_model_preset(model_id: str) -> Optional[ModelPreset]:
    """按模型 ID 查预埋档案（能力 + 限额兜底值）；未知族返回 None。"""
    model_lower = (model_id or "").lower().strip()
    for key in _KNOWN_MODEL_KEYS:
        if model_lower == key or model_lower.startswith(key + "-") or model_lower.startswith(key + "."):
            return MODEL_PRESETS[key]
    return None


def apply_preset_defaults(model_id: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """把预埋目录的限额/能力兜底合并进模型条目（服务商自有值为首选）。

    合并规则：
    - ``capabilities``：仅在条目缺失/为空时填充预埋能力；
    - ``context_window`` / ``max_tokens``：仅在与 0/None/4096(ModelInfo 默认占位)
      相等时填充 —— 任何非占位现值（服务商发现/配置/用户手填）一律保留；
    - ``max_tokens`` 二级兜底：精确 id 命中 ``model_limits.MODEL_MAX_TOKENS``
      （服务商文档维护表）优先于本目录族级值；
    - 未知模型（不在预埋目录）原样返回，不添加键。
    """
    preset = lookup_model_preset(model_id)
    if preset is None:
        return entry

    out = dict(entry)
    caps = out.get("capabilities")
    if not caps:
        if preset.capabilities:
            out["capabilities"] = list(preset.capabilities)
        # 预埋条目也可能不含能力（如 joyai 仅登记限额）——留给名称推断兜底

    if out.get("context_window") in (None, 0, 4096) and preset.context_window:
        out["context_window"] = preset.context_window

    if out.get("max_tokens") in (None, 0, 4096):
        # 二级兜底：model_limits 精确表（服务商文档）优先于族级预埋
        from neurova.llm.model_limits import MODEL_MAX_TOKENS

        limit = MODEL_MAX_TOKENS.get(model_id) or MODEL_MAX_TOKENS.get(
            (model_id or "").lower()
        )
        if limit:
            out["max_tokens"] = limit
        elif preset.max_tokens:
            out["max_tokens"] = preset.max_tokens
    return out


def infer_capabilities(model_id: str, display_name: str = "") -> List[str]:
    """按模型 ID（及显示名兜底）推断能力列表（canonical 排序）。"""
    checked = f"{(model_id or '').lower()} {(display_name or '').lower()}"

    if not checked.strip():
        return ["text"]

    caps: set = set()
    catalog = _catalog_caps((model_id or "").lower()) or _catalog_caps(checked.strip())
    if catalog is not None:
        caps.update(catalog)

    if _REASONING_PAT.search(checked):
        caps.add("reasoning")
    if _VISION_PAT.search(checked):
        caps.add("vision")
    if _IMAGE_GEN_PAT.search(checked):
        caps.add("image_generation")

    # 视频生成信号优先；仅有 video 字样 → 视频理解（目录已判生成时不降级为理解）
    if _VIDEO_GEN_PAT.search(checked) or "video_generation" in caps:
        caps.add("video_generation")
    elif _VIDEO_UNDERSTAND_PAT.search(checked):
        caps.add("video")

    if _AUDIO_PAT.search(checked):
        caps.add("audio")
    if _TTS_PAT.search(checked):
        caps.add("tts")

    if not caps:
        # 普通对话模型默认文本；无任何信号的空名也一样
        return ["text"]

    # 理解/对话类模型默认补 text 基线（纯生成模型除外）
    if not (caps & _GENERATION_ONLY_CAPS):
        caps.add("text")

    # 纯生成模型不标记文本对话（dall-e/flux/sora 等不接聊天链路）
    if caps & _GENERATION_ONLY_CAPS:
        caps.discard("text")

    return sort_capabilities([c for c in caps if c in _KNOWN_CAPS])


def sort_capabilities(caps: Iterable[str]) -> List[str]:
    """按 canonical 序排序并去重（未知能力排在最后，保持稳定）。"""
    seen: set = set()
    ordered: List[str] = []
    for cap in sorted(set(caps), key=lambda c: CAPABILITY_ORDER.index(c) if c in CAPABILITY_ORDER else len(CAPABILITY_ORDER)):
        if cap not in seen:
            seen.add(cap)
            ordered.append(cap)
    return ordered


def detect_model_capabilities(
    model_id: str,
    existing: Optional[List[str]] = None,
    display_name: str = "",
) -> List[str]:
    """检测模型能力：显式元数据优先，缺失时名称推断兜底。

    Args:
        model_id: 模型 ID
        existing: 已持久化/发现链路写入的显式能力（非空则直接采信）
        display_name: 显示名（推断兜底用）
    Returns:
        canonical 排序的能力列表（永不为空，至少含 text）
    """
    if existing:
        known = [str(c) for c in existing if str(c) in _KNOWN_CAPS]
        if known:
            if "text" not in known and not (set(known) & _GENERATION_ONLY_CAPS):
                known.append("text")
            return sort_capabilities(known)
    return infer_capabilities(model_id, display_name)
