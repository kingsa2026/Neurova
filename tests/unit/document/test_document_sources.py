"""Markdown 子集 → 中间文档树（纯函数，不依赖 reportlab）。

首批子集见 spec §6：标题、段落、无序/有序列表、粗体/斜体/行内码。
渲染出口只有一条（document_pdf），所以本文件的断言只针对树形状，不针对版式。
"""

from neurova.document_model import NodeKind
from neurova.document_sources import parse_markdown


def _kinds(nodes):
    return [n.kind for n in nodes]


def test_headings_carry_level_and_styled_text():
    nodes = parse_markdown("# 一级\n\n### 三级").blocks
    assert _kinds(nodes) == [NodeKind.HEADING, NodeKind.HEADING]
    assert [n.level for n in nodes] == [1, 3]
    assert nodes[0].runs[0].text == "一级"


def test_heading_cap_six_and_over_cap_is_paragraph():
    """`#######` 不是合法标题级别，按普通段落处理，不静默丢弃。"""
    nodes = parse_markdown("####### 七级").blocks
    assert nodes[0].kind == NodeKind.PARAGRAPH
    assert nodes[0].runs[0].text.startswith("#######")


def test_blank_line_splits_paragraphs():
    nodes = parse_markdown("第一段\n继续第一段\n\n第二段").blocks
    assert _kinds(nodes) == [NodeKind.PARAGRAPH, NodeKind.PARAGRAPH]
    assert nodes[0].runs[0].text == "第一段 继续第一段"


def test_inline_marks_become_runs():
    nodes = parse_markdown("普通 **粗** 和 *斜* 和 `码`").blocks
    texts = [r.text for r in nodes[0].runs]
    assert nodes[0].runs[1].bold is True
    assert nodes[0].runs[3].italic is True
    assert nodes[0].runs[5].code is True
    assert "粗" in texts and "斜" in texts and "码" in texts


def test_unordered_and_ordered_lists():
    nodes = parse_markdown("- 甲\n- 乙\n\n1. 一\n2. 二").blocks
    lists = [n for n in nodes if n.kind == NodeKind.LIST]
    assert [l.ordered for l in lists] == [False, True]
    assert [i.text for i in lists[0].items] == ["甲", "乙"]
    assert [i.text for i in lists[1].items] == ["一", "二"]


def test_adjacent_lists_of_same_kind_merge():
    nodes = parse_markdown("- 甲\n\n一些话\n\n- 乙").blocks
    assert _kinds(nodes) == [NodeKind.LIST, NodeKind.PARAGRAPH, NodeKind.LIST]


def test_empty_input_yields_no_nodes():
    assert parse_markdown("").blocks == []
    assert parse_markdown("").warnings == []
    assert parse_markdown("   \n\t\n").blocks == []


def test_unclosed_emphasis_stays_literal():
    """`**未闭合` 不吞掉后半句，也不报错——按字面文本保留。"""
    nodes = parse_markdown("**未闭合 收尾").blocks
    assert nodes[0].runs[0].text == "**未闭合 收尾"


# ── 表格（工单 002）────────────────────────────────────────────


def test_pipe_table_becomes_table_node():
    result = parse_markdown("| 名称 | 数量 |\n|---|---|\n| 甲 | 2 |\n| 乙 | 3 |")
    table = result.blocks[0]
    assert table.kind == NodeKind.TABLE
    assert [c.text for c in table.header] == ["名称", "数量"]
    assert [[c.text for c in row] for row in table.rows] == [["甲", "2"], ["乙", "3"]]


def test_alignment_row_is_not_a_data_row():
    result = parse_markdown("| a | b |\n|:--|--:|\n| 1 | 2 |")
    table = result.blocks[0]
    assert table.align == ["left", "right"]
    assert len(table.rows) == 1, "对齐行不得变成数据行"


def test_malformed_table_falls_back_to_paragraph_with_warning():
    """缺分隔行的"伪表格"按段落原样呈现，并说明为什么不是表格——
    静默降级会让作者以为表格生效了。"""
    result = parse_markdown("| a | b |\n| 1 | 2 |")
    assert result.blocks[0].kind == NodeKind.PARAGRAPH
    assert any("表格" in w for w in result.warnings)
    assert "a" in result.blocks[0].text, "降级不得丢内容"


def test_ragged_rows_are_padded_and_reported():
    result = parse_markdown("| a | b | c |\n|---|---|---|\n| 1 |")
    table = result.blocks[0]
    assert len(table.rows[0]) == 3
    assert any("列" in w for w in result.warnings)


# ── 图片（工单 003）────────────────────────────────────────────


def test_image_reference_becomes_image_node():
    result = parse_markdown("![图一](assets/a.png)")
    image = result.blocks[0]
    assert image.kind == NodeKind.IMAGE
    assert image.src == "assets/a.png" and image.alt == "图一"


def test_image_inside_paragraph_text_stays_split():
    """正文中间的 ![](...) 只识整行独立图片，混排时保持文字原样（不静默吞图记号）。"""
    result = parse_markdown("见下图 ![图一](a.png) 如上")
    assert result.blocks[0].kind == NodeKind.PARAGRAPH
    assert "![图一](a.png)" in result.blocks[0].text


