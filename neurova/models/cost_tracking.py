"""
LLM Cost Tracking - Universal Cost Ledger

所有 LLM 调用的成本记账统一入口：落盘 SQLite 账本 + 预算告警。

审计 §3.5-9：CostTracker 的 PostgreSQL/asyncpg 形态（db_pool.acquire、$N 占位符）
生产零消费已退役——在役记账走 cost_store.py 的 SQLite 实现（record_llm_cost 单一入口）。
"""

import uuid
import inspect
import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from functools import wraps

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class LLMProvider(str, Enum):
    """LLM 服务商"""
    
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"
    NOVITA = "novita"
    ORCAROUTER = "orcarouter"
    BYOA_CLAUDE = "byoa-claude"
    BYOA_CODEX = "byoa-codex"


class LLMDirection(str, Enum):
    """调用方向"""
    
    INPUT = "input"
    OUTPUT = "output"


@dataclass
class LLMCall:
    """
    LLM 调用记录

    对应 llm_calls 明细表 schema
    """
    
    call_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str = ""
    turn_id: Optional[str] = None
    session_id: Optional[str] = None
    
    provider: LLMProvider = LLMProvider.OPENAI
    model: str = ""
    
    direction: LLMDirection = LLMDirection.INPUT
    input_tokens: int = 0
    output_tokens: Optional[int] = None
    
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    
    cost_usd: float = 0.0
    called_at: datetime = field(default_factory=datetime.utcnow)
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "call_id": self.call_id,
            "agent_id": self.agent_id,
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "provider": self.provider.value,
            "model": self.model,
            "direction": self.direction.value,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens or 0,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cost_usd": self.cost_usd,
            "called_at": self.called_at.isoformat(),
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "LLMCall":
        """从字典创建"""
        return cls(
            call_id=data.get("call_id", str(uuid.uuid4())),
            agent_id=data.get("agent_id", ""),
            turn_id=data.get("turn_id"),
            session_id=data.get("session_id"),
            provider=LLMProvider(data.get("provider", "openai")),
            model=data.get("model", ""),
            direction=LLMDirection(data.get("direction", "input")),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens"),
            cache_read_tokens=data.get("cache_read_tokens", 0),
            cache_write_tokens=data.get("cache_write_tokens", 0),
            cost_usd=data.get("cost_usd", 0.0),
            called_at=datetime.fromisoformat(data["called_at"]) if "called_at" in data else datetime.utcnow(),
            metadata=data.get("metadata", {}),
        )


# Price tables (USD per 1K tokens)
PRICE_TABLES = {
    LLMProvider.OPENAI: {
        "gpt-4": {"input": 0.03, "output": 0.06},
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
        "gpt-4o": {"input": 0.0025, "output": 0.01},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    },
    LLMProvider.ANTHROPIC: {
        "claude-3-opus": {"input": 0.015, "output": 0.075},
        "claude-3-sonnet": {"input": 0.003, "output": 0.015},
        "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
        "claude-3.5-sonnet": {"input": 0.003, "output": 0.015},
    },
    LLMProvider.GEMINI: {
        "gemini-1.5-pro": {"input": 0.0025, "output": 0.0075},
        "gemini-1.5-flash": {"input": 0.000375, "output": 0.00075},
    },
}


# ── 调用成本上下文（agent/session/turn 归属）────────────────────────
# LLMClient 层不知道当前是哪个 agent/会话/轮次；由上层（ChatPipeline）
# 每轮设置 contextvar，record_llm_cost 读取后归属到真实维度。
_llm_cost_ctx: "contextvars.ContextVar[Optional[dict]]" = contextvars.ContextVar(
    "neurova_llm_cost_ctx", default=None
)


@contextmanager
def llm_cost_context(agent_id=None, session_id=None, turn_id=None):
    """在一段代码内为 LLM 成本记账绑定 agent/session/turn 归属。"""
    prev = _llm_cost_ctx.get()
    _llm_cost_ctx.set(
        {"agent_id": agent_id, "session_id": session_id, "turn_id": turn_id}
    )
    try:
        yield
    finally:
        _llm_cost_ctx.set(prev)


def get_llm_cost_context() -> dict:
    return _llm_cost_ctx.get() or {}


def set_llm_cost_context(agent_id=None, session_id=None, turn_id=None) -> None:
    """直接设置当前上下文（供 ChatPipeline 每轮顶部调用，镜像
    identity_context.set_request_user_id 的用法，无需包裹代码块）。"""
    _llm_cost_ctx.set(
        {"agent_id": agent_id, "session_id": session_id, "turn_id": turn_id}
    )


# ── 单一记账入口 ───────────────────────────────────────────────────────
def record_llm_cost(
    provider: LLMProvider,
    model: str,
    usage: Optional[dict],
    agent_id: Optional[str] = None,
    direction: LLMDirection = LLMDirection.INPUT,
    turn_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """
    所有 LLM 调用成本记账的唯一入口：落盘 SQLite 账本 + 记预算 + 查告警。

    agent/session/turn 归属优先级：显式参数 > llm_cost_context 上下文 > "unknown"。
    fail-open 副路径纪律：账本未装配时静默降级，任何异常都不得影响主流程。
    """
    try:
        usage = usage or {}
        ctx = get_llm_cost_context()
        agent = agent_id or ctx.get("agent_id") or "unknown"
        turn_id = turn_id or ctx.get("turn_id")
        session_id = session_id or ctx.get("session_id")
        cost = _calculate_cost_from_usage(provider, model, usage)

        from neurova.models.cost_store import get_llm_cost_store

        store = get_llm_cost_store()
        if store is not None:
            store.record_call(
                call_id=str(uuid.uuid4()),
                agent_id=agent,
                provider=provider.value if isinstance(provider, LLMProvider) else str(provider),
                model=model,
                direction=direction.value,
                input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                output_tokens=int(usage.get("completion_tokens", 0) or 0),
                cache_read_tokens=int(usage.get("cache_read_tokens", 0) or 0),
                cache_write_tokens=int(usage.get("cache_write_tokens", 0) or 0),
                cost=float(cost),
                turn_id=turn_id,
                session_id=session_id,
            )

        _record_budget_and_check_alerts(
            provider=provider, model=model, cost=float(cost), agent_id=agent
        )
    except Exception as e:  # noqa: BLE001 - 记账不得阻断 LLM 主流程
        logger.warning("record_llm_cost failed (ignored): %s", e)


def _extract_usage(result) -> tuple:
    """从 LLM 返回中提取 (usage_dict, model_or_None)。

    兼容三种形态：LLMResponse dataclass（.usage/.model）、
    含 'usage' 键的 dict、以及 usage 本身就是 token dict。
    """
    usage = getattr(result, "usage", None)
    model = getattr(result, "model", None)

    if usage is None and isinstance(result, dict):
        maybe = result.get("usage")
        if isinstance(maybe, dict):
            usage = maybe
            model = result.get("model") or model
        elif "prompt_tokens" in result or "completion_tokens" in result:
            usage = result
            model = result.get("model") or model

    if not isinstance(usage, dict):
        usage = {}
    return usage, (model or None)


# Decorator for automatic cost tracking
def track_llm_call(
    provider: LLMProvider,
    model: str,
    direction: LLMDirection = LLMDirection.INPUT,
    agent_id: Optional[str] = None,
):
    """
    装饰器：自动记录非流式 LLM 调用的成本。

    - sync/async 自适应（不会把同步方法变成协程）；
    - usage 从返回体（LLMResponse/dict）解析，真实模型名覆盖装饰器默认；
    - 对生成器（流式）方法原样返回，不拦截逐块输出——流式记账由
      方法体内显式调用 record_llm_cost 完成。
    """
    def decorator(func):
        if inspect.isgeneratorfunction(func) or inspect.isasyncgenfunction(func):
            return func

        def _post(result):
            try:
                usage, real_model = _extract_usage(result)
                record_llm_cost(
                    provider=provider,
                    model=real_model or model,
                    usage=usage,
                    agent_id=agent_id,
                    direction=direction,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("track_llm_call failed to record (ignored): %s", e)

        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                result = await func(*args, **kwargs)
                _post(result)
                return result
            return async_wrapper

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            _post(result)
            return result
        return sync_wrapper
    return decorator


def _calculate_cost_from_usage(provider: LLMProvider, model: str, usage: dict) -> float:
    """从 usage 计算成本（输入+输出 token，USD）"""
    price_map = PRICE_TABLES.get(provider, {}).get(model) or PRICE_TABLES.get(provider, {}).get("default")
    if not price_map:
        return 0.0
    input_tokens = usage.get("prompt_tokens", 0) or 0
    output_tokens = usage.get("completion_tokens", 0) or 0
    cache_read = usage.get("cache_read_tokens", 0) or 0
    cache_write = usage.get("cache_write_tokens", 0) or 0
    cost = (
        input_tokens * price_map.get("input", 0) / 1000
        + output_tokens * price_map.get("output", 0) / 1000
        + cache_read * price_map.get("cache_read", 0) / 1000
        + cache_write * price_map.get("cache_write", 0) / 1000
    )
    return round(cost, 6)


def _record_budget_and_check_alerts(
    provider: LLMProvider,
    model: str,
    cost: float,
    agent_id: str
):
    """Record cost against budgets and check for alerts"""
    try:
        from neurova.models.cost_budget import get_budget_service
        
        budget_service = get_budget_service()
        budget_service.record_llm_call_cost(
            agent_id=agent_id,
            provider=provider.value,
            model=model,
            cost=cost
        )
    except Exception as e:
        # Don't let budget failures break LLM calls
        logger.warning(f"Failed to record budget: {e}")
