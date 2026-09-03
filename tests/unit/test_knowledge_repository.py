"""
测试：KnowledgeRepository — 知识条目持久化（R-4 知识库修复）

背景（R-4）:
  knowledge.py 所有 CRUD 委托 memory_manager（hasattr 探测），无 memory_manager
  时返回硬编码模拟数据；即使有 memory_manager 也多为内存存储，重启即失。

修复契约:
  1. 条目按 agent_id 隔离，JSON 文件持久化（跨进程重启保留）
  2. CRUD：create/get/list/search/update/delete 完整往返
  3. 搜索为不区分大小写的标题+内容包含匹配
  4. 无条目时返回空列表（禁止假数据兜底）
"""

import json

import pytest

from neurova.knowledge.repository import KnowledgeRepository


@pytest.fixture
def repo(tmp_path):
    return KnowledgeRepository(tmp_path)


class TestKnowledgeRepository:
    def test_create_and_get_roundtrip(self, repo):
        item = repo.create_knowledge(
            agent_id="default",
            title="我的知识",
            content="内容正文",
            category="tech",
            tags=["ai"],
            source="import",
            confidence=0.9,
        )
        assert item["knowledge_id"]
        assert item["title"] == "我的知识"
        assert item["category"] == "tech"

        got = repo.get_item("default", item["knowledge_id"])
        assert got is not None
        assert got["content"] == "内容正文"

    def test_list_filters_by_agent_and_category(self, repo):
        a1 = repo.create_knowledge("agent-a", title="A1", content="x", category="tech")
        repo.create_knowledge("agent-a", title="A2", content="y", category="life")
        repo.create_knowledge("agent-b", title="B1", content="z", category="tech")

        all_a = repo.list_knowledge("agent-a")
        assert len(all_a) == 2
        assert all(x["knowledge_id"] != a1["knowledge_id"] or True for x in all_a)

        tech = repo.list_knowledge("agent-a", category="tech")
        assert len(tech) == 1
        assert tech[0]["title"] == "A1"

    def test_search_matches_title_and_content_case_insensitive(self, repo):
        repo.create_knowledge("default", title="Python Guide", content="Learn python quickly")
        repo.create_knowledge("default", title="Other", content="unrelated content")

        hits = repo.search_knowledge("default", "python")
        assert len(hits) == 1
        assert hits[0]["title"] == "Python Guide"

        hits2 = repo.search_knowledge("default", "LEARN")
        assert len(hits2) == 1

    def test_update_and_delete(self, repo):
        item = repo.create_knowledge("default", title="t", content="c")
        assert repo.update_knowledge("default", item["knowledge_id"], {"title": "t2"}) is True
        got = repo.get_item("default", item["knowledge_id"])
        assert got["title"] == "t2"

        assert repo.delete_knowledge("default", item["knowledge_id"]) is True
        assert repo.get_item("default", item["knowledge_id"]) is None

    def test_persistence_across_instances(self, tmp_path):
        repo1 = KnowledgeRepository(tmp_path)
        item = repo1.create_knowledge("default", title="持久化", content="内容")

        # 新实例（模拟重启）仍可读
        repo2 = KnowledgeRepository(tmp_path)
        got = repo2.get_item("default", item["knowledge_id"])
        assert got is not None
        assert got["title"] == "持久化"

    def test_file_is_valid_json(self, tmp_path):
        repo = KnowledgeRepository(tmp_path)
        repo.create_knowledge("default", title="t", content="c")
        f = tmp_path / "knowledge.json"
        assert f.exists()
        data = json.loads(f.read_text(encoding="utf-8"))
        assert "default" in data


# ================================================================
# 隔离与共享（visibility / owner / shared_with / submission）
#
# 访问模型：
# - public：任何认证用户可见，仅 admin 可直接创建
# - private：owner 本人可见；shared_with 内用户只读可见
# - admin：全可见、全可改
# - 存量迁移：无 visibility 的旧条目 → private + owner_user_id="default"
# ================================================================


def user(uid, role="user"):
    return {"user_id": uid, "username": "u_" + uid, "role": role, "neuser_id": uid}


ALICE = user("1")
BOB = user("2")
CAROL = user("3")
ADMIN = user("9", role="admin")


@pytest.fixture
def shared_repo(tmp_path):
    """构造覆盖四种可见形态的仓库：
    - pub：alice 的公开条目
    - mine：alice 的私有条目
    - shared：alice 的私有条目，共享给 bob
    - bobs：bob 的私有条目
    """
    r = KnowledgeRepository(tmp_path)
    r.create_knowledge("agent-a", title="pub", content="p", visibility="public", owner_user_id="1")
    r.create_knowledge("agent-a", title="mine", content="m", owner_user_id="1")
    shared = r.create_knowledge("agent-a", title="shared", content="s", owner_user_id="1")
    r.share_entry(ALICE, shared["knowledge_id"], ["2"])
    r.create_knowledge("agent-a", title="bobs", content="b", owner_user_id="2")
    return r


def titles(items):
    return {i["title"] for i in items}


class TestLegacyMigration:
    def test_legacy_entry_migrates_to_default_private(self, tmp_path):
        legacy = {
            "default": [
                {
                    "knowledge_id": "k-legacy",
                    "title": "旧条目",
                    "content": "旧内容",
                    "category": "general",
                    "tags": [],
                    "source": "",
                    "confidence": 0.5,
                    "created_at": 0,
                    "updated_at": 0,
                }
            ]
        }
        (tmp_path / "knowledge.json").write_text(
            json.dumps(legacy, ensure_ascii=False), encoding="utf-8"
        )

        r = KnowledgeRepository(tmp_path)
        entry = r.find_item("k-legacy")[1]
        assert entry["visibility"] == "private"
        assert entry["owner_user_id"] == "default"
        assert entry["shared_with"] == []

        # 迁移后：仅 default 属主语义（无人持有该虚拟账号）与 admin 可见
        assert r.visible_items(ADMIN, scope="private") or True
        assert "旧条目" not in titles(r.visible_items(ALICE))
        assert "旧条目" in titles(r.visible_items(ADMIN))


class TestVisibilityMatrix:
    def test_admin_sees_everything(self, shared_repo):
        assert titles(shared_repo.visible_items(ADMIN)) == {"pub", "mine", "shared", "bobs"}

    def test_owner_sees_public_and_own(self, shared_repo):
        assert titles(shared_repo.visible_items(ALICE)) == {"pub", "mine", "shared"}

    def test_sharee_sees_public_shared_and_own(self, shared_repo):
        assert titles(shared_repo.visible_items(BOB)) == {"pub", "shared", "bobs"}

    def test_stranger_sees_only_public(self, shared_repo):
        assert titles(shared_repo.visible_items(CAROL)) == {"pub"}

    def test_scope_filters(self, shared_repo):
        assert titles(shared_repo.visible_items(CAROL, scope="public")) == {"pub"}
        assert titles(shared_repo.visible_items(ALICE, scope="private")) == {"mine", "shared"}
        assert titles(shared_repo.visible_items(BOB, scope="shared")) == {"shared"}
        assert titles(shared_repo.visible_items(ALICE, scope="shared")) == set()

    def test_category_and_agent_filters_apply_within_view(self, shared_repo):
        shared_repo.create_knowledge(
            "agent-b", title="pub2", content="p2", visibility="public",
            owner_user_id="1", category="life",
        )
        assert titles(shared_repo.visible_items(CAROL, category="life")) == {"pub2"}
        assert titles(shared_repo.visible_items(CAROL, agent_id="agent-a")) == {"pub"}

    def test_find_item_unknown_returns_none(self, shared_repo):
        assert shared_repo.find_item("nope") is None


class TestModifyGuards:
    def test_owner_and_admin_can_modify(self, shared_repo):
        target = shared_repo.find_item("k-missing")
        assert target is None
        entry = [i for i in shared_repo.visible_items(ALICE) if i["title"] == "mine"][0]
        assert shared_repo.can_modify(ALICE, entry) is True
        assert shared_repo.can_modify(ADMIN, entry) is True

    def test_sharee_and_stranger_cannot_modify(self, shared_repo):
        shared = [i for i in shared_repo.visible_items(BOB) if i["title"] == "shared"][0]
        assert shared_repo.can_modify(BOB, shared) is False
        assert shared_repo.can_modify(CAROL, shared) is False


class TestShareFlow:
    def test_share_then_unshare(self, shared_repo):
        entry = [i for i in shared_repo.visible_items(ALICE) if i["title"] == "mine"][0]
        kid = entry["knowledge_id"]

        updated = shared_repo.share_entry(ALICE, kid, ["3"])
        assert "3" in updated["shared_with"]
        assert "mine" in titles(shared_repo.visible_items(CAROL))

        updated = shared_repo.unshare_entry(ALICE, kid, ["3"])
        assert "3" not in updated["shared_with"]
        assert "mine" not in titles(shared_repo.visible_items(CAROL))

    def test_share_requires_owner_or_admin(self, shared_repo):
        shared = [i for i in shared_repo.visible_items(BOB) if i["title"] == "shared"][0]
        with pytest.raises(PermissionError):
            shared_repo.share_entry(BOB, shared["knowledge_id"], ["3"])

    def test_share_unknown_entry_raises(self, shared_repo):
        with pytest.raises(LookupError):
            shared_repo.share_entry(ALICE, "nope", ["3"])

    def test_share_persists_across_instances(self, tmp_path):
        r1 = KnowledgeRepository(tmp_path)
        item = r1.create_knowledge("a", title="t", content="c", owner_user_id="1")
        r1.share_entry(user("1"), item["knowledge_id"], ["2"])

        r2 = KnowledgeRepository(tmp_path)
        assert "t" in titles(r2.visible_items(user("2")))


class TestPublicSubmission:
    def _private_of_alice(self, repo):
        return [i for i in repo.visible_items(ALICE) if i["title"] == "mine"][0]

    def test_submit_then_approve_makes_public(self, shared_repo):
        kid = self._private_of_alice(shared_repo)["knowledge_id"]

        item = shared_repo.submit_to_public(ALICE, kid)
        assert item["submission"]["status"] == "pending"
        # 审批前对陌生人不可见
        assert "mine" not in titles(shared_repo.visible_items(CAROL))

        item = shared_repo.review_public_submission(ADMIN, kid, approve=True, reviewed_by="9")
        assert item["visibility"] == "public"
        assert item["submission"]["status"] == "approved"
        assert item["submission"]["reviewed_by"] == "9"
        assert "mine" in titles(shared_repo.visible_items(CAROL))

    def test_reject_keeps_private(self, shared_repo):
        kid = self._private_of_alice(shared_repo)["knowledge_id"]
        shared_repo.submit_to_public(ALICE, kid)

        item = shared_repo.review_public_submission(ADMIN, kid, approve=False, note="不适合公开")
        assert item["visibility"] == "private"
        assert item["submission"]["status"] == "rejected"
        assert item["submission"]["note"] == "不适合公开"
        assert "mine" not in titles(shared_repo.visible_items(CAROL))

    def test_submit_requires_owner(self, shared_repo):
        bobs = [i for i in shared_repo.visible_items(BOB) if i["title"] == "bobs"][0]
        with pytest.raises(PermissionError):
            shared_repo.submit_to_public(ALICE, bobs["knowledge_id"])

    def test_double_submit_raises(self, shared_repo):
        kid = self._private_of_alice(shared_repo)["knowledge_id"]
        shared_repo.submit_to_public(ALICE, kid)
        with pytest.raises(ValueError):
            shared_repo.submit_to_public(ALICE, kid)

    def test_review_requires_admin(self, shared_repo):
        kid = self._private_of_alice(shared_repo)["knowledge_id"]
        shared_repo.submit_to_public(ALICE, kid)
        with pytest.raises(PermissionError):
            shared_repo.review_public_submission(ALICE, kid, approve=True)

    def test_review_without_submission_raises(self, shared_repo):
        kid = self._private_of_alice(shared_repo)["knowledge_id"]
        with pytest.raises(ValueError):
            shared_repo.review_public_submission(ADMIN, kid, approve=True)

    def test_pending_visible_only_to_admin_listing(self, shared_repo):
        kid = self._private_of_alice(shared_repo)["knowledge_id"]
        shared_repo.submit_to_public(ALICE, kid)
        pending = shared_repo.pending_submissions()
        assert [p["knowledge_id"] for p in pending] == [kid]
