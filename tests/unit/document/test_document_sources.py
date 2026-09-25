"""Markdown 子集 → 中间文档树（纯函数，不依赖 reportlab）。

首批子集见 spec §6：标题、段落、无序/有序列表、粗体/斜体/行内码。
渲染出口只有一条（document_pdf），所以本文件的断言只针对树形状，不针对版式。
"""

from neurova.document_model import NodeKind
from neurova.document_sources import parse_html, parse_markdown


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


def test_divider_line_becomes_divider_node():
    """spec §6 承诺的分隔线：`---` 不再被当成正段落印出来。"""
    result = parse_markdown("上\n\n---\n\n下")
    assert [n.kind for n in result.blocks] == [
        NodeKind.PARAGRAPH,
        NodeKind.DIVIDER,
        NodeKind.PARAGRAPH,
    ]


# ── HTML 子集入口（工单 004）───────────────────────────────────


def test_html_headings_paragraph_and_list():
    result = parse_html("<h2>小节</h2><p>正文</p><ul><li>甲</li><li>乙</li></ul>")
    assert [n.kind for n in result.blocks] == [NodeKind.HEADING, NodeKind.PARAGRAPH, NodeKind.LIST]
    assert result.blocks[0].level == 2
    assert [i.text for i in result.blocks[2].items] == ["甲", "乙"]


def test_html_inline_styles_map_to_runs():
    result = parse_html("<p>前 <strong>粗</strong> 后 <em>斜</em></p>")
    runs = result.blocks[0].runs
    assert [r.text for r in runs if r.bold] == ["粗"]
    assert [r.text for r in runs if r.italic] == ["斜"]


def test_html_table_and_divider():
    result = parse_html("<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table><hr>")
    assert result.blocks[0].kind == NodeKind.TABLE
    assert [c.text for c in result.blocks[0].header] == ["A", "B"]
    assert result.blocks[1].kind == NodeKind.DIVIDER


def test_script_and_style_dropped_and_reported():
    """脚本/样式不进 PDF，也不能静默消失：丢的东西必须点名。"""
    result = parse_html("<p>正文</p><script>alert(1)</script><style>p{}</style>")
    assert [n.text for n in result.blocks] == ["正文"]
    assert any("script" in w for w in result.warnings)
    assert any("style" in w for w in result.warnings)


def test_link_href_is_not_carried_into_document():
    result = parse_html('<p>看 <a href="https://example.invalid">这里</a></p>')
    assert result.blocks[0].text == "看 这里"
    assert not any("example.invalid" in (r.text if hasattr(r, "text") else "") for n in result.blocks for r in n.runs)


def test_unclosed_and_nested_tags_do_not_crash():
    result = parse_html("<p>未闭合 <b>加粗<div>段落")
    assert result.blocks and "未闭合" in result.blocks[0].text


def test_html_and_markdown_agree_on_normalized_text():
    """两个入口汇入同一棵树：同内容的归一化文本必须一致（否则两条路会长出两套行为）。"""
    md = parse_markdown("# 标题\n\n正文一段\n\n- 甲\n- 乙")
    html = parse_html("<h1>标题</h1><p>正文一段</p><ul><li>甲</li><li>乙</li></ul>")
    assert [b.text for b in md.blocks] == [b.text for b in html.blocks]



