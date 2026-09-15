"""P1#11 遗忘墓碑测试。

契约（§7 #11）：
用户主动遗忘（删除记忆/确认遗忘提议）后，同一内容不得被再提炼/再提议
落库——"默默断言错误猜测/复活用户删掉的事实，是记忆功能永久失去信任的方式"。

确认门（propose→confirm 才落库）已由 pending 独立分库架构保证，本文件
加防回退断言；墓碑为本次新增：
- PendingMemoryStore.tombstone_content / is_content_tombstoned
- propose(store)：命中内容墓碑 → {"rejected": True, "reason": "previously_forgotten"}
- confirm(store)：命中 → 不执行 remember_fn、记录转 rejected、抛 ValueError
- forget 动作提议（target 指纹）不受内容墓碑误伤
"""

import pytest

from neurova.memory.pending_memory import PendingMemoryStore


@pytest.fixture
def store(tmp_path):
    return PendingMemoryStore(str(tmp_path / "pending.db"))


def _remember_fn(saved):
    def fn(content, category, memory_type):
        saved["content"] = content
        return "mem-1"

    return fn


class TestForgetTombstone:
    def test_tombstoned_content_propose_rejected(self, store):
        store.tombstone_content("用户住在上海", by_user="u1")
        rec = store.propose("用户住在上海", proposed_by="u1")
        assert rec.get("rejected") is True
        assert rec.get("reason") == "previously_forgotten"

    def test_pending_row_confirm_blocked(self, store):
        # 先提议未裁决，随后用户遗忘了同内容 → confirm 不得再落库
        rec = store.propose("用户养了猫", proposed_by="u1")
        store.tombstone_content("用户养了猫", by_user="u1", source="user_forget")
        saved = {}
        with pytest.raises(ValueError):
            store.confirm(rec["id"], _remember_fn(saved))
        assert "content" not in saved, "被遗忘内容绝不得写入主库"
        assert store.get(rec["id"])["status"] == "rejected"

    def test_tombstone_idempotent(self, store):
        store.tombstone_content("AAA", by_user="u1")
        store.tombstone_content("AAA", by_user="u2")  # 不炸
        assert store.is_content_tombstoned("AAA")
        assert not store.is_content_tombstoned("BBB")

    def test_forget_action_not_content_blocked(self, store):
        # forget 提议的指纹绑定 target（审计⑤），内容级墓碑不得误伤其流程
        store.tombstone_content("删除该记忆摘要", by_user="u1")
        rec = store.propose(
            "删除该记忆摘要", proposed_action="forget", target_memory_id="m9", proposed_by="u1"
        )
        assert rec.get("status") == "pending"


class TestConfirmationGatePinned:
    def test_pending_absent_from_main_until_confirm(self, store):
        """确认门架构断言：未确认条目只在 pending 表，主库唯一写路径=confirm。"""
        store.propose("未确认的记忆", proposed_by="u1")
        assert [r["status"] for r in store.list_pending()] == ["pending"]
        saved = {}
        store.confirm(store.list_pending()[0]["id"], _remember_fn(saved))
        assert saved.get("content") == "未确认的记忆"
        assert store.list_pending() == []


class TestNormalizedKeySupersede:
    """② NormalizedKey。"""

    def test_normalized_key_collapses_punct_case_prefix(self):
        from neurova.memory.pending_memory import normalized_key

        assert normalized_key("用户偏好深色。") == normalized_key("用户偏好深色")
        assert normalized_key("用户：喜欢 Vim") == normalized_key("用户喜欢vim")
        assert normalized_key("助手：回复A") == normalized_key("回复a")
        # 不同事实不被折叠
        assert normalized_key("用户住在上海") != normalized_key("用户住在北京")

    def test_find_supersede_ids_exact_key_different_id(self):
        from neurova.memory.pending_memory import find_supersede_ids

        mems = [
            {"id": "m1", "content": "用户偏好深色。", "lifecycle_stage": "active"},
            {"id": "m2", "content": "用户偏好浅色", "lifecycle_stage": "active"},
            {"id": "m3", "content": "用户偏好深色", "lifecycle_stage": "forgotten"},
        ]
        assert find_supersede_ids(mems, "用户偏好深色") == ["m1"]  # m3 已 forgotten 不算

    def test_supersede_same_key_forgets_exact_key_memories(self):
        """②：supersede_same_key 软遗忘同 key 活跃旧记忆（新说法接管，无 LLM）。"""
        from unittest.mock import MagicMock, call

        from neurova.memory.pending_memory import supersede_same_key

        mgr = MagicMock()
        mgr.get_all_memories.return_value = [
            {"id": "m1", "content": "用户偏好深色", "lifecycle_stage": "active"},
            {"id": "m2", "content": "用户偏好浅色", "lifecycle_stage": "active"},
            {"id": "m3", "content": "用户偏好深色。", "lifecycle_stage": "forgotten"},
        ]
        mgr.forget.side_effect = lambda mid, soft=True: True
        gone = supersede_same_key(mgr, "用户偏好深色。")
        assert gone == ["m1"]
        assert mgr.forget.call_args_list == [call("m1", soft=True)]
