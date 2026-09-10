"""声明式 provider 兼容开关（OpenClaw 启发 P0-2）

背景（docs/Neurova_OpenClaw代码级对比_2026-09-04.md §3 P0-2）：
  OpenClaw 用 OpenAICompletionsCompat 约 30 个声明式字段支撑几十个
  OpenAI 兼容 provider——兼容逻辑是"开关表 + baseUrl 自动探测"而非
  if 分支。Neurova 的 sensetime/model_limits/商汤三层根因这类 bug 的
  共性就是兼容逻辑散落在 per-provider 代码分支里。

Neurova 现状（散落的分支，本模块收编）：
  - llm_client.py 无条件 params["stream_options"]={"include_usage": True}：
    不支持该参数的网关（sensetime 实测流式 usage 恒空、部分 400）会
    请求失败或静默不回传——需要 per-provider 开关。
  - 后续 compat 面（thinking 格式、tool-call 格式差异等）在此表扩展，
    不再新增 if provider == "xxx" 分支。

使用方式：
  1. 静态表 PROVIDER_COMPAT：按 provider id / baseUrl host 配置开关；
  2. LLMConfig.compat: ProviderCompat 字段——LLMClient 请求构造时
     声明式消费（cfg.compat.include_stream_usage 决定是否带 stream_options）；
  3. resolve_compat()：provider id → host 匹配 → 默认值 的解析顺序，
     ProviderConfig.compat_dict 显式声明优先于静态表。

新扩展点默认关：静态表只收录已实测过的 provider；未收录的走
安全默认（include_stream_usage=True——OpenAI 协议标准行为）。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional
from urllib.parse import urlparse


@dataclass(frozen=True)
class ProviderCompat:
    """OpenAI 兼容 provider 的声明式开关（OC OpenAICompletionsCompat 对位）。

    字段语义一律正向命名（"支持/需要"），未列出的 provider 走 dataclass
    默认值=OpenAI 官方协议行为。
    """

    # 流式请求是否携带 stream_options={"include_usage": True}。OpenAI 官方
    # 及绝大多数兼容网关支持；实测不支持的网关在此声明 False。
    include_stream_usage: bool = True

    # 是否支持 reasoning_effort 请求参数（OpenAI o 系扩展，AMD RADEON 网关
    # 2026-09-08 实测三模型均支持；未声明的网关不注入，防低容忍网关 400）。
    # 开启后 chat/chat_stream 请求按 thinking_effort 映射注入
    # （light→不传 / standard→medium / deep→high）。
    supports_reasoning_effort: bool = False

    # thinking_effort（前端深度选择器）→ reasoning_effort（API 参数）映射。
    # 仅 supports_reasoning_effort=True 的 provider 消费。
    _REASONING_EFFORT_MAP = {"light": None, "standard": "medium", "deep": "high"}

    # B1-3（QwenPaw #6302 对齐）：是否支持思考开关两级参数
    # enable_thinking(bool) / thinking_budget(int)（Qwen3/DashScope 风格）。
    # 仅声明 True 的网关注入；thinking_budget 只在 thinking_enabled=True 时随发。
    supports_thinking_toggle: bool = False

    def map_reasoning_effort(self, thinking_effort: Optional[str]) -> Optional[str]:
        """前端深度档位 → API reasoning_effort 值；light/未知/空 → None（不注入）。"""
        if not self.supports_reasoning_effort:
            return None
        return self._REASONING_EFFORT_MAP.get((thinking_effort or "").strip().lower())

    def merged(self, overrides: Optional[dict]) -> "ProviderCompat":
        """显式声明覆盖静态表（字段级合并）。"""
        if not overrides:
            return self
        valid = {f for f in self.__dataclass_fields__ if f in overrides}
        if not valid:
            return self
        return replace(self, **{f: overrides[f] for f in valid})


# 静态描述表：provider id 精确匹配优先，其次 baseUrl host 匹配。
# 只收录实测过的 provider；新 provider 默认走协议标准行为，实测异常再加行。
PROVIDER_COMPAT: dict = {
    # sensetime 网关实测：流式 usage 恒空（token 记账走 tiktoken 估值），
    # 且对未知请求参数容忍度低——关闭 include_usage 请求体。
    "sensetime": ProviderCompat(include_stream_usage=False),
    "token.sensenova.cn": ProviderCompat(include_stream_usage=False),
    # AMD RADEON 网关（developer.amd.com.cn/radeon，2026-09-08 实测）：
    # DeepSeek-V4-Flash / DeepSeek-V4-Flash-Vision-Exp 默认不吐思考内容，
    # 须显式带 reasoning_effort（high→522/213 字符实测）；Qwen3.8-Flash-Next
    # 默认吐 delta.reasoning（LLMClient._pick_reasoning 已兼容字段名）。
    # 思考档位：xhigh(默认)/high/medium…，reasoning.max_tokens 不支持。
    "amd": ProviderCompat(include_stream_usage=True, supports_reasoning_effort=True),
    "developer.amd.com.cn": ProviderCompat(include_stream_usage=True, supports_reasoning_effort=True),
}


def _host_of(base_url) -> str:
    """baseUrl → 小写 host。非 str 输入（duck-typed provider/mock）归一为空。"""
    if not isinstance(base_url, str) or not base_url:
        return ""
    try:
        return (urlparse(base_url).hostname or "").lower()
    except ValueError:
        return ""


def _id_key(provider_id) -> str:
    return provider_id.lower() if isinstance(provider_id, str) else ""


def resolve_compat(
    provider_id: str = "",
    base_url: str = "",
    compat_dict: Optional[dict] = None,
) -> ProviderCompat:
    """解析 provider 的 compat 开关。

    优先级：ProviderConfig 显式声明（compat_dict）> provider id 静态表 >
    baseUrl host 静态表 > 默认值。
    """
    compat = ProviderCompat()
    base = PROVIDER_COMPAT.get(_id_key(provider_id))
    if base is None:
        host = _host_of(base_url)
        base = PROVIDER_COMPAT.get(host)
    if base is not None:
        compat = base
    return compat.merged(compat_dict)
