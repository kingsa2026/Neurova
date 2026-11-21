# -*- coding: utf-8 -*-
"""
B3：scope 化检查点 + 隔离回滚（追平 T3 Code 编排检查点）

计划：docs/04-plans/2026-11-21-reference-ac-catchup-implementation-plan.md 任务卡 B3

锁定契约：
1. scopeRefFor 确定性命名：refs/neurova/checkpoints/<sha256(scope_id) 前 32 hex>/ordinal/<N>
2. captureScope → restoreScope 往返（文件名含 '/'、二进制内容不丢）
3. 同 scope 同 ordinal 重捕获覆盖同一 ref
4. restore / rollback 目标不存在 → CheckpointNotFoundError（不静默回退）
5. listScopeOrdinals 升序；pruneScope 每 scope 保留最近 keep 个
6. rollbackScope 无冲突：恢复文件 + apply_fn + 清理 target 之后 stale ref
7. rollbackScope 隔离冲突：isolation_check 报因 → 只会话级回退（不动文件、不删 ref）
"""
import pytest

from neurova.checkpoints.service import (
    DEFAULT_SCOPE_KEEP,
    SCOPE_REF_PREFIX,
    CheckpointNotFoundError,
    CheckpointService,
    scopeRefFor,
)

SCOPE_A = "run-20261121-001"
SCOPE_B = "subagent://planner#7"

P0 = {"a.txt": b"zero", "nested/dir/b.bin": bytes(range(256))}
P1 = {"a.txt": b"one", "nested/dir/b.bin": b"\x00\x01"}
P2 = {"a.txt": b"two", "extra/c.txt": b"tail"}


@pytest.fixture()
def svc(tmp_path):
    return CheckpointService(agent_id="t1", base_dir=str(tmp_path / "cp"))


class TestScopeRefFor:
    def test_sameInput_sameRef(self):
        assert scopeRefFor(SCOPE_A, 3) == scopeRefFor(SCOPE_A, 3)
        assert scopeRefFor(SCOPE_A, 3) == scopeRefFor("run-20261121-001", 3)

    def test_differentScope_differentRef(self):
        assert scopeRefFor(SCOPE_A, 3) != scopeRefFor(SCOPE_B, 3)

    def test_refShape_prefixAndOrdinalSegment(self):
        ref = scopeRefFor(SCOPE_A, 0)
        assert ref.startswith(SCOPE_REF_PREFIX + "/")
        parts = ref.split("/")
        # refs / neurova / checkpoints / <32hex> / ordinal / <N>
        assert len(parts) == 6
        assert parts[:3] == ["refs", "neurova", "checkpoints"]
        assert parts[4] == "ordinal"
        assert parts[5] == "0"
        assert len(parts[3]) == 32
        int(parts[3], 16)  # 摘要段是 32 位十六进制

    def test_defaultKeep_positiveInt(self):
        assert isinstance(DEFAULT_SCOPE_KEEP, int) and DEFAULT_SCOPE_KEEP > 0


class TestCaptureRestoreRoundtrip:
    def test_roundtrip_preservesNamesAndBytes(self, svc):
        ref = svc.captureScope(SCOPE_A, 0, P0, message="第 0 步")
        assert ref == scopeRefFor(SCOPE_A, 0)
        assert svc.restoreScope(SCOPE_A, 0) == P0

    def test_recapture_sameOrdinal_overwrites(self, svc):
        svc.captureScope(SCOPE_A, 0, P0)
        svc.captureScope(SCOPE_A, 0, P1)
        assert svc.restoreScope(SCOPE_A, 0) == P1
        assert svc.listScopeOrdinals(SCOPE_A) == [0]  # 仍只有一个 ref

    def test_emptyPayload_roundtrip(self, svc):
        svc.captureScope(SCOPE_A, 1, {})
        assert svc.restoreScope(SCOPE_A, 1) == {}


class TestMissingTargets:
    def test_restore_missing_ordinal_raises(self, svc):
        svc.captureScope(SCOPE_A, 0, P0)
        with pytest.raises(CheckpointNotFoundError):
            svc.restoreScope(SCOPE_A, 99)

    def test_restore_on_emptyScope_raises(self, svc):
        with pytest.raises(CheckpointNotFoundError):
            svc.restoreScope("never-captured", 0)

    def test_rollback_missing_target_raises(self, svc):
        with pytest.raises(CheckpointNotFoundError):
            svc.rollbackScope(SCOPE_A, 42)


class TestListOrdinals:
    def test_ascending_regardlessOfCaptureOrder(self, svc):
        for o in (5, 1, 3):
            svc.captureScope(SCOPE_A, o, {"n": str(o).encode()})
        assert svc.listScopeOrdinals(SCOPE_A) == [1, 3, 5]

    def test_scopes_isolated(self, svc):
        svc.captureScope(SCOPE_A, 0, P0)
        svc.captureScope(SCOPE_B, 0, P1)
        svc.captureScope(SCOPE_B, 7, P2)
        assert svc.listScopeOrdinals(SCOPE_A) == [0]
        assert svc.listScopeOrdinals(SCOPE_B) == [0, 7]


class TestPruneScope:
    def test_keepsMostRecentN(self, svc):
        for o in range(6):
            svc.captureScope(SCOPE_A, o, {"n": str(o).encode()})
        removed = svc.pruneScope(SCOPE_A, keep=2)
        assert removed == 4
        assert svc.listScopeOrdinals(SCOPE_A) == [4, 5]
        assert svc.restoreScope(SCOPE_A, 5) == {"n": b"5"}

    def test_defaultKeep_constant(self, svc):
        for o in range(DEFAULT_SCOPE_KEEP + 3):
            svc.captureScope(SCOPE_A, o, {"n": str(o).encode()})
        assert svc.pruneScope(SCOPE_A) == 3
        assert svc.listScopeOrdinals(SCOPE_A)[0] == 3

    def test_noop_whenUnderKeep(self, svc):
        svc.captureScope(SCOPE_A, 0, P0)
        assert svc.pruneScope(SCOPE_A, keep=5) == 0
        assert svc.listScopeOrdinals(SCOPE_A) == [0]

    def test_scopes_prunedIndependently(self, svc):
        for o in range(4):
            svc.captureScope(SCOPE_A, o, P0)
            svc.captureScope(SCOPE_B, o, P1)
        assert svc.pruneScope(SCOPE_A, keep=1) == 3
        assert svc.listScopeOrdinals(SCOPE_A) == [3]
        assert svc.listScopeOrdinals(SCOPE_B) == [0, 1, 2, 3]


class TestRollbackScope:
    def test_noConflict_restoresFiles_applies_andPrunesStale(self, svc):
        svc.captureScope(SCOPE_A, 0, P0)
        svc.captureScope(SCOPE_A, 1, P1)
        svc.captureScope(SCOPE_A, 2, P2)

        applied = []

        def apply_fn(payload):
            applied.append(payload)

        result = svc.rollbackScope(SCOPE_A, 1, apply_fn=apply_fn)

        assert result == {
            "files_restored": True,
            "conversation_only": False,
            "restored_ordinal": 1,
            "pruned": 1,
        }
        assert applied == [P1]  # apply_fn 收到恢复出的文件内容
        assert svc.restoreScope(SCOPE_A, 1) == P1
        assert svc.listScopeOrdinals(SCOPE_A) == [0, 1]  # target 之后的 stale 已清

    def test_noConflict_withoutApplyFn(self, svc):
        svc.captureScope(SCOPE_A, 0, P0)
        svc.captureScope(SCOPE_A, 1, P1)
        result = svc.rollbackScope(SCOPE_A, 0)
        assert result["files_restored"] is True
        assert result["conversation_only"] is False
        assert result["restored_ordinal"] == 0
        assert result["pruned"] == 1
        assert svc.listScopeOrdinals(SCOPE_A) == [0]

    def test_applyFn_exception_propagates_andKeepsRefs(self, svc):
        svc.captureScope(SCOPE_A, 0, P0)
        svc.captureScope(SCOPE_A, 1, P1)

        def boom(payload):
            raise RuntimeError("事务写回失败")

        with pytest.raises(RuntimeError):
            svc.rollbackScope(SCOPE_A, 0, apply_fn=boom)
        # apply 失败由调用方决定事务回滚——stale ref 不动
        assert svc.listScopeOrdinals(SCOPE_A) == [0, 1]

    def test_rolledBack_staleOrdinal_becomesMissing(self, svc):
        svc.captureScope(SCOPE_A, 0, P0)
        svc.captureScope(SCOPE_A, 1, P1)
        svc.rollbackScope(SCOPE_A, 0)
        with pytest.raises(CheckpointNotFoundError):
            svc.restoreScope(SCOPE_A, 1)

    def test_isolationConflict_conversationOnly(self, svc):
        svc.captureScope(SCOPE_A, 0, P0)
        svc.captureScope(SCOPE_A, 1, P1)
        svc.captureScope(SCOPE_A, 2, P2)

        applied = []

        def apply_fn(payload):
            applied.append(payload)

        def isolation_check():
            return "其他活跃 run 共享同一工作区"

        result = svc.rollbackScope(
            SCOPE_A, 1, apply_fn=apply_fn, isolation_check=isolation_check
        )

        assert result == {
            "files_restored": False,
            "conversation_only": True,
            "reason": "其他活跃 run 共享同一工作区",
        }
        assert applied == []  # 不恢复文件 → 不触发 apply_fn
        assert svc.listScopeOrdinals(SCOPE_A) == [0, 1, 2]  # 不删 ref
        assert svc.restoreScope(SCOPE_A, 2) == P2  # 各 ref 内容原封不动

    def test_isolationCheck_none_meansNoConflict(self, svc):
        svc.captureScope(SCOPE_A, 0, P0)
        result = svc.rollbackScope(SCOPE_A, 0, isolation_check=lambda: None)
        assert result["files_restored"] is True
        assert result["conversation_only"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
