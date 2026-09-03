"""cli.py REPL 界面（Hermes 对齐 · 蓝色系）渲染契约测试。

锁定界面元素：
- 用户消息回显: `❯ 你` 标签 + 正文（primary 蓝）
- 助手流式: 首次 chunk 带 `● ` 前缀（accent 天蓝），后续 chunk 纯文本
- 工具调用: `● [工具] 名称 · 参数摘要`；工具结果: `↳ 摘要`（dim 缩进）
- 推理: 聚合成单行 `▸ 思考 · 摘要`（不再逐 token 打标签）
- 欢迎屏状态行: ✓/○/! 符号行；帮助提示 dim 行；prompt 为 `❯ `
- 回合收尾: `· 模型: x · 会话: y` 的状态行
- 渲染函数返回 rich Text（.plain 断言内容，颜色经 force_terminal 渲染断言 ANSI）
"""

import io
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FAKE_TOKEN = os.environ.get("TEST_FAKE_ACCESS_TOKEN", "fake-token-for-tests")


def _render_to_ansi(text) -> str:
    """把 rich Text 渲染成带 ANSI 的字符串（truecolor/force, 挂 REPL_THEME）。"""
    import cli as repl_mod
    from rich.console import Console
    from rich.theme import Theme

    buf = io.StringIO()
    c = Console(file=buf, force_terminal=True, color_system="truecolor", theme=Theme(repl_mod.REPL_THEME))
    c.print(text)
    return buf.getvalue()


class TestRenderHelpers(unittest.TestCase):
    def test_ansi_colors_only_when_enabled(self):
        import cli

        self.assertEqual(cli.ansi("OK", "ok", enabled=True), "\033[38;2;74;222;128mOK\033[0m")
        # 非 tty / NO_COLOR 时透明
        self.assertEqual(cli.ansi("OK", "ok", enabled=False), "OK")

    def test_user_message_has_blue_you_label(self):
        import cli

        out = cli.render_user_message("你好，世界")
        self.assertIn("❯ 你", out.plain)
        self.assertIn("你好，世界", out.plain)
        # 标签行用 primary 蓝
        ansi_out = _render_to_ansi(out)
        self.assertIn("\033[38;2;91;155;255m❯ 你\033[0m", ansi_out)

    def test_tool_call_line_bullet_and_args(self):
        import cli

        out = cli.render_tool_call("calculator", "1 + 1")
        self.assertIn("● [工具] calculator", out.plain)
        self.assertIn("1 + 1", out.plain)

    def test_tool_result_preview_indented(self):
        import cli

        out = cli.render_tool_result("结果: 2")
        self.assertIn("↳ 结果: 2", out.plain)

    def test_reasoning_single_line_arrow(self):
        import cli

        out = cli.render_reasoning("需要先解析意图")
        self.assertIn("▸ 思考 · 需要先解析意图", out.plain)

    def test_reasoning_long_text_truncated(self):
        import cli

        out = cli.render_reasoning("x" * 500)
        self.assertLessEqual(len(out.plain.split(" · ", 1)[1]), 210)
        self.assertIn("…", out.plain)

    def test_welcome_badge_line(self):
        import cli

        self.assertIn("✓ 后端连接成功", cli.render_welcome_icon_line("✓", "后端连接成功").plain)
        self.assertIn("✕ 无法连接", cli.render_welcome_icon_line("✕", "无法连接", style="err").plain)

    def test_welcome_panel_rounded_with_title(self):
        """欢迎屏内容包进双线 panel,标题在左上（Hermes 窗口范式 + logo 同款线框）。"""
        import cli
        from rich import box

        panel = cli.render_welcome_panel("✓ 后端连接成功", "› 输入 /help 查看命令")
        self.assertIsNotNone(panel.title)
        self.assertIn("智星", panel.title.plain)
        self.assertIn("Neurova", panel.title.plain)
        # 双线框 (DOUBLE, 与 print_logo 同款 ╔═╗║╚═╝)
        self.assertIs(panel.box, box.DOUBLE)

    def test_status_bar_hermes_style(self):
        """回合收尾状态栏: `⚑ 模型 | 轮次 · 会话 | 用时`（Hermes 底栏范式）。"""
        import cli

        out = cli.render_status_bar("deepseek-v4-pro", "a1b2c3d4", turn=3, elapsed=4.2)
        self.assertIn("⚑", out.plain)
        self.assertIn("deepseek-v4-pro", out.plain)
        self.assertIn("a1b2c3d4", out.plain)
        self.assertIn("第 3 轮", out.plain)
        self.assertIn("4.2s", out.plain)

    def test_meta_line_model_session(self):
        import cli

        out = cli.render_status_bar("deepseek-v4-pro", "s1a2b3", turn=1, elapsed=0.3)
        self.assertIn("deepseek-v4-pro", out.plain)
        self.assertIn("s1a2b3", out.plain)

    def test_turn_frame_top_opens_double_box(self):
        """回合顶框: ╔ 开头、用户消息在框内、双线样式。"""
        import cli

        top = cli.render_turn_frame_top("你好，世界", limit=60, color=True)
        self.assertTrue(top.startswith("╔═"))
        self.assertIn("❯ 你", top)
        self.assertIn("你好，世界", top)

    def test_turn_frame_bottom_double_box(self):
        import cli

        bottom = cli.render_turn_frame_bottom(60)
        self.assertTrue(bottom.startswith("╚"))
        self.assertTrue(bottom.endswith("╝"))

    def test_stream_chunks_wrapped_in_frame(self):
        """流式 chunk 在回合帧内输出, 每行都有 ║ 竖线包裹。"""
        import cli

        buf = io.StringIO()
        console = __import__("rich").console.Console(file=buf, force_terminal=True, color_system=None, width=80)
        c = cli.NeurovaCLI(base_url="http://test", console=console)
        c._draw_color = False
        c.token = FAKE_TOKEN
        c._begin_turn("你好")
        c._render_stream_event("chunk", "第一段")
        c._render_stream_event("chunk", "第二段\n换行后")
        c._end_turn()
        out = buf.getvalue().splitlines()
        # 第一行是顶框, 最后一行是底框, 中间内容行均有竖线
        self.assertTrue(out[0].startswith("╔"))
        self.assertTrue(out[-1].startswith("╚"))
        for line in out[1:-1]:
            self.assertTrue(line.startswith("║ ") or line.startswith("║"), f"帧内行缺竖线: {line!r}")
        self.assertIn("第一段", buf.getvalue())
        self.assertIn("换行后", buf.getvalue())

    def test_frame_stream_auto_wraps_long_lines(self):
        """超过帧宽的流式行自动折行, 折后仍带竖线。"""
        import cli

        buf = io.StringIO()
        console = __import__("rich").console.Console(file=buf, force_terminal=True, color_system=None, width=50)
        c = cli.NeurovaCLI(base_url="http://test", console=console)
        c._draw_color = False
        c.token = FAKE_TOKEN
        c._begin_turn("x")
        c._render_stream_event("chunk", "很长的回复" * 20)
        c._end_turn()
        lines = buf.getvalue().splitlines()
        self.assertGreaterEqual(len(lines), 4, "长文本应折行为多行")
        for line in lines[1:-1]:
            self.assertLessEqual(len(line), 50, f"折行未限制宽度: {len(line)} {line!r}")

    def test_status_bar_after_frame_close(self):
        """回合结束: 底框之后才是 ⚑ 状态栏（框外）。"""
        import cli

        buf = io.StringIO()
        console = __import__("rich").console.Console(file=buf, force_terminal=True, color_system=None, width=80)
        cli_obj = cli.NeurovaCLI(base_url="http://test", console=console)
        cli_obj._draw_color = False
        cli_obj.token = FAKE_TOKEN
        cli_obj.current_agent_id = "default"
        cli_obj.current_session_id = "s1"
        cli_obj.send_chat = lambda *a, **k: "回复内容"
        cli_obj._chat_message("测试")
        out = buf.getvalue()
        self.assertIn("╚", out)
        # 状态栏在底框之后
        self.assertLess(out.rfind("╚"), out.rfind("⚑"))

    def test_prompt_text(self):
        import cli

        self.assertEqual(cli.prompt_text(enabled=False), "❯ ")
        self.assertIn("\033[38;2;56;189;248m❯", cli.prompt_text(enabled=True))


class TestStreamRendering(unittest.TestCase):
    def _mk_cli(self, width: int = 80):
        from cli import NeurovaCLI

        buf = io.StringIO()
        console = __import__("rich").console.Console(file=buf, force_terminal=True, color_system=None, width=width)
        cli = NeurovaCLI(base_url="http://test", console=console)
        cli._draw_color = False
        cli.token = FAKE_TOKEN
        return cli, buf

    def test_chunk_first_looks_marked_then_plain(self):
        cli, buf = self._mk_cli()
        cli._begin_turn("hi")
        cli._render_stream_event("chunk", "第一段")
        cli._render_stream_event("chunk", "第二段")
        cli._end_turn()
        out = buf.getvalue()
        self.assertEqual(out.count("● "), 1, f"● 前缀只应出现在首个 chunk: {out!r}")
        self.assertIn("第一段", out)
        self.assertIn("第二段", out)

    def test_tool_call_rendered_with_bullet(self):
        cli, buf = self._mk_cli()
        cli._begin_turn("hi")
        cli._render_stream_event("tool_call", {"name": "calculator", "arguments": "1+1"})
        cli._end_turn()
        self.assertIn("● [工具] calculator", buf.getvalue())

    def test_tool_result_indented(self):
        cli, buf = self._mk_cli()
        cli._begin_turn("hi")
        cli._render_stream_event("tool_result", {"content": '{"ok": true}'})
        cli._end_turn()
        self.assertIn("↳", buf.getvalue())

    def test_approval_warn_line(self):
        cli, buf = self._mk_cli()
        cli._begin_turn("hi")
        cli._render_stream_event("approval_required", {"approval_id": "a1", "tool_name": "shell"})
        cli._end_turn()
        out = buf.getvalue()
        self.assertIn("! [待审批] shell", out)

    def test_reasoning_aggregated_once(self):
        cli, buf = self._mk_cli()
        cli._begin_turn("hi")
        for piece in ("We", " need", " to respond"):
            cli._render_stream_event("reasoning", piece)
        cli._render_stream_event("chunk", "你好")
        cli._end_turn()
        out = buf.getvalue()
        self.assertEqual(out.count("▸ 思考"), 1, f"reasoning 应聚合为单行: {out!r}")
        self.assertIn("We need to respond", out)


class TestChatMessageExperience(unittest.TestCase):
    def _mk_cli(self):
        from cli import NeurovaCLI

        buf = io.StringIO()
        console = __import__("rich").console.Console(file=buf, force_terminal=True, color_system=None)
        cli = NeurovaCLI(base_url="http://test", console=console)
        cli._draw_color = False
        cli.token = FAKE_TOKEN
        cli.current_agent_id = "default"
        cli.current_session_id = "s1"
        # 保留 _render_stream_event 走真实文件缓冲，仅替换 send_chat
        cli.send_chat = lambda *a, **k: "回复内容"
        return cli, buf

    def test_message_echoes_user_then_meta_line(self):
        cli, buf = self._mk_cli()
        cli._chat_message("测试消息")
        out = buf.getvalue()
        self.assertIn("❯ 你", out)
        self.assertIn("测试消息", out)
        # Hermes 底栏: ⚑ 模型 | 轮次 · 会话 | 用时
        self.assertIn("⚑", out)
        self.assertIn("第 1 轮", out)
        self.assertIn("s1", out)

    def test_reply_printed_after_marker_reset(self):
        cli, buf = self._mk_cli()
        cli._begin_turn("首轮")
        cli._render_stream_event("chunk", "首句")
        cli._end_turn()
        cli._chat_message("再来")  # 新回合, marker 应复位
        self.assertEqual(buf.getvalue().count("● "), 1)


if __name__ == "__main__":
    unittest.main()
