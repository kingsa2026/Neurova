"""012 · 归档语义不静默失真 —— memory_type 侧（红绿灯 TDD）。

根因：`post_chat_pipeline.py:2916` 传 `memory_type="workflow_experience"`，而
`MemoryType` 枚举里没有这个值 ⇒ `manager.py` 的解析分支 warning 后**静默换成
SEMANTIC**，每条工作流经验都退化成语义记忆，类型区分在写入瞬间就丢了。

落定契约（spec §4 D1 口径：标无证据、不砍量）：
1. `workflow_experience` 进枚举 ⇒ 按声明类型落库，且可按类型检索；
2. 仍未知的类型 ⇒ 行照存（拒绝等于把用户内容丢成 500，是把降级放大成丢数据），
   但必须留下证据：`metadata["_declared_memory_type"]` 记原值 +
   `_stats["unknown_memory_type_count"]` 计数可见 —— 不得再静默改类型；
3. 合法类型不得留下任何"无证据"痕迹（反向锁，防止标记无条件写）。
"""

from __future__ import annotations

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.models import MemoryType


@pytest.fixture()
def mgr(tmp_path):
    m = MemoryManager(
        db_path=str(tmp_path / "mem.db"),
        agent_id="type-agent",
        neuser_id="neu",
        user_id="u1",
        enable_buffer=False,
    )
    yield m
    m.close()


class TestWorkflowExperienceTypeSurvives:
    def test_declared_type_is_the_stored_type(self, mgr):
        mid = mgr.remember("先搜索再汇总再导出", memory_type="workflow_experience")
        assert mgr._memories[mid].memory_type is MemoryType.WORKFLOW_EXPERIENCE

    def test_retrievable_by_declared_type(self, mgr):
        mid = mgr.remember("先搜索再汇总再导出", memory_type="workflow_experience")
        mgr.remember("用户喜欢咖啡", memory_type="semantic")
        hits = mgr.recall(
            query="先搜索再汇总再导出", limit=10,
            memory_type="workflow_experience", use_semantic=False,
        )
        assert [h["id"] for h in hits] == [mid], "按类型检索必须只取到工作流经验"

    def test_persisted_type_survives_reload(self, tmp_path):
        first = MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="type-agent",
                              neuser_id="neu", user_id="u1", enable_buffer=False)
        first.remember("先搜索再汇总再导出", memory_type="workflow_experience")
        first.close()
        reopened = MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="type-agent",
                                 neuser_id="neu", user_id="u1", enable_buffer=False)
        try:
            assert [m.memory_type for m in reopened._memories.values()] == [
                MemoryType.WORKFLOW_EXPERIENCE
            ], "类型必须跨重启保留，不得回落到 semantic"
        finally:
            reopened.close()


class TestUnknownTypeIsLoud:
    def test_unknown_type_marks_declared_value_and_counts(self, mgr):
        mid = mgr.remember("某条事实", memory_type="totally_unknown_type")
        mem = mgr._memories[mid]
        assert mem.metadata.get("_declared_memory_type") == "totally_unknown_type", (
            "未知类型必须留下原始声明，不得静默换成 semantic"
        )
        assert mgr._stats["unknown_memory_type_count"] == 1

    def test_unknown_type_still_stores_the_row(self, mgr):
        """D1 不砍量：类型无证据不等于内容无价值，行必须保住。"""
        mgr.remember("某条事实", memory_type="totally_unknown_type")
        assert len(mgr.get_all_memories()) == 1

    def test_valid_type_leaves_no_unevidenced_trace(self, mgr):
        mid = mgr.remember("正常事实", memory_type="episodic")
        assert "_declared_memory_type" not in mgr._memories[mid].metadata
        assert mgr._stats["unknown_memory_type_count"] == 0
