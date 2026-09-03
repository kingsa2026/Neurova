"""
天气 / 网络搜索工具执行修复 — 回归测试

根因（本次修复）：
  R-1: _execute_weather 使用 User-Agent: Mozilla/5.0。
       wttr.in 对浏览器 UA 返回完整 HTML 网页（~12KB），导致 format=3 / lang=zh
       参数失效，返回一整页 HTML 污染结果（LLM 无法解析、前端展示乱码），
       用户感知为"天气查询失败"。
  R-2: _execute_web_search 使用 google.com/search 静态抓取。
       现代 Google SERP 需 JS 渲染且反爬，re.findall 提取不到摘要，
       总是返回"未能提取摘要"。

修复：
  F-1: weather 改用 curl UA，wttr.in 才返回 format=3 精简文本；并加 HTML 兜底提取。
  F-2: web_search 改用 Bing HTML 接口（無 JS 请求可解析的 b_caption / b_lineclamp 摘要）。
"""

import pytest
from unittest.mock import Mock, patch
import urllib.request


def _make_executor():
    from neurova.tool_executor import ToolExecutor

    agent = Mock()
    agent._skill_registry = Mock()
    agent.tool_router = Mock()
    agent.tool_memory = Mock()
    agent.tool_lifecycle = Mock()
    agent.skill_packer = Mock()
    agent.config = Mock()
    agent.memory_manager = Mock()
    agent.memory_manager._emotion_analyzer = Mock()

    return ToolExecutor(agent)


def _urlopen_returning(body_bytes):
    """构造一个模拟 urllib.request.urlopen 返回值的 context manager。

    urlopen 返回的对象需支持 `with ... as resp:`，且 resp.read() 返回 bytes。
    """
    resp = Mock()
    resp.read = Mock(return_value=body_bytes)

    cm = Mock()
    cm.__enter__ = Mock(return_value=resp)
    cm.__exit__ = Mock(return_value=False)
    return cm


# ═══════════════════════════════════════════════════════════════
# R-1: weather UA 修复
# ═══════════════════════════════════════════════════════════════

class TestWeatherFix:
    @pytest.mark.asyncio
    async def test_weather_uses_curl_user_agent(self):
        """wttr.in 必须使用 curl UA 才能拿到 format=3 精简文本，不能用浏览器 UA"""
        executor = _make_executor()
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["req"] = req
            return _urlopen_returning("许昌: 🌦️ +80°F".encode("utf-8"))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = await executor._execute_weather({"location": "许昌"})

        req = captured["req"]
        ua = req.get_header("User-agent") or req.get_header("User-Agent")
        assert ua is not None, "weather 请求必须携带 User-Agent"
        assert "Mozilla" not in ua, (
            f"weather 不能用浏览器 UA（wttr.in 会返回 HTML），实际: {ua}"
        )
        assert "curl" in ua.lower(), f"weather 应用 curl UA，实际: {ua}"

    @pytest.mark.asyncio
    async def test_weather_url_has_format_param(self):
        """wttr.in URL 必须保留 format=3，确保返回精简文本"""
        executor = _make_executor()
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["req"] = req
            return _urlopen_returning("北京: 🌫️ +69°F".encode("utf-8"))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = await executor._execute_weather({"city": "北京"})

        full_url = captured["req"].full_url
        assert "wttr.in" in full_url
        assert "format=3" in full_url, f"weather URL 必须含 format=3: {full_url}"

    @pytest.mark.asyncio
    async def test_weather_returns_clean_text(self):
        """修复后 weather 返回精简文本，而非 HTML"""
        executor = _make_executor()

        with patch("urllib.request.urlopen", return_value=_urlopen_returning("许昌: 🌦️ +80°F".encode("utf-8"))):
            result = await executor._execute_weather({"location": "许昌"})

        assert result.get("location") == "许昌"
        weather = result.get("weather", "")
        assert "<html" not in weather.lower(), "weather 结果不应包含 HTML"
        assert "<div" not in weather.lower()
        assert "许昌" in weather

    @pytest.mark.asyncio
    async def test_weather_html_fallback_extracts_text(self):
        """极少数 wttr.in 变体即便用 curl UA 仍返回 HTML 时应兜底提取纯文本"""
        executor = _make_executor()
        html = (
            "<!DOCTYPE html><html><head><style>.x{}</style></head>"
            "<body><h1>许昌: 🌦️ +80°F</h1></body></html>"
        )

        with patch("urllib.request.urlopen", return_value=_urlopen_returning(html.encode("utf-8"))):
            result = await executor._execute_weather({"location": "许昌"})

        weather = result.get("weather", "")
        assert "<html" not in weather.lower(), "HTML 兜底应移除标签"
        assert "style" not in weather.lower()
        assert "许昌" in weather

    @pytest.mark.asyncio
    async def test_weather_missing_location(self):
        """缺地点应返回明确错误，而非调用网络"""
        executor = _make_executor()

        with patch("urllib.request.urlopen") as mock_urlopen:
            result = await executor._execute_weather({})

        mock_urlopen.assert_not_called()
        assert result.get("error") == "缺少地点信息"


# ═══════════════════════════════════════════════════════════════
# R-2: web_search 改用 Bing
# ═══════════════════════════════════════════════════════════════

class TestWebSearchFix:
    @pytest.mark.asyncio
    async def test_web_search_uses_bing(self):
        """web_search 应使用 Bing 接口，而非 google.com（后者静态抓取拿不到摘要）"""
        executor = _make_executor()
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["req"] = req
            html = (
                '<html><body>'
                '<div class="b_caption"><p>北京天气预报，及时准确发布中央气象台天气信息</p></div>'
                '</body></html>'
            )
            return _urlopen_returning(html.encode("utf-8"))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = await executor._execute_web_search({"query": "北京天气"})

        full_url = captured["req"].full_url
        assert "bing.com" in full_url, f"web_search 应使用 Bing：{full_url}"
        assert "google.com" not in full_url

    @pytest.mark.asyncio
    async def test_web_search_extracts_snippet(self):
        """Bing 结果应能提取到真实摘要文本"""
        executor = _make_executor()
        html = (
            '<html><body>'
            '<div class="b_caption"><p>北京今日天气：多云转晴，气温18~26°C</p></div>'
            '<div class="b_caption"><p>北京7天预报请查看中央气象台官网</p></div>'
            '</body></html>'
        )

        with patch("urllib.request.urlopen", return_value=_urlopen_returning(html.encode("utf-8"))):
            result = await executor._execute_web_search({"query": "北京天气"})

        results = result.get("results", "")
        assert "北京" in results
        assert "未能提取摘要" not in results, "应提取到真实摘要而非降级文案"
        assert "<div" not in results and "<p" not in results, "摘要应为纯文本"

    @pytest.mark.asyncio
    async def test_web_search_missing_query(self):
        """缺查询词应返回明确错误"""
        executor = _make_executor()

        with patch("urllib.request.urlopen") as mock_urlopen:
            result = await executor._execute_web_search({})

        mock_urlopen.assert_not_called()
        assert "error" in result
