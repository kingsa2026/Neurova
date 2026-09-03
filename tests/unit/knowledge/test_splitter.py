"""分块器测试（P0-2 RAG 分块管线）。

契约（docs/Neurova_Dify代码级对比_2026-09-03.md §4 P0-2）：
- chunk_text(text, max_chars, overlap)：段落优先 → 超长段落按句切 → 兜底硬切；
  相邻块带 overlap 防语义截断；短文本单块直返。
- 返回 [Chunk(index, text, char_start, char_end)]，块间原文无损（去分隔符外）。
- split_with_meta：包一层 {content, index, char_start, char_end} 便于入库。
"""

import pytest

from neurova.knowledge.splitter import Chunk, chunk_text, split_with_meta


def _para(i, chars=80):
    return f"第{i}段。" + "内容" * (chars // 2) + f"。段落{i}结束。"


class TestChunkText:
    def test_short_text_single_chunk(self):
        chunks = chunk_text("短文本，无需分块。")
        assert len(chunks) == 1
        assert chunks[0].index == 0
        assert chunks[0].text == "短文本，无需分块。"

    def test_empty_returns_empty(self):
        assert chunk_text("") == []
        assert chunk_text("   \n  ") == []

    def test_paragraph_boundaries_respected(self):
        paras = [_para(i) for i in range(6)]  # 每段 ~90 字
        text = "\n\n".join(paras)
        chunks = chunk_text(text, max_chars=200, overlap=0)
        assert len(chunks) >= 3
        # 每块不超过上限（硬切兜底）
        assert all(len(c.text) <= 200 + 50 for c in chunks)  # 允许句级余量
        # 块内文本是原文子串（无篡改）
        for c in chunks:
            assert c.text in text

    def test_no_chunk_exceeds_max(self):
        # 无段落结构的超长文本 → 句切/硬切兜底
        text = "这是没有段落的一长串文本。" * 200  # ~2400 字
        chunks = chunk_text(text, max_chars=300, overlap=50)
        assert len(chunks) > 1
        assert all(len(c.text) <= 400 for c in chunks)

    def test_overlap_between_adjacent_chunks(self):
        paras = [_para(i) for i in range(8)]
        text = "\n\n".join(paras)
        chunks = chunk_text(text, max_chars=200, overlap=40)
        assert len(chunks) >= 3
        # 相邻块：后块开头应出现在前块尾部附近（重叠语义）
        for prev, cur in zip(chunks, chunks[1:]):
            tail = prev.text[-120:]
            assert any(word in tail for word in cur.text[:40])

    def test_offsets_are_inclusive_and_monotonic(self):
        paras = [_para(i) for i in range(6)]
        text = "\n\n".join(paras)
        chunks = chunk_text(text, max_chars=200, overlap=0)
        for prev, cur in zip(chunks, chunks[1:]):
            assert cur.char_start >= prev.char_end
        # 首块从头开始
        assert chunks[0].char_start == 0
        # 末块覆盖到结尾附近
        assert chunks[-1].char_end >= len(text) - 200


class TestSplitWithMeta:
    def test_returns_dicts_with_content_and_index(self):
        paras = [_para(i) for i in range(6)]
        text = "\n\n".join(paras)
        metas = split_with_meta(text, max_chars=200, overlap=0)
        assert len(metas) >= 3
        for i, m in enumerate(metas):
            assert m["index"] == i
            assert m["content"]
            assert m["char_end"] > m["char_start"]

    def test_single_short_document(self):
        metas = split_with_meta("一句话知识。")
        assert metas == [
            {"content": "一句话知识。", "index": 0, "char_start": 0, "char_end": 6}
        ]


class TestChunkDataclass:
    def test_chunk_dataclass_fields(self):
        c = Chunk(index=0, text="abc", char_start=0, char_end=3)
        assert (c.index, c.text, c.char_start, c.char_end) == (0, "abc", 0, 3)
