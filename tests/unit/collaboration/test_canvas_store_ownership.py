# -*- coding: utf-8 -*-
"""B0 画布属主隔离（CanvasStore 层契约，TDD 先红后绿）。

契约（对齐 neurflow storage P0-1 属主语义，6238766c 先例）：
- create(snapshot, user_id=...) 落属主；无 user_id → 'default'（存量懒归一口径）
- get(canvas_id, requester_id=..., is_admin=..., project_ids=...)
  * requester=None → 系统内部路径不受限（cron/agent op/项目统计）
  * owner/admin 全通过；项目成员可读（project_id ∈ project_ids）；其余 None（与不存在同构）
- update/delete/mutate 写语义：仅 owner/admin（项目成员只读）
- update 不得篡改属主：快照带他人 user_id 时被 existing 覆盖
- list(...) 摘要含 user_id/project_id/agent_id/origin；视图过滤
  * view=personal: 自己的且 project_id/agent_id 均空
  * view=project: project_id 非空（可按 project_id 参数细化）
  * view=agent: agent_id 非空（可按 agent_id 参数细化）
"""
import shutil
import unittest
from pathlib import Path
from tempfile import mkdtemp

from neurova.collaboration.canvas_store import CanvasStore, CanvasVersionConflict


def _snapshot(name="测试画布"):
    return {
        "name": name,
        "nodes": [{"id": "n1", "type": "builtin:start", "position": {"x": 0, "y": 0}, "config": {}}],
        "edges": [],
    }


class TestCanvasStoreOwnership(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = CanvasStore(self.tmp)

    # ── 属主落盘 ──

    def test_create_stamps_user_id(self):
        rec = self.store.create(_snapshot(), user_id="alice")
        self.assertEqual(rec["user_id"], "alice")
        self.assertEqual(self.store.get(rec["id"])["user_id"], "alice")

    def test_create_defaults_to_default_user(self):
        rec = self.store.create(_snapshot())
        self.assertEqual(rec["user_id"], "default")

    def test_owner_backfilled_from_existing_on_update(self):
        """update 快照携带他人 user_id 时，属主以 existing 为准（防篡改）。"""
        rec = self.store.create(_snapshot(), user_id="alice")
        payload = {**_snapshot("改名"), "user_id": "mallory"}
        updated = self.store.update(rec["id"], payload)
        self.assertEqual(updated["name"], "改名")
        self.assertEqual(updated["user_id"], "alice")

    # ── 读语义 ──

    def test_get_system_path_unrestricted(self):
        rec = self.store.create(_snapshot(), user_id="alice")
        self.assertIsNotNone(self.store.get(rec["id"]))  # requester=None 内部路径

    def test_get_non_owner_denied(self):
        rec = self.store.create(_snapshot(), user_id="alice")
        self.assertIsNone(self.store.get(rec["id"], requester_id="bob"))

    def test_get_owner_and_admin_ok(self):
        rec = self.store.create(_snapshot(), user_id="alice")
        self.assertIsNotNone(self.store.get(rec["id"], requester_id="alice"))
        self.assertIsNotNone(self.store.get(rec["id"], requester_id="root", is_admin=True))

    def test_legacy_record_without_user_id_is_default_owned(self):
        """存量文件缺 user_id → 懒归 'default'：default 用户可读，bob 不可。"""
        rec = self.store.create(_snapshot())
        path = self.tmp / "canvases" / f"{rec['id']}.json"
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("user_id", None)
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertIsNotNone(self.store.get(rec["id"], requester_id="default"))
        self.assertIsNone(self.store.get(rec["id"], requester_id="bob"))

    # ── 项目成员可读 ──

    def test_project_member_can_read(self):
        rec = self.store.create({**_snapshot(), "project_id": "p1"}, user_id="alice")
        got = self.store.get(rec["id"], requester_id="bob", project_ids={"p1"})
        self.assertIsNotNone(got)
        # 成员只读：不可 update（写语义不看 project_ids）
        self.assertIsNone(self.store.update(rec["id"], _snapshot("劫持"), requester_id="bob"))

    # ── 写语义 ──

    def test_update_requires_owner(self):
        rec = self.store.create(_snapshot(), user_id="alice")
        self.assertIsNone(self.store.update(rec["id"], _snapshot("bob改"), requester_id="bob"))
        self.assertIsNone(self.store.get(rec["id"], requester_id="bob"))
        self.assertIsNotNone(self.store.update(rec["id"], _snapshot("alice改"), requester_id="alice"))

    def test_delete_requires_owner(self):
        rec = self.store.create(_snapshot(), user_id="alice")
        self.assertFalse(self.store.delete(rec["id"], requester_id="bob"))
        self.assertTrue(self.store.delete(rec["id"], requester_id="alice"))

    def test_mutate_requires_owner(self):
        rec = self.store.create(_snapshot(), user_id="alice")
        self.assertIsNone(self.store.mutate(rec["id"], lambda r: r, requester_id="bob"))
        self.assertIsNotNone(self.store.mutate(rec["id"], lambda r: r, requester_id="alice"))

    def test_version_conflict_still_raises_for_owner(self):
        rec = self.store.create(_snapshot(), user_id="alice")
        with self.assertRaises(CanvasVersionConflict):
            self.store.update(rec["id"], _snapshot(), base_version=99, requester_id="alice")

    # ── 列表视图 ──

    def test_list_summary_contains_ownership_fields(self):
        self.store.create(
            {**_snapshot(), "project_id": "p1", "agent_id": "a1", "origin": "nl_chat"}, user_id="alice"
        )
        item = self.store.list()[0]
        self.assertEqual(item["user_id"], "alice")
        self.assertEqual(item["project_id"], "p1")
        self.assertEqual(item["agent_id"], "a1")
        self.assertEqual(item.get("origin"), "nl_chat")

    def test_list_hides_other_users_canvases(self):
        self.store.create(_snapshot("A"), user_id="alice")
        self.store.create(_snapshot("B"), user_id="bob")
        ids = {i["id"] for i in self.store.list(requester_id="alice")}
        self.assertEqual(len(ids), 1)

    def test_list_includes_project_member_canvases(self):
        self.store.create({**_snapshot("共享"), "project_id": "p1"}, user_id="alice")
        self.store.create(_snapshot("私密"), user_id="alice")
        bob_ids = {i["id"] for i in self.store.list(requester_id="bob", project_ids={"p1"})}
        self.assertEqual(len(bob_ids), 1)

    def test_list_views_personal_project_agent(self):
        self.store.create(_snapshot("个人"), user_id="alice")
        self.store.create({**_snapshot("项目"), "project_id": "p1"}, user_id="alice")
        self.store.create({**_snapshot("agent"), "agent_id": "a1"}, user_id="alice")
        names = lambda **kw: {i["name"] for i in self.store.list(requester_id="alice", **kw)}
        self.assertEqual(names(view="personal"), {"个人"})
        self.assertEqual(names(view="project"), {"项目"})
        self.assertEqual(names(view="agent"), {"agent"})
        self.assertEqual(names(view="project", project_id="p1"), {"项目"})
        self.assertEqual(names(view="agent", agent_id="a1"), {"agent"})

    def test_list_unfiltered_system_path_returns_all(self):
        self.store.create(_snapshot("A"), user_id="alice")
        self.store.create(_snapshot("B"), user_id="bob")
        self.assertEqual(len(self.store.list()), 2)


if __name__ == "__main__":
    unittest.main()
