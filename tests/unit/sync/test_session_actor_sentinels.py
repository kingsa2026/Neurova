# -*- coding: utf-8 -*-
"""session 同步面的系统行为者哨兵单源（fullrepo 审计 2026-11-18 C2）。

swarm/tool_executor 注册 session 时落的是字面量 "swarm"/"agent"——
不能道出真实主体，且哨兵名散落各处（chat_pipeline 另用 "anonymous"）。
收口到 session_sync_manager 单源常量：两个哨兵标的是"注册来源是哪个
系统面"，与 "anonymous"（请求身份缺失时的用量兜底，§3 口径）语义互斥。
"""
import inspect

import neurova.agent.swarm as swarm_mod
import neurova.tool_executor as tool_executor_mod
from neurova.sync.session_sync_manager import SYSTEM_ACTOR_AGENT, SYSTEM_ACTOR_SWARM


def test_sentinels_are_single_sourced():
    assert SYSTEM_ACTOR_SWARM == "swarm"
    assert SYSTEM_ACTOR_AGENT == "agent"
    # 值不漂移：与历史字面量一致（改值=改运行态行为，需另批评审）
    swarm_src = inspect.getsource(swarm_mod)
    tool_src = inspect.getsource(tool_executor_mod)
    assert "user_id=SYSTEM_ACTOR_SWARM" in swarm_src, "swarm 注册点未走单源哨兵"
    assert "user_id=SYSTEM_ACTOR_AGENT" in tool_src, "tool_executor 注册点未走单源哨兵"
    assert 'user_id="swarm"' not in swarm_src, "swarm 侧仍有裸字面量哨兵"
    assert 'user_id="agent"' not in tool_src, "tool_executor 侧仍有裸字面量哨兵"
