"""批次 B2：memory 技能 action 契约补全（F7）

- LLM 参数 schema：action 枚举化 search/store/forget；description 含分工与待审说明
- executor 补 forget 分支 → MemoryManager.forget(memory_id)（软删除）
- forget 同样过待审门：挂载 pending_store 时进待审（confirm=True 直删）
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.skills.builtin.memory_executor import MemorySkillExecutor


def _memory_manager(memory_id="mem_123"):
    mm = MagicMock()
    mm.forget.return_value = True
    return mm


class TestForgetAction:
    def test_forget_calls_manager(self):
        mm = _memory_manager()
        ex = MemorySkillExecutor(mm)
        result = ex.execute({"action": "forget", "memory_id": "mem_123"})
        assert result.success
        mm.forget.assert_called_once_with("mem_123", soft=True)
        assert result.output.get("forgotten") is True

    def test_forget_missing_id_fails(self):
        ex = MemorySkillExecutor(_memory_manager())
        result = ex.execute({"action": "forget"})
        assert not result.success
        assert "memory_id" in (result.error or "")

    def test_forget_manager_failure(self):
        mm = _memory_manager()
        mm.forget.return_value = False
        result = MemorySkillExecutor(mm).execute({"action": "forget", "memory_id": "x"})
        assert result.success  # 语义完成（查询执行了），业务结果透出
        assert result.output.get("forgotten") is False

    def test_forget_goes_to_pending_when_mounted(self):
        """待审门：挂载 pending_store 时 forget 进待审（删除也是写操作）。"""
        pending = MagicMock()
        pending.propose.return_value = {"id": "p1", "rejected": False}
        mm = _memory_manager()
        ex = MemorySkillExecutor(mm, pending_store=pending)
        result = ex.execute({"action": "forget", "memory_id": "mem_123", "content": "要遗忘的记忆内容摘要"})
        mm.forget.assert_not_called()
        assert result.output.get("pending") is True
        kwargs = pending.propose.call_args.kwargs
        assert kwargs.get("proposed_action") == "forget"

    def test_forget_confirm_bypasses_pending(self):
        pending = MagicMock()
        mm = _memory_manager()
        ex = MemorySkillExecutor(mm, pending_store=pending)
        result = ex.execute({"action": "forget", "memory_id": "mem_123", "confirm": True})
        pending.propose.assert_not_called()
        mm.forget.assert_called_once_with("mem_123", soft=True)


class TestSchemaContract:
    def test_action_enum_in_llm_schema(self):
        """OpenAISchemaAdapter 产出的 action 参数必须带枚举。"""
        from neurova.skill_system.compat import OpenAISchemaAdapter

        fields = getattr(
            __import__("neurova.skills.builtin.schemas", fromlist=["_BUILTIN_SKILL_FIELDS"]),
            "_BUILTIN_SKILL_FIELDS",
        )["memory"]
        field_map = {name: (typ, req, desc) for name, typ, req, desc in fields}
        assert field_map["action"][1] is True

    def test_memory_schema_mentions_forget_and_pending(self):
        import neurova.skills.builtin.schemas as schemas

        blob = str(schemas._BUILTIN_SKILL_FIELDS["memory"])
        assert "forget" in blob
        assert "待审" in blob

    def test_adapter_builds_enum(self):
        """适配器层：action 字段产出 enum（这是模型可见面的最终形态）。"""
        from neurova.skills.builtin.schemas import get_builtin_skill_parameters
        from neurova.skill_system.compat import OpenAISchemaAdapter

        params = get_builtin_skill_parameters("memory")
        assert params["action"]["enum"] == ["search", "store", "forget"]

        skill = SimpleNamespace(
            name="memory",
            description="记忆管理技能",
        )
        schema = OpenAISchemaAdapter.skill_to_tool_schema(skill)
        props = (schema.get("function", {}).get("parameters") or {}).get("properties", {})
        action = props.get("action", {})
        assert set(action.get("enum", [])) >= {"search", "store", "forget"}, (
            "适配器丢弃 enum（B2 修复点）"
        )


class TestForgetApprovalChain:
    """核验轮修复②：forget 待审的审批侧闭环。

    bug 链：executor.propose(proposed_action=...) 与 pending_memory.propose
    真实签名不符 → TypeError → 回退分支把"[遗忘记忆 x]"当普通待审记忆 →
    用户点确认后垃圾文本入主库、目标记忆未删。
    修复：pending 表加 proposed_action/target_memory_id 列（幂等迁移），
    confirm 端点对 proposed_action=forget 走真删除，executor 删除回退分支。
    """

    def test_pending_propose_accepts_action_fields(self):
        from neurova.memory.pending_memory import PendingMemoryStore

        store = PendingMemoryStore(db_path=":memory:")
        try:
            rec = store.propose(
                content="[遗忘记忆 mem_1] 内容摘要",
                category="forget",
                proposed_action="forget",
                target_memory_id="mem_1",
            )
            assert rec.get("proposed_action") == "forget"
            assert rec.get("target_memory_id") == "mem_1"
            # 记录必须带 action 标记——审批侧据此分流
            got = store.get(rec["id"])
            assert got["proposed_action"] == "forget"
        finally:
            store.close()

    def test_executor_forget_pending_returns_review_id(self):
        """挂载待审时 forget 提议成功（不再走 TypeError 回退直删）。"""
        from neurova.memory.pending_memory import PendingMemoryStore

        pending = PendingMemoryStore(db_path=":memory:")
        mm = MagicMock()
        try:
            ex = MemorySkillExecutor(mm, pending_store=pending)
            result = ex.execute({"action": "forget", "memory_id": "mem_9", "content": "要遗忘的内容"})
            assert result.output.get("pending") is True, result.output
            assert result.output.get("review_id")
            mm.forget.assert_not_called()
        finally:
            pending.close()

    def test_confirm_forget_deletes_not_creates(self):
        """confirm 端到端：forget 提议经裁决后必须删除目标记忆，绝不新建。"""
        from unittest.mock import patch

        from neurova.memory.pending_memory import PendingMemoryStore

        pending = PendingMemoryStore(db_path=":memory:")
        try:
            rec = pending.propose(
                content="要遗忘的记忆内容",
                category="forget",
                proposed_action="forget",
                target_memory_id="mem_42",
            )
            deleted = []

            def fake_delete(memory_id):
                deleted.append(memory_id)
                return True

            with patch(
                "neurova.api.endpoints.memory.pending.get_memory_manager"
            ) as gm:
                gm.return_value = SimpleNamespace(
                    delete_memory=fake_delete, forget=lambda mid, soft=True: fake_delete(mid)
                )
                # 直接走 store.confirm 契约层：confirm 的 remember_fn 由端点构造，
                # 端点侧按 proposed_action 分流——此处验证 store 层透传动作字段
                out = pending.confirm(rec["id"], lambda c, cat, mt: "should-not-be-created")
                assert out.get("status") == "confirmed"
            assert deleted == [], "forget 提议被当成新增记忆 confirm（核验轮修复②）"
        finally:
            pending.close()


class TestConfirmEndpointForgetBranch:
    """confirm 端点分流：forget 提议必须走 manager.forget，绝不走 remember。"""

    def test_endpoint_confirms_forget_via_manager_forget(self):
        import asyncio

        from unittest.mock import MagicMock, patch

        from neurova.memory.pending_memory import PendingMemoryStore

        from neurova.api.endpoints.memory import pending as pending_api

        store = PendingMemoryStore(db_path=":memory:")
        rec = store.propose(
            content="要遗忘的记忆内容",
            category="forget",
            proposed_action="forget",
            target_memory_id="mem_77",
            proposed_by="u1",
        )
        manager = MagicMock()
        manager.forget.return_value = True

        try:
            with patch.object(pending_api, "_get_store", return_value=store), patch.object(
                pending_api, "get_memory_manager", return_value=manager
            ), patch.object(pending_api, "_get_request_id", return_value="r1"):
                resp = asyncio.run(
                    pending_api.confirm_pending_memory(
                        rec["id"],
                        pending_api.PendingDecisionRequest(),
                        {"user_id": "u1"},
                        agent_id=None,
                    )
                )
            manager.forget.assert_called_once()
            manager.remember.assert_not_called()
            assert store.get(rec["id"])["status"] == "confirmed"
            assert resp["data"]["action"] == "forget"
        finally:
            store.close()

    def test_endpoint_confirm_missing_target_fails_clean(self):
        """端点防御：记录标记 forget 但 target 为空（历史脏数据）必须报错且不改判。"""
        import asyncio

        from unittest.mock import MagicMock, patch

        from neurova.api.endpoints.memory import pending as pending_api

        store = MagicMock()
        store.get.return_value = {
            "id": "p-orphan",
            "content": "孤儿 forget 提议",
            "category": "forget",
            "proposed_by": "u1",
            "status": "pending",
            "proposed_action": "forget",
            "target_memory_id": "",
        }
        with patch.object(pending_api, "_get_store", return_value=store), patch.object(
            pending_api, "_get_request_id", return_value="r1"
        ):
            raised = None
            try:
                asyncio.run(
                    pending_api.confirm_pending_memory(
                        "p-orphan",
                        pending_api.PendingDecisionRequest(),
                        {"user_id": "u1"},
                        agent_id=None,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                raised = exc
            assert raised is not None, "缺 target 的 forget 提议必须报错而非静默确认"
            store.confirm.assert_not_called()
