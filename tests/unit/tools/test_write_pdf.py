"""write_pdf 工具端到端（工单 001 示踪弹）

覆盖：出件落产物目录、响应字段、输入校验、渲染库缺席、降级可读、注册三处齐全。
`path` 分支属工单 006，本文件不涉及。
"""

import re

import pytest

from neurova.document_pdf import RenderUnavailable


def _make_executor():
    from unittest.mock import Mock

    from neurova.tool_executor import ToolExecutor

    agent = Mock()
    agent.workspace_path = None
    return ToolExecutor(agent)


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
async def test_missing_content_is_refused(out_dir):
    """001 只有 Markdown 入口；`content_html` 与二选一规则在工单 004 同批加入
    （schema 与执行体必须同步长参数，否则撞 test_tool_schema_contract 的漂移契约）。"""
    result = await _make_executor()._execute_write_pdf({"title": "只有标题"})
    assert "error" in result


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
