"""
上下文组成实测（Context Composition）

2026-09-07 聊天页"上下文容量"悬停面板数据源。

此前 GET /v1/context/stats 恒零 stub，前端环图无真实数据可悬停。
本模块在管线真实挂点（ChatPipeline._step_llm_call——ctx.context 与
tools_for_llm 已就绪、紧邻 loop.predict_step）实测一次 prompt 组成：

- messages 按角色分桶（system 提示词 / 用户 / 助手 / 工具结果）
- tools 按 schema 来源分类（MCP / 系统工具 / 技能 / 其他），逐条计 token
- 命中率：优先采信供应商回传的 prompt_tokens_details.cached_tokens
  （usage_accounting 已归集）；无供应商明细时用 LRU 重复前缀比例估算
  （相邻两轮 prompt 的公共前缀占比——上下文缓存命中的近似）

token 计数统一走 context.token_estimator（EXACT 策略优先，tiktoken 失败
自动回退比例估算），与注入侧预算口径一致。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from neurova.context.token_estimator import EstimationStrategy, get_token_estimator
from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 估算器（EXACT：tiktoken o200k，失败自动回退 BALANCED——estimator 内部处理）
_estimator = get_token_estimator(EstimationStrategy.EXACT)

# 最近一轮实测快照：{agent_id: composition_dict}
_last_composition: Dict[str, Dict[str, Any]] = {}
# 最近一轮的消息列表（命中率重复前缀估算用）：{agent_id: messages}
_last_messages: Dict[str, Optional[List[Dict]]] = {}
_lock = threading.RLock()

# 重复前缀估算最多比对的字符量（前缀重复是大头，够用且防超长会话 O(n²)）
_PREFIX_SCAN_MAX_CHARS = 200_000

# 工具来源分类的键序（"其他"兜底；与 orchestrator 聚合顺序一致）
_TOOL_SOURCE_ORDER = ("mcp", "system", "skill", "other")


def _estimate(text: str) -> int:
    """估算单段文本 token（空文本返回 0）。"""
    if not text:
        return 0
    try:
        return _estimator.estimate(text)
    except Exception:  # noqa: BLE001 - 估算失败按 4 字符/token 兜底，不阻断实测
        return max(1, len(text) // 4)


def _json_schema_chars(schema: Any) -> str:
    """把工具 parameters schema 渲染成可计数的文本（原样 JSON 序列化）。"""
    import json

    if schema is None:
        return ""
    if isinstance(schema, str):
        return schema
    try:
        return json.dumps(schema, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return str(schema)


def classify_tool_schema(tool: Dict[str, Any]) -> str:
    """按 OpenAI function schema 推断工具来源分类。

    orchestrator._build_tools_for_llm 的聚合顺序是 内置+MCP（ToolRouter）→
    Skill → workflow；MCP 工具名由 server 前缀（`mcp__server__tool` 或
    `server_tool` 命名约定）带入，技能 schema 由 OpenAISchemaAdapter 生成。
    返回 mcp / system / skill / other 之一。

    纯函数，供分类统计与单测共用。
    """
    fn = tool.get("function") if isinstance(tool, dict) else None
    name = str((fn or {}).get("name") or "")
    if not name:
        return "other"
    lower = name.lower()
    if "__" in name or lower.startswith("mcp_"):
        return "mcp"
    # 带完整参数 schema 的 function 定义且非内置前缀 → 技能适配器产物；
    # 内置/系统工具名走 get_builtin_tool_params 的白名单形态
    try:
        from neurova.builtin_tools import get_builtin_tool_params

        if get_builtin_tool_params(name) is not None:
            return "system"
    except Exception:  # noqa: BLE001
        pass
    return "skill"


def _classify_and_measure_tools(tools: Optional[List[Dict]]) -> Dict[str, Dict[str, int]]:
    """按来源分类累计工具 token（含 description + parameters schema）。"""
    stats: Dict[str, Dict[str, int]] = {k: {"count": 0, "tokens": 0} for k in _TOOL_SOURCE_ORDER}
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        fn = tool.get("function") or {}
        name = str(fn.get("name") or "")
        source = classify_tool_schema(tool)
        tokens = _estimate(str(fn.get("description") or "")) + _estimate(_json_schema_chars(fn.get("parameters")))
        stats[source]["count"] += 1
        stats[source]["tokens"] += tokens
    return stats


def _message_role_bucket(role: str) -> str:
    """消息角色 → 分桶键（system/user/assistant/tool）。未知角色入 other。"""
    if role in ("system", "developer"):
        return "system"
    if role in ("user",):
        return "user"
    if role in ("assistant",):
        return "assistant"
    if role in ("tool", "function"):
        return "tool"
    return "other"


def _measure_messages(messages: Optional[List[Dict]]) -> Dict[str, Any]:
    """按角色分桶实测 messages token。"""
    buckets: Dict[str, Dict[str, int]] = {
        "system": {"count": 0, "tokens": 0},
        "user": {"count": 0, "tokens": 0},
        "assistant": {"count": 0, "tokens": 0},
        "tool": {"count": 0, "tokens": 0},
        "other": {"count": 0, "tokens": 0},
    }
    total = 0
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = _message_role_bucket(str(msg.get("role") or ""))
        content = msg.get("content", "")
        if isinstance(content, list):
            # 多模态 content parts：文本段计数，图片段按固定 800 token 计
            text = " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict) and p.get("type") == "text")
            images = sum(1 for p in content if isinstance(p, dict) and p.get("type") == "image_url")
            tokens = _estimate(text) + images * 800
        else:
            tokens = _estimate(str(content or ""))
        # tool_calls 定义本身也是 prompt 的一部分
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            try:
                import json

                tokens += _estimate(json.dumps(tool_calls, ensure_ascii=False))
            except Exception:  # noqa: BLE001
                pass
        buckets[role]["count"] += 1
        buckets[role]["tokens"] += tokens
        total += tokens
    return {"buckets": buckets, "total_tokens": total}


def _prefix_repeat_ratio(prev_messages: Optional[List[Dict]], curr_messages: Optional[List[Dict]]) -> Optional[float]:
    """重复前缀比例（无供应商 cached_tokens 明细时的命中率近似）。

    上下文缓存的命中段 = 相邻两轮 prompt 的公共前缀（system 前缀 + 历史
    append-only）。渲染两轮消息为文本，取公共前缀长度 / 当前轮长度。
    无法计算（任一轮为空）返回 None。
    """
    import json

    def _render(msgs: Optional[List[Dict]]) -> str:
        # 空轮次必须渲染为空串：json.dumps([]) 的 "[]" 会与真实列表的
        # "[..." 开头撞出假公共前缀（首轮误报命中率，测试实锤）
        if not msgs:
            return ""
        try:
            return json.dumps(msgs, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            return ""

    prev_text = _render(prev_messages)[:_PREFIX_SCAN_MAX_CHARS]
    curr_text = _render(curr_messages)[:_PREFIX_SCAN_MAX_CHARS]
    if not prev_text or not curr_text:
        return None
    limit = min(len(prev_text), len(curr_text))
    # 二分公共前缀长度（逐字符比较在长前缀下太慢）
    lo, hi = 0, limit
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if prev_text[:mid] == curr_text[:mid]:
            lo = mid
        else:
            hi = mid - 1
    if lo == 0:
        return 0.0
    return round(min(1.0, lo / max(1, len(curr_text))), 4)


def measure_composition(
    agent_id: str,
    messages: Optional[List[Dict]],
    tools: Optional[List[Dict]],
    provider_usage: Optional[Dict[str, Any]] = None,
    context_window: Optional[int] = None,
) -> Dict[str, Any]:
    """实测一次 prompt 组成并更新该 agent 的最近快照。

    Args:
        agent_id: agent 标识（快照键）
        messages: 即将发给 LLM 的完整消息列表（含 system）
        tools: OpenAI function schema 工具列表
        provider_usage: 本轮供应商 usage（含 prompt_tokens_details.cached_tokens 时优先采信）
        context_window: 当前模型上下文窗口（token 上限）

    Returns:
        composition dict（同时更新快照，供 GET /v1/context/composition 读取）
    """
    started = time.time()
    with _lock:
        previous_messages = _last_messages.get(agent_id)
    msg_stats = _measure_messages(messages)
    tool_stats = _classify_and_measure_tools(tools)
    tools_total = sum(v["tokens"] for v in tool_stats.values())

    # 消息口径里 system 已含工具清单文本（orchestrator 把 tools_desc 塞进
    # developer/system 段），为免重复计数，面板把工具 schema 单列一档，
    # 消息 total 减去无法剥离的清单文本 —— 这里不做减法（无法精确剥离），
    # 而是把展示总量定为 messages + tools 两档之和的原始实测值，注明口径。
    total_tokens = msg_stats["total_tokens"] + tools_total

    # 命中率：优先供应商明细，否则重复前缀比例
    cache_hit_rate: Optional[float] = None
    cache_source = "none"
    details = None
    if isinstance(provider_usage, dict):
        details = provider_usage.get("prompt_tokens_details") or {}
        if isinstance(details, dict) and details.get("cached_tokens") is not None:
            prompt_tokens = float(provider_usage.get("prompt_tokens") or 0)
            if prompt_tokens > 0:
                cache_hit_rate = round(min(1.0, float(details["cached_tokens"]) / prompt_tokens), 4)
                cache_source = "provider"

    if cache_hit_rate is None:
        ratio = _prefix_repeat_ratio(previous_messages, messages)
        if ratio is not None:
            cache_hit_rate = ratio
            cache_source = "prefix_estimate"

    composition: Dict[str, Any] = {
        "agent_id": agent_id,
        "measured_at": time.time(),
        "elapsed_ms": round((time.time() - started) * 1000, 2),
        "context_window": context_window,
        "total_tokens": total_tokens,
        "messages": msg_stats,
        "tools": tool_stats,
        "cache_hit_rate": cache_hit_rate,
        "cache_source": cache_source,
    }
    with _lock:
        _last_composition[agent_id] = composition
        _last_messages[agent_id] = messages
    return composition


def get_last_composition(agent_id: str) -> Optional[Dict[str, Any]]:
    """读取 agent 最近一次实测快照（无记录返回 None）。"""
    with _lock:
        return _last_composition.get(agent_id)


def reset_composition() -> None:
    """清空快照（测试用）。"""
    with _lock:
        _last_composition.clear()
        _last_messages.clear()
