"""脚本 LOGO 对齐回归测试。

历史问题（2026-08-31 实测）：LOGO_ART 的 subtitle 行用 `{subtitle:^51}` 格式化，
`^51` 按字符（码点）数居中，而中文小标题（如 "智能无限，协作无间"）每个字
在终端占 2 列——51 个码点的填充实际渲染出 60 列，整行比边框行（73 列）
宽 2 列，导致右侧竖线错位。

断言标准：LOGO 每一行的视觉宽度（CJK/全角按 2 列计）必须相同 = 73。
"""

import contextlib
import io
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 控制台运行时 CJK 字符会被 ANSI 颜色码包裹，但解析时按无颜色处理
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

FRAME_WIDTH = 73  # LOGO_ART 边界行（码点=视觉列，全单宽）的固定宽度


def _visual_width(text: str) -> int:
    """UTF-8 字符的终端显示宽度：CJK/全角按 2 列，其余按 1 列。"""
    width = 0
    for ch in text:
        cp = ord(ch)
        if (
            0x1100 <= cp <= 0x115F
            or 0x2E80 <= cp <= 0x303E
            or 0x3041 <= cp <= 0x33FF
            or 0x3400 <= cp <= 0x4DBF
            or 0x4E00 <= cp <= 0x9FFF
            or 0xA000 <= cp <= 0xA4CF
            or 0xAC00 <= cp <= 0xD7A3
            or 0xF900 <= cp <= 0xFAFF
            or 0xFE30 <= cp <= 0xFE4F
            or 0xFF00 <= cp <= 0xFF60
            or 0xFFE0 <= cp <= 0xFFE6
            or 0x20000 <= cp <= 0x2FFFD
            or 0x30000 <= cp <= 0x3FFFD
        ):
            width += 2
        else:
            width += 1
    return width


def _render_logo_lines(**kwargs) -> list[str]:
    """调用 scripts.common.print_logo 并返回剥离 ANSI 后的输出行。"""
    from scripts.common import print_logo

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_logo(**kwargs)
    return [l for l in ANSI_RE.sub("", buf.getvalue()).splitlines() if l.strip()]


class TestLogoAlignment(unittest.TestCase):
    """所有 LOGO 行的视觉宽度必须一致（右侧竖线对齐）。"""

    def test_frame_lines_are_single_width(self) -> None:
        """无小标题时，各行的视觉宽度应完全相同。"""
        lines = _render_logo_lines()
        assert len(lines) >= 3, "LOGO 至少应输出 3 行"
        widths = [_visual_width(l) for l in lines]
        self.assertEqual(len(set(widths)), 1, f"LOGO 行宽不一致: {widths}")
        self.assertEqual(widths[0], FRAME_WIDTH)

    def test_cjk_subtitle_line_aligned(self) -> None:
        """中文小标题行（双宽字符）的视觉宽度必须与其他行一致。"""
        lines = _render_logo_lines(subtitle="智能无限，协作无间")
        widths = [_visual_width(l) for l in lines]
        self.assertEqual(len(set(widths)), 1, f"中文小标题未对齐: {widths}")
        self.assertEqual(widths[0], FRAME_WIDTH)

    def test_double_subtitle_lines_aligned(self) -> None:
        """双行小标题的两行也必须与边框对齐。"""
        lines = _render_logo_lines(subtitle="智能无限，协作无间", double_subtitle="一键启动脚本")
        widths = [_visual_width(l) for l in lines]
        self.assertEqual(len(set(widths)), 1, f"双行小标题未对齐: {widths}")
        self.assertEqual(widths[0], FRAME_WIDTH)

    def test_ascii_subtitle_lines_aligned(self) -> None:
        """纯 ASCII 小标题同样不得错位（原 `^51` 在 ASCII 下偏窄 7 列）。"""
        lines = _render_logo_lines(subtitle="Neurova Starter")
        widths = [_visual_width(l) for l in lines]
        self.assertEqual(len(set(widths)), 1, f"ASCII 小标题未对齐: {widths}")
        self.assertEqual(widths[0], FRAME_WIDTH)


if __name__ == "__main__":
    unittest.main()
