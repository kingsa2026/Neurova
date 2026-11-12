# -*- coding: utf-8 -*-
"""P2-15 MemorySkill 接真记忆管理器红测（全库断点审计 2026-11-12）。

缺陷：MemorySkill._search_memory/_store_memory 是恒空/假成功 stub
（"这里应该调用记忆管理器"）——该 Skill 仅存在于 builtin 注册失败的回退
分支，失败形态是"查无记忆"而非报错。

修复口径（审计开方，拍板：接真 recall）：走注入的记忆管理器 recall/remember。
"""
import asyncio

import pytest


@pytest.fixture
def skill(tmp_path):
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager
    from neurova.skill_system.core import MemorySkill

    mgr = MemoryManager(
        db_path=str(tmp_path / "m.db"),
        agent_id="agent_ms",
        neuser_id="default",
        user_id="default",
    )
    return MemorySkill(mgr)


def test_memory_skill_wires_real_manager(skill):
    marker = "技能链私有事实标记X"
    skill.memory_manager.remember(marker, auto_classify=False)

    result = asyncio.run(
        skill.execute({"action": "search", "query": marker}, None)
    )
    assert result.success, f"search 失败：{result.error}"
    assert result.data, "回退分支的记忆 Skill 必须接真 recall（P2-15）"
    assert any(marker in (r.get("content") or "") for r in result.data)

    stored = asyncio.run(skill.execute({"action": "store", "content": "新记忆Y"}, None))
    assert stored.success and stored.data.get("memory_id"), "store 必须真落库"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
