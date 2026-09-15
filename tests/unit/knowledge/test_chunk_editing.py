"""P1#8 chunk 编辑乐观锁 + revision 账本 + 自动重索引测试。

契约：
- repository.update_chunk(knowledge_id, index, content, user, expected_revision=None)
  - 权限：can_modify（属主/admin），越权 PermissionError；
  - 乐观锁：expected_revision 与当前 revision 不符 → ChunkRevisionConflict；
  - 追加式账本：旧值快照进 chunk.revisions（append-only），revision 自增；
  - 编辑后自动重索引（record reindex——下一次检索已带新文本）；
  - 块是其文本的权威副本（_chunk_hit/_item_index_docs 已优先读块 content），
    整篇 content 保持原文不变（供导出/参照），不联动重写其他块。
"""

import pytest

from neurova.knowledge.repository import (
    ChunkRevisionConflict,
    KnowledgeRepository,
)
from neurova.knowledge.splitter import build_entry_chunks, split_with_meta


@pytest.fixture
def repo(tmp_path):
    r = KnowledgeRepository(str(tmp_path))
    text = "第一块内容 关键词甲。" * 60 + "\n\n" + "第二块内容 关键词乙。" * 60
    item = r.create_knowledge(
        "default", "双块条目", text, owner_user_id="1", chunks=split_with_meta(text)
    )
    return r, item["knowledge_id"]


ADMIN = {"user_id": "1"}


class TestUpdateChunk:
    def test_edit_reindexes_and_searchable(self, repo):
        r, kid = repo
        n = r.update_chunk(kid, 1, "第三块改写 关键词丙。", user=ADMIN)
        assert n == 1
        hits = r.search_visible_items(user=ADMIN, query="关键词丙", scope="all", limit=5)
        assert hits and hits[0]["knowledge_id"] == kid
        # 编辑后块 1 的命中内容是新文本（索引/chunk_hits 反映编辑，非旧块）
        ch1 = [h for h in hits[0]["chunk_hits"] if h["chunk_index"] == 1]
        assert ch1 and ch1[0]["content"] == "第三块改写 关键词丙。"

    def test_chunk_hit_returns_edited_content(self, repo):
        r, kid = repo
        r.update_chunk(kid, 1, "改写后的块 关键词乙。", user=ADMIN)
        hits = r.search_visible_items(user=ADMIN, query="关键词乙", scope="all", limit=5)
        ch_hit = [h for h in hits[0]["chunk_hits"] if h["chunk_index"] == 1]
        assert ch_hit and ch_hit[0]["content"] == "改写后的块 关键词乙。"

    def test_full_content_not_rewritten(self, repo):
        """块编辑不改整篇 content（原文供导出/参照），只改块副本。"""
        r, kid = repo
        before = r.get_item("default", kid)["content"]
        r.update_chunk(kid, 0, "被改写。", user=ADMIN)
        assert r.get_item("default", kid)["content"] == before

    def test_optimistic_conflict(self, repo):
        r, kid = repo
        r.update_chunk(kid, 0, "第一次编辑。", user=ADMIN, expected_revision=0)
        with pytest.raises(ChunkRevisionConflict):
            r.update_chunk(kid, 0, "冲突编辑。", user=ADMIN, expected_revision=0)

    def test_revision_ledger_append_only(self, repo):
        r, kid = repo
        old = r.get_item("default", kid)["chunks"][0]["content"]
        r.update_chunk(kid, 0, "新文本一。", user=ADMIN)
        r.update_chunk(kid, 0, "新文本二。", user=ADMIN)
        ch = r.get_item("default", kid)["chunks"][0]
        assert ch["revision"] == 2
        revs = ch["revisions"]
        assert len(revs) == 2
        assert revs[0]["content"] == old
        assert revs[1]["content"] == "新文本一。"

    def test_permission_denied(self, repo):
        r, kid = repo
        with pytest.raises(PermissionError):
            r.update_chunk(kid, 0, "越权。", user={"user_id": "999"})

    def test_guards(self, repo):
        r, kid = repo
        with pytest.raises(ValueError):
            r.update_chunk(kid, 0, "   ", user=ADMIN)
        with pytest.raises(LookupError):
            r.update_chunk(kid, 99, "越界块。", user=ADMIN)
        with pytest.raises(LookupError):
            r.update_chunk("missing-kid", 0, "x", user=ADMIN)


class TestParentChildEditing:
    def test_edit_child_keeps_parent_index(self, tmp_path):
        r = KnowledgeRepository(str(tmp_path))
        text = "父一内容区。" * 100 + "\n\n" + "父二内容区。" * 100
        children, parents = build_entry_chunks(text)
        item = r.create_knowledge(
            "default", "父子条目", text, owner_user_id="1",
            chunks=children, parents=parents,
        )
        kid = item["knowledge_id"]
        r.update_chunk(kid, 0, "改写子块零 独有词。", user={"user_id": "1"})
        ch = r.get_item("default", kid)["chunks"][0]
        assert ch.get("parent_index") == 0
        assert ch["content"] == "改写子块零 独有词。"
        hits = r.search_visible_items(user={"user_id": "1"}, query="独有词", scope="all", limit=3)
        assert hits and hits[0]["knowledge_id"] == kid
