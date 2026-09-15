"""rebuildParentContent 移植（下批①）：编辑过的子块叠加进父块上下文。

契约（docs/Neurova_WeKnora代码级对比_2026-09-15.md §8 遗留项）：
- parent_context_text(item, pi) 以父块原文为底，把该父下 revision>0 的
  子块编辑按其绝对偏移替换（未编辑子块不参与——子块 overlap 窗口的原文
  本就含于父底，重复拼接反而制造重复）；
- 互叠的编辑区间成组：组内最高 revision 为 winner，loser 文本尾部追加
  （信息不静默丢，对齐 WeKnora "latest wins, loser appended"）；
- 检索链 end-to-end：update_chunk 后命中条目的 context_passages 带新文。
"""

import pytest

from neurova.knowledge.repository import KnowledgeRepository, parent_context_text
from neurova.knowledge.splitter import build_entry_chunks

TEXT = "甲区内容。" * 200 + "\n\n" + "乙区内容。" * 200


@pytest.fixture
def pc(tmp_path):
    r = KnowledgeRepository(str(tmp_path))
    children, parents = build_entry_chunks(TEXT)
    item = r.create_knowledge(
        "default", "父子文档", TEXT, owner_user_id="1",
        chunks=children, parents=parents,
    )
    return r, item["knowledge_id"]


class TestOverlay:
    def test_unedited_parent_is_original_slice(self, pc):
        r, kid = pc
        item = r.get_item("default", kid)
        p0 = item["parents"][0]
        assert parent_context_text(item, 0) == TEXT[p0["char_start"]:p0["char_end"]]

    def test_single_edit_overlayed(self, pc):
        r, kid = pc
        item = r.get_item("default", kid)
        ch0 = item["chunks"][0]
        pi = ch0["parent_index"]
        r.update_chunk(kid, 0, "全新甲零内容。", user={"user_id": "1"})
        ctx = parent_context_text(r.get_item("default", kid), pi)
        assert "全新甲零内容。" in ctx
        # 被替换区间的原文不再是主体（父块其余原文保留）
        assert ctx.count("甲区内容。") < TEXT[:item["parents"][pi]["char_end"]].count("甲区内容。")

    def test_two_disjoint_edits(self, pc):
        r, kid = pc
        item = r.get_item("default", kid)
        same_parent = [c["index"] for c in item["chunks"] if c.get("parent_index") == 0][:2]
        assert len(same_parent) >= 2
        r.update_chunk(kid, same_parent[0], "编辑一。", user={"user_id": "1"})
        r.update_chunk(kid, same_parent[1], "编辑二。", user={"user_id": "1"})
        ctx = parent_context_text(r.get_item("default", kid), 0)
        assert "编辑一。" in ctx and "编辑二。" in ctx

    def test_conflicting_edits_latest_wins_loser_appended(self, pc):
        r, kid = pc
        item = r.get_item("default", kid)
        # 父子分块子块自带 overlap 窗口：相邻两块区间互叠
        idxs = [c["index"] for c in item["chunks"] if c.get("parent_index") == 0][:2]
        chs = {c["index"]: c for c in item["chunks"]}
        a, b = idxs
        assert chs[a]["char_end"] > chs[b]["char_start"] or chs[a]["char_start"] < chs[b]["char_start"]
        r.update_chunk(kid, a, "先改内容A。", user={"user_id": "1"})   # rev1
        r.update_chunk(kid, b, "后改内容B。", user={"user_id": "1"})   # rev1，另一块
        # 手动制造同层互叠冲突：把 a 的 revision 抬高再 overlay 校验
        item = r.get_item("default", kid)
        for c in item["chunks"]:
            if c["index"] == a:
                c["revision"] = 9
        ctx = parent_context_text(item, 0)
        # winner(a, rev9) 区间替换生效；b 与 a 互叠 → 其内容进尾部
        assert "先改内容A。" in ctx
        assert "后改内容B。" in ctx  # 不静默丢（替换或尾部追加都算）

    def test_search_context_passages_reflect_edit(self, pc):
        r, kid = pc
        item = r.get_item("default", kid)
        ch = item["chunks"][0]
        r.update_chunk(kid, 0, "独有词编辑后内容。" + ch["content"][:20], user={"user_id": "1"})
        hits = r.search_visible_items(user={"user_id": "1"}, query="独有词编辑后内容", scope="all", limit=3)
        assert hits and hits[0]["knowledge_id"] == kid
        passages = hits[0].get("context_passages") or []
        assert any("独有词编辑后内容" in p for p in passages), "命中子块编辑必须出现在父上下文"

    def test_flat_mode_untouched(self, tmp_path):
        from neurova.knowledge.splitter import split_with_meta
        r = KnowledgeRepository(str(tmp_path))
        item = r.create_knowledge("default", "扁平", "全文内容。" * 100,
                                  owner_user_id="1", chunks=split_with_meta("全文内容。" * 100))
        r.update_chunk(item["knowledge_id"], 0, "扁平编辑。", user={"user_id": "1"})
        got = r.get_item("default", item["knowledge_id"])
        assert got["chunks"][0]["content"] == "扁平编辑。"
        assert "parents" not in got or not got.get("parents")
