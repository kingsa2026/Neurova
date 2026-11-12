# -*- coding: utf-8 -*-
"""P2-23 injector 兜底路径注入登记红测（全库断点审计 2026-11-12）。

缺陷：EKB 经验的采纳回写（injected_count/adoption_outcome）只认
`set_turn_injected_experiences` 登记的 id，而登记只发生在 chat_pipeline
主检索路径——injector 兜底路径（experience 为空时按需查 EKB 渲染）注入的
经验行永不登记，采纳计数系统性偏低。

修复口径（审计开方）：兜底渲染时同走登记函数。
"""
from types import SimpleNamespace

import pytest


@pytest.fixture
def injector():
    from neurova.context.injector import UnifiedContextInjector

    inj = object.__new__(UnifiedContextInjector)
    inj._memory_manager = SimpleNamespace(agent_id="agent_x")
    inj._show_empathy = False
    inj._metacog_agent_id = None
    return inj


def test_fallback_registers_injected_experience_ids(injector, monkeypatch):
    import neurova.skills.experience_knowledge_base as ekb_mod
    from neurova.core import turn_context

    hit = {
        "id": 42, "success": True, "skill_name": "chat",
        "context": {"user_input": "查询"}, "result": {"reply_excerpt": "r"},
        "adoption_outcome": None, "operator_disposition": None,
    }

    class FakeEKB:
        def find_similar_experiences(self, **kwargs):
            return [hit]

    monkeypatch.setattr(ekb_mod, "get_experience_knowledge_base", lambda: FakeEKB())

    # 复现时序：主检索路径未命中时先登记空列表，兜底渲染随后发生
    turn_context.set_turn_injected_experiences([])

    content = injector._build_experience_context("查询")

    assert content, "兜底渲染不应为空"
    assert turn_context.get_turn_injected_experiences() == [42], (
        "兜底路径注入的经验未登记——采纳回写（injected_count/adoption_outcome）"
        "永远不会更新（P2-23）"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
