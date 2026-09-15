"""P0#2 切分器精修测试。

契约：
- 英文句界：`[.!?]` 仅在跟随空白时是句子边界（"3.14"/"v1.2" 内部不切，
中文句末标点行为不变
- 代码围栏保护：≤ max_chars 的 fenced code block 作为原子单元，不被句级/\n
  切碎；超限围栏降级硬切（块仍为原文连续切片）。
- 表格表头再注入：跨块 GFM 表格的续块获得 context_header（该表头行原文），
  首块（含表头本体）context_header 为空。
- build_index_content(title, content, context_header) 为索引输入唯一组装函数
- split_with_meta 入库契约新增 context_header 键（默认 ""）。
"""

import re

from neurova.knowledge.splitter import (
    build_index_content,
    chunk_text,
    split_with_meta,
)


class TestEnglishSentenceBoundary:
    def test_english_period_space_boundaries(self):
        text = "Knowledge bases store facts. Values like 3.14 stay intact. " * 25
        chunks = chunk_text(text, max_chars=120, overlap=0)
        assert len(chunks) > 2, "英文句界应生效（旧实现无英文句切分→硬切）"
        for c in chunks:
            assert c.text.rstrip().endswith("."), f"块应结束于句边界: {c.text[-20:]!r}"
            # 绝不切进数字：块尾不能是 "数字." + 空白（如 "3.14" 被截成 "3."）
            assert not re.search(r"\d\.\s*$", c.text), c.text[-20:]

    def test_cjk_boundaries_unchanged(self):
        text = "数值 3.14 有效。" * 40
        chunks = chunk_text(text, max_chars=50, overlap=0)
        for c in chunks:
            assert c.text.endswith("。") or c.char_end == len(text)


class TestCodeFenceProtection:
    def test_code_fence_atomic_within_max(self):
        code = "```python\nprint('知识库')\nprint('切分器')\n```"
        pre = "前置说明。" * 20
        post = "后置说明。" * 20
        para = pre + "\n" + code + "\n" + post  # 单段落 > max_chars，含围栏
        chunks = chunk_text(para, max_chars=120, overlap=0)
        assert any(code in c.text for c in chunks), "≤max_chars 的代码围栏必须整体出现在某一块中"

    def test_oversized_fence_hard_split_ok(self):
        code = "```python\n" + "\n".join(f"v{i} = {i}" for i in range(80)) + "\n```"
        text = code + "\n" + "尾部说明。" * 10
        chunks = chunk_text(text, max_chars=150, overlap=0)
        assert chunks
        for c in chunks:
            assert c.text == text[c.char_start : c.char_end]


class TestTableHeaderContext:
    header = "| 城市 | 人口 | 面积 |"

    def _table_text(self):
        rows = "\n".join(f"| 城{i} | {i * 100} | {i * 3} |" for i in range(30))
        return self.header + "\n|---|---|---|\n" + rows

    def test_first_chunk_contains_header_no_context(self):
        metas = split_with_meta(self._table_text(), max_chars=120, overlap=0)
        assert metas[0]["context_header"] == ""
        assert self.header in metas[0]["content"]

    def test_continuation_chunks_get_header(self):
        metas = split_with_meta(self._table_text(), max_chars=120, overlap=0)
        later = [m for m in metas[1:] if m["content"].lstrip().startswith("|")]
        assert later, "表格应跨块"
        for m in later:
            assert m["context_header"] == self.header

    def test_prose_chunks_no_header(self):
        text = "普通段落。" * 30 + "\n\n" + "另一段。" * 30
        metas = split_with_meta(text, max_chars=120, overlap=0)
        assert all(m["context_header"] == "" for m in metas)


class TestBuildIndexContent:
    def test_title_and_content(self):
        assert build_index_content("标题", "正文") == "标题\n正文"

    def test_with_context_header(self):
        assert (
            build_index_content("标题", "正文", "| 城市 | 人口 |")
            == "标题\n| 城市 | 人口 |\n正文"
        )

    def test_no_title(self):
        assert build_index_content("", "正文") == "正文"

    def test_header_only_no_title(self):
        assert build_index_content("", "正文", "头") == "头\n正文"


class TestSplitWithMetaContract:
    def test_context_header_key_present(self):
        metas = split_with_meta("一句话知识。")
        assert metas[0]["context_header"] == ""
