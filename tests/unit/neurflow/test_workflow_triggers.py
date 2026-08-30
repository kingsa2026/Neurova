"""
NeurFlow P1 Step 2 — WorkflowTrigger 模型与持久化测试

契约：
- WorkflowTrigger dataclass：id/workflow_id/type/config/secret_hash/enabled/rate_limit
- secret 入库前必须 hash（sha256 hex），绝不存明文
- storage 层 CRUD：save_trigger / get_trigger / list_triggers_by_workflow / delete_trigger
- type 枚举：webhook | cron | manual

TDD：先红后绿。测试直接用 NeurflowStorage（tmp_path 隔离 DB），
不构造任何 SQL 字符串（查询在 storage 内部完成）。
"""
import hashlib
import os
import pytest

from neurova.collaboration.neurflow.models import (
    WorkflowTrigger,
    TriggerType,
    WorkflowDefinition,
    WorkflowNode,
    WorkflowEdge,
    WorkflowStatus,
)
from neurova.collaboration.neurflow.storage import NeurflowStorage


def _make_min_workflow(workflow_id: str) -> WorkflowDefinition:
    """构造可入库的最小工作流定义（start → end）。"""
    return WorkflowDefinition(
        id=workflow_id,
        name=f"wf-{workflow_id}",
        description="test workflow",
        version="1.0.0",
        nodes=[
            WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="end", type="builtin:end", position={"x": 100, "y": 0}, config={}),
        ],
        edges=[WorkflowEdge(id="e1", source="start", target="end")],
        variables=[],
        tags=["test"],
        category="test",
        author="test",
        created_at=0,
        updated_at=0,
        status=WorkflowStatus.PUBLISHED,
    )


class TestWorkflowTriggerModel:
    """WorkflowTrigger 数据模型契约"""

    def test_trigger_model_importable(self):
        assert WorkflowTrigger is not None
        assert TriggerType is not None

    def test_trigger_type_enum_values(self):
        assert TriggerType.WEBHOOK.value == "webhook"
        assert TriggerType.CRON.value == "cron"
        assert TriggerType.MANUAL.value == "manual"

    def test_trigger_required_fields(self):
        tr = WorkflowTrigger(
            id="trg_1",
            workflow_id="wf_1",
            type=TriggerType.WEBHOOK,
        )
        assert tr.id == "trg_1"
        assert tr.workflow_id == "wf_1"
        assert tr.type == TriggerType.WEBHOOK

    def test_trigger_defaults(self):
        tr = WorkflowTrigger(id="trg_2", workflow_id="wf_1", type=TriggerType.MANUAL)
        assert tr.enabled is True
        assert tr.config == {}
        assert tr.rate_limit_per_minute is None  # None = 不限流
        assert tr.secret_hash is None  # manual 触发器无 secret

    def test_trigger_cron_config_shape(self):
        tr = WorkflowTrigger(
            id="trg_3",
            workflow_id="wf_1",
            type=TriggerType.CRON,
            config={"cron": "0 9 * * 1-5", "timezone": "Asia/Shanghai"},
        )
        assert tr.config["cron"] == "0 9 * * 1-5"


class TestTriggerSecretHashing:
    """secret 入库必须 hash（不存明文）"""

    def test_hash_secret_helper_exists(self):
        from neurova.collaboration.neurflow.storage import NeurflowStorage

        assert hasattr(NeurflowStorage, "hash_trigger_secret")

    def test_hash_secret_produces_sha256_hex(self):
        from neurova.collaboration.neurflow.storage import NeurflowStorage

        h = NeurflowStorage.hash_trigger_secret("my-webhook-secret")
        # sha256 hex 长度 64
        assert len(h) == 64
        assert h == hashlib.sha256(b"my-webhook-secret").hexdigest()

    def test_hash_secret_deterministic(self):
        from neurova.collaboration.neurflow.storage import NeurflowStorage

        assert NeurflowStorage.hash_trigger_secret("abc") == NeurflowStorage.hash_trigger_secret("abc")


class TestTriggerStorageCRUD:
    """storage 层触发器 CRUD（tmp_path 隔离 DB）"""

    @pytest.fixture
    def storage(self, tmp_path):
        db_path = str(tmp_path / "neurflow_test.db")
        st = NeurflowStorage(db_path=db_path)
        # FK 约束：先建被引用的 workflow
        st.save_workflow(_make_min_workflow("wf_1"))
        st.save_workflow(_make_min_workflow("wf_list"))
        st.save_workflow(_make_min_workflow("wf_other"))
        return st

    def test_save_and_get_trigger(self, storage):
        tr = WorkflowTrigger(
            id="trg_s1",
            workflow_id="wf_1",
            type=TriggerType.WEBHOOK,
            secret_hash=NeurflowStorage.hash_trigger_secret("s3cret"),
            rate_limit_per_minute=30,
        )
        assert storage.save_trigger(tr) is True

        loaded = storage.get_trigger("trg_s1")
        assert loaded is not None
        assert loaded.workflow_id == "wf_1"
        assert loaded.type == TriggerType.WEBHOOK
        assert loaded.secret_hash == hashlib.sha256(b"s3cret").hexdigest()
        assert loaded.rate_limit_per_minute == 30

    def test_get_missing_trigger_returns_none(self, storage):
        assert storage.get_trigger("trg_nope") is None

    def test_list_triggers_by_workflow(self, storage):
        for i in range(3):
            storage.save_trigger(
                WorkflowTrigger(
                    id=f"trg_l{i}",
                    workflow_id="wf_list",
                    type=TriggerType.WEBHOOK if i % 2 == 0 else TriggerType.CRON,
                )
            )
        # 别的 workflow 的触发器不混入
        storage.save_trigger(
            WorkflowTrigger(id="trg_other", workflow_id="wf_other", type=TriggerType.MANUAL)
        )

        got = storage.list_triggers_by_workflow("wf_list")
        assert len(got) == 3
        assert all(t.workflow_id == "wf_list" for t in got)

    def test_delete_trigger(self, storage):
        storage.save_trigger(
            WorkflowTrigger(id="trg_d1", workflow_id="wf_1", type=TriggerType.MANUAL)
        )
        assert storage.delete_trigger("trg_d1") is True
        assert storage.get_trigger("trg_d1") is None
        assert storage.delete_trigger("trg_d1") is False  # 二次删除 False

    def test_update_trigger_via_save(self, storage):
        tr = WorkflowTrigger(id="trg_u1", workflow_id="wf_1", type=TriggerType.CRON)
        storage.save_trigger(tr)

        tr.enabled = False
        storage.save_trigger(tr)
        loaded = storage.get_trigger("trg_u1")
        assert loaded.enabled is False

    def test_trigger_persists_secret_hash_not_plaintext(self, storage):
        """明文 secret 绝不出现在 DB——只存 hash"""
        raw = "super-secret-value"
        storage.save_trigger(
            WorkflowTrigger(
                id="trg_sec",
                workflow_id="wf_1",
                type=TriggerType.WEBHOOK,
                secret_hash=NeurflowStorage.hash_trigger_secret(raw),
            )
        )
        # 直接查库验证（storage 内部连接）
        with storage._lock:
            row = storage._conn.execute(
                "SELECT secret_hash FROM workflow_triggers WHERE id = 'trg_sec'"
            ).fetchone()
        assert row is not None
        assert raw not in (row["secret_hash"] or "")
        assert row["secret_hash"] == hashlib.sha256(b"super-secret-value").hexdigest()
