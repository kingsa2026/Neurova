"""
模型 max_tokens 能力注册表

每个模型的实际输出 token 上限。用于自动适配 max_tokens 参数，
避免因超出限制导致 400 错误。

来源: 各服务商官方文档 (2025 Q2)
"""

# 模型 ID → max_tokens (输出 token 上限)
MODEL_MAX_TOKENS: dict[str, int] = {
    # ── 商汤科技 (SenseTime) ──
    "sensenova-6.7-flash-lite": 65536,
    "sensechat-5": 8192,
    "deepseek-v4-flash": 65536,

    # ── OpenAI ──
    "gpt-4o": 16384,
    "gpt-4o-2024-05-13": 16384,
    "gpt-4o-mini": 16384,
    "gpt-4o-mini-2024-07-18": 16384,
    "gpt-4-turbo": 4096,
    "gpt-4-turbo-2024-04-09": 4096,
    "gpt-4": 8192,
    "gpt-4-0613": 8192,
    "gpt-3.5-turbo": 4096,
    "gpt-3.5-turbo-0125": 4096,

    # ── Anthropic ──
    "claude-sonnet-4-20250514": 8192,
    "claude-3-5-sonnet-20241022": 8192,
    "claude-3-5-haiku-20241022": 8192,
    "claude-3-opus-20240229": 4096,
    "claude-3-haiku-20240307": 4096,

    # ── DeepSeek ──
    "deepseek-chat": 8192,
    "deepseek-reasoner": 8192,

    # ── Google Gemini ──
    "gemini-1.5-pro": 8192,
    "gemini-1.5-flash": 8192,
    "gemini-2.0-flash": 8192,

    # ── 通义千问 (Qwen) ──
    "qwen-max": 8192,
    "qwen-plus": 8192,
    "qwen-turbo": 8192,

    # ── 智谱 (GLM) ──
    "glm-4": 4096,
    "glm-4-flash": 4096,
    "glm-3-turbo": 2048,
}

# 未知模型的安全回退值
DEFAULT_MAX_TOKENS = 4096

# 全局最小值保护（任何模型不低于此值）
MIN_MAX_TOKENS = 256

# 全局最大值保护（任何模型不高于此值）
MAX_MAX_TOKENS = 200000


def get_model_max_tokens(model_id: str) -> int:
    """
    获取模型的 max_tokens 上限。

    按优先级查找:
    1. 精确匹配 MODEL_MAX_TOKENS
    2. 前缀匹配 (如 "gpt-4o-2024-11-20" → "gpt-4o")
    3. 返回 DEFAULT_MAX_TOKENS

    Args:
        model_id: 模型 ID (如 "gpt-4o", "sensenova-6.7-flash-lite")

    Returns:
        该模型的推荐 max_tokens 值
    """
    if not model_id:
        return DEFAULT_MAX_TOKENS

    # 精确匹配
    if model_id in MODEL_MAX_TOKENS:
        return MODEL_MAX_TOKENS[model_id]

    # 前缀匹配: 尝试去掉日期后缀
    # "gpt-4o-2024-05-13" → 先试 "gpt-4o-2024-05-13" (已试)
    #                       再试 "gpt-4o-2024-05" → "gpt-4o-2024"
    #                       再试 "gpt-4o"
    parts = model_id.rsplit("-", 1)
    while len(parts) > 1:
        candidate = parts[0]
        if candidate in MODEL_MAX_TOKENS:
            return MODEL_MAX_TOKENS[candidate]
        parts = candidate.rsplit("-", 1)

    return DEFAULT_MAX_TOKENS


def clamp_max_tokens(max_tokens: int, model_id: str = "") -> int:
    """
    将 max_tokens 限制在合理范围内。

    Args:
        max_tokens: 请求的 max_tokens
        model_id: 模型 ID (用于获取上限)

    Returns:
        夹紧后的 max_tokens
    """
    model_limit = get_model_max_tokens(model_id)
    return max(MIN_MAX_TOKENS, min(max_tokens, model_limit, MAX_MAX_TOKENS))
