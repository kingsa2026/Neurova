"""中间树 → PDF 字节（reportlab 出口，唯一 import 处）与字体决策。

字体决策单独可测：本仓的纪律是"无中文字体时不得伪装成功"（见 core/ffmpeg 烧录
同款教训），所以降级必须落在可读回的响应字段上，而不是只写在日志里。
"""

import pytest

from neurova.document_model import Block, DocSettings, NodeKind
from neurova.document_pdf import render_document, resolve_cjk_font
from neurova.document_sources import parse_markdown


def _blocks(md: str = "# 标题\n\n正文一段\n\n- 甲\n- 乙"):
    return parse_markdown(md).blocks


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

        runs = parse_markdown("甲 <b> & **粗**").blocks[0].runs
        assert runs_to_markup(runs) == "甲 &lt;b&gt; &amp; <b>粗</b>"

    def test_code_run_uses_monospace_face(self):
        from neurova.document_pdf import runs_to_markup

        runs = parse_markdown("`x=1`").blocks[0].runs
        assert runs_to_markup(runs) == '<font face="Courier">x=1</font>'


class TestTable:
    """表格断言一律用 ASCII 内容：无中文字体的环境（CI）走 CID 路径，
    那里抽取不可靠，用它当判据会造出假绿或假红。"""

    @staticmethod
    def _extract_pages(pdf: bytes):
        import io

        from pypdf import PdfReader

        return [(p.extract_text() or "").replace(" ", "") for p in PdfReader(io.BytesIO(pdf)).pages]

    def test_header_repeats_on_every_page(self):
        md = "| ITEM | QTY |\n|---|---|\n" + "".join(f"| row{i} | {i} |\n" for i in range(60))
        out = render_document(_blocks(md), DocSettings())
        pages = self._extract_pages(out["pdf"])
        assert len(pages) >= 2, "60 行表应当跨页"
        assert all("ITEM" in page and "QTY" in page for page in pages), "跨页必须重复表头"

    def test_unbreakable_overlong_cell_is_truncated_and_reported(self):
        giant = "x" * 200
        out = render_document(_blocks(f"| A | B |\n|---|---|\n| {giant} | 短 |"), DocSettings())
        assert out["pages"] >= 1
        assert any("第 1 列" in w for w in out["warnings"]), "截断必须点名到列"

    def test_wide_but_wrappable_table_warns_nothing(self):
        md = "| alpha | beta | gamma | delta |\n|---|---|---|---|\n" + "| 一 | 二 | 三 | 四 |\n"
        out = render_document(_blocks(md), DocSettings())
        assert not any("列" in w for w in out["warnings"]), "能折行的宽表不该报截断"


PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


class TestImage:
    def _doc(self, src):
        return _blocks(f"![图一]({src})")

    def test_local_image_is_embedded(self, tmp_path):
        pic = tmp_path / "a.png"
        pic.write_bytes(PNG_1PX)
        out = render_document(self._doc(str(pic)), DocSettings())
        assert out["pages"] >= 1
        assert not any("图" in w for w in out["warnings"])

    def test_missing_image_skips_with_warning_and_still_renders(self, tmp_path):
        """渲染层也要能自守：文件在解析后被人删掉时，出件不得整体失败。"""
        out = render_document(self._doc(str(tmp_path / "gone.png")), DocSettings())
        assert out["pages"] >= 1
        assert any("跳过" in w for w in out["warnings"])
