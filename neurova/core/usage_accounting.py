"""
Per-turn Token 对账 + 成本核算（P2-4）

单一事实源记账器：LLM 调用方（multi_model_client.chat）从底层 response.usage
提取真实 token 数并 record()，取代字符长度伪造（chat_pipeline 原实现）。

- 线程安全（RLock）——LLM 调用可来自多线程（asyncio.to_thread）
- per-model 聚合 + per-provider 拆分（snapshot()）
- 成本核算按定价目录（$/token，缺省未知模型计 0）
- 轻量：仅内存计数，不落盘（后续可挂导出）
"""

from __future__ import annotations

import threading
from contextvars import ContextVar
from typing import Any, Dict, Optional

# P2-6（审计 2026-09-11）：任务级"最近一次调用"——并发会话下全局单槽
# _last_call会被其它请求覆写（A 的 usage 事件读到 B 的 model/token 串号）。
# record() 与消费方（chat_pipeline trace / console run_chat）同任务执行，
# ContextVar 天然按请求隔离；无任务上下文的调用方回退全局槽。
_last_call_var: ContextVar = ContextVar("neurova_last_llm_call", default=None)


def set_task_last_call(payload: Optional[Dict[str, Any]]) -> None:
    """在当前请求任务内回填任务级最近调用（P2-6，供 to_thread 调用方使用）。"""
    if payload:
        try:
            _last_call_var.set(payload)
        except Exception:  # noqa: BLE001
            pass

# 定价目录（$/token；首批准 OpenAI 公开价，待接 provider 元数据扩展）
_PRICING_DEFAULT: Dict[str, Dict[str, float]] = {
    "gpt-4o": {"prompt": 2.5e-06, "completion": 1e-05},
    "gpt-4-turbo": {"prompt": 1e-05, "completion": 3e-05},
    "gpt-4": {"prompt": 3e-05, "completion": 6e-05},
    "gpt-3.5-turbo": {"prompt": 5e-07, "completion": 1.5e-06},
    "deepseek-chat": {"prompt": 1.4e-07, "completion": 2.8e-07},
}


class TokenUsageAccounting:
    """进程级 token 用量/成本记账器（线程安全）。"""

    # 类级定价表（测试可 monkeypatch）
    _PRICING = _PRICING_DEFAULT

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # {model: {"calls", "prompt_tokens", "completion_tokens", "total_tokens",
        #          "by_provider": {provider: {...}}}}
        self._by_model: Dict[str, Dict[str, Any]] = {}
        self._last_call: Optional[Dict[str, Any]] = None

    def record(
        self,
        *,
        model: str,
        provider: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated: bool = False,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> None:
        """记一次 LLM 调用的真实 token 用量。

        estimated=True：provider 网关不回传 usage（实测 sensetime 流式恒空）
        时由 tiktoken 估值入账，供对账区分真值/估计值。
        B1-5（#7342）：cache_read/write_tokens 记 Prompt Cache 命中与写入
        （OpenAI prompt_tokens_details.cached_tokens / Anthropic
        cache_creation_input_tokens——由 multi_model_client 提取透传）。
        """
        prompt_tokens = int(prompt_tokens or 0)
        completion_tokens = int(completion_tokens or 0)
        cache_read_tokens = int(cache_read_tokens or 0)
        cache_write_tokens = int(cache_write_tokens or 0)
        total = prompt_tokens + completion_tokens

        with self._lock:
            entry = self._by_model.setdefault(
                model,
                {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "estimated_calls": 0,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                    "by_provider": {},
                },
            )
            entry["calls"] += 1
            entry["prompt_tokens"] += prompt_tokens
            entry["completion_tokens"] += completion_tokens
            entry["total_tokens"] += total
            entry["cache_read_tokens"] = entry.get("cache_read_tokens", 0) + cache_read_tokens
            entry["cache_write_tokens"] = entry.get("cache_write_tokens", 0) + cache_write_tokens
            if estimated:
                entry["estimated_calls"] = entry.get("estimated_calls", 0) + 1

            p_entry = entry["by_provider"].setdefault(
                provider,
                {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                 "cache_read_tokens": 0, "cache_write_tokens": 0},
            )
            p_entry["calls"] += 1
            p_entry["prompt_tokens"] += prompt_tokens
            p_entry["completion_tokens"] += completion_tokens
            p_entry["total_tokens"] += total
            p_entry["cache_read_tokens"] = p_entry.get("cache_read_tokens", 0) + cache_read_tokens
            p_entry["cache_write_tokens"] = p_entry.get("cache_write_tokens", 0) + cache_write_tokens

            payload = {
                "model": model,
                "provider": provider,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total,
                "estimated": estimated,
                "cache_read_tokens": cache_read_tokens,
                "cache_write_tokens": cache_write_tokens,
            }
            with self._lock:
                self._last_call = payload
            # P2-6：任务级快照——同任务内的 last_call() 读到的必是本次调用。
            # 注意 to_thread 工作线程内的 set 不回传调用任务，调用方须以
            # set_task_last_call() 在事件循环任务内显式回填。
            try:
                _last_call_var.set(payload)
            except Exception:  # noqa: BLE001 — 无任务上下文时跳过
                pass
            return payload

    def last_call(self) -> Optional[Dict[str, Any]]:
        """最近一次调用的真实 usage（trace 对账用）；无记录返回 None。

        P2-6：请求任务上下文内优先返回任务级快照（并发隔离），
        否则回退进程级最近一次（后台脚本等无请求语义的调用方）。
        """
        task_local = _last_call_var.get()
        if task_local:
            return dict(task_local)
        with self._lock:
            last = getattr(self, "_last_call", None)
        return dict(last) if last else None

    def snapshot(self) -> Dict[str, Any]:
        """当前累计快照：by_model（含 per-provider 拆分）+ total + total_cost。"""
        import copy

        with self._lock:
            by_model = copy.deepcopy(self._by_model)

        total = {
            "calls": sum(e["calls"] for e in by_model.values()),
            "prompt_tokens": sum(e["prompt_tokens"] for e in by_model.values()),
            "completion_tokens": sum(e["completion_tokens"] for e in by_model.values()),
            "total_tokens": sum(e["total_tokens"] for e in by_model.values()),
            "estimated_calls": sum(e.get("estimated_calls", 0) for e in by_model.values()),
            "cache_read_tokens": sum(e.get("cache_read_tokens", 0) for e in by_model.values()),
            "cache_write_tokens": sum(e.get("cache_write_tokens", 0) for e in by_model.values()),
        }
        return {
            "by_model": by_model,
            "total": total,
            "total_cost": self._total_cost(by_model),
        }

    def estimate_cost(self, model: str) -> float:
        """按定价目录估算某模型累计成本（$）；未知模型 0.0。"""
        with self._lock:
            entry = self._by_model.get(model)
        if not entry:
            return 0.0
        pricing = self._PRICING.get(model, {})
        if not pricing:
            return 0.0
        return (
            entry["prompt_tokens"] * pricing.get("prompt", 0.0)
            + entry["completion_tokens"] * pricing.get("completion", 0.0)
        )

    @classmethod
    def _total_cost(cls, by_model: Dict[str, Any]) -> float:
        cost = 0.0
        for model, entry in by_model.items():
            pricing = cls._PRICING.get(model)
            if not pricing:
                continue
            cost += (
                entry["prompt_tokens"] * pricing.get("prompt", 0.0)
                + entry["completion_tokens"] * pricing.get("completion", 0.0)
            )
        return cost


_usage_accounting: Optional[TokenUsageAccounting] = None
_usage_lock = threading.Lock()


def get_usage_accounting() -> TokenUsageAccounting:
    """进程级单例（全部 LLM 调用方共享一本账）。"""
    global _usage_accounting
    if _usage_accounting is None:
        with _usage_lock:
            if _usage_accounting is None:
                _usage_accounting = TokenUsageAccounting()
    return _usage_accounting


def reset_usage_accounting() -> None:
    """重置单例（测试用）。

    P2-6 配套：必须同时清任务级 ContextVar——record() 在测试主上下文
    set 的任务级快照会跨测试泄漏（同线程 context 复用），仅置空单例
    时 last_call() 仍读到旧值（test_no_usage_event_without_record 假红根因）。
    """
    global _usage_accounting
    with _usage_lock:
        _usage_accounting = None
    # 直接 set None 清任务级快照（set_task_last_call 的 if payload 守卫
    # 使传 None 成为空操作，清不掉跨测试泄漏的 ContextVar）
    try:
        _last_call_var.set(None)
    except Exception:  # noqa: BLE001
        pass
