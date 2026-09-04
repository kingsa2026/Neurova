"""P2 trigger 统一契约（TDD — Dify 对标 §4 P2）。

契约：
- TriggerType 补全三态：WEBHOOK / CRON / MANUAL 既有 + PLUGIN 新增
  （plugin 事件触发：插件经 plugin_api_registry 投递事件 → dispatch）
- 统一 trigger 面：TriggerManager.fire 对三种类型统一派发语义
  （webhook 不经 fire——入站签名路径独立；cron/plugin/manual 统一走
  fire，inputs 携带来源标记 source_type 供工作流内变量引用）
- webhook 投递重试：TriggerRetryService——webhook_deliveries 表已有
  记录（signature_valid/execution_id/status_code），补 attempt/next_retry_at
  列 + 失败投递按退避重试（max_attempts 上限，超限标记 dead）；
  retry_delivery(delivery_id) 手动单条重试
"""

import pytest


class TestTriggerTypeUnification:
    def test_plugin_type_exists(self):
        from neurova.collaboration.neurflow.models import TriggerType

        assert {t.value for t in TriggerType} == {"webhook", "cron", "manual", "plugin"}

    @pytest.mark.asyncio
    async def test_fire_uniform_across_types(self):
        """cron/plugin/manual 统一走 fire：inputs 携带 source_type 标记"""
        from neurova.collaboration.neurflow.models import TriggerType, WorkflowTrigger
        from neurova.collaboration.neurflow.triggers import TriggerManager

        dispatched = []

        async def _dispatch(workflow_id, inputs):
            dispatched.append((workflow_id, inputs))
            return {"success": True, "execution_id": "e1"}

        mgr = TriggerManager(dispatch=_dispatch)
        for ttype in (TriggerType.CRON, TriggerType.PLUGIN, TriggerType.MANUAL):
            tr = WorkflowTrigger(id=f"t_{ttype.value}", workflow_id="wf1", type=ttype, config={})
            await mgr.fire(tr, {"k": "v"})

        assert len(dispatched) == 3
        for (wf_id, inputs), ttype in zip(dispatched, (TriggerType.CRON, TriggerType.PLUGIN, TriggerType.MANUAL)):
            assert wf_id == "wf1"
            assert inputs["k"] == "v"
            assert inputs["trigger_source"] == ttype.value, "来源标记供工作流内变量引用"

    @pytest.mark.asyncio
    async def test_fire_missing_dispatch_returns_none(self):
        from neurova.collaboration.neurflow.models import TriggerType, WorkflowTrigger
        from neurova.collaboration.neurflow.triggers import TriggerManager

        mgr = TriggerManager()  # 无 dispatch
        tr = WorkflowTrigger(id="t1", workflow_id="wf1", type=TriggerType.PLUGIN, config={})
        assert await mgr.fire(tr, {}) is None


class TestDeliveryRetry:
    @pytest.fixture
    def storage(self, tmp_path):
        from neurova.collaboration.neurflow.storage import NeurflowStorage

        return NeurflowStorage(str(tmp_path / "nf.db"))

    def test_deliveries_table_has_retry_columns(self, storage):
        cols = {r[1] for r in storage._conn.execute("PRAGMA table_info(webhook_deliveries)").fetchall()}
        assert {"attempt", "next_retry_at", "status"} <= cols, "重试三列（幂等迁移：老库自动补列）"

    def test_record_and_list_failed(self, storage):
        from neurova.collaboration.neurflow.trigger_retry import TriggerRetryService

        svc = TriggerRetryService(storage)
        delivery_id = storage.save_delivery(
            trigger_id="tr1", signature_valid=True, execution_id=None,
            status_code=503, latency_ms=12.0,
        )
        failed = svc.list_failed()
        assert any(d["id"] == delivery_id for d in failed)

    @pytest.mark.asyncio
    async def test_retry_delivery_success_marks_done(self, storage):
        from neurova.collaboration.neurflow.trigger_retry import TriggerRetryService

        svc = TriggerRetryService(storage)
        delivery_id = storage.save_delivery(
            trigger_id="tr1", signature_valid=True, execution_id=None,
            status_code=500, latency_ms=5.0,
        )
        attempts = []

        async def _redeliver(trigger_id, attempt):
            attempts.append((trigger_id, attempt))
            return {"ok": True, "execution_id": "e_new"}

        outcome = await svc.retry_delivery(delivery_id, redeliver=_redeliver)
        assert outcome["success"] is True
        assert outcome["status"] == "delivered"
        row = storage.get_delivery(delivery_id)
        assert row["status"] == "delivered" and row["attempt"] == 1

    @pytest.mark.asyncio
    async def test_retry_failure_backoff_and_dead(self, storage):
        """重试失败 → attempt+1 + next_retry_at 退避；超过上限标 dead"""
        from neurova.collaboration.neurflow.trigger_retry import TriggerRetryService

        svc = TriggerRetryService(storage, max_attempts=2)
        delivery_id = storage.save_delivery(
            trigger_id="tr1", signature_valid=True, execution_id=None,
            status_code=500, latency_ms=5.0,
        )

        async def _fail(trigger_id, attempt):
            return {"ok": False}

        o1 = await svc.retry_delivery(delivery_id, redeliver=_fail)
        assert o1["success"] is False and o1["status"] == "pending_retry"
        row1 = storage.get_delivery(delivery_id)
        assert row1["attempt"] == 1 and row1["next_retry_at"] > 0

        o2 = await svc.retry_delivery(delivery_id, redeliver=_fail)
        assert o2["status"] == "dead", "第二次失败达上限 → dead"

        o3 = await svc.retry_delivery(delivery_id, redeliver=_fail)
        assert o3["success"] is False and o3["status"] == "dead", "dead 不再重试"

    @pytest.mark.asyncio
    async def test_retry_due_batch(self, storage):
        """到期批量重试：只处理 next_retry_at <= now 的 pending 项"""
        from neurova.collaboration.neurflow.trigger_retry import TriggerRetryService

        svc = TriggerRetryService(storage, max_attempts=3)
        d1 = storage.save_delivery(trigger_id="tr1", signature_valid=True,
                                          execution_id=None, status_code=500, latency_ms=1.0)
        d2 = storage.save_delivery(trigger_id="tr2", signature_valid=True,
                                          execution_id=None, status_code=502, latency_ms=1.0)

        async def _ok(trigger_id, attempt):
            return {"ok": True, "execution_id": f"e_{trigger_id}"}

        processed = await svc.retry_due(redeliver=_ok)
        assert set(processed) >= {d1, d2}
        assert storage.get_delivery(d1)["status"] == "delivered"
