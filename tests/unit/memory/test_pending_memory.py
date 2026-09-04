"""P1-2 交互式记忆写入待确认中间态（Utopia pending_facts 裁剪版）。

契约（docs/Neurova_Utopia代码级对比_2026-09-04.md §2.3/§4 P1-2）：

PendingMemoryStore（独立 SQLite，与主记忆库分库分表——失败方向：
漏读 pending 的后果是"待审队列看不见"，不是"未确认记忆混进检索"）：
- propose：写入待审记录（content 原文 + category + 指纹），返回记录含 id；
- list_pending：按时间倒序；pending 记录绝不进入主记忆检索；
- confirm：把 content 经 remember_fn 真正落库（传回 memory_id），记录关闭；
- reject：记录关闭并记指纹（content 小写归一 sha256），同指纹不再被提议；
- 指纹拒绝防重提议：propose 命中已拒绝指纹返回 rejected 标记，不新建记录；
- 重启（重开连接）后 pending/已拒指纹均持久；
- store 异常不向上传播到调用方（写 pending 失败只少一个待审项）。

MemorySkillExecutor 挂钩（交互式单条写入口）：
- store 且 confirm=False（默认）→ 写 pending，返回 {pending: True, review_id}，
  不调 memory_manager.remember；
- store 且 confirm=True → 走原直写链路（语义不变）。
"""

import sqlite3

import pytest

from neurova.memory.pending_memory import PendingMemoryStore
from neurova.skills.builtin.memory_executor import MemorySkillExecutor
from neurova.skills.executor import SkillResult


@pytest.fixture
def store(tmp_path):
    return PendingMemoryStore(db_path=str(tmp_path / "pending_mem.db"))


class TestPendingStore:
    def test_propose_creates_pending(self, store):
        rec = store.propose(content="用户偏好深色主题", category="preference")
        assert rec["status"] == "pending"
        assert rec["content"] == "用户偏好深色主题"
        assert rec["id"]
        assert len(store.list_pending()) == 1

    def test_propose_empty_content_raises(self, store):
        with pytest.raises(ValueError):
            store.propose(content="   ")

    def test_list_pending_ordered_desc(self, store):
        store.propose(content="第一条")
        store.propose(content="第二条")
        items = store.list_pending()
        assert [i["content"] for i in items] == ["第二条", "第一条"]

    def test_confirm_calls_remember_and_closes(self, store):
        rec = store.propose(content="项目上线日期是周五", category="fact")
        seen = {}

        def remember_fn(content, category, memory_type):
            seen.update(content=content, category=category)
            return "mem_123"

        out = store.confirm(rec["id"], remember_fn)
        assert out["memory_id"] == "mem_123"
        assert seen == {"content": "项目上线日期是周五", "category": "fact"}
        assert store.list_pending() == []

    def test_remember_failure_keeps_pending(self, store):
        rec = store.propose(content="主库写入会失败的记录")

        def boom(content, category, memory_type):
            raise RuntimeError("db locked")

        with pytest.raises(RuntimeError):
            store.confirm(rec["id"], boom)
        # 记录仍 pending（未确认的记忆不能凭空消失）
        assert len(store.list_pending()) == 1

    def test_reject_fingerprint_blocks_reproposals(self, store):
        rec = store.propose(content="这条会被拒绝")
        store.reject(rec["id"], rejected_by="admin")

        again = store.propose(content="这条会被拒绝")
        assert again.get("rejected") is True
        assert len(store.list_pending()) == 0

    def test_reject_fingerprint_normalizes(self, store):
        rec = store.propose(content="统一大小写测试")
        store.reject(rec["id"])
        again = store.propose(content="统一大小写测试  ")
        assert again.get("rejected") is True

    def test_persistence_across_connections(self, tmp_path):
        db = str(tmp_path / "persist.db")
        s1 = PendingMemoryStore(db_path=db)
        rec = s1.propose(content="重启后仍在")

        s2 = PendingMemoryStore(db_path=db)
        assert [i["content"] for i in s2.list_pending()] == ["重启后仍在"]
        out = s2.confirm(rec["id"], lambda c, cat, mt: "mem_1")
        assert out["memory_id"] == "mem_1"

    def test_rejected_history_queryable(self, store):
        rec = store.propose(content="拒绝历史")
        store.reject(rec["id"], rejected_by="admin1")
        done = store.list_decisions(status="rejected")
        assert len(done) == 1
        assert done[0]["status"] == "rejected"
        assert done[0]["decided_by"] == "admin1"


class TestExecutorHook:
    @pytest.fixture
    def mm(self):
        mm = __import__("unittest").mock.MagicMock()
        mm.remember.return_value = "mem_direct"
        return mm

    def test_store_defaults_to_pending(self, mm, tmp_path):
        ex = MemorySkillExecutor(mm)
        ex.pending_store = PendingMemoryStore(db_path=str(tmp_path / "p.db"))
        result = ex.execute({"action": "store", "content": "需要确认的内容"})
        assert result.success is True
        assert result.output["pending"] is True
        assert result.output["review_id"]
        # 未直接落库
        mm.remember.assert_not_called()

    def test_store_confirm_true_keeps_direct_path(self, mm):
        ex = MemorySkillExecutor(mm)
        result = ex.execute({"action": "store", "content": "直接落库", "confirm": True})
        assert result.success is True
        assert result.output == {"stored": True}
        mm.remember.assert_called_once()


class TestProposedByServerSide:
    """P1-2 闭环审查修 F：提议归属以服务端隔离作用域身份优先，
    防调用方伪造 proposed_by 把内容栽进他人待审队列。"""

    def _executor_with_store(self, mm, tmp_path):
        from neurova.skills.builtin.memory_executor import MemorySkillExecutor

        ex = MemorySkillExecutor(mm)
        ex.pending_store = PendingMemoryStore(db_path=str(tmp_path / "p.db"))
        return ex

    def test_scope_identity_overrides_forged_param(self, tmp_path):
        from unittest.mock import MagicMock

        mm = MagicMock()
        mm.effective_user_id.return_value = "u_real"
        ex = self._executor_with_store(mm, tmp_path)

        result = ex.execute(
            {"action": "store", "content": "伪造归属的内容", "proposed_by": "u_victim"}
        )
        assert result.success is True
        rec = ex.pending_store.list_pending()[0]
        assert rec["proposed_by"] == "u_real"  # 服务端身份胜出
        assert rec["proposed_by"] != "u_victim"

    def test_falls_back_to_param_without_scope(self, tmp_path):
        """无作用域环境（CLI 等未设 request scope）：回退参数自报。"""
        from unittest.mock import MagicMock

        mm = MagicMock(spec=[])  # 无 effective_user_id 属性
        ex = self._executor_with_store(mm, tmp_path)

        result = ex.execute(
            {"action": "store", "content": "无作用域提议", "proposed_by": "u_cli"}
        )
        assert result.success is True
        rec = ex.pending_store.list_pending()[0]
        assert rec["proposed_by"] == "u_cli"

    def test_default_scope_ignored(self, tmp_path):
        """作用域返回 default（未登录/系统上下文）：不冒充真实用户，
        回退参数（原行为）。"""
        from unittest.mock import MagicMock

        mm = MagicMock()
        mm.effective_user_id.return_value = "default"
        ex = self._executor_with_store(mm, tmp_path)

        ex.execute({"action": "store", "content": "默认作用域", "proposed_by": "u9"})
        rec = ex.pending_store.list_pending()[0]
        assert rec["proposed_by"] == "u9"
