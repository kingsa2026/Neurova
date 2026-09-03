"""记忆检索数据源统一回归测试（TDD）

修复的断点：
- W2/双写分裂: 缓冲区 flush 曾优先写入 CognitiveStorageEngine/MemoryStorage
  （JSON 痕迹库，recall 永远读不到）→ 改为优先 memory_manager.remember。
- M1/MoE 读错存储: MoE 路由器的 L0 下钻与初始索引曾指向 JSON MemoryStorage
  （聊天记忆根本不在里面）→ 统一指向 MemoryManager 的 persist.db（memories 表），
  专家定义列名对齐真实 schema（category/lifecycle_stage，去掉不存在的
  is_crystallized 列）。
"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from neurova.cognitive_layers.memory_layer.conversation_buffer import MemoryItem, MemoryWriteQueue


# ----------------------------- P0-2 flush 归一 -----------------------------


def _make_queue():
    storage = MagicMock()
    manager = MagicMock()
    queue = MemoryWriteQueue(storage=storage, agent_id="a1", memory_manager=manager)
    return queue, storage, manager


def test_flush_prefers_memory_manager_over_trace_storage():
    """同时具备 storage 与 memory_manager 时，必须走可被 recall 读取的 memory_manager"""
    queue, storage, manager = _make_queue()
    item = MemoryItem(id="i1", content="用户喜欢蓝色", timestamp=datetime.now())
    queue.enqueue(item)

    written = queue.flush_to_storage()

    assert written == 1
    manager.remember.assert_called_once()
    kwargs = manager.remember.call_args.kwargs
    assert kwargs["content"] == "用户喜欢蓝色"
    # 痕迹库不应再接收对话记忆（只存不取的双写源头）
    storage.save.assert_not_called()


def test_flush_falls_back_to_storage_without_manager():
    """无 memory_manager 时保留原降级路径"""
    storage = MagicMock()
    queue = MemoryWriteQueue(storage=storage, agent_id="a1", memory_manager=None)
    queue.enqueue(MemoryItem(id="i2", content="fallback", timestamp=datetime.now()))

    assert queue.flush_to_storage() == 1
    storage.save.assert_called_once()


# ----------------------------- P0-1 MoE 数据源统一 -----------------------------


@pytest.fixture
def mem_core_with_sqlite(tmp_path):
    """真实 MemoryManager（persist.db 落在 tmp_path），经 MemCore 组装"""
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager
    from neurova.mem_core import MemCore

    db_path = str(tmp_path / "agent_mem.db")
    manager = MemoryManager(db_path, agent_id="a_test", neuser_id="n1", user_id="u1")
    manager.remember("用户提到喜欢爬山", memory_type="episodic", category="conversation")
    manager.remember("知识：地球是圆的", memory_type="semantic", category="knowledge")

    agent = MagicMock()
    agent.memory_manager = manager
    return MemCore(agent), manager


def test_moe_router_reads_persist_db_not_json_store(mem_core_with_sqlite):
    """MoE 路由器的 L0 存储必须是 persist.db（memories 表可 SQL 查询）"""
    mem_core, manager = mem_core_with_sqlite
    mem_core.init_moe_router()

    moe = mem_core.moe_router
    assert moe is not None, "MoE 路由器应初始化成功"
    store = moe.storage
    rows = store.execute(
        "SELECT content FROM memories WHERE category = :category",
        {"category": "conversation"},
    ).fetchall()
    contents = [r["content"] for r in rows]
    assert "用户提到喜欢爬山" in contents, "L0 下钻应能从 persist.db 命中聊天记忆"


def test_moe_expert_defs_match_real_schema(mem_core_with_sqlite):
    """专家定义不得引用 persist.db 不存在的列（is_crystallized 曾致 L0 必然异常返回空）"""
    mem_core, _ = mem_core_with_sqlite
    mem_core.init_moe_router()

    valid_columns = {
        "id", "content", "memory_type", "category", "lifecycle_stage", "perspective",
        "emotion", "temperature", "importance", "access_count", "metadata",
        "agent_id", "neuser_id", "user_id", "shared", "created_at", "updated_at",
        "last_accessed_at",
    }
    moe = mem_core.moe_router
    for expert_id, expert in moe.experts.items():
        for key in expert:
            if key in ("name", "centroid_text"):
                continue
            assert key in valid_columns, f"专家 {expert_id} 引用了 memories 表不存在的列: {key}"


def test_refresh_moe_index_uses_memory_manager(mem_core_with_sqlite):
    """refresh_moe_index 应从 MemoryManager（persist 数据源）重建索引，而非 JSON store"""
    mem_core, manager = mem_core_with_sqlite
    mem_core.init_moe_router()
    mem_core.refresh_moe_index()

    moe = mem_core.moe_router
    assert len(moe.vector_store.memory_ids) >= 2, "索引应包含刚写入的两条记忆"
