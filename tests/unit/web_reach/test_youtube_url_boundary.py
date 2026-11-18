# -*- coding: utf-8 -*-
"""_is_youtube_url host 边界判定（fullrepo 审计 2026-11-18 D 组）。

红灯依据：原实现是子串匹配（"youtube.com/watch" in url.lower()）——
`https://evil.com/youtube.com/watch`、`https://notyoutube.com/watch`
这类任意主机都会命中，属校验宽口径。改为 urlparse 后按 host+path
边界判，语义与函数自述（youtube.com/watch 或 youtu.be/）一致。
"""
from neurova.web_reach.reach import _is_youtube_url


class TestYoutubeUrlBoundary:
    def test_substring_lookalikes_are_rejected(self):
        assert _is_youtube_url("https://evil.com/youtube.com/watch?v=x") is False
        assert _is_youtube_url("https://notyoutube.com/watch") is False
        assert _is_youtube_url("https://example.com/redirect?to=youtu.be/abc") is False

    def test_real_youtube_shapes_still_pass(self):
        assert _is_youtube_url("https://www.youtube.com/watch?v=abc") is True
        assert _is_youtube_url("https://youtube.com/watch?v=abc") is True
        assert _is_youtube_url("https://m.youtube.com/watch?v=abc") is True
        assert _is_youtube_url("https://youtu.be/abc123") is True

    def test_non_youtube_hosts_and_garbage_rejected(self):
        assert _is_youtube_url("https://example.com/watch") is False
        assert _is_youtube_url("") is False
        assert _is_youtube_url("not a url") is False
