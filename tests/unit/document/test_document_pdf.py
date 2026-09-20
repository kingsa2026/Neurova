"""中间树 → PDF 字节（reportlab 出口，唯一 import 处）与字体决策。

字体决策单独可测：本仓的纪律是"无中文字体时不得伪装成功"（见 core/ffmpeg 烧录
同款教训），所以降级必须落在可读回的响应字段上，而不是只写在日志里。
"""

import pytest

from neurova.document_model import Block, DocSettings, NodeKind
from neurova.document_pdf import render_document, resolve_cjk_font
from neurova.document_sources import parse_markdown


def _blocks(md: str = "# 标题\n\n正文一段\n\n- 甲\n- 乙"):
    return parse_markdown(md)


class TestFontDecision:
    def test_prefers_real_ttf_when_available(self, monkeypatch, tmp_path):
        fake = tmp_path / "fake-cjk.ttf"
        fake.write_bytes(b"x")
        monkeypatch.setattr("neurova.document_pdf.find_cjk_font", lambda: fake)
        font = resolve_cjk_font(None)
        assert font["mode"] == "embedded" and font["path"] == str(fake)

    def test_falls_back_to_cid_and_says_so(self, monkeypatch):
        monkeypatch.setattr("neurova.document_pdf.find_cjk_font", lambda: None)
        font = resolve_cjk_font(None)
        assert font["mode"] == "cid"
        assert font["embeds_font"] is False, "CID 路径不嵌字体，这是阅读器侧 substitutes 的前提"

    def test_explicit_font_wins(self, monkeypatch, tmp_path):
        chosen = tmp_path / "chosen.ttf"
        chosen.write_bytes(b"x")
        monkeypatch.setattr("neurova.document_pdf.find_cjk_font", lambda: None)
        assert resolve_cjk_font(str(chosen))["path"] == str(chosen)

    def test_explicit_font_missing_is_error_not_fallback(self, monkeypatch, tmp_path):
        """指名要某字体而文件不在 → 报错，不悄悄换字体（换字体会让调用方以为生效了）。"""
        monkeypatch.setattr("neurova.document_pdf.find_cjk_font", lambda: None)
        with pytest.raises(FileNotFoundError):
            resolve_cjk_font(str(tmp_path / "absent.ttf"))


class TestRender:
    def test_renders_valid_pdf_with_page_count(self):
        out = render_document(_blocks(), DocSettings())
        assert out["pdf"][:5] == b"%PDF-"
        assert out["pages"] >= 1
        assert isinstance(out["warnings"], list)

    def test_no_font_available_reports_cid_and_warning(self, monkeypatch):
        monkeypatch.setattr("neurova.document_pdf.find_cjk_font", lambda: None)
        out = render_document(_blocks(), DocSettings(title="中文标题"))
        assert out["font"]["mode"] == "cid"
        assert any("方框" in w for w in out["warnings"]), "降级必须在响应里可读，不能只进日志"

    @pytest.mark.skipif(
        __import__("neurova.core.ffmpeg", fromlist=["find_cjk_font"]).find_cjk_font() is None,
        reason="本机无中文字体，嵌入字体的可读性断言不成立（CI 即此态）",
    )
    def test_embedded_font_round_trips_cjk_text(self):
        out = render_document(_blocks("# 汉字标题\n\n汉字正文可抽取"), DocSettings())
        assert out["font"]["mode"] == "embedded"

        import io

        from pypdf import PdfReader

        text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(out["pdf"])).pages)
        assert "汉字正文可抽取" in text.replace(" ", "")

    def test_empty_blocks_is_refused_not_rendered(self):
        """空输入不出空白 PDF（错误由工具层转成 error 响应）。"""
        with pytest.raises(ValueError):
            render_document([], DocSettings())

    def test_runs_to_markup_escapes_then_marks(self):
        """runs → Paragraph 标记：先转义再上样式（正文里的 `<b>` 不得变成真标记）。"""
        from neurova.document_pdf import runs_to_markup

        runs = parse_markdown("甲 <b> & **粗**")[0].runs
        assert runs_to_markup(runs) == "甲 &lt;b&gt; &amp; <b>粗</b>"

    def test_code_run_uses_monospace_face(self):
        from neurova.document_pdf import runs_to_markup

        runs = parse_markdown("`x=1`")[0].runs
        assert runs_to_markup(runs) == '<font face="Courier">x=1</font>'
