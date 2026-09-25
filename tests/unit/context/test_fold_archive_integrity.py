# -*- coding: utf-8 -*-
"""B6-10 批次 B：「折叠前必须已归档」这条零丢失判据必须真的有人校验（Issue #90 审计 §5）。

## 红灯依据（改前实证）

审计 §5 把 `_last_archived_window_hashes` 记为「只写不读」并点名：它是
"折叠前必须已归档"这条**零丢失判据的唯一物证**，却**留下没人校验**。
本仓实测，它不只是"没读"，而是**判据本身错域**：

- 归档侧按来源分域：`role=tool` 的消息以 `ContextSource.TOOL_CALL` 入池，
  其余按 `CONVERSATION`；
- 折叠侧（`_last_folded_hashes` 与防召回集合）**一律按 CONVERSATION 域**算指纹。

于是工具结果这一支的折叠指纹**永远匹配不到池内条目**：

```
折叠了但池中无同域条目的条数: 1     ← role=tool 的那条
池内 tool 条目指纹域: CONVERSATION? False  TOOL_CALL? True
```

后果有两处，都是静默的：① 零丢失判据拿它校验必然报假缺失（所以它一直没被读）；
② 防召回集合对工具归档恒不命中 —— 折叠掉的工具原文会被当轮语义召回原位注回视图，
折叠白做（B6-5 修的正是这条链的工具寻址侧）。

## 契约（修复后）

1. **指纹域单源**：窗口消息 → 归档指纹的域判定只有一处（与归档侧同一份），
   `role=tool` 走 `TOOL_CALL`，其余走 `CONVERSATION`；折叠侧复用它，
   不再各自写一份"一律 CONVERSATION"。
2. **判据真被读**：折叠发生后，折叠集合逐条对池校验"原文在池"，
   读数经 `get_context_health()["fold_integrity"]` 上报（`checked` / `missing` /
   `last_error`）。缺一条即点名，不静默。
3. **校验不得恒真**：喂一个池内必然不存在的指纹，`missing` 必须为 1 且点名原因。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.context.fold_integrity import verifyFoldIntegrity
from neurova.context.orchestrator import ContextOrchestrator
from neurova.context_pool import ContextInput, ContextSource


def _agent() -> MagicMock:
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.memory_manager = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u1"
    agent.agent_id = "a1"
    return agent


def _orchestrator(budget: int = 2500) -> ContextOrchestrator:
    orch = ContextOrchestrator(_agent(), use_pool=True, auto_tag=False)
    orch._window_token_budget = budget
    orch._window_summarizer = None
    return orch


TOOL_PAYLOAD = "工具结果" * 400


def _history_with_tool_result() -> list:
    """含完整 tool 轮（assistant.tool_calls + role=tool）的长历史。

    工具结果体积独大 → 必然落在折叠区（`split_window_by_budget` 从尾部保留），
    这正是判据错域那一支。
    """
    history = [
        {"role": "user", "content": "帮我查一下固件版本"},
        {
            "role": "assistant",
            "content": "调用工具",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "content": TOOL_PAYLOAD, "tool_call_id": "c1", "name": "web_search"},
    ]
    for i in range(1, 8):
        history.append({"role": "user", "content": f"问题{i}: " + "问" * 300})
        history.append({"role": "assistant", "content": f"回答{i}: " + "答" * 300})
    return history


async def _build(orch: ContextOrchestrator, history: list):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock, return_value=""):
        return await orch.build_context(
            user_input="固件 工具结果",
            session_context=history,
            relevant_memories=[],
        )


class TestFoldFingerprintSharesSourceDomain:
    """折叠侧与归档侧的指纹域必须同源（改前各自写一份）。"""

    def test_tool_message_fingerprint_uses_tool_call_domain(self):
        orch = _orchestrator()
        source, content = orch._windowChunkIdentity({"role": "tool", "content": "x"}, )
        assert source == ContextSource.TOOL_CALL, (
            "role=tool 的窗口消息必须以 TOOL_CALL 域取指纹——归档侧就是这么写的，"
            "折叠侧按 CONVERSATION 取会永远匹配不到池内条目"
        )
        assert content == "x"

    def test_non_tool_message_fingerprint_uses_conversation_domain(self):
        orch = _orchestrator()
        source, _ = orch._windowChunkIdentity({"role": "assistant", "content": "x"})
        assert source == ContextSource.CONVERSATION

    @pytest.mark.asyncio
    async def test_folded_tool_result_matches_its_pooled_entry(self):
        """工具结果被折叠时，其折叠指纹必须能在池里找到同域条目。"""
        orch = _orchestrator()
        history = _history_with_tool_result()
        await _build(orch, history)

        tool_hash = ContextInput.compute_hash(ContextSource.TOOL_CALL, TOOL_PAYLOAD)
        assert tool_hash in orch._last_folded_hashes, (
            "工具结果没有被折叠 —— 本用例的前提不成立（预算或历史形状变了）"
        )
        assert tool_hash in set(orch.context_pool._by_hash.keys()), (
            "折叠指纹与池内条目错域：归档走 TOOL_CALL、折叠走 CONVERSATION，"
            "于是零丢失判据必然报假缺失、防召回集合恒不命中工具归档"
        )

    @pytest.mark.asyncio
    async def test_every_folded_hash_is_archived(self):
        """零丢失判据：折叠集合 ⊆ 池内条目（逐条校验，不是抽样）。"""
        orch = _orchestrator()
        await _build(orch, _history_with_tool_result())

        missing = orch._last_folded_hashes - set(orch.context_pool._by_hash.keys())
        assert not missing, (
            f"有 {len(missing)} 条被折叠的内容在池中找不到归档 —— 折叠即丢失"
            "（池是唯一副本，折叠后视图不再持有原文）"
        )


class TestFoldIntegrityIsReadAndNamed:
    """判据必须真被读：读数上看得见，缺条即点名。"""

    @pytest.mark.asyncio
    async def test_readout_reports_checked_and_clean(self):
        orch = _orchestrator()
        await _build(orch, _history_with_tool_result())

        report = orch.get_context_health()["fold_integrity"]
        assert report["checked"] > 0, "折叠发生了却零校验 —— 判据又变成只写不读"
        assert report["missing"] == 0, f"零丢失判据报缺失：{report}"
        assert report["not_archived_before_fold"] == 0, (
            f"折叠不在归档之后 —— 时序判据（_last_archived_window_hashes）报红：{report}"
        )
        assert report["last_error"] is None

    def test_check_can_actually_fail_on_fold_before_archive(self):
        """反向控制一：折叠指纹不在归档集合里 → 判据报「折叠早于归档」。"""
        orch = _orchestrator()

        report = verifyFoldIntegrity({"折叠了但没归档"}, {"别的指纹"}, orch.context_pool)

        assert report["checked"] == 1
        assert report["not_archived_before_fold"] == 1, (
            "折叠早于归档却零告警 —— 时序判据（_last_archived_window_hashes）恒真"
        )
        assert report["last_error"] and "FoldBeforeArchive" in report["last_error"], (
            "缺失了却不说原因（教义第 2 条：不许静默）"
        )

    def test_check_can_actually_fail_on_missing_pool_entry(self):
        """反向控制二：指纹声明已归档、池里却没有 → 判据报「折叠即丢失」。"""
        orch = _orchestrator()
        ghost = "折叠指纹"

        report = verifyFoldIntegrity({ghost}, {ghost}, orch.context_pool)

        assert report["not_archived_before_fold"] == 0
        assert report["missing"] == 1, "校验恒真 —— 它就不是判据"
        assert report["last_error"] and "FoldLost" in report["last_error"], (
            "缺失了却不说原因（教义第 2 条：不许静默）"
        )

    def test_pool_absent_is_named_not_silently_passed(self):
        """无池时判据没有落点：如实点名，不静默通过成"零缺失"。"""
        report = verifyFoldIntegrity({"x"}, {"x"}, None)

        assert report["last_error"] and "PoolAbsent" in report["last_error"]
        assert report["missing"] == 0

    @pytest.mark.asyncio
    async def test_clean_build_leaves_readout_clean(self):
        """正常路径反向控制：校验不能把好数据报成缺失。"""
        orch = _orchestrator()
        await _build(orch, _history_with_tool_result())

        assert orch.get_context_health()["fold_integrity"]["last_error"] is None
