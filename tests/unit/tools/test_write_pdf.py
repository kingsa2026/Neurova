"""write_pdf 工具端到端（工单 001 示踪弹）

覆盖：出件落产物目录、响应字段、输入校验、渲染库缺席、降级可读、注册三处齐全。
`path` 分支属工单 006，本文件不涉及。
"""

import re

import pytest

from neurova.document_pdf import RenderUnavailable


def _make_executor(workspace=None):
    from unittest.mock import Mock

    from neurova.tool_executor import ToolExecutor

    agent = Mock()
    agent.workspace_path = str(workspace) if workspace else None
    return ToolExecutor(agent)


PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    """产物目录可注入：不 patch 就会写进真实 data/generations（本仓踩过 6773 个一次性文件）。"""
    import neurova.llm.generators.runtime as runtime

    target = tmp_path / "generations"
    monkeypatch.setattr(runtime, "GENERATION_OUTPUT_DIR", target)
    return target


@pytest.mark.asyncio
async def test_write_pdf_lands_in_generations_and_reports_url(out_dir):
    result = await _make_executor()._execute_write_pdf(
        {"content": "# 月报\n\n这是正文。", "title": "月报"}
    )
    assert "error" not in result, result
    name = result["file_name"]
    assert re.fullmatch(r"[A-Za-z0-9._-]+", name), f"文件名过不了产物路由白名单: {name}"
    assert result["download_url"] == f"/api/v1/generation/files/{name}"
    assert (out_dir / name).read_bytes()[:5] == b"%PDF-"
    assert result["pages"] >= 1 and result["bytes"] > 0


@pytest.mark.asyncio
async def test_cjk_title_does_not_leak_into_file_name(out_dir):
    """产物路由有文件名白名单，中文标题只能进 PDF 元数据，不能进文件名。"""
    result = await _make_executor()._execute_write_pdf({"content": "正文", "title": "季度总结报告"})
    assert result["file_name"].isascii()


@pytest.mark.asyncio
async def test_both_or_neither_input_is_refused(out_dir):
    """两条入口必须恰好走一条——同给时不猜优先级，都不给时不出件。"""
    exe = _make_executor()
    both = await exe._execute_write_pdf({"content": "甲", "content_html": "<p>乙</p>"})
    neither = await exe._execute_write_pdf({"title": "只有标题"})
    assert "error" in both and "二选一" in both["error"]
    assert "error" in neither


@pytest.mark.asyncio
async def test_html_entry_renders_and_reports_dropped_tags(out_dir):
    result = await _make_executor()._execute_write_pdf(
        {"content_html": "<h1>标题</h1><p>正文</p><script>alert(1)</script>"}
    )
    assert "error" not in result, result
    assert result["pages"] >= 1
    assert any("script" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_blank_content_produces_no_file(out_dir):
    result = await _make_executor()._execute_write_pdf({"content": "   \n\t "})
    assert "error" in result
    assert list(out_dir.glob("*.pdf")) == []


@pytest.mark.asyncio
async def test_missing_render_library_is_structured_error(monkeypatch):
    import neurova.tool_executor as te

    def _boom(*a, **k):
        raise RenderUnavailable("reportlab 未安装")

    monkeypatch.setattr(te, "render_document", _boom)
    result = await _make_executor()._execute_write_pdf({"content": "正文"})
    assert "error" in result and "reportlab" in result["error"]


@pytest.mark.asyncio
async def test_cid_fallback_warning_reaches_the_response(monkeypatch, out_dir):
    import neurova.document_pdf as dpdf

    monkeypatch.setattr(dpdf, "find_cjk_font", lambda: None)
    result = await _make_executor()._execute_write_pdf({"content": "正文"})
    assert result["font"]["mode"] == "cid"
    assert any("方框" in w for w in result["warnings"])


def test_tool_is_registered_everywhere_a_tool_must_be():
    """schema、分派表、权限归类三处齐全——少一处就是"模型看不见"或"权限面不认识"。"""
    from neurova.builtin_tools import get_builtin_tool_params
    from neurova.skills.permissions import _CATEGORY_TOOLS
    from neurova.tool_executor import ToolExecutor

    assert get_builtin_tool_params("write_pdf") is not None
    assert ToolExecutor._builtin_dispatch["write_pdf"] == "_execute_write_pdf"
    assert "write_pdf" in _CATEGORY_TOOLS["file"]


# ── 图片内嵌（工单 003）────────────────────────────────────────


@pytest.mark.asyncio
async def test_workspace_relative_image_embeds_cleanly(out_dir, tmp_path):
    (tmp_path / "pic.png").write_bytes(PNG_1PX)
    result = await _make_executor(tmp_path)._execute_write_pdf(
        {"content": "# 报告\n\n![图一](pic.png)"}
    )
    assert "error" not in result, result
    assert result["warnings"] == [] or not any("图" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_remote_image_goes_through_the_one_egress_channel(out_dir, tmp_path, monkeypatch):
    """远程图必须走 persist_media（它带全局出网 SSRF 校验），不在别处再开一条下载路。"""
    import neurova.llm.generators.runtime as runtime

    calls = []

    async def fake_persist(url_or_data, kind, task_id, index, out_dir=None):
        calls.append(url_or_data)
        target = tmp_path / f"remote{index}.png"
        target.write_bytes(PNG_1PX)
        return str(target)

    monkeypatch.setattr(runtime, "persist_media", fake_persist)
    result = await _make_executor(tmp_path)._execute_write_pdf(
        {"content": "![远端](https://example.invalid/a.png)"}
    )
    assert calls == ["https://example.invalid/a.png"]
    assert not any("跳过" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_unresolvable_image_degrades_to_alt_text(out_dir, tmp_path):
    result = await _make_executor(tmp_path)._execute_write_pdf({"content": "![缺失的图](nope.png)"})
    assert "error" not in result, "图丢了不是整件失败的理由"
    assert any("缺失的图" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_image_count_is_bounded(out_dir, tmp_path):
    for i in range(21):
        (tmp_path / f"p{i}.png").write_bytes(PNG_1PX)
    content = "".join(f"![图{i}](p{i}.png)\n\n" for i in range(21))
    result = await _make_executor(tmp_path)._execute_write_pdf({"content": content})
    assert any("上限" in w or "20" in w for w in result["warnings"]), "超限必须报告，不得静默丢图"
