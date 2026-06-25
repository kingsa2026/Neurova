"""
LLM 配置解析器 — 统一三层配置合并

优先级: Agent 配置 > 用户/服务商配置 > 系统默认配置

Agent 配置: AgentConfig.llm_config 中显式设置的值（非空、非默认）
用户/服务商配置: LLMProviderManager 中的 ProviderConfig（api_key, base_url, default_model）
系统默认配置: LLMConfig dataclass 的硬编码默认值
"""

from neurova.core.logger import get_logger
from dataclasses import dataclass, field
from typing import Optional

logger = get_logger(__name__)

# 系统默认值（与 LLMConfig dataclass 一致，max_tokens 使用安全回退值）
_SYSTEM_DEFAULTS = {
    "api_key": "",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4",
    "temperature": 0.7,
    "max_tokens": 4096,
    "top_p": 1.0,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
    "stream": False,
}


@dataclass
class ResolvedLLMConfig:
    """解析后的 LLM 配置 — 最终生效的值"""

    model: str = "gpt-4"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    temperature: float = 0.7
    max_tokens: int = 131072
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    stream: bool = False
    provider_id: str = ""

    # 追踪来源（用于调试）
    _source_model: str = ""
    _source_api_key: str = ""
    _source_base_url: str = ""
    _source_temperature: str = ""


def _is_default(key: str, value) -> bool:
    """判断值是否等于系统默认值"""
    default = _SYSTEM_DEFAULTS.get(key)
    if default is None:
        return False
    return value == default


def _is_empty(value) -> bool:
    """判断值是否为空"""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def resolve_llm_config(agent_config=None, provider_manager=None) -> ResolvedLLMConfig:
    """
    三层配置合并: Agent > 用户/服务商 > 系统默认

    Args:
        agent_config: AgentConfig 实例（包含 llm_config 和 llm_provider）
        provider_manager: LLMProviderManager 实例（可选，用于查找服务商配置）

    Returns:
        ResolvedLLMConfig: 最终生效的配置
    """
    result = ResolvedLLMConfig()
    agent_llm = getattr(agent_config, "llm_config", None)
    provider_id = getattr(agent_config, "llm_provider", "") or ""

    # ── 第 1 层: 系统默认值（已作为 ResolvedLLMConfig 的初始值）──

    # ── 第 2 层: 用户/服务商配置 ──
    provider_config = None
    if provider_id and provider_manager:
        try:
            provider_config = provider_manager.get_provider(provider_id)
        except Exception as e:
            logger.warning("获取服务商配置失败 (%s): %s", provider_id, e)

    if provider_config:
        # 服务商提供 api_key 和 base_url
        if provider_config.api_key:
            result.api_key = provider_config.api_key
            result._source_api_key = f"provider:{provider_id}"
        if provider_config.base_url:
            result.base_url = provider_config.base_url
            result._source_base_url = f"provider:{provider_id}"
        # 服务商的 default_model 作为候选
        if provider_config.default_model:
            result.model = provider_config.default_model
            result._source_model = f"provider:{provider_id}"

    # ── 第 3 层: Agent 配置（最高优先级）──
    if agent_llm:
        # model: agent 显式设置且非空
        agent_model = getattr(agent_llm, "model", "")
        if agent_model and not _is_empty(agent_model):
            result.model = agent_model
            result._source_model = "agent"

        # api_key: agent 显式设置且非空（覆盖服务商）
        agent_api_key = getattr(agent_llm, "api_key", "")
        if agent_api_key and not _is_empty(agent_api_key):
            result.api_key = agent_api_key
            result._source_api_key = "agent"

        # base_url: agent 显式设置且非默认值（覆盖服务商）
        agent_base_url = getattr(agent_llm, "base_url", "")
        if agent_base_url and not _is_empty(agent_base_url) and agent_base_url != _SYSTEM_DEFAULTS["base_url"]:
            result.base_url = agent_base_url
            result._source_base_url = "agent"

        # temperature: agent 显式设置且非默认值
        agent_temp = getattr(agent_llm, "temperature", None)
        if agent_temp is not None and not _is_default("temperature", agent_temp):
            result.temperature = agent_temp
            result._source_temperature = "agent"

        # max_tokens: agent 显式设置且非默认值
        agent_max = getattr(agent_llm, "max_tokens", None)
        if agent_max is not None and not _is_default("max_tokens", agent_max):
            result.max_tokens = agent_max

        # top_p
        agent_top_p = getattr(agent_llm, "top_p", None)
        if agent_top_p is not None and not _is_default("top_p", agent_top_p):
            result.top_p = agent_top_p

        # frequency_penalty
        agent_fp = getattr(agent_llm, "frequency_penalty", None)
        if agent_fp is not None and not _is_default("frequency_penalty", agent_fp):
            result.frequency_penalty = agent_fp

        # presence_penalty
        agent_pp = getattr(agent_llm, "presence_penalty", None)
        if agent_pp is not None and not _is_default("presence_penalty", agent_pp):
            result.presence_penalty = agent_pp

        # stream
        agent_stream = getattr(agent_llm, "stream", None)
        if agent_stream is not None and agent_stream != _SYSTEM_DEFAULTS["stream"]:
            result.stream = agent_stream

    result.provider_id = provider_id

    logger.debug(
        "LLM config resolved: model=%s (from %s), api_key=%s (from %s), base_url=%s (from %s), temp=%.2f (from %s)",
        result.model,
        result._source_model or "system",
        "set" if result.api_key else "empty",
        result._source_api_key or "system",
        result.base_url[:30],
        result._source_base_url or "system",
        result.temperature,
        result._source_temperature or "system",
    )

    return result
