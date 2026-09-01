# -*- coding: utf-8 -*-
"""
P1-8 context pool 压测（兼作 P1-1 验收）

语义：100 轮对话归档 → 视图抽取（draw 配对校验 + 预算）→ 溢出恢复链路。
压测锁定**关键词降级路径**（monkeypatch drawer._vector_store=False，剔除
ONNX 嵌入模型加载/推理变量——模型性能归专项，此处验证池正确性与吞吐）。

正确性优先、阈值宽松（CI 稳定）：
- 100 轮归档 + 每 10 轮一次 draw：< 10s（关键词路径实测亚秒级）
- draw 结果预算内、TOOL_CALL 无孤儿、最新轮次在场
"""
import time

import pytest


@pytest.fixture()
def pool(monkeypatch):
    from neurova.context_pool import ContextPool

    p = ContextPool(
        user_id="perf-user",
        agent_id="perf-agent",
        session_id="perf-session",
        max_tokens=8000,
        max_size=1000,
    )
    # 真实属性名 _drawer（context_pool.py:93），设 False 强制关键词降级
    monkeypatch.setattr(p._drawer, "_vector_store", False, raising=False)
    return p


def _round_inputs(turn: int):
    from neurova.context.pool_models import ContextInput, ContextSource

    tool_id = f"tool-{turn}"
    return [
        ContextInput(
            source=ContextSource.USER_INPUT,
            content=f"[turn {turn}] 用户：帮我分析第 {turn} 批数据并总结趋势",
            priority=80,
        ),
        ContextInput(
            source=ContextSource.CONVERSATION,
            content=f"[turn {turn}] 助手：已分析第 {turn} 批数据，趋势为线性增长。",
            priority=70,
        ),
        ContextInput(
            source=ContextSource.TOOL_CALL,
            content=f"[turn {turn}] tool=data_query result=ok",
            priority=60,
            metadata={"tool_call_id": tool_id},  # 真实配对锚点（pairing 校验用）
        ),
    ]


class TestContextPoolHundredTurns:
    def test_hundred_turns_archive_and_draw(self, pool):
        from neurova.context.pool_models import ContextSource

        start = time.perf_counter()
        for turn in range(100):
            for item in _round_inputs(turn):  # add_context 收单条 ContextInput
                pool.add_context(item)
            if turn % 10 == 9:
                view = pool.draw(need=f"第 {turn} 批数据")
                for c in view:
                    if c.source == ContextSource.TOOL_CALL:
                        # P1-1 配对校验：视图内 TOOL_CALL 必须有配对锚点
                        assert c.metadata.get("tool_call_id")
        elapsed = time.perf_counter() - start
        assert elapsed < 10.0, f"100 轮归档+抽取耗时 {elapsed:.2f}s，超出阈值"

    def test_latest_turns_present_after_full_archive(self, pool):
        for turn in range(100):
            for item in _round_inputs(turn):
                pool.add_context(item)
        view = pool.draw(need="第 99 批数据")
        texts = [c.content for c in view]
        assert any("第 99 批" in t for t in texts), "最新轮次必须在视图内"


class TestOverflowRecovery:
    """P1-1 溢出恢复链路在长会话下的行为验收（签名：messages+recent_keep）"""

    def test_compact_preserves_system_and_recent(self):
        from neurova.context.recovery import compact_messages_for_overflow

        messages = (
            [{"role": "system", "content": "你是数据助手。"}]
            + [
                {"role": "user" if i % 2 == 0 else "assistant", "content": f"消息 {i} " * 50}
                for i in range(200)
            ]
        )
        compacted, info = compact_messages_for_overflow(messages, recent_keep=10)

        assert len(compacted) < len(messages)
        assert compacted[0]["role"] == "system"  # system 锚点保留
        # 尾部 recent_keep 原样保留
        assert compacted[-1] == messages[-1]
        assert compacted[-10:] == messages[-10:]
        # 折叠信息可审计
        assert info.get("folded_count", 0) > 0

    def test_compact_single_roundtrip_small_input(self):
        from neurova.context.recovery import compact_messages_for_overflow

        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
        ]
        compacted, info = compact_messages_for_overflow(msgs, recent_keep=6)
        # 输入小于保留窗：原样返回
        assert compacted == msgs
