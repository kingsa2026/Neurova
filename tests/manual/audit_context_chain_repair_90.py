#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上下文三链路修复（Issue #90）live-verify 复现脚本。

手工运行，不进 CI；写盘全在系统临时目录（不碰 data/ 生产库）。
路径对齐审计报告的取证脚本约定（tests/manual/）。

用法：
    PYTHONPATH=. python tests/manual/audit_context_chain_repair_90.py

验四件事（每条都走真 Agent 构造面 + 真 orchestrator 链路）：
- B1/P0-1：判据估算（o200k）与真值同量级；9000 字符块触发折叠。
- B2/P0-2：群轮归档带作用域；单聊轮泄露 = False。
- B2/P1-1：折叠缓存按房间分槽，槽数受上限约束。
- B3/P0-3：draw 截断后池内原文与 hash 自洽。
- B3/P1-2：沿用旧摘要不算"本轮摘要成功"。
"""

import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402
isolatedDataRoot()
os.environ.setdefault("NEUROVA_AGENT_DB", os.path.join(tempfile.mkdtemp(prefix="ctxchain90_"), "agent.db"))

import tiktoken  # noqa: E402

from neurova.agent_core import Agent, AgentConfig  # noqa: E402
from neurova.context.token_estimator import estimate_tokens  # noqa: E402
from neurova.context.window_compactor import compact_window, estimate_window_tokens  # noqa: E402
from neurova.context_pool import ContextInput, ContextSource  # noqa: E402
from neurova.collaboration.memory_scope import scope_from_metadata  # noqa: E402

_ENCODER = tiktoken.get_encoding("o200k_base")


def _true_tokens(text: str) -> int:
    return len(_ENCODER.encode(text))


def _production_shape_history() -> list:
    """生产形状三轮历史：12 段英文散文 + 12 段 JSON + 一个 9000 字符无空格块。"""
    english = (
        "Context compression decides whether a model can hold a long conversation. "
        "If the estimate is wrong, folding never triggers and the prompt grows without bound. "
    )
    payload = json.dumps(
        {"name": "alpha", "items": [{"id": 1, "tag": "x"}], "nested": {"a": "b"}},
        ensure_ascii=False,
        indent=2,
    )
    history = [{"role": "user", "content": f"English paragraph {i}: " + english[:160]} for i in range(12)]
    history += [{"role": "assistant", "content": payload[:180]} for _ in range(12)]
    history.append({"role": "user", "content": "x" * 9000})
    return history


def check_ruler():
    print("[B1/P0-1] 尺子不低估 + 超预算必折叠")
    for label, blob in (
        ("x*9000", "x" * 9000),
        ("英文段", _production_shape_history()[0]["content"]),
        ("JSON 段", _production_shape_history()[12]["content"]),
    ):
        estimate, true = estimate_tokens(blob), _true_tokens(blob)
        print(f"  {label:10s} 判据={estimate:6d} 真值={true:6d} 比值={estimate / true:.2f}")
        assert estimate >= true, f"{label} 判据低估真值"

    history = _production_shape_history()
    true_tokens = sum(_true_tokens(m["content"]) + 4 for m in history)
    estimate = estimate_window_tokens(history)
    print(f"  三轮历史 判据={estimate} 真值={true_tokens}")
    assert estimate >= true_tokens

    async def produce(dropped, previous_summary=""):
        return "摘要"

    budget = true_tokens - 200
    result = asyncio.run(compact_window(history, budget, summarize=produce))
    print(f"  预算={budget} → 折叠 {result.compacted_count} 条，token {result.tokens_before}→{result.tokens_after}")
    assert result is not None and result.compacted_count > 0, "真值超预算却零折叠"


def check_scope(agent):
    """P0-2：归档带作用域 + 群聊不泄入单聊。"""
    print("[B2/P0-2 + P1-1] 归档带作用域 / 群聊不泄入单聊 / 缓存分槽")
    orch = agent.context_orchestrator
    secret = "量子项目代号 ZEPHYR-9"

    asyncio.run(
        orch.build_context(
            user_input="继续讨论",
            session_context=[{"role": "user", "content": secret}],
            relevant_memories=[],
            chat_collab=True,
            chat_room_id="project_roomB",
        )
    )
    archived = [c for c in orch.context_pool.get_contexts() if "ZEPHYR-9" in str(c.content)]
    assert archived, "群轮内容未入池"
    for chunk in archived:
        md = chunk.metadata or {}
        print(f"  chat_scope={md.get('chat_scope')!r} → {scope_from_metadata(md)!r}")
        assert md.get("chat_scope") == "room:project_roomB"

    view = asyncio.run(
        orch.build_context(
            user_input="量子项目代号是什么",
            session_context=[{"role": "user", "content": "量子项目代号是什么"}],
            relevant_memories=[],
            chat_collab=False,
        )
    )
    joined = "\n".join(str(m.get("content", "")) for m in view)
    print(f"  单聊轮泄露 = {secret in joined}")
    assert secret not in joined, "群聊原文泄入单聊"
    return orch


def check_cache_slots(agent):
    """P1-1：两房间各自折叠 → 摘要绝不串台；槽数受类级上限约束。"""
    print("[B2/P1-1] 折叠摘要按房间分槽 + 槽数上限")
    orch = agent.context_orchestrator
    orch._window_token_budget = 1200
    for room, topic in (("project_roomA", "量子计算"), ("project_roomB", "火星殖民")):
        history = [
            {"role": "user", "content": f"{room} 第{i}条：" + topic * 60} for i in range(12)
        ]
        asyncio.run(
            orch.build_context(
                user_input=f"继续 {room}",
                session_context=history,
                relevant_memories=[],
                chat_collab=True,
                chat_room_id=room,
            )
        )
    keys = sorted(orch._window_compaction_cache)
    print(f"  缓存键 = {keys}")
    print(f"  槽上限 = {orch._WINDOW_CACHE_SLOTS}，实际 = {len(keys)}")
    # 键是**会话身份**（房间 id），不是记忆作用域标签 `room:<id>`——
    # 两者语义不同：作用域是隔离策略（单聊恒 direct），身份是"哪一段对话"。
    assert "project_roomA" in keys and "project_roomB" in keys, "两房间未各自分槽"
    assert "_" not in keys, "仍有 '_' 键（session_id 恒 None 的旧记账）"
    # 各槽摘要必须由其自身上下文生成（本例无 LLM 客户端，摘要为错误占位符，
    # 故只断言"槽存在且互不相同"这一结构性事实）
    assert len(orch._window_compaction_cache) <= orch._WINDOW_CACHE_SLOTS, "槽数超上限"


def check_archive_immutable(orch):
    print("[B3/P0-3] 视图截断不就地改写归档（hash 与内容自洽）")
    long_text = "上下文压缩决定模型能否长期对话，" * 70
    chunk = ContextInput(
        source=ContextSource.CONVERSATION, content=long_text, priority=60, metadata={"role": "user"}
    )
    orch.context_pool.add_context(chunk)
    before_len, before_hash = len(chunk.content), chunk.hash

    orch.context_pool._drawer.max_tokens = 500
    drawn = orch.context_pool.draw(need="")
    print(f"  归档 {before_len} 字符 → draw 视图 {[len(d.content) for d in drawn]} 字符")
    print(f"  draw 后池内 {len(chunk.content)} 字符，hash 自洽 = "
          f"{ContextInput.compute_hash(chunk.source, chunk.content) == before_hash}")
    assert len(chunk.content) == before_len, "归档实体被就地截断"
    assert ContextInput.compute_hash(chunk.source, chunk.content) == before_hash
    truncated_views = [d for d in drawn if (d.metadata or {}).get("truncated_from") == before_hash]
    assert truncated_views, "未观察到带 truncated_from 标注的视图副本"
    assert all(d is not chunk for d in drawn), "返回的是归档实体本身"


def check_summary_freshness():
    print("[B3/P1-2] 沿用旧摘要不算'本轮摘要成功'")
    msgs = [{"role": "user", "content": "内容" * 200} for _ in range(12)]

    async def reuse_previous(dropped, previous_summary=""):
        return previous_summary

    async def produce_new(dropped, previous_summary=""):
        return "本轮新摘要"

    reused = asyncio.run(compact_window(msgs, 300, summarize=reuse_previous, previous_summary="旧摘要"))
    fresh = asyncio.run(compact_window(msgs, 300, summarize=produce_new, previous_summary="旧摘要"))
    print(f"  沿用旧摘要 summary_is_fresh={reused.summary_is_fresh}")
    print(f"  新摘要     summary_is_fresh={fresh.summary_is_fresh}")
    assert reused.summary_is_fresh is False, "沿用旧摘要被判为新鲜 → 覆盖记账会谎报"
    assert fresh.summary_is_fresh is True


def main():
    workspace = tempfile.mkdtemp(prefix="ctxchain90_ws_")
    agent = Agent(AgentConfig(name="ctx90", agent_id="ctx90", llm_model="gpt-4o", workspace_path=workspace))
    print(f"[setup] Agent 构造完成：orchestrator={type(agent.context_orchestrator).__name__}, "
          f"pool session_id={agent.context_orchestrator.context_pool.session_id}")

    check_ruler()
    orch = check_scope(agent)
    check_cache_slots(agent)
    check_archive_immutable(orch)
    check_summary_freshness()
    print("\nLIVE-VERIFY PASSED：B1 尺子 / B2 隔离写入口与缓存分槽 / B3 归档不可变与摘要新鲜度")


if __name__ == "__main__":
    main()
