"""S16 D2 记忆重纪律——红灯测试（先红后绿）。

四道必答（方案 S16 红灯定义）：
1. 3-Task 候选转正：跨 3 个独立任务第 3 次观测才转正，前两次不转；
2. 世代失效：矛盾事实使旧代标记 superseded 且可追溯（不物理删）；
3. 人工审阅接通：待审候选经 screenMemoryContent 拦截敏感内容，
   人工显式放行/拒收留痕；
4. 门控：NEUROVA_MEMORY_DISCIPLINE 关闭时行为与现状完全一致。

装配纪律：一律走生产装配点——MemCore.memory_manager setter 单点包层
（installMemoryAdmission + installMemoryDiscipline），测试不自装闸、不绕过装配点。
候选/世代字段落点 = metadata["memoryDiscipline"]（零 schema 变更、零枚举扩容）；
转正判定单点 = memory_discipline.installMemoryDiscipline 包装的 remember 观察簿记。
"""

from unittest.mock import MagicMock

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.mem_core import MemCore


# ============================================================
# 测试辅助
# ============================================================

DISCIPLINE_KEY = "memoryDiscipline"


def make_manager(tmp_path: pytest.TempPathFactory, name: str = "persist") -> MemoryManager:
    """真实 MemoryManager（tmp_path 隔离，persist 库随主库落 tmp）。"""
    db = str(tmp_path / f"{name}.db")
    return MemoryManager(db, agent_id="agent-q", neuser_id="nq", user_id="uq")


def make_gated_core(manager: MemoryManager) -> MemCore:
    """经生产装配点（MemCore.memory_manager setter）接入真实管理器。"""
    agent = MagicMock()
    agent.memory_manager = None
    core = MemCore(agent)
    core.memory_manager = manager  # setter 内完成单点包层（admission + discipline）
    return core


@pytest.fixture(autouse=True)
def restoreDisciplineGate():
    """每个用例后恢复门控默认 off，避免开启态用例污染后续用例。"""
    yield
    from neurova.memory_discipline import setMemoryDisciplineEnabled

    setMemoryDisciplineEnabled(False)


def enable_discipline() -> None:
    from neurova.memory_discipline import setMemoryDisciplineEnabled

    setMemoryDisciplineEnabled(True)


def disc_meta(memory: dict) -> dict:
    return (memory.get("metadata") or {}).get(DISCIPLINE_KEY) or {}


# ============================================================
# 一、3-Task 候选转正（门控开启态）
# ============================================================


class TestThreeTaskPromotion:
    def test_first_observation_enters_as_candidate(self, tmp_path):
        """第 1 次观测：带来源任务标入候选，不转正。"""
        enable_discipline()
        manager = make_manager(tmp_path)
        make_gated_core(manager)

        mem_id = manager.remember(
            content="用户的项目代号是启明", metadata={"session_id": "task-a"}
        )
        row = manager.get_memory(mem_id)
        disc = disc_meta(row)
        assert disc.get("status") == "candidate"
        assert disc.get("taskKeys") == ["task-a"]
        # 候选语义可见：生命周期保持 active，既有读路径不受影响
        assert row["lifecycle_stage"] == "active"

    def test_second_distinct_task_still_candidate(self, tmp_path):
        """第 2 次跨任务观测：仍不转正。"""
        enable_discipline()
        manager = make_manager(tmp_path)
        make_gated_core(manager)
        content = "用户的项目代号是启明"

        id1 = manager.remember(content=content, metadata={"session_id": "task-a"})
        id2 = manager.remember(content=content, metadata={"session_id": "task-b"})

        assert id1 == id2  # 内容门命中同一行（再观测）
        disc = disc_meta(manager.get_memory(id2))
        assert disc["status"] == "candidate"
        assert sorted(disc["taskKeys"]) == ["task-a", "task-b"]

    def test_third_distinct_task_promotes(self, tmp_path):
        """第 3 次跨任务观测：转正为持久记忆。"""
        enable_discipline()
        manager = make_manager(tmp_path)
        make_gated_core(manager)
        content = "用户的项目代号是启明"

        id1 = manager.remember(content=content, metadata={"session_id": "task-a"})
        id2 = manager.remember(content=content, metadata={"session_id": "task-b"})
        id3 = manager.remember(content=content, metadata={"session_id": "task-c"})

        assert id1 == id2 == id3
        disc = disc_meta(manager.get_memory(id3))
        assert disc["status"] == "promoted"
        assert sorted(disc["taskKeys"]) == ["task-a", "task-b", "task-c"]
        assert disc.get("promotedAt")

    def test_same_task_reobservation_does_not_duplicate_count(self, tmp_path):
        """同任务内重复观测不重复计数（跨独立任务才算）。"""
        enable_discipline()
        manager = make_manager(tmp_path)
        make_gated_core(manager)
        content = "用户的交付时区是 UTC+8"

        manager.remember(content=content, metadata={"session_id": "task-a"})
        manager.remember(content=content, metadata={"session_id": "task-a"})
        mem_id = manager.remember(content=content, metadata={"session_id": "task-a"})

        disc = disc_meta(manager.get_memory(mem_id))
        assert disc["status"] == "candidate"
        assert disc["taskKeys"] == ["task-a"]

    def test_task_key_prefers_run_id_over_session_id(self, tmp_path):
        """任务键取值优先级：task_id > run_id > session_id（单一口径）。"""
        enable_discipline()
        manager = make_manager(tmp_path)
        make_gated_core(manager)

        mem_id = manager.remember(
            content="用户的发布窗口是周五", metadata={"run_id": "run-9", "session_id": "s1"}
        )
        assert disc_meta(manager.get_memory(mem_id))["taskKeys"] == ["run-9"]

    def test_unattributed_write_skips_candidacy(self, tmp_path):
        """无任务/会话上下文的写入（API 人工直写）：不进候选，行为不变。"""
        enable_discipline()
        manager = make_manager(tmp_path)
        make_gated_core(manager)

        mem_id = manager.remember(content="用户明确要求记住这个约定")
        row = manager.get_memory(mem_id)
        assert DISCIPLINE_KEY not in (row.get("metadata") or {})
        assert row["lifecycle_stage"] == "active"


# ============================================================
# 二、世代失效（门控开启态）
# ============================================================


class TestGenerationalSupersession:
    def test_contradiction_supersedes_old_generation(self, tmp_path):
        """矛盾事实使旧代失效：superseded + 指针可追溯，不物理删。"""
        enable_discipline()
        manager = make_manager(tmp_path)
        make_gated_core(manager)

        old_id = manager.remember(
            content="用户住在上海", metadata={"session_id": "s-old"}
        )
        new_id = manager.remember(
            content="用户不住在上海", metadata={"session_id": "s-new"}
        )

        old_row = manager.get_memory(old_id)
        # 退出召回但不物理删（可按 id 追溯）
        assert old_row is not None
        assert old_row["lifecycle_stage"] == "forgotten"
        disc = disc_meta(old_row)
        assert disc["status"] == "superseded"
        assert disc["supersededBy"] == new_id
        assert disc.get("supersededAt")
        assert disc.get("supersededBasis")  # 凭哪两句认定的，逐字可查
        # 新代存活
        assert manager.get_memory(new_id)["lifecycle_stage"] == "active"

    def test_non_contradiction_keeps_old_generation(self, tmp_path):
        """无关事实不误伤旧代。"""
        enable_discipline()
        manager = make_manager(tmp_path)
        make_gated_core(manager)

        old_id = manager.remember(
            content="用户住在上海", metadata={"session_id": "s-old"}
        )
        manager.remember(
            content="用户喜欢深色主题", metadata={"session_id": "s-new"}
        )
        assert manager.get_memory(old_id)["lifecycle_stage"] == "active"

    def test_superseded_row_excluded_from_recall(self, tmp_path):
        """失效旧代不再进入召回（检索不被矛盾旧事实污染）。"""
        enable_discipline()
        manager = make_manager(tmp_path)
        make_gated_core(manager)

        manager.remember(content="用户住在上海", metadata={"session_id": "s-old"})
        manager.remember(content="用户不住在上海", metadata={"session_id": "s-new"})

        recalled = manager.recall(query="用户住在上海", limit=10, use_semantic=False)
        assert all("用户住在上海" not in str(r.get("content")) for r in recalled)


# ============================================================
# 三、人工审阅接通（pending_memories 的 propose/confirm 两点）
# ============================================================


SENSITIVE_CONTENT = "我的内部部署密码是 super-secret-123"
NORMAL_CONTENT = "用户喜欢深色主题"


class TestPendingManualReview:
    def _store(self, tmp_path):
        from neurova.memory.pending_memory import PendingMemoryStore

        return PendingMemoryStore(db_path=str(tmp_path / "pending.db"))

    def test_propose_flags_sensitive_content(self, tmp_path):
        """propose 点：敏感候选被 screenMemoryContent 拦截标记，进入人工审阅。"""
        enable_discipline()
        store = self._store(tmp_path)

        rec = store.propose(content=SENSITIVE_CONTENT, proposed_by="user-1")

        assert rec["status"] == "pending"
        assert rec["sensitive_rule"]  # 命中规则名落列，可解释
        from neurova.memory_discipline import disciplineCounters

        assert disciplineCounters()["pendingSensitiveProposed"] == 1

    def test_propose_normal_content_not_flagged(self, tmp_path):
        """普通候选不经敏感标记，照常待审。"""
        enable_discipline()
        store = self._store(tmp_path)

        rec = store.propose(content=NORMAL_CONTENT, proposed_by="user-1")

        assert rec["status"] == "pending"
        assert rec["sensitive_rule"] == ""

    def test_propose_forget_action_not_screened(self, tmp_path):
        """forget 动作提议（内容是删除摘要，不进主库）不做敏感筛查。"""
        enable_discipline()
        store = self._store(tmp_path)

        rec = store.propose(
            content="密码是 abc12345",
            proposed_action="forget",
            target_memory_id="mem-1",
            proposed_by="user-1",
        )
        assert rec["status"] == "pending"
        assert rec["sensitive_rule"] == ""

    def test_confirm_sensitive_requires_explicit_release(self, tmp_path):
        """confirm 点：敏感候选未显式放行时诚实报错，记录保持待审。"""
        enable_discipline()
        store = self._store(tmp_path)
        rec = store.propose(content=SENSITIVE_CONTENT, proposed_by="user-1")

        with pytest.raises(ValueError, match="显式放行"):
            store.confirm(rec["id"], lambda content, category, mtype: "mem-x")

        assert store.get(rec["id"])["status"] == "pending"

    def test_confirm_sensitive_release_lands_and_audits(self, tmp_path):
        """人工显式放行：经生产装配点写入真落库，放行人留痕。"""
        enable_discipline()
        manager = make_manager(tmp_path)
        make_gated_core(manager)
        store = self._store(tmp_path)
        rec = store.propose(content=SENSITIVE_CONTENT, proposed_by="user-1")

        def rememberFn(content, category, memory_type):
            return manager.remember(
                content=content,
                category=category,
                memory_type=memory_type,
                metadata={"from_pending": True},
            )

        out = store.confirm(
            rec["id"], rememberFn, allow_sensitive=True, decided_by="admin-1"
        )

        assert out["status"] == "confirmed"
        assert out["decided_by"] == "admin-1"
        assert out["memory_id"]
        # 放行令牌生效：S7 准入闸（enforce 默认）未拦下这次人工放行写入
        assert manager.get_memory(out["memory_id"]) is not None
        from neurova.memory_discipline import disciplineCounters

        assert disciplineCounters()["pendingSensitiveReleased"] == 1

    def test_reject_sensitive_leaves_audit_trail(self, tmp_path):
        """人工拒收敏感候选：拒收留痕（计数可见）。"""
        enable_discipline()
        store = self._store(tmp_path)
        rec = store.propose(content=SENSITIVE_CONTENT, proposed_by="user-1")

        out = store.reject(rec["id"], rejected_by="admin-1", note="不收敏感内容")

        assert out["status"] == "rejected"
        from neurova.memory_discipline import disciplineCounters

        assert disciplineCounters()["pendingSensitiveRejected"] == 1

    def test_screening_off_when_gate_disabled(self, tmp_path):
        """门控关闭：propose 不做敏感筛查（行为与现状完全一致）。"""
        store = self._store(tmp_path)

        rec = store.propose(content=SENSITIVE_CONTENT, proposed_by="user-1")

        assert rec["status"] == "pending"
        assert rec["sensitive_rule"] == ""


# ============================================================
# 四、门控关闭态行为不变（现状回归锁）
# ============================================================


class TestGateOffBehaviorUnchanged:
    def test_gate_defaults_off(self):
        from neurova.memory_discipline import memoryDisciplineEnabled

        assert memoryDisciplineEnabled() is False

    def test_gate_off_remember_leaves_no_discipline_metadata(self, tmp_path):
        manager = make_manager(tmp_path)
        make_gated_core(manager)
        content = "用户的项目代号是启明"

        id1 = manager.remember(content=content, metadata={"session_id": "task-a"})
        id2 = manager.remember(content=content, metadata={"session_id": "task-b"})
        id3 = manager.remember(content=content, metadata={"session_id": "task-c"})

        assert id1 == id2 == id3
        assert DISCIPLINE_KEY not in (manager.get_memory(id3).get("metadata") or {})

    def test_gate_off_contradiction_does_not_supersede(self, tmp_path):
        manager = make_manager(tmp_path)
        make_gated_core(manager)

        old_id = manager.remember(
            content="用户住在上海", metadata={"session_id": "s-old"}
        )
        manager.remember(content="用户不住在上海", metadata={"session_id": "s-new"})

        assert manager.get_memory(old_id)["lifecycle_stage"] == "active"


# ============================================================
# 五、准入放行令牌（人工放行的写入闸语义）
# ============================================================


class TestAdmissionReleaseToken:
    def test_enforce_rejects_sensitive_by_default(self):
        from neurova.memory_admission import (
            MemoryAdmissionRejected,
            enforceMemoryAdmission,
        )

        with pytest.raises(MemoryAdmissionRejected):
            enforceMemoryAdmission(SENSITIVE_CONTENT, origin="test")

    def test_release_token_is_scope_scoped(self):
        """放行令牌只在作用域内生效，退出即恢复拒收（不黏连）。"""
        from neurova.memory_admission import (
            MemoryAdmissionRejected,
            enforceMemoryAdmission,
            memoryAdmissionRelease,
        )

        with memoryAdmissionRelease():
            assert enforceMemoryAdmission(SENSITIVE_CONTENT, origin="test") == (
                SENSITIVE_CONTENT
            )
        with pytest.raises(MemoryAdmissionRejected):
            enforceMemoryAdmission(SENSITIVE_CONTENT, origin="test")

    def test_release_token_audit_visible(self):
        """放行留痕：计数可见，不静默放行。"""
        from neurova.memory_admission import (
            admissionCounters,
            enforceMemoryAdmission,
            memoryAdmissionRelease,
        )

        before = admissionCounters()["releasedSensitiveWrites"]
        with memoryAdmissionRelease():
            enforceMemoryAdmission(SENSITIVE_CONTENT, origin="test")
        assert admissionCounters()["releasedSensitiveWrites"] == before + 1
