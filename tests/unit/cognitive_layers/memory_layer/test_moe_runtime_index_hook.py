# -*- coding: utf-8 -*-
"""MoE 向量库的运行期增量入口（缺陷：MoE store 只在启动扫描时被灌满）。

MemoryManager 在 remember/forget 两处已经增量维护关键词倒排
（semantic_search.upsert_memory_index / remove_memory_index），但 MoE 路由器
持有的 UnifiedVectorStore 是 init_moe_router 自建的另一个实例，运行期没人喂它
——新增记忆要到下次启动重扫才可见，refresh_moe_index 又零调用方。本测试锁定
"同一条记忆同时进运行期向量库"这条闭环。
"""
from pathlib import Path

from neurova.cognitive_layers.memory_layer.manager import MemoryManager


class _RecordingStore:
    """最小 UnifiedVectorStore 契约：按 id 增量索引 + 按谓词摘除。"""

    def __init__(self):
        self.memory_ids: list = []
        self.index_calls: list = []
        self.removed_ids: list = []

    def index_memories(self, memories, incremental=False):
        self.index_calls.append(list(memories))
        for m in memories:
            if m["id"] not in self.memory_ids:
                self.memory_ids.append(m["id"])

    def remove_documents(self, predicate):
        kept = [mid for mid in self.memory_ids if not predicate(str(mid))]
        dropped = [mid for mid in self.memory_ids if predicate(str(mid))]
        self.removed_ids.extend(dropped)
        self.memory_ids = kept
        return len(dropped)


def _manager(tmp_path: Path) -> MemoryManager:
    return MemoryManager(db_path=str(tmp_path / "memory" / "memory.db"))


def test_remember_syncs_registered_vector_store(tmp_path: Path):
    manager = _manager(tmp_path)
    store = _RecordingStore()
    manager.register_runtime_vector_store(store)

    memory_id = manager.remember("运行期新增的探针记忆")

    assert store.index_calls, "remember 必须把这条同步进已登记的向量库"
    assert store.index_calls[-1][0]["id"] == memory_id
    assert memory_id in store.memory_ids


def test_hard_forget_drops_from_registered_vector_store(tmp_path: Path):
    manager = _manager(tmp_path)
    store = _RecordingStore()
    manager.register_runtime_vector_store(store)
    memory_id = manager.remember("随后被硬删除的记忆")

    assert manager.forget(memory_id, soft=False) is True

    assert memory_id not in store.memory_ids
    assert store.removed_ids == [memory_id]


def test_unregistered_manager_writes_without_error(tmp_path: Path):
    """没登记向量库（未起 MoE 的裸记忆库）时写入链路不得被新钩子打断。"""
    manager = _manager(tmp_path)

    assert manager.remember("未登记向量库时照常写入")


def test_agent_wires_moe_store_into_runtime_sync(tmp_path: Path):
    """装配闭环：真实 Agent 起来后，新记忆即刻进 MoE 向量库。"""
    from neurova.agent_core import Agent

    agent = Agent(workspace_path=str(tmp_path))
    store = agent.memory_agent.moe_router.vector_store
    assert agent.memory_manager._runtime_vector_store is store

    memory_id = agent.memory_manager.remember("运行期新增记忆应即刻进 MoE 索引")

    assert memory_id in store.memory_ids
