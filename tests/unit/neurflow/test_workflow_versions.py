"""
NeurFlow P2-4.4 — 工作流版本与回滚测试

契约（storage 层）：
- save_workflow 自动快照旧版本到 workflow_versions 表（容量上限 20）
- list_workflow_versions(workflow_id)：倒序历史（含 version 序号/快照/时间/备注）
- rollback_workflow(workflow_id, version)：恢复指定快照为当前定义
- 快照去重：内容未变时不产生新版本

TDD：先红后绿。tmp DB 隔离。
"""
import pytest

from neurova.collaboration.neurflow.models import (
    WorkflowDefinition,
    WorkflowNode,
    WorkflowEdge,
    WorkflowStatus,
)


def _make_workflow(workflow_id="wf_ver", label="v0"):
    return WorkflowDefinition(
        id=workflow_id,
        name=f"版本测试 {label}",
        description=f"desc-{label}",
        version="1.0.0",
        nodes=[
            WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="end", type="builtin:end", position={"x": 10, "y": 0}, config={}),
        ],
        edges=[WorkflowEdge(id="e1", source="start", target="end")],
        variables=[], tags=[], category="test", author="t",
        created_at=0, updated_at=0, status=WorkflowStatus.DRAFT,
    )


@pytest.fixture
def storage(tmp_path):
    from neurova.collaboration.neurflow.storage import NeurflowStorage

    return NeurflowStorage(db_path=str(tmp_path / "ver.db"))


class TestVersionSnapshot:
    def test_first_save_creates_v1(self, storage):
        storage.save_workflow(_make_workflow())
        versions = storage.list_workflow_versions("wf_ver")
        assert len(versions) == 1
        assert versions[0]["version"] == 1

    def test_content_change_creates_new_version(self, storage):
        storage.save_workflow(_make_workflow(label="v0"))
        wf = _make_workflow(label="v1")  # name/description 变化
        storage.save_workflow(wf)
        versions = storage.list_workflow_versions("wf_ver")
        assert len(versions) == 2

    def test_unchanged_content_no_new_version(self, storage):
        storage.save_workflow(_make_workflow(label="same"))
        storage.save_workflow(_make_workflow(label="same"))
        assert len(storage.list_workflow_versions("wf_ver")) == 1

    def test_versions_desc_order(self, storage):
        for i in range(3):
            storage.save_workflow(_make_workflow(label=f"v{i}"))
        versions = storage.list_workflow_versions("wf_ver")
        assert [v["version"] for v in versions] == [3, 2, 1]

    def test_capacity_limit_20(self, storage):
        for i in range(25):
            storage.save_workflow(_make_workflow(label=f"v{i}"))
        versions = storage.list_workflow_versions("wf_ver")
        assert len(versions) == 20
        # 保留最新的 20 个（v5..v24），最老的 v4 已被挤出
        assert versions[-1]["version"] == 6


class TestRollback:
    def test_rollback_restores_old_snapshot(self, storage):
        storage.save_workflow(_make_workflow(label="first"))
        storage.save_workflow(_make_workflow(label="second"))

        ok = storage.rollback_workflow("wf_ver", 1)
        assert ok is True

        current = storage.get_workflow("wf_ver")
        assert current.name == "版本测试 first"
        # 回滚本身产生新版本（当前内容再次入史）
        assert len(storage.list_workflow_versions("wf_ver")) == 3

    def test_rollback_unknown_version_fails(self, storage):
        storage.save_workflow(_make_workflow())
        assert storage.rollback_workflow("wf_ver", 99) is False

    def test_rollback_unknown_workflow_fails(self, storage):
        assert storage.rollback_workflow("wf_none", 1) is False

    def test_rollback_preserves_published_status(self, storage):
        wf = _make_workflow(label="pub")
        wf.status = WorkflowStatus.PUBLISHED
        storage.save_workflow(wf)
        # 已发布工作流的内容迭代（status 保持 PUBLISHED）
        wf2 = _make_workflow(label="pub-v2")
        wf2.status = WorkflowStatus.PUBLISHED
        storage.save_workflow(wf2)

        storage.rollback_workflow("wf_ver", 1)
        current = storage.get_workflow("wf_ver")
        # 回滚恢复定义内容，状态保持当前（PUBLISHED）——避免悄悄下线
        assert current.status == WorkflowStatus.PUBLISHED