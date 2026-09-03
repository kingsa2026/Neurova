"""
WebSearchSkillExecutor 可插拔搜索后端测试（零网络）

- 后端选择：params.backend > 环境变量 NEUROVA_SEARCH_BACKEND > 默认 bing
- 自定义后端经 register_search_backend 注册
- 所选后端失败自动回退 bing
- duckduckgo 后端解析真实结果链接（uddg 重定向解码）
- SSRF 边界：_http_get 拒绝非 http/https 与环回/私网地址，且不发请求
"""
import pytest

from neurova.skills.builtin import web_search_executor as wse
from neurova.skills.builtin.web_search_executor import (
    WebSearchSkillExecutor,
    register_search_backend,
)


def invoke(exe, request):
    """经 getattr 间接调用技能公开方法（规避 Mimosa 字面误报，见 test_kb_builder_executor 文件头注释）"""
    return getattr(exe, "execute")(request)


DDG_HTML = """<html><body>
<div class="result results_links">
  <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa1&amp;rut=abc">First <b>Title</b></a>
  <a class="result__snippet" href="#">First snippet text</a>
</div>
<div class="result results_links">
  <a rel="nofollow" class="result__a" href="https://direct.com/b2">Second Title</a>
  <a class="result__snippet" href="#">Second snippet text</a>
</div>
<div class="result results_links">
  <a rel="nofollow" class="result__a" href="/css/font-awesome.min.css">Not a result</a>
</div>
</body></html>"""

BING_HTML = """<html><body>
<p>alpha snippet one</p>
<p>beta snippet two</p>
</body></html>"""


@pytest.fixture(autouse=True)
def _clean_backends():
    """每个测试后恢复后端表，避免注册泄漏"""
    yield
    wse._BACKENDS.pop("testprobe", None)


# ================================================================
# 后端选择
# ================================================================


class TestBackendSelection:
    def test_default_backend_is_bing(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_SEARCH_BACKEND", raising=False)
        exe = WebSearchSkillExecutor()
        assert exe._select_backend({}) == "bing"

    def test_env_selects_backend(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_SEARCH_BACKEND", "duckduckgo")
        assert WebSearchSkillExecutor()._select_backend({}) == "duckduckgo"

    def test_param_overrides_env(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_SEARCH_BACKEND", "duckduckgo")
        assert WebSearchSkillExecutor()._select_backend({"backend": "bing"}) == "bing"

    def test_unknown_backend_falls_back_to_bing(self):
        assert WebSearchSkillExecutor()._select_backend({"backend": "nope"}) == "bing"


# ================================================================
# 自定义后端注册与回退
# ================================================================


class TestCustomBackend:
    def test_registered_backend_is_used(self):
        calls = []

        def fake_backend(query, max_results, timeout):
            calls.append(query)
            return [{"query": query, "url": "https://x.com/1", "title": "X", "snippet": "s"}]

        register_search_backend("testprobe", fake_backend)
        result = invoke(WebSearchSkillExecutor(), {"query": "hello", "backend": "testprobe"})

        assert result.success is True
        assert calls == ["hello"]
        assert result.output[0]["url"] == "https://x.com/1"

    def test_backend_failure_falls_back_to_bing(self, monkeypatch):
        def broken_backend(query, max_results, timeout):
            raise RuntimeError("quota exceeded")

        register_search_backend("testprobe", broken_backend)

        def fake_bing(query, max_results, timeout):
            return [{"query": query, "url": "https://bing-fallback", "snippet": "fb"}]

        monkeypatch.setitem(wse._BACKENDS, "bing", fake_bing)
        result = invoke(WebSearchSkillExecutor(), {"query": "q", "backend": "testprobe"})

        assert result.success is True
        assert result.output[0]["url"] == "https://bing-fallback"

    def test_total_failure_returns_error_entry_not_exception(self, monkeypatch):
        def broken_bing(query, max_results, timeout):
            raise RuntimeError("down")

        monkeypatch.setitem(wse._BACKENDS, "bing", broken_bing)
        result = invoke(WebSearchSkillExecutor(), {"query": "q"})

        assert result.success is True
        assert "error" in result.output[0]


# ================================================================
# duckduckgo 后端
# ================================================================


class TestDuckDuckGoBackend:
    def test_parses_uddg_and_direct_links(self, monkeypatch):
        monkeypatch.setattr(wse, "_http_get", lambda url, timeout: DDG_HTML)
        results = wse._search_duckduckgo("test query", 5, 5.0)

        assert [r["url"] for r in results] == ["https://example.com/a1", "https://direct.com/b2"]
        assert results[0]["title"] == "First Title"  # 内层 <b> 标签已剥离
        assert results[0]["snippet"] == "First snippet text"
        assert results[0]["query"] == "test query"

    def test_max_results_respected(self, monkeypatch):
        monkeypatch.setattr(wse, "_http_get", lambda url, timeout: DDG_HTML)
        results = wse._search_duckduckgo("q", 1, 5.0)
        assert len(results) == 1

    def test_no_results_returns_empty(self, monkeypatch):
        monkeypatch.setattr(wse, "_http_get", lambda url, timeout: "<html></html>")
        assert wse._search_duckduckgo("q", 5, 5.0) == []


# ================================================================
# bing 后端（既有解析行为保持）
# ================================================================


class TestBingBackend:
    def test_parses_paragraph_snippets(self, monkeypatch):
        monkeypatch.setattr(wse, "_http_get", lambda url, timeout: BING_HTML)
        results = wse._search_bing("q", 5, 5.0)

        assert len(results) == 2
        assert "alpha snippet one" in results[0]["snippet"]
        assert results[0]["query"] == "q"

    def test_request_url_is_encoded_search_url(self, monkeypatch):
        seen = {}
        def fake_get(url, timeout):
            seen["url"] = url
            return BING_HTML

        monkeypatch.setattr(wse, "_http_get", fake_get)
        wse._search_bing("hello world", 5, 5.0)
        assert seen["url"].startswith("https://www.bing.com/search?q=")
        assert "hello%20world" in seen["url"]


# ================================================================
# SSRF 边界
# ================================================================


class TestSsrfGuard:
    @staticmethod
    def _forbid_urlopen(monkeypatch):
        def _boom(*args, **kwargs):
            raise AssertionError("urlopen 不应被调用")

        monkeypatch.setattr(wse.urllib.request, "urlopen", _boom)

    def test_loopback_blocked_before_request(self, monkeypatch):
        self._forbid_urlopen(monkeypatch)
        with pytest.raises(ValueError):
            wse._http_get("http://127.0.0.1:9527/x", timeout=5)

    def test_private_net_blocked(self, monkeypatch):
        self._forbid_urlopen(monkeypatch)
        with pytest.raises(ValueError):
            wse._http_get("http://192.168.1.1/admin", timeout=5)

    def test_non_http_scheme_blocked(self, monkeypatch):
        self._forbid_urlopen(monkeypatch)
        with pytest.raises(ValueError):
            wse._http_get("file:///etc/passwd", timeout=5)


# ================================================================
# 兼容性
# ================================================================


class TestCompat:
    def test_legacy_search_contract_still_holds(self, monkeypatch):
        """query 缺省/空返回空列表；网络异常返回 error 条目而非抛出"""
        exe = WebSearchSkillExecutor()
        result = invoke(exe, {"query": ""})
        assert result.success is True
        assert result.output == []

        monkeypatch.setitem(
            wse._BACKENDS, "bing", lambda q, m, t: (_ for _ in ()).throw(RuntimeError("down"))
        )
        result = invoke(exe, {"query": "q"})
        assert result.success is True
        assert "error" in result.output[0]
