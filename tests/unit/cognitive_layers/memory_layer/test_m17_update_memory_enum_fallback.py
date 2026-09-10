"""M-17 回归测试：update_memory 枚举解析兜底。

根因：manager.update_memory 的 `MemoryCategory(kwargs["category"])` /
`LifecycleStage(stage_val)` 直接枚举构造，非法值抛 ValueError → API 500。
对比 remember（:731-741）已有 warning + 回落默认的兜底模式。

修复后契约：非法字符串 warning + 回落默认（GENERAL / ACTIVE），
合法值与枚举实例直通行为不变。
"""

import uuid

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.models import (
    LifecycleStage,
    MemoryCategory,
)


@pytest.fixture()
def manager(tmp_path):
    mgr = MemoryManager(
        db_path=str(tmp_path / "m17" / "mem.db"),
        agent_id="m17-agent",
        neuser_id="neu",
        user_id="u",
    )
    yield mgr
    try:
        mgr._emotion_module.shutdown()
    except Exception:
        pass


def _new_memory(manager) -> str:
    return manager.remember(
        content=f"m17-{uuid.uuid4().hex[:8]}",
        temperature=50.0,
        importance=50.0,
    )


class TestM17UpdateMemoryEnumFallback:
    def test_invalid_category_falls_back_to_general(self, manager):
        mid = _new_memory(manager)
        ok = manager.update_memory(mid, category="totally-bogus-category")
        assert ok is True, "非法 category 不应导致 update_memory 失败（API 500）"
        assert manager._memories[mid].category == MemoryCategory.GENERAL

    def test_invalid_lifecycle_stage_falls_back_to_active(self, manager):
        mid = _new_memory(manager)
        ok = manager.update_memory(mid, lifecycle_stage="bogus-stage")
        assert ok is True, "非法 lifecycle_stage 不应导致 update_memory 失败"
        assert manager._memories[mid].lifecycle_stage == LifecycleStage.ACTIVE

    def test_valid_values_still_applied(self, manager):
        mid = _new_memory(manager)
        manager.update_memory(mid, category="conversation", lifecycle_stage="crystallized")
        assert manager._memories[mid].category == MemoryCategory.CONVERSATION
        assert manager._memories[mid].lifecycle_stage == LifecycleStage.CRYSTALLIZED

    def test_enum_instances_still_applied(self, manager):
        mid = _new_memory(manager)
        manager.update_memory(
            mid,
            category=MemoryCategory.KNOWLEDGE,
            lifecycle_stage=LifecycleStage.CRYSTALLIZED,
        )
        assert manager._memories[mid].category == MemoryCategory.KNOWLEDGE
        assert manager._memories[mid].lifecycle_stage == LifecycleStage.CRYSTALLIZED
