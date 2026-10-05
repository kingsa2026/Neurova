"""`update_memory` 归属校验（P1-6 补齐）

2026-08-30 那批三层隔离根修给 `get_memory`/`forget` 加了归属校验
（`docs/01-architecture/audit/three-tier-isolation-fixes.md` P1-6），但同族方法
`update_memory` 从未纳入：它只 `self._memories.get(memory_id)`，既不校验 agent
也不校验 neuser/user。同一个 manager 实例按 agent 持有**全部用户**的记忆，
于是知道 id 就能改内容——取证见 `audit-reports/memory-isolation-2026-10-05.md`
图证 [2]/[3]（bob 与匿名各 PUT 一次，alice 的记忆内容就真的变了）。

作用域是 ContextVar（同进程内会跨用例残留），沿用同目录
`test_memory_request_scope.py` 的进出归还口径。
"""

import pytest

from neurova.cognitive_layers.memory_layer import manager as manager_mod
from neurova.cognitive_layers.memory_layer.manager import MemoryManager


@pytest.fixture
def mgr(tmp_path):
    return MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="agent_a")


@pytest.fixture(autouse=True)
def _cleanScope():
    manager_mod._scope_var.set(None)
    yield
    manager_mod._scope_var.set(None)


class TestUpdateOwnership:
    """归属校验必须与 get_memory/forget 同规则，否则第 2、3 层形同虚设"""

    def test_foreignScopeUpdateIsRejected(self, mgr):
        with mgr.request_scope(neuser_id="ne_1", user_id="u_1"):
            mid = mgr.remember("owned content")

        with mgr.request_scope(neuser_id="ne_2", user_id="u_2"):
            rejected = mgr.update_memory(mid, content="tampered by other user")

        assert rejected is False, "他人作用域竟能改写记忆：update_memory 无归属校验"
        with mgr.request_scope(neuser_id="ne_1", user_id="u_1"):
            assert mgr._memories[mid].content == "owned content"

    def test_ownerCanStillUpdate(self, mgr):
        """校验不能把正常归属者的编辑也关掉（防过度收紧）"""
        with mgr.request_scope(neuser_id="ne_1", user_id="u_1"):
            mid = mgr.remember("v1")
            assert mgr.update_memory(mid, content="v2") is True
            assert mgr._memories[mid].content == "v2"
