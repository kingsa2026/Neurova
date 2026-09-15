# -*- coding: utf-8 -*-
"""A5：FFmpeg 字幕烧录支撑件（core/ffmpeg 扩展）。

契约（台账 A5，pf1 字体教训 + ffmpeg b6.0 Live 实测转义矩阵）：
- escape_subtitles_path：反斜杠→正斜杠 + 冒号转义为 \:（filter 层以未转义 :
  分参数，盘符 E: 截断致假 Invalid argument）；单引号包裹保空格；
  含单引号的路径直接拒绝（ValueError）——诚实拒烧而非拼出错误 filter。
- has_cjk_font：无中文字体时烧录只会得到方框（假成功），必须先探测；
  探测失败 → 调用方降级不烧录并 warning（数据侧 SRT 仍产出）。
- burn_subtitles：`-i in -vf subtitles=<esc> -c:a copy out`；
  返回 (ok, err)，失败不抛（调用方回退无字幕成片）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from neurova.core import ffmpeg as ff


class TestEscapeSubtitlesPath:
    def test_backslash_to_slash_and_colon_escaped(self):
        # filter 层以未转义 ':' 分参数：盘符冒号必须 `\:`（Live 实测假 Invalid argument 根因）
        assert ff.escape_subtitles_path(
            r"E:\项目\data\generations\sub.srt") == "E\\:/项目/data/generations/sub.srt"

    def test_posix_path_unchanged(self):
        assert ff.escape_subtitles_path("/data/sub.srt") == "/data/sub.srt"

    def test_single_quote_rejected(self):
        with pytest.raises(ValueError):
            ff.escape_subtitles_path(r"C:\a'b\sub.srt")


class TestCjkFontProbe:
    def test_true_when_candidate_exists(self, tmp_path, monkeypatch):
        font = tmp_path / "msyh.ttc"
        font.write_bytes(b"FAKEFONT")
        monkeypatch.setattr(ff, "_cjk_font_candidates", lambda: [font])
        assert ff.has_cjk_font() is True

    def test_false_when_all_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ff, "_cjk_font_candidates",
                            lambda: [tmp_path / "nope.ttf"])
        assert ff.has_cjk_font() is False


class TestBurnSubtitles:
    def test_builds_expected_command(self, tmp_path, monkeypatch):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(list(cmd))
            Path(cmd[-1]).write_bytes(b"MPEG")  # 模拟 ffmpeg 产出（实现以文件存在判成败）
            return type("P", (), {"returncode": 0, "stderr": b""})()

        monkeypatch.setattr(ff.subprocess, "run", fake_run)
        a, s, o = str(tmp_path / "a.mp4"), str(tmp_path / "a.srt"), str(tmp_path / "sub.mp4")
        ok, err = ff.burn_subtitles("/x/ffmpeg", a, s, o)
        assert ok is True and err == ""
        cmd = calls[0]
        assert cmd[:2] == ["/x/ffmpeg", "-y"]
        assert cmd[cmd.index("-i") + 1] == a
        assert cmd[cmd.index("-vf") + 1] == \
            "subtitles=filename='" + s.replace("\\", "/").replace(":", "\\:") + "'"
        assert cmd[cmd.index("-c:a") + 1] == "copy"
        assert cmd[-1] == o

    def test_failure_returns_false_with_stderr(self, tmp_path, monkeypatch):
        def fake_run(cmd, **kw):
            return type("P", (), {"returncode": 1, "stderr": b"Invalid argument"})()

        monkeypatch.setattr(ff.subprocess, "run", fake_run)
        ok, err = ff.burn_subtitles("/x/ffmpeg", "/in/a.mp4", "/in/a.srt", "/in/sub.mp4")
        assert ok is False
        assert "Invalid argument" in err

    def test_escaped_path_used_in_filter(self, tmp_path, monkeypatch):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(list(cmd))
            return type("P", (), {"returncode": 0, "stderr": b""})()

        monkeypatch.setattr(ff.subprocess, "run", fake_run)
        ff.burn_subtitles("ffmpeg", r"C:\v\a.mp4", r"C:\v\字幕.srt", r"C:\v\s.mp4")
        vf = calls[0][calls[0].index("-vf") + 1]
        assert vf == "subtitles=filename='C\\:/v/字幕.srt'"
