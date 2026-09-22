"""008 残留 · 多 agent 下肌肉记忆的身份必须显式收口。

票据 008 的数据层要求：「`MuscleMemory.__init__`（`:150`）以 `**kwargs` 静默吞掉
`agent_id` ⇒ 一并收口为**显式参数**（否则多 agent 下仍可能串库；原子写 `:644-705` 保留）」。

现状：`MuscleMemory(agent_id="a1")` 不报错也不生效（`**kwargs` 吞掉），
`hasattr(m, "_agent_id")` 为 False —— 生产装配点 `agent_core.py` 传的 `agent_id`
落进黑洞，任何按身份读快照/落账的读取方都取不到值。合规形态是**显式参数 + 可读属性**。
"""

from __future__ import annotations

import inspect

from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory


class TestExplicitAgentIdentity:
    def test_signature_has_no_catch_all(self):
        parameters = inspect.signature(MuscleMemory.__init__).parameters
        assert "kwargs" not in parameters, (
            f"仍用 **kwargs 静默吞参数（agent_id 就是这么消失的）：{list(parameters)}"
        )

    def test_agent_id_is_keyword_only_and_readable(self):
        parameters = inspect.signature(MuscleMemory.__init__).parameters
        assert "agent_id" in parameters, "agent_id 未收口为显式参数"
        memory = MuscleMemory(agent_id="kai")
        assert getattr(memory, "agent_id", None) == "kai", (
            "显式传入的 agent_id 没落成可读属性（多 agent 下按身份取快照取不到）"
        )

    def test_unknown_keyword_still_fails_loudly(self):
        """收口后未知 kwarg 必须报错，不再静默吞掉（这正是串库的温床）。"""
        import pytest

        with pytest.raises(TypeError):
            MuscleMemory(agent_identity="typo")

    def test_default_identity_is_empty_not_none(self):
        """未传身份时给空串：与 `_sanitize_agent_id` 的既有口径一致，不落 None。"""
        memory = MuscleMemory()
        assert memory.agent_id == ""
