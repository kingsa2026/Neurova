# -*- coding: utf-8 -*-
"""记忆技能在"管理器没挂上"时必须诚实失败（审计 §6-17 的**真实现场**）。

原判"executor 注册失败即回退注册假 Skill 子类"经复核不成立在活路径上——那些桩类
被同名包遮蔽（见 `tests/unit/core/test_no_shadowed_module_files.py`）。同一个谎却在
真执行器里活着：`MemorySkillExecutor` 在 `memory_manager is None` 时

    store  → success=True, output={"stored": True, "degraded": True}
    search → success=True, output=[]

调用方读的两个字段是 `success` 与 `output["stored"]`，`degraded` 只是附注；实际一条
记忆都没写。把失败收进 `success=False` + 点名原因（实测全仓无人读 `stored` 键，
收紧不破任何消费方）。
"""

from neurova.skills.builtin.memory_executor import MemorySkillExecutor


def testStoreWithoutManagerIsHonestFailure():
    result = MemorySkillExecutor().execute({"action": "store", "content": "要记住的事"})

    assert result.success is False, (
        "一条都没写进库却回执成功：success=%r output=%r" % (result.success, result.output)
    )
    assert result.error and "记忆管理器" in result.error, (
        "失败必须点名缺什么，不能只留一个 degraded 附注：%r" % result.error
    )
    assert not (result.output or {}).get("stored") if isinstance(result.output, dict) else True, \
        "仍回 stored=True：%s" % result.output


def testSearchWithoutManagerIsHonestFailure():
    """无管理器时返回空列表且 success=True，与"真查了、没命中"不可区分。"""
    result = MemorySkillExecutor().execute({"action": "search", "query": "任何词"})

    assert result.success is False, (
        "缺席的能力不得伪装成一次成功的空结果集：%r" % (result.output,))
    assert result.error and "记忆管理器" in result.error, result.error


def testStoreWithManagerStillWrites(tmp_path):
    """反向证明：收紧后真挂了管理器的路径仍要能写进去，且"成功"来自被调用过。

    不凭 `success` 字段自证——断言管理器的 `remember` 真被调用（生产实现即此方法）。
    """
    calls = []

    class _RecordingManager:
        def remember(self, **kwargs):
            calls.append(kwargs)
            return {"id": "m-1"}

    result = MemorySkillExecutor(memory_manager=_RecordingManager()).execute(
        {"action": "store", "content": "要记住的事", "category": "general"})

    assert result.success is True, "%s / %s" % (result.success, result.error)
    assert calls and calls[0]["content"] == "要记住的事", calls
