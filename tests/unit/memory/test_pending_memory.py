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
import time
import uuid

import pytest

from neurova.memory.pending_memory import PendingMemoryStore, _fingerprint
from neurova.skills.builtin.memory_executor import MemorySkillExecutor
from neurova.skills.executor import SkillResult


_LEGACY_SCHEMA = """
CREATE TABLE pending_memories (
    id TEXT PRIMARY KEY, content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    memory_type TEXT NOT NULL DEFAULT 'semantic',
    source_sentence TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','confirmed','rejected')),
    fingerprint TEXT NOT NULL, memory_id TEXT,
    proposed_by TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL, decided_by TEXT, decided_at REAL, note TEXT
);
"""


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

    # ── 指纹状态机自洽（09-07 UNIQUE constraint 事故防回归）──────────

    def test_propose_idempotent_and_tombstone_lifecycle(self, store):
        """事故根因：propose 允许同指纹 pending 堆积，reject 盲改状态撞
        单墓碑唯一索引（UNIQUE constraint failed: pending_memories.fingerprint）。

        新状态机：同指纹未决行幂等回指（堆积不可达）→ 单条拒绝封存指纹
        → 同内容再提议命中墓碑 rejected_before。"""
        r1 = store.propose(content="同内容 A")
        r2 = store.propose(content="同内容 A")
        assert r1["id"] == r2["id"]  # 幂等回指，不再堆积
        out = store.reject(r1["id"], rejected_by="admin")
        assert out["status"] == "rejected"
        with pytest.raises(ValueError):  # 已裁决行不可重复拒绝
            store.reject(r1["id"], rejected_by="admin")
        assert store.propose(content="同内容 A").get("rejected") is True
        assert len(store.list_decisions(status="rejected")) == 1

    def test_propose_returns_existing_pending_for_same_fingerprint(self, store):
        """propose 命中已有未决指纹时回指既有记录，不无限堆积待审行。"""
        first = store.propose(content="重复提议")
        second = store.propose(content="重复提议")
        assert second["id"] == first["id"]
        assert len(store.list_pending()) == 1

    def test_propose_normalized_fingerprint_dedup(self, store):
        """归一化指纹（大小写/首尾空白）在未决态同样判重。"""
        store.propose(content="大小写测试")
        again = store.propose(content="  大小写测试  ")
        assert len(store.list_pending()) == 1
        assert again["content"] == "大小写测试"

    def test_propose_after_confirm_allows_reproposal(self, store):
        """confirmed 不是拒绝墓碑：同内容确认入库后允许再次提议。"""
        r1 = store.propose(content="确认后再提")
        store.confirm(r1["id"], lambda c, cat, mt: "mem_x")
        r2 = store.propose(content="确认后再提")
        assert r2.get("rejected") is not True
        assert r2["status"] == "pending"

    def test_propose_per_user_isolation(self, store):
        """判重按提议人隔离（09-07 用户拍板）：甲的未决/墓碑不影响乙。"""
        a = store.propose(content="共享内容", proposed_by="alice")
        b = store.propose(content="共享内容", proposed_by="bob")
        assert a["id"] != b["id"]
        assert b["status"] == "pending"
        assert [i["id"] for i in store.list_pending(proposed_by="alice")] == [a["id"]]
        assert [i["id"] for i in store.list_pending(proposed_by="bob")] == [b["id"]]
        # 同用户仍幂等回指
        a2 = store.propose(content="共享内容", proposed_by="alice")
        assert a2["id"] == a["id"]

    def test_reject_tombstone_scoped_to_proposer(self, store):
        """拒绝墓碑只封存提议人自己：甲拒后甲再提 rejected_before，乙可提。"""
        a = store.propose(content="被拒内容", proposed_by="alice")
        store.reject(a["id"], rejected_by="admin")
        assert store.propose(content="被拒内容", proposed_by="alice").get("rejected") is True
        b = store.propose(content="被拒内容", proposed_by="bob")
        assert b.get("rejected") is not True
        assert b["status"] == "pending"
        # 匿名桶（proposed_by=''）自成一域，不受 alice 墓碑影响
        anon = store.propose(content="被拒内容")
        assert anon.get("rejected") is not True

    def test_migrate_tombstone_scoped_to_user(self, tmp_path):
        """存量迁移按 (指纹, 提议人) 收敛：u1 墓碑清掉 u1 残留 pending，
        u2 同内容 pending 保留（全局判重时代会被误删）。"""
        db = str(tmp_path / "scoped_legacy.db")
        conn = sqlite3.connect(db)
        conn.executescript(
            _LEGACY_SCHEMA
            + """
            CREATE UNIQUE INDEX pending_memories_rejected_fp_idx
                ON pending_memories (fingerprint) WHERE status = 'rejected';
            """
        )
        fp = _fingerprint("跨用户内容")
        now = time.time()
        conn.execute(
            "INSERT INTO pending_memories (id, content, status, fingerprint,"
            " proposed_by, created_at, decided_by, decided_at)"
            " VALUES ('tomb-u1', '跨用户内容', 'rejected', ?, 'u1', ?, 'admin', ?)",
            (fp, now, now),
        )
        conn.execute(
            "INSERT INTO pending_memories (id, content, status, fingerprint,"
            " proposed_by, created_at) VALUES ('stale-u1', '跨用户内容', 'pending', ?, 'u1', ?)",
            (fp, now + 1),
        )
        conn.execute(
            "INSERT INTO pending_memories (id, content, status, fingerprint,"
            " proposed_by, created_at) VALUES ('keep-u2', '跨用户内容', 'pending', ?, 'u2', ?)",
            (fp, now + 2),
        )
        conn.commit()
        conn.close()

        s2 = PendingMemoryStore(db_path=db)
        assert s2.get("stale-u1") is None  # u1 墓碑指纹下残留清除
        kept = s2.get("keep-u2")
        assert kept is not None and kept["status"] == "pending"  # u2 不受 u1 墓碑影响
        assert [i["id"] for i in s2.list_pending(proposed_by="u2")] == ["keep-u2"]
        assert s2.propose("跨用户内容", proposed_by="u1").get("rejected") is True
        assert s2.propose("跨用户内容", proposed_by="u2")["id"] == "keep-u2"

    def test_migrate_legacy_pending_duplicates(self, tmp_path):
        """存量库堆积的多条同指纹 pending（现场实况：8 pending + 1 墓碑）：
        重开连接时自动收敛——墓碑指纹下残留 pending 删除，无墓碑堆积留最新
        一条，此后 reject 不再撞唯一索引。"""
        db = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(db)
        conn.executescript(
            """
            CREATE TABLE pending_memories (
                id TEXT PRIMARY KEY, content TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                memory_type TEXT NOT NULL DEFAULT 'semantic',
                source_sentence TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','confirmed','rejected')),
                fingerprint TEXT NOT NULL, memory_id TEXT,
                proposed_by TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL, decided_by TEXT, decided_at REAL, note TEXT
            );
            CREATE UNIQUE INDEX pending_memories_rejected_fp_idx
                ON pending_memories (fingerprint) WHERE status = 'rejected';
            """
        )
        fp = _fingerprint("堆积的历史提议")
        ids = [str(uuid.uuid4()) for _ in range(3)]
        for i, rid in enumerate(ids):
            conn.execute(
                "INSERT INTO pending_memories (id, content, status, fingerprint,"
                " proposed_by, created_at) VALUES (?, '堆积的历史提议', 'pending', ?, 'u1', ?)",
                (rid, fp, time.time() + i),
            )
        conn.commit()
        conn.close()

        s2 = PendingMemoryStore(db_path=db)  # 重开连接触发存量清洗
        items = s2.list_pending()
        assert len(items) == 1
        assert items[0]["id"] == ids[-1]  # 保留最新一条
        for rid in ids[:-1]:
            assert s2.get(rid) is None  # 堆积行已收敛（内容由保留行代表）
        s2.reject(ids[-1], rejected_by="admin")  # 不再撞索引
        assert s2.get(ids[-1])["status"] == "rejected"

    def test_migrate_pending_under_rejected_fingerprint_removed(self, tmp_path):
        """现场形态：墓碑已存在，同指纹 pending 残留（旧行为下 reject 必炸）。
        迁移后残留清除，墓碑保留，同内容再提议仍被封存。"""
        db = str(tmp_path / "tombstone_legacy.db")
        tomb_id = str(uuid.uuid4())
        conn = sqlite3.connect(db)  # 用旧 schema 裸建库模拟存量现场
        conn.executescript(
            """
            CREATE TABLE pending_memories (
                id TEXT PRIMARY KEY, content TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                memory_type TEXT NOT NULL DEFAULT 'semantic',
                source_sentence TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','confirmed','rejected')),
                fingerprint TEXT NOT NULL, memory_id TEXT,
                proposed_by TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL, decided_by TEXT, decided_at REAL, note TEXT
            );
            CREATE UNIQUE INDEX pending_memories_rejected_fp_idx
                ON pending_memories (fingerprint) WHERE status = 'rejected';
            """
        )
        conn.execute(
            "INSERT INTO pending_memories (id, content, status, fingerprint,"
            " proposed_by, created_at, decided_by, decided_at)"
            " VALUES (?, '先拒后堆', 'rejected', ?, 'u1', ?, 'admin', ?)",
            (tomb_id, _fingerprint("先拒后堆"), time.time(), time.time()),
        )
        conn.execute(
            "INSERT INTO pending_memories (id, content, status, fingerprint,"
            " proposed_by, created_at) VALUES ('stale-1', '先拒后堆', 'pending', ?, 'u1', ?)",
            (_fingerprint("先拒后堆"), time.time()),
        )
        conn.commit()
        conn.close()

        s2 = PendingMemoryStore(db_path=db)
        assert s2.list_pending() == []  # 墓碑指纹下同提议人残留清除
        assert s2.get("stale-1") is None
        tomb = s2.list_decisions(status="rejected")
        assert len(tomb) == 1 and tomb[0]["id"] == tomb_id
        assert s2.propose(content="先拒后堆", proposed_by="u1").get("rejected") is True


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
