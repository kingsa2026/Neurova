"""Markdown 子集 → 中间文档树（纯函数，不依赖 reportlab）。

首批子集见 spec §6：标题、段落、无序/有序列表、粗体/斜体/行内码。
渲染出口只有一条（document_pdf），所以本文件的断言只针对树形状，不针对版式。
"""

from neurova.document_model import NodeKind
from neurova.document_sources import parse_markdown


def _kinds(nodes):
    return [n.kind for n in nodes]


def test_headings_carry_level_and_styled_text():
    nodes = parse_markdown("# 一级\n\n### 三级")
    assert _kinds(nodes) == [NodeKind.HEADING, NodeKind.HEADING]
    assert [n.level for n in nodes] == [1, 3]
    assert nodes[0].runs[0].text == "一级"


def test_heading_cap_six_and_over_cap_is_paragraph():
    """`#######` 不是合法标题级别，按普通段落处理，不静默丢弃。"""
    nodes = parse_markdown("####### 七级")
    assert nodes[0].kind == NodeKind.PARAGRAPH
    assert nodes[0].runs[0].text.startswith("#######")


def test_blank_line_splits_paragraphs():
    nodes = parse_markdown("第一段\n继续第一段\n\n第二段")
    assert _kinds(nodes) == [NodeKind.PARAGRAPH, NodeKind.PARAGRAPH]
    assert nodes[0].runs[0].text == "第一段 继续第一段"


def test_inline_marks_become_runs():
    nodes = parse_markdown("普通 **粗** 和 *斜* 和 `码`")
    texts = [r.text for r in nodes[0].runs]
    assert nodes[0].runs[1].bold is True
    assert nodes[0].runs[3].italic is True
    assert nodes[0].runs[5].code is True
    assert "粗" in texts and "斜" in texts and "码" in texts


def test_unordered_and_ordered_lists():
    nodes = parse_markdown("- 甲\n- 乙\n\n1. 一\n2. 二")
    lists = [n for n in nodes if n.kind == NodeKind.LIST]
    assert [l.ordered for l in lists] == [False, True]
    assert [i.text for i in lists[0].items] == ["甲", "乙"]
    assert [i.text for i in lists[1].items] == ["一", "二"]


def test_adjacent_lists_of_same_kind_merge():
    nodes = parse_markdown("- 甲\n\n一些话\n\n- 乙")
    assert _kinds(nodes) == [NodeKind.LIST, NodeKind.PARAGRAPH, NodeKind.LIST]


def test_empty_input_yields_no_nodes():
    assert parse_markdown("") == []
    assert parse_markdown("   \n\t\n") == []


def test_unclosed_emphasis_stays_literal():
    """`**未闭合` 不吞掉后半句，也不报错——按字面文本保留。"""
    nodes = parse_markdown("**未闭合 收尾")
    assert nodes[0].runs[0].text == "**未闭合 收尾"
