"""知识库分块 API 验收测试（P0-2）。

验收标准（docs/Neurova_Dify代码级对比_2026-09-03.md §4 P0-2）：
- 长文导入产出多块（chunk_count > 1）
- 检索命中定位到块（chunk_hits 带 chunk_index + content）
"""

import pytest

from neurova.api.endpoints import knowledge as kb
from neurova.knowledge.repository import KnowledgeRepository


def _long_text(paragraphs=30):
    """构造多段落长文（每段 ~120 字，总 ~3.6k 字）。"""
    parts = []
    for i in range(paragraphs):
        core = f"第{i}章主题内容。" + ("知识细节描述，" * 10) + f"本段结束标记{i}。"
        parts.append(core)
    return "\n\n".join(parts)


class TestImportChunking:
    @pytest.mark.asyncio
    async def test_long_import_produces_multiple_chunks(self, monkeypatch, tmp_path):
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        repo._items.clear()
        monkeypatch.setattr(kb, "_get_repository", lambda agent_id="default": repo)

        class FakeUpload:
            filename = "manual.txt"
            content_type = "text/plain"

            async def read(self):
                return _long_text().encode("utf-8")

        result = await kb.import_knowledge_file(
            FakeUpload(), request=None, current_user={"user_id": "u1"}, agent_id="default"
        )
        assert result["code"] == 0
        items = result["data"]["items"]
        assert len(items) == 1
        item = items[0]
        # 长文产出多块
        assert item["chunk_count"] > 1, f"chunk_count={item.get('chunk_count')}"
        # 检索块正文的偏移复原：条目 content 覆盖全部块
        assert item["content"].startswith("第0章主题内容。")

    @pytest.mark.asyncio
    async def test_short_import_single_chunk(self, monkeypatch, tmp_path):
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        repo._items.clear()
        monkeypatch.setattr(kb, "_get_repository", lambda agent_id="default": repo)

        class FakeUpload:
            filename = "note.txt"
            content_type = "text/plain"

            async def read(self):
                return "短笔记内容。".encode("utf-8")

        result = await kb.import_knowledge_file(
            FakeUpload(), request=None, current_user={"user_id": "u1"}, agent_id="default"
        )
        assert result["data"]["items"][0]["chunk_count"] == 1

    @pytest.mark.asyncio
    async def test_search_hits_locate_chunk(self, monkeypatch, tmp_path):
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        repo._items.clear()
        monkeypatch.setattr(kb, "_get_repository", lambda agent_id="default": repo)

        class FakeUpload:
            filename = "manual.txt"
            content_type = "text/plain"

            async def read(self):
                # 唯一关键词放中后段（第 20 章），验证命中定位到对应块
                text = _long_text(30).replace("第20章主题内容。", "第20章主题内容。量子纠缠的独特术语。")
                return text.encode("utf-8")

        await kb.import_knowledge_file(
            FakeUpload(), request=None, current_user={"user_id": "u1"}, agent_id="default"
        )

        body = kb.KnowledgeSearchRequest(query="量子纠缠的独特术语", limit=10)
        results = await kb.search_knowledge(
            request=None, body=body, current_user={"user_id": "u1", "role": "admin"}, agent_id=None
        )
        assert results, "应命中条目"
        hit = results[0]
        hits = hit.chunk_hits
        assert hits, "应返回块级命中"
        assert "量子纠缠的独特术语" in hits[0]["content"]
        assert hits[0]["chunk_index"] >= 1  # 中后段的块
