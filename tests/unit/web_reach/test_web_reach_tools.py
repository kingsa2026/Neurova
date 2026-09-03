"""Web Reach 整合测试（TDD 红绿）—— docs/agent-reach-integration.md 方案 B

对标 Agent-Reach（Panniantong/Agent-Reach）的零配置读取能力，封装为 Neurova
一等内置工具。设计约束：
- 不经 agent-reach CLI 中转（实际读取就是上游命令组合：Jina/V2EX API/
  feedparser/yt-dlp），直接在 Python 内实现，少一层子进程
- 与 agent-reach 的路由约定对齐（后端选型/安全边界：不碰用户浏览器）
- 全部外呼 mock，单测不打真网
"""

import pytest
from unittest.mock import MagicMock, patch


class TestV2exHot:
    def test_parses_topics_json(self):
        from neurova.web_reach import v2ex_hot

        fake_json = '[{"title":"问题讨论","url":"https://v2ex.com/t/1","replies":3,"member":{"username":"alice"}}]'
        with patch("neurova.web_reach.reach._http_get_text", return_value=fake_json) as get_mock:
            result = v2ex_hot(limit=5)

        assert result["success"] is True
        assert result["data"][0]["title"] == "问题讨论"
        assert result["data"][0]["url"] == "https://v2ex.com/t/1"
        assert result["source"] == "v2ex"
        get_mock.assert_called_once()

    def test_v2ex_http_error_returns_error(self):
        from neurova.web_reach import v2ex_hot

        with patch(
            "neurova.web_reach.reach._http_get_text",
            side_effect=OSError("V2EX API 返回 503"),
        ):
            result = v2ex_hot()

        assert result["success"] is False


class TestWebRead:
    def test_web_read_via_jina(self):
        from neurova.web_reach import web_read

        body = "Title: Example\n\nExample body in markdown"
        with patch("neurova.web_reach.reach._http_get_text", return_value=body) as get_mock:
            result = web_read("https://example.com/article")

        assert result["success"] is True
        assert "Example body" in result["data"]
        # Jina Reader 前缀拼接
        assert get_mock.call_args.args[0] == "https://r.jina.ai/https://example.com/article"

    def test_web_read_rejects_non_http(self):
        from neurova.web_reach import web_read

        result = web_read("file:///etc/passwd")
        assert result["success"] is False
        result2 = web_read("ftp://example.com/x")
        assert result2["success"] is False


class TestRssRead:
    def test_rss_parses_entries(self):
        import feedparser

        from neurova.web_reach import rss_read

        fake_feed = feedparser.FeedParserDict(
            entries=[
                {"title": "Entry A", "link": "https://blog.example/a", "summary": "sum a"},
                {"title": "Entry B", "link": "https://blog.example/b", "summary": "sum b"},
            ]
        )
        with (
            patch("neurova.web_reach.reach.feedparser.parse", return_value=fake_feed),
            patch("neurova.web_reach.reach._assert_public_host", return_value=None),
        ):
            result = rss_read("https://blog.example/feed.xml", limit=2)

        assert result["success"] is True
        assert result["data"][0]["title"] == "Entry A"
        assert result["data"][1]["link"] == "https://blog.example/b"

    def test_rss_rejects_non_http(self):
        from neurova.web_reach import rss_read

        result = rss_read("file:///x/feed")
        assert result["success"] is False


class TestYoutubeTranscript:
    def test_transcript_uses_ytdlp_subtitles(self, tmp_path):
        import json as _json

        from neurova.web_reach import youtube_transcript

        workdir = tmp_path / "ytwork"
        workdir.mkdir()

        def fake_run(cmd, **kwargs):
            # 从 cmd 中解析 -o 模板目录，把字幕文件写进去（模拟 yt-dlp 行为）
            out_template = cmd[cmd.index("-o") + 1]
            json3 = '{"events": [{"segs": [{"utf8": "hello world"}]}]}'
            (workdir / "sub.en.json3").write_text(json3, encoding="utf-8")
            assert out_template.startswith(str(workdir))
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch(
            "neurova.web_reach.reach.subprocess.run", side_effect=fake_run
        ) as run_mock:
            # 把 workdir 注入 tempfile.mkdtemp 的返回（patch mkdtemp）
            with patch("neurova.web_reach.reach.tempfile") as tf:
                tf.mkdtemp.return_value = str(workdir)
                result = youtube_transcript("https://www.youtube.com/watch?v=abc123")

        assert result["success"] is True
        assert "hello world" in result["data"]
        cmd = run_mock.call_args.args[0]
        assert "yt_dlp" in cmd
        assert any("v=abc123" in str(a) or "abc123" in str(a) for a in cmd)

    def test_transcript_rejects_non_youtube_url(self):
        from neurova.web_reach import youtube_transcript

        result = youtube_transcript("https://example.com/video")
        assert result["success"] is False
        assert "youtube" in result["error"].lower()

    def test_transcript_timeout_returns_error(self):
        import subprocess as _sp

        from neurova.web_reach import youtube_transcript

        with patch(
            "neurova.web_reach.reach.subprocess.run",
            side_effect=_sp.TimeoutExpired(cmd="yt-dlp", timeout=60),
        ):
            result = youtube_transcript("https://www.youtube.com/watch?v=abc", timeout=60)
        assert result["success"] is False
        assert "超时" in result["error"] or "timeout" in result["error"].lower()


class TestBilibiliSearch:
    def test_bilibili_search_via_ytdlp(self):
        from neurova.web_reach import bilibili_search

        fake_run = MagicMock(
            returncode=0,
            stdout='{"entries": [{"title": "BV 视频", "url": "https://www.bilibili.com/video/BV1"}]}',
            stderr="",
        )
        with patch("neurova.web_reach.reach.subprocess.run", return_value=fake_run) as run_mock:
            result = bilibili_search("agent 教程", limit=3)

        assert result["success"] is True
        assert result["data"][0]["title"] == "BV 视频"
        cmd = run_mock.call_args.args[0]
        assert any("bilisearch" in str(a) for a in cmd)  # yt-dlp 的 B 站搜索前缀


class TestSocialSearch:
    def test_unconfigured_platform_returns_setup_guide(self):
        """渐进式暴露：登录态平台未配置时返回配置引导，不报错、不自动登录"""
        from neurova.web_reach import social_search

        fake_doctor = {"channels": {"twitter": {"active_backend": None}}}
        with patch("neurova.web_reach.reach.run_doctor", return_value=fake_doctor):
            result = social_search("twitter", "neurova")

        assert result["success"] is False
        assert result["needs_setup"] is True
        assert "twitter" in result["guide"].lower()

    def test_active_backend_reported_when_configured(self):
        """后端就绪 + 无凭据 → needs_setup 且带 missing_keys（新契约）"""
        from neurova.web_reach import social_search

        fake_doctor = {"channels": {"twitter": {"active_backend": "twitter-cli"}}}
        with patch("neurova.web_reach.reach.run_doctor", return_value=fake_doctor):
            result = social_search("twitter", "neurova")

        assert result["success"] is False
        assert result["needs_setup"] is True
        assert "twitter_auth_token" in result["missing_keys"]

    def test_unknown_platform_rejected(self):
        from neurova.web_reach import social_search

        result = social_search("baidu_tieba", "x")
        assert result["success"] is False


class TestBuiltinIntegration:
    def test_schemas_registered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        for name in ("youtube_transcript", "bilibili_search", "rss_read", "v2ex_hot", "social_search"):
            assert name in _BUILTIN_SCHEMAS, f"{name} 未注册"
            assert _BUILTIN_SCHEMAS[name].get("description")

    @pytest.mark.asyncio
    async def test_executor_dispatches_v2ex_hot(self, tmp_path):
        from unittest.mock import patch

        from neurova.tool_executor import ToolExecutor

        exe = ToolExecutor(_AgentStub())
        with patch("neurova.web_reach.reach._http_get_text", return_value="[]"):
            result = await exe._execute_builtin_tool("v2ex_hot", {"limit": 3})

        assert result["success"] is True


class _AgentStub:
    pass
