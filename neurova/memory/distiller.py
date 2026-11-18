# -*- coding: utf-8 -*-
"""记忆蒸馏回写（2026-11-18 立项，docs/04-plans/2026-11-18-memory-distillation-plan.md）。

对话轮末异步归纳"值得长期记住的事实"，走既有治理链落库：

    LLM 归纳（agent 自身 provider 链，非流式 chat）
      → memory_admission 敏感筛查（enforce 策略下源头跳过）
      → PendingMemoryStore.propose（指纹幂等/墓碑/S16 敏感标记）
      → 人工审阅（pending 审阅面 + S16 转正）
      → memories 表（温度生命周期）

红线：不直写 memories 表；不写任何文件旁路；LLM 失败 fail-soft 不阻断
主对话，连续失败熔断。开关 NEUROVA_MEMORY_DISTILL 默认 off=零行为。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any, Dict, List

from neurova.memory.pending_memory import get_pending_memory_store
from neurova.memory_admission import currentAdmissionPolicy, screenMemoryContent

logger = logging.getLogger(__name__)

#: 灰度开关：默认 off（关=不调 LLM、不产候选、零行为变化）
DISTILL_ENV = "NEUROVA_MEMORY_DISTILL"

#: 单次归纳的 LLM 超时（秒）
_LLM_TIMEOUT_S = 30.0
#: 单轮候选上限（洪水防护）
_MAX_CANDIDATES = 8
#: 取材窗口字符上限
_WINDOW_CHARS = 6000
#: 窗口最小长度：过短对话无蒸馏价值，省一次 LLM 调用
_MIN_WINDOW_CHARS = 24
#: 连续失败熔断阈值（同 agent）
_BREAKER_LIMIT = 3
#: 熔断冷却（秒）：超过后自动半开重试
_BREAKER_COOLDOWN_S = 300.0

_lock = threading.Lock()
_failureCounts: Dict[str, int] = {}
_lastFailureAt: Dict[str, float] = {}
_counters: Dict[str, int] = {
    "turns": 0,
    "llmFailures": 0,
    "candidates": 0,
    "submitted": 0,
    "skippedSensitive": 0,
    "duplicates": 0,
    "breakerOpens": 0,
}


def distillEnabled() -> bool:
    """灰度开关：env 显式 =1 才启用。"""
    import os

    return os.environ.get(DISTILL_ENV, "").strip() == "1"


def distillCounters() -> dict:
    """进程内蒸馏计数快照（D4 观测面数据源）。"""
    with _lock:
        return dict(_counters)


def resetDistillerBreaker(agent_id: str) -> None:
    """复位某 agent 的连续失败计数（测试与运维用）。"""
    with _lock:
        _failureCounts.pop(str(agent_id or "default"), None)
        _lastFailureAt.pop(str(agent_id or "default"), None)


def _bump(name: str) -> None:
    with _lock:
        _counters[name] = _counters.get(name, 0) + 1


def _recordMetric(outcome: str) -> None:
    """D4 观测面：蒸馏结果进既有 /metrics 指标读面（fail-soft）。"""
    try:
        from neurova.core.metrics import get_metrics

        get_metrics().record_memory_distill(outcome)
    except Exception:  # noqa: BLE001 - 观测失败不影响主流程
        pass


def _agentId(agent: Any) -> str:
    config = getattr(agent, "config", None)
    return str(getattr(config, "agent_id", "") or "default")


def _breakerOpen(agent_id: str) -> bool:
    with _lock:
        count = _failureCounts.get(agent_id, 0)
        if count < _BREAKER_LIMIT:
            return False
        last = _lastFailureAt.get(agent_id, 0.0)
        if time.time() - last >= _BREAKER_COOLDOWN_S:
            # 冷却过半开：给一次重试机会，失败会立刻重新计满
            _failureCounts[agent_id] = _BREAKER_LIMIT - 1
            return False
        return True


def _noteFailure(agent_id: str, message: str) -> Dict[str, Any]:
    opened = False
    with _lock:
        count = _failureCounts.get(agent_id, 0) + 1
        _failureCounts[agent_id] = count
        _lastFailureAt[agent_id] = time.time()
        if count == _BREAKER_LIMIT:
            _counters["breakerOpens"] = _counters.get("breakerOpens", 0) + 1
            opened = True
    _bump("llmFailures")
    _recordMetric("failed")
    if opened:
        logger.warning(
            "记忆蒸馏连续失败 %d 次，已熔断 %s（冷却 %.0fs）：%s",
            count, agent_id, _BREAKER_COOLDOWN_S, message)
    else:
        logger.warning("记忆蒸馏失败（%s）：%s", agent_id, message)
    return {"error": message, "agent_id": agent_id, "failures": count}


def _noteSuccess(agent_id: str) -> None:
    with _lock:
        _failureCounts.pop(agent_id, None)
        _lastFailureAt.pop(agent_id, None)


def _buildWindow(user_input: str, reply: str) -> str:
    parts = []
    if str(user_input or "").strip():
        parts.append(f"用户：{str(user_input).strip()}")
    if str(reply or "").strip():
        parts.append(f"助手：{str(reply).strip()}")
    return "\n".join(parts).strip()[:_WINDOW_CHARS]


def _buildPrompt(window: str) -> str:
    return (
        "你是记忆蒸馏器。从下面的对话片段提炼\"值得长期记住的事实\""
        "（用户偏好、约束、项目背景、明确结论）。\n"
        "只输出 JSON 数组，每项形如 "
        '{"content": "事实一句话", "category": "preference|constraint|project|fact", '
        '"memory_type": "semantic"}。'
        "不要泛化、不要编造、不要包含密钥密码等敏感凭据；"
        "没有值得记的就输出 []。\n\n"
        f"对话片段：\n{window}"
    )


def _parseCandidates(text: str) -> List[Dict[str, str]]:
    """从 LLM 输出解析候选数组（取首个 '[' 到末个 ']'，容错围栏文本）。"""
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end <= start:
        raise ValueError("蒸馏输出不含 JSON 数组")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, list):
        raise ValueError("蒸馏输出不是 JSON 数组")
    out: List[Dict[str, str]] = []
    for item in data[:_MAX_CANDIDATES]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        out.append({
            "content": content,
            "category": str(item.get("category") or "").strip() or "fact",
            "memory_type": str(item.get("memory_type") or "").strip() or "semantic",
        })
    return out


async def distillTurnMemory(
    agent: Any, *, user_input: str, reply: str, session_id: str = ""
) -> Dict[str, Any]:
    """轮末蒸馏入口：开关关/窗口短/熔断开时零行为；否则归纳→筛查→候选。

    任何失败 fail-soft（计数+熔断），绝不向调用方抛异常——本步骤是
    PostChatPipeline 的旁路后台步骤，主对话不因蒸馏故障受损。
    """
    if not distillEnabled():
        return {"skipped": "disabled"}

    agent_id = _agentId(agent)
    if _breakerOpen(agent_id):
        return {"skipped": "breaker", "agent_id": agent_id}

    window = _buildWindow(user_input, reply)
    if len(window) < _MIN_WINDOW_CHARS:
        return {"skipped": "window_too_short", "agent_id": agent_id}

    llm = getattr(agent, "llm_client", None)
    if llm is None or not hasattr(llm, "chat"):
        # 配置缺 LLM 客户端属部署形态问题，不计熔断（避免误关正常 agent）
        return {"skipped": "no_llm", "agent_id": agent_id}

    prompt = _buildPrompt(window)
    _bump("turns")
    _recordMetric("turn")
    try:
        response = await asyncio.wait_for(
            llm.chat([{"role": "user", "content": prompt}], temperature=0.0),
            timeout=_LLM_TIMEOUT_S,
        )
    except Exception as e:  # noqa: BLE001 - 超时/网络/客户端异常统一 fail-soft
        return _noteFailure(agent_id, f"llm timeout/error: {e}")

    text = str(getattr(response, "content", "") or "")
    if text.startswith("[LLM Error]"):
        return _noteFailure(agent_id, f"llm error envelope: {text[:200]}")

    try:
        candidates = _parseCandidates(text)
    except Exception as e:  # noqa: BLE001 - 坏输出按失败计（防重复撞坏输出）
        return _noteFailure(agent_id, f"parse: {e}")

    _bump("candidates")
    store = get_pending_memory_store()
    existing_ids = {str(r.get("id") or "") for r in store.list_pending(proposed_by="distiller")}
    submitted = 0
    skipped_sensitive = 0
    duplicates = 0
    enforce = currentAdmissionPolicy() == "enforce"
    for cand in candidates:
        content = cand["content"]
        # 源头准入：enforce 策略下敏感候选不进队列（audit/off 交由 propose
        # 的 S16 筛查标记 + 人工审阅裁决）
        if enforce and screenMemoryContent(content) is not None:
            skipped_sensitive += 1
            _bump("skippedSensitive")
            _recordMetric("sensitive")
            continue
        try:
            rec = store.propose(
                content=content,
                category=cand["category"],
                memory_type=cand["memory_type"],
                source_sentence=str(user_input or "")[:200],
                proposed_by="distiller",
            )
        except Exception as e:  # noqa: BLE001 - 单条候选失败不拖垮整批
            logger.warning("蒸馏候选落候选队列失败: %s", e)
            continue
        rid = str(rec.get("id") or "") if isinstance(rec, dict) else ""
        if isinstance(rec, dict) and rec.get("rejected"):
            # 墓碑/历史拒绝：内容不得再进队列（按重复弃置计）
            duplicates += 1
            _bump("duplicates")
            _recordMetric("duplicate")
            continue
        if rid and rid in existing_ids:
            # 指纹幂等回指：同内容未决候选已存在，不重复计提交
            duplicates += 1
            _bump("duplicates")
            _recordMetric("duplicate")
            continue
        if rid:
            existing_ids.add(rid)
        submitted += 1
        _bump("submitted")
        _recordMetric("submitted")

    _noteSuccess(agent_id)
    logger.info(
        "记忆蒸馏完成（%s/%s）：候选 %d，入候选队列 %d，敏感跳过 %d，重复 %d",
        agent_id, session_id or "-", len(candidates), submitted,
        skipped_sensitive, duplicates,
    )
    return {
        "candidates": len(candidates),
        "submitted": submitted,
        "skipped_sensitive": skipped_sensitive,
        "duplicates": duplicates,
        "agent_id": agent_id,
    }
