# -*- coding: utf-8 -*-
"""clear_turn_state 全量清空守卫（审计 3.2-7，2026-11-17）：

teardown 清空必须覆盖**全部**轮次级 ContextVar——原实现漏清
`_subagent_tool_allowlist_var`（蜂群子代理工具面白名单）与
`_tool_call_id_var`（当前工具调用回投地址），跨回合残留：
子代理会话结束后白名单收窄仍生效（面外工具被结构化拒绝），
审批回投地址串到下一轮的工具调用上。
"""

from __future__ import annotations

import pytest

from neurova.core.turn_context import (
    clear_turn_state,
    get_subagent_tool_allowlist,
    get_turn_tool_call_id,
    set_subagent_tool_allowlist,
    set_turn_tool_call_id,
)


class TestClearTurnStateFullSweep:
    def test_subagent_allowlist_cleared(self):
        set_subagent_tool_allowlist({"read_file", "web_search"})
        try:
            clear_turn_state()
            assert get_subagent_tool_allowlist() is None, (
                "clear_turn_state 后子代理工具面白名单必须回到「不收窄」"
            )
        finally:
            clear_turn_state()

    def test_tool_call_id_cleared(self):
        set_turn_tool_call_id("call_abc123")
        try:
            clear_turn_state()
            assert get_turn_tool_call_id() is None, (
                "clear_turn_state 后当前工具调用 id 必须清空（审批回投不得串轮）"
            )
        finally:
            clear_turn_state()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
