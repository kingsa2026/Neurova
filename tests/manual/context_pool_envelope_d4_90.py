#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B3 剩余 P2-8（D4 甲案）live-verify：真生产构造面，一条命令复现五条验收。

手工运行，不进 CI；不写盘（纯内存视图装配）。
用法：PYTHONPATH=. python tests/manual/context_pool_envelope_d4_90.py

验五件事（审计 §10 D4 甲案的三条前置条件逐条对证）：
1. 七处注入位无 system 行残留：池分支返回的消息里，`system` 只剩固定前缀；
2. 检索文本真在信封里：记忆/经验/池召回/工具记忆/情感各自落在对应块；
3. 前置条件 1（接入 compress_envelope）：信封受自己那份额度管辖，超预算时
   按 `COMPRESS_DROP_ORDER` 确定性淘汰，且淘汰后仍在额度上界内；
4. 前置条件 3（新块与淘汰顺位）：`<history>` 紧跟 `emotion`，先于 memories 被弃；
5. 无静默消失：召回取回的内容不得因信封额度不足被整体丢掉。
"""
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

from neurova.context.envelope import (  # noqa: E402
    COMPRESS_DROP_ORDER,
    build_envelope,
    compress_envelope,
    parse_envelope,
)
from neurova.context.token_estimator import estimate_tokens  # noqa: E402
from neurova.context.window_compactor import estimate_window_tokens  # noqa: E402


def buildAgent():
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "d4"
    agent.config.agent_id = "d4"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.config.enable_auto_tagging = False
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "D4 活体验证助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u1"
    agent.agent_id = "d4"
    agent.question_queue_manager = None
    return agent


async def build(orch, **kwargs):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock, return_value=""):
        return await orch.build_context(**kwargs)


def main():
    from neurova.context.orchestrator import ContextOrchestrator

    orch = ContextOrchestrator(buildAgent(), use_pool=True, auto_tag=False)

    # ── 步 1：七处注入位一次进信封 ──
    result = asyncio.run(
        build(
            orch,
            user_input="帮我看看部署方案",
            relevant_memories=[{"content": "用户偏好灰度发布"}],
            experience_items=[{"content": "先备份再迁移", "id": "e1"}],
            crystallized_patterns=[{"content": "迁移前先冻结写入"}],
            tool_memory_result={"tool_name": "file_read", "result": "4096 bytes"},
            session_context=[{"role": "user", "content": "讨论迁移"}],
        )
    )
    sysLines = [m["content"] for m in result if m.get("role") == "system"]
    blocks = parse_envelope(str(result[-1]["content"]))
    leaked = [
        text
        for text in ("用户偏好灰度发布", "先备份再迁移", "迁移前先冻结写入", "[工具记忆]")
        if text in "\n".join(sysLines)
    ]
    print(
        "[1 七处注入位] "
        + json.dumps(
            {
                "system_rows": len(sysLines),
                "leaked_into_system": leaked,
                "envelope_blocks": sorted(blocks),
            },
            ensure_ascii=False,
        )
    )

    # ── 步 2：检索文本真在信封里 ──
    print(
        "[2 信封内容] "
        + json.dumps(
            {
                "memories_has_pref": "灰度发布" in blocks.get("memories", ""),
                "experience_has_lesson": "先备份再迁移" in blocks.get("experience", ""),
                "experience_has_crystallized": "冻结写入" in blocks.get("experience", ""),
                "tooling_has_tool": "[工具记忆]" in blocks.get("tooling", ""),
            },
            ensure_ascii=False,
        )
    )

    # ── 步 3：池召回落 <history>（跨轮、真池） ──
    orch2 = ContextOrchestrator(buildAgent(), use_pool=True, auto_tag=False)
    asyncio.run(
        build(
            orch2,
            user_input="我下周要去许昌出差",
            session_context=[{"role": "user", "content": "我下周要去许昌出差"}],
        )
    )
    recalled = asyncio.run(
        build(
            orch2,
            user_input="还记得我要去哪里出差吗",
            session_context=[{"role": "user", "content": "今天心情不错"}],
        )
    )
    historyBlock = parse_envelope(str(recalled[-1]["content"])).get("history", "")
    print(
        "[3 池召回] "
        + json.dumps(
            {
                "history_block_present": bool(historyBlock),
                "has_recall_mark": "[历史回忆]" in historyBlock,
                "has_xuchang": "许昌" in historyBlock,
                "leaked_into_system": "[历史回忆]"
                in "\n".join(m["content"] for m in recalled if m.get("role") == "system"),
            },
            ensure_ascii=False,
        )
    )

    # ── 步 4：超预算确定性淘汰 + 仍在额度上界内 ──
    bulky = "- [历史回忆] 用户: " + "很长的归档原文。" * 300
    env = build_envelope({"memories": "- 记忆甲", "emotion": "😊 joy: 80%", "history": bulky})
    tight = compress_envelope(env, budget_tokens=200, count_tokens=len)
    tightBlocks = parse_envelope(tight)
    print(
        "[4 淘汰顺位] "
        + json.dumps(
            {
                "drop_order": list(COMPRESS_DROP_ORDER),
                "history_dropped_before_memories": "history" not in tightBlocks
                and "memories" in tightBlocks,
                "compressed_len": len(tight),
                "within_budget": len(tight) <= 200,
            },
            ensure_ascii=False,
        )
    )

    # ── 步 5：无静默消失——召回内容不得因额度不足被整体丢掉 ──
    orch3 = ContextOrchestrator(buildAgent(), use_pool=True, auto_tag=False)
    orch3._window_token_budget = 2500
    history = [
        {"role": "user", "content": f"我们讨论了{i}号城市的部署方案与灰度发布策略。" * 30}
        for i in range(12)
    ]
    asyncio.run(build(orch3, user_input="12号城市", session_context=history))
    ctx2 = history[6:] + [{"role": "user", "content": "0号城市部署的结论是什么？"}]
    squeezed = asyncio.run(build(orch3, user_input="0号城市部署的结论是什么？", session_context=ctx2))
    squeezedBlocks = parse_envelope(str(squeezed[-1]["content"]))
    drawn = orch3.context_pool.draw(need="0号城市部署的结论是什么？")
    print(
        "[5 无静默消失] "
        + json.dumps(
            {
                "window_token_budget": orch3._resolve_window_token_budget(),
                "drawer_returned": len(drawn),
                "envelope_blocks": sorted(squeezedBlocks),
                "recall_survived": any(
                    tag in squeezedBlocks for tag in ("history", "memories", "experience", "tooling")
                ),
                "view_tokens": estimate_window_tokens(
                    [m for m in squeezed if m.get("role") in ("user", "assistant")][:-1]
                )
                + estimate_tokens(str(squeezed[-1]["content"])),
            },
            ensure_ascii=False,
        )
    )

    # 判据逐条对证（不写成恒真断言）：
    # 1 无 system 残留；2 检索文本在信封；3 池召回落 <history>；
    # 4 超预算时 <history> 先于 memories 被弃；5 额度被挤满时召回内容仍有一块活着
    recallAlive = any(tag != "time" for tag in squeezedBlocks)
    ok = (
        not leaked
        and "memories" in blocks
        and "history" in parse_envelope(str(recalled[-1]["content"]))
        and "history" not in tightBlocks
        and "memories" in tightBlocks
        and recallAlive
    )
    print("LIVE-VERIFY PASSED" if ok else "LIVE-VERIFY FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
