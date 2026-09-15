"""P0#5 引用句柄压缩 + 资格分离测试。

契约：
- CitationRegistry：本轮作用域句柄分配器——长 UUID（memory_id/knowledge_id）
  进 prompt 前压缩为 m1/k1 短句柄（省 token + 防长 ID 被模型改写损坏）；
  同 id 重复 register 返回同一句柄（幂等）。
- 知识条目（带 knowledge_id 的 memories 载荷，P0#4 归一化后）用 k 前缀，
  纯记忆用 m 前缀。
- render_memory_line(memory, registry=…)：有句柄渲染 ref="m1"；无标识字段
  条目退回旧格式（无 marker，行为不变）。
- extract_citations(text, registry=…)：资格分离——只承认本轮注册过的句柄
  （ref="m2" → 解析回真实 id 返回）；未注册句柄与不匹配的本轮外
  memory_id 一律丢弃（防历史回放/模型伪造引用）；registry=None 保持旧行为。
- decode_citation_handles(text, registry)：把回复中的 ref 句柄还原为
  memory_id="…" 供落库/UI/审计；本轮未注册的 ref 标记整体删除。
"""

import pytest

from neurova.memory.citation import (
    CitationRegistry,
    decode_citation_handles,
    extract_citations,
    render_citation,
    render_memory_line,
)


def _mem(mid="a1b2c3d4-long-memory-uuid", **kw):
    d = {"memory_id": mid, "content": "用户偏好深色", "category": "preference"}
    d.update(kw)
    return d


class TestRegistry:
    def test_handle_allocation_and_prefix(self):
        reg = CitationRegistry()
        m = _mem()
        k = {"knowledge_id": "k-uuid-long", "content": "NeurFlow 文档"}
        h1 = reg.register(m)
        h2 = reg.register(k)
        assert h1.startswith("m") and h1 != m["memory_id"]
        assert h2.startswith("k")
        assert reg.register(m) == h1, "同 id 幂等复用句柄"
        assert reg.resolve(h1) == m["memory_id"]
        assert reg.resolve(h2) == "k-uuid-long"
        assert reg.resolve("m99") is None

    def test_no_identifier_no_handle(self):
        reg = CitationRegistry()
        assert reg.register({"content": "无标识"}) is None


class TestRenderWithRegistry:
    def test_handle_format_compact(self):
        reg = CitationRegistry()
        mem = _mem()
        line = render_memory_line(mem, registry=reg)
        assert f'{mem["memory_id"]}' not in line, "长 UUID 不得再进 prompt"
        assert 'ref="m1"' in line

    def test_without_registry_legacy_unchanged(self):
        line = render_memory_line(_mem())
        assert 'memory_id="a1b2c3d4-long-memory-uuid"' in line

    def test_no_id_entry_no_marker(self):
        reg = CitationRegistry()
        assert render_memory_line({"content": "裸"}, registry=reg) == "[记忆] 裸"


class TestEligibility:
    def test_extract_only_registered_handles(self):
        reg = CitationRegistry()
        mid = _mem()["memory_id"]
        reg.register({"memory_id": mid})
        reg.register({"knowledge_id": "k-1"})
        text = (
            '引用一 <memory_citation ref="m1"/>'
            ' 引用二 <memory_citation ref="k1"/>'
            ' 伪造 <memory_citation ref="m7"/>'  # 本轮未注册 → 丢
        )
        out = extract_citations(text, registry=reg)
        got = {c.get("memory_id") for c in out}
        assert got == {mid, "k-1"}

    def test_extract_legacy_id_replayed_rejected(self):
        """历史消息回放的完整 UUID 引用：不在本轮注册表 → 资格分离丢弃。"""
        reg = CitationRegistry()
        reg.register({"memory_id": "mine"})
        text = (
            '<memory_citation memory_id="mine"/>'
            '<memory_citation memory_id="从上一轮偷来的"/>'
        )
        out = extract_citations(text, registry=reg)
        assert [c["memory_id"] for c in out] == ["mine"]

    def test_extract_registry_none_keeps_legacy(self):
        text = '<memory_citation memory_id="x"/>'
        assert extract_citations(text) == [{"memory_id": "x"}]


class TestDecode:
    def test_handles_restored_unknown_dropped(self):
        reg = CitationRegistry()
        reg.register({"memory_id": "real-uuid"})
        text = '答案 <memory_citation ref="m1"/> 伪造 <memory_citation ref="k5"/>'
        out = decode_citation_handles(text, reg)
        assert 'memory_id="real-uuid"' in out
        assert 'ref="m1"' not in out
        assert "ref=" not in out  # 未注册句柄标记整体删除（含 ref 属性）

    def test_plain_text_untouched(self):
        reg = CitationRegistry()
        assert decode_citation_handles("正常回复", reg) == "正常回复"

    def test_legacy_format_passthrough(self):
        reg = CitationRegistry()
        reg.register({"memory_id": "a"})
        t = '<memory_citation memory_id="a" category="x"/>'
        assert decode_citation_handles(t, reg) == t


class TestStreamCitationBuffer:
    """④ 流式后缀缓冲：标记跨 SSE 分片不泄漏半截 tag，完整标记按资格解码。"""

    def _reg(self):
        reg = CitationRegistry()
        reg.register({"memory_id": "real-uuid"})
        return reg

    def test_split_across_chunks_decoded_as_one(self):
        from neurova.memory.citation import StreamCitationBuffer

        buf = StreamCitationBuffer(self._reg())
        out = buf.feed("答案前") + buf.feed("<memory_cita")
        out += buf.feed('tion ref="m1"/>答案后')
        out += buf.flush()
        assert out == '答案前<memory_citation memory_id="real-uuid"/>答案后'

    def test_unknown_ref_dropped_in_stream(self):
        from neurova.memory.citation import StreamCitationBuffer

        buf = StreamCitationBuffer(self._reg())
        out = buf.feed('文本 <memory_citation ref="k9"/>结束') + buf.flush()
        assert "k9" not in out and "<memory_citation" not in out

    def test_plain_text_untouched_and_lt_tail(self):
        from neurova.memory.citation import StreamCitationBuffer

        buf = StreamCitationBuffer(self._reg())
        assert buf.feed("普通句子，含 < 符号") == "普通句子，含 < 符号"
        # "<m" 结尾疑似标记开头 → 挂起，flush 释放（不是标记也必须出来）
        assert buf.feed("尾部 <m") == "尾部 "
        assert buf.flush() == "<m"

    def test_no_registry_passthrough(self):
        from neurova.memory.citation import StreamCitationBuffer

        buf = StreamCitationBuffer(None)
        assert buf.feed("a<memory_citation memory_id=\"x\"/>b") == "a<memory_citation memory_id=\"x\"/>b"
