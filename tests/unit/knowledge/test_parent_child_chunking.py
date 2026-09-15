"""P1#6 父子分块检索测试。

契约：
- splitter.build_entry_chunks(text)：父块（800）+ 子块（384，child_overlap=child/5）；
  子块带 parent_index，偏移恒为原文绝对偏移（text == 原文[start:end] 不变式保持）。
- 索引只进子块（细粒度命中）；检索命中子块后 LLM 消费父块上下文
  （context_passages，按命中分数序去重，封顶 3 个父块）。
- 摄取（/import 与 create 路径）、live-preview、update 重切共享同一构造
  （单源，防分叉）。存量扁平条目（无 parents 字段）保持旧行为零迁移。
"""

import pytest

from neurova.knowledge.splitter import build_entry_chunks, chunk_text
from neurova.knowledge.repository import KnowledgeRepository


def _long_doc():
    paras = []
    for i in range(12):
        paras.append(f"第{i}章导言。" + f"内容{chr(65 + i)}。" * 120)
    return "\n\n".join(paras)


class TestBuildEntryChunks:
    def test_parents_and_children_shapes(self):
        text = _long_doc()
        chunks, parents = build_entry_chunks(text)
        assert chunks and parents
        # 子块粒度显著细于父块
        assert len(chunks) >= len(parents)
        for ch in chunks:
            assert "parent_index" in ch
            assert 0 <= ch["parent_index"] < len(parents)
            assert ch["content"] == text[ch["char_start"] : ch["char_end"]]
            assert ch["content"], "子块不得为空"
        for p in parents:
            assert p["content"] == text[p["char_start"] : p["char_end"]]
            assert len(p["content"]) <= 800 + 60

    def test_children_within_parent_span(self):
        text = _long_doc()
        chunks, parents = build_entry_chunks(text)
        by_pi = {}
        for ch in chunks:
            by_pi.setdefault(ch["parent_index"], []).append(ch)
        for pi, kids in by_pi.items():
            pa = parents[pi]
            for ch in kids:
                assert ch["char_start"] >= pa["char_start"] - 1
                assert ch["char_end"] <= pa["char_end"] + 1

    def test_short_text_single(self):
        chunks, parents = build_entry_chunks("短条目。")
        assert len(chunks) == 1 and len(parents) == 1
        assert chunks[0]["parent_index"] == 0


class TestRepoParentChild:
    @pytest.fixture
    def repo(self, tmp_path):
        return KnowledgeRepository(str(tmp_path))

    def _seed_pc(self, repo):
        text = (
            "工作流引擎章节。NeurFlow 支持可视化编排与触发器。" * 60
            + "\n\n"
            + "记忆系统章节。温度衰减与巩固策略说明。" * 60
        )
        chunks, parents = build_entry_chunks(text)
        return repo.create_knowledge(
            "default", "NeurFlow 手册", text, owner_user_id="1",
            chunks=chunks, parents=parents,
        )

    def test_index_granularity_is_child(self, repo):
        kid = self._seed_pc(repo)["knowledge_id"]
        store = repo._get_vector_store("private", "1")
        repo.search_visible_items(user={"user_id": "1"}, query="占位", scope="all", limit=1)
        ids = store.memory_ids
        assert all(i.startswith(kid + "#") for i in ids)
        # 子块数 > 父块数（索引进的是子粒度）
        assert len(ids) > len(repo.get_item("default", kid)["parents"])

    def test_hit_returns_parent_context(self, repo):
        self._seed_pc(repo)
        results = repo.search_visible_items(
            user={"user_id": "1"}, query="可视化编排触发器", scope="all", limit=3
        )
        assert results, "子块命中"
        top = results[0]
        passages = top.get("context_passages") or []
        assert passages, "命中子块必须回传父块上下文（LLM 消费父）"
        assert any("NeurFlow" in p for p in passages)
        assert all(len(p) <= 800 + 60 for p in passages)

    def test_flat_entries_unchanged(self, repo):
        """存量扁平模式零迁移：无 parents → 无 context_passages 字段也不报错。"""
        from neurova.knowledge.splitter import split_with_meta

        repo.create_knowledge(
            "default", "扁平旧条目", "NeurFlow 扁平条目正文 触发器" * 30,
            owner_user_id="1", chunks=split_with_meta("NeurFlow 扁平条目正文 触发器" * 30),
        )
        results = repo.search_visible_items(
            user={"user_id": "1"}, query="触发器", scope="all", limit=3
        )
        assert results
        assert "context_passages" not in results[0] or results[0]["context_passages"] == []

    def test_adapter_prefers_parent_context(self, repo):
        import asyncio
        from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter
        from neurova.agent.memory_retrieval_chain import RetrievalContext

        self._seed_pc(repo)
        import types
        repo_stub_vindex = types.SimpleNamespace(search=lambda *a, **k: [])
        import neurova.knowledge.vector_index as vidx
        orig = vidx.get_knowledge_vector_index
        vidx.get_knowledge_vector_index = lambda: repo_stub_vindex
        try:
            adapter = KnowledgeRetrieverAdapter(repo)
            r = asyncio.run(
                adapter.retrieve(RetrievalContext(query="可视化编排触发器", user_id="1", limit=3))
            )
        finally:
            vidx.get_knowledge_vector_index = orig
        assert r.memories
        m = r.memories[0]
        assert "NeurFlow" in m["content"]
        # 父上下文远小于整篇（LLM 消费父块而非全文）
        full = len(repo.get_item("default", m["knowledge_id"])["content"])
        assert len(m["content"]) < full
