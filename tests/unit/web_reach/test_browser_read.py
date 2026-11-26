"""browser_read 工具回归测试。

覆盖：
- SSRF 边界（私网/环回/协议校验）在启动浏览器前拦截
- 正常流程：Playwright 导航 → JS 提取 → Markdown 文本返回
- 浏览器缺失 / 页面为空 / 异常的错误封装
- 与 web_reach._ok/_error 返回契约一致
"""

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from tests.unit.web_reach._playwrightStub import stubAsyncPlaywright

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _make_fake_page(result: dict) -> AsyncMock:
    """构造 fake page：goto 成功，evaluate 返回给定结果。"""
    page = AsyncMock()
    page.goto = AsyncMock(return_value=None)
    page.evaluate = AsyncMock(return_value=result)
    return page


def _make_fake_browser(page: AsyncMock) -> AsyncMock:
    browser = AsyncMock()
    browser.new_page = AsyncMock(return_value=page)
    browser.close = AsyncMock(return_value=None)
    return browser


def _make_fake_playwright(browser: AsyncMock):
    p = AsyncMock()
    p.__aenter__.return_value = p
    p.__aexit__.return_value = None
    p.chromium.launch = AsyncMock(return_value=browser)
    p.stop = AsyncMock(return_value=None)
    return p


class TestBrowserReadSSRF(unittest.TestCase):
    """SSRF 与协议校验必须在启动浏览器之前拦截。"""

    def test_private_loopback_blocked(self):
        from neurova.web_reach.browser_read import browser_read

        with stubAsyncPlaywright() as mock_pw:
            result = browser_read("http://127.0.0.1:9527/health")
            self.assertFalse(result.get("success"))
            self.assertIn("source", result)
            mock_pw.assert_not_called()

    def test_scheme_rejected(self):
        from neurova.web_reach.browser_read import browser_read

        with stubAsyncPlaywright() as mock_pw:
            result = browser_read("file:///etc/passwd")
            self.assertFalse(result.get("success"))
            mock_pw.assert_not_called()

    def test_metadata_ip_blocked(self):
        from neurova.web_reach.browser_read import browser_read

        with stubAsyncPlaywright() as mock_pw:
            result = browser_read("http://169.254.169.254/latest/meta-data/")
            self.assertFalse(result.get("success"))
            mock_pw.assert_not_called()


class TestBrowserReadSuccess(unittest.TestCase):
    def test_returns_markdown_text(self):
        from neurova.web_reach.browser_read import browser_read

        page = _make_fake_page(
            {"title": "示例页", "text": "# 标题\n\n第一段内容\n\n- 列表项"}
        )
        browser = _make_fake_browser(page)
        pw = _make_fake_playwright(browser)

        with stubAsyncPlaywright() as _pwFactory:
            _pwFactory.return_value = pw
            result = browser_read("https://example.com/docs", timeout=15)

        self.assertTrue(result.get("success"))
        data = result["data"]
        self.assertEqual(data["title"], "示例页")
        self.assertIn("# 标题", data["text"])
        self.assertEqual(data["url"], "https://example.com/docs")
        self.assertEqual(data["source"], "browser_read")
        self.assertGreater(data["text_length"], 0)
        # 浏览器确实被启动与关闭
        browser.close.assert_awaited_once()

    def test_goes_to_url_and_waits_network_idle(self):
        from neurova.web_reach.browser_read import browser_read

        page = _make_fake_page({"title": "t", "text": "正文"})
        browser = _make_fake_browser(page)
        pw = _make_fake_playwright(browser)

        with stubAsyncPlaywright() as _pwFactory:
            _pwFactory.return_value = pw
            browser_read("https://example.com", timeout=30)

        page.goto.assert_awaited_once()
        pos_args, kw = page.goto.await_args
        self.assertEqual(pos_args[0], "https://example.com")
        self.assertEqual(kw["wait_until"], "load")
        self.assertLessEqual(kw["timeout"], 30_000)
        page.wait_for_timeout.assert_awaited_once()
        page.route.assert_awaited_once()


class TestBrowserReadNetworkRoute(unittest.TestCase):
    def _routeHandler(self, safeFetch):
        from neurova.web_reach.browser_read import browser_read

        page = _make_fake_page({"title": "t", "text": "正文"})
        browser = _make_fake_browser(page)
        pw = _make_fake_playwright(browser)
        patcher = patch("neurova.security.safe_fetch.safe_fetch", safeFetch)
        patcher.start()
        self.addCleanup(patcher.stop)
        with stubAsyncPlaywright() as factory:
            factory.return_value = pw
            self.assertTrue(browser_read("http://1.2.3.4/page")["success"])
        return page.route.await_args.args[1]

    def test_privateSubresourceIsBlockedBySafeFetch(self):
        from neurova.security.safe_fetch import SSRFBlockedError

        def safeFetch(url, **kwargs):
            raise SSRFBlockedError("私网拒绝")

        handler = self._routeHandler(safeFetch)
        request = SimpleNamespace(
            url="http://127.0.0.1/admin", method="GET", headers={}, post_data_buffer=None,
        )
        route = SimpleNamespace(
            request=request,
            continue_=AsyncMock(), fulfill=AsyncMock(), abort=AsyncMock(),
        )

        asyncio.run(handler(route))

        route.abort.assert_awaited_once()
        route.fulfill.assert_not_awaited()

    def test_publicSubresourceIsFulfilledWithoutBrowserDNS(self):
        from neurova.security.safe_fetch import SafeFetchResponse

        calls = []

        def safeFetch(url, **kwargs):
            calls.append((url, kwargs))
            return SafeFetchResponse(
                200,
                {"content-type": "text/html", "content-length": "999", "content-encoding": "gzip"},
                b"<p>safe</p>",
                url,
            )

        handler = self._routeHandler(safeFetch)
        request = SimpleNamespace(
            url="https://public.example/app.js", method="GET", headers={}, post_data_buffer=None,
        )
        route = SimpleNamespace(
            request=request,
            continue_=AsyncMock(), fulfill=AsyncMock(), abort=AsyncMock(),
        )

        asyncio.run(handler(route))

        self.assertEqual(calls[0][0], request.url)
        kwargs = route.fulfill.await_args.kwargs
        self.assertEqual(kwargs["body"], b"<p>safe</p>")
        self.assertNotIn("content-length", kwargs["headers"])
        self.assertNotIn("content-encoding", kwargs["headers"])
        route.continue_.assert_not_awaited()


class TestBrowserReadErrors(unittest.TestCase):
    def test_browser_missing_clear_error(self):
        from neurova.web_reach.browser_read import browser_read

        pw = AsyncMock()
        pw.__aenter__.return_value = pw
        pw.__aexit__.return_value = None
        pw.chromium.launch = AsyncMock(
            side_effect=Exception("Executable doesn't exist at ... run playwright install")
        )
        with stubAsyncPlaywright() as _pwFactory:
            _pwFactory.return_value = pw
            result = browser_read("https://example.com")
        self.assertFalse(result.get("success"))
        self.assertIn("浏览器未安装", result.get("error", ""))

    def test_empty_page_text_error(self):
        from neurova.web_reach.browser_read import browser_read

        page = _make_fake_page({"title": "", "text": "   "})
        browser = _make_fake_browser(page)
        pw = _make_fake_playwright(browser)
        with stubAsyncPlaywright() as _pwFactory:
            _pwFactory.return_value = pw
            result = browser_read("https://example.com")
        self.assertFalse(result.get("success"))
        self.assertIn("未提取到文本", result.get("error", ""))

    def test_generic_exception_wrapped(self):
        from neurova.web_reach.browser_read import browser_read

        pw = AsyncMock()
        pw.__aenter__.return_value = pw
        pw.__aexit__.return_value = None
        pw.chromium.launch = AsyncMock(side_effect=Exception("boom"))
        with stubAsyncPlaywright() as _pwFactory:
            _pwFactory.return_value = pw
            result = browser_read("https://example.com")
        self.assertFalse(result.get("success"))
        self.assertIn("boom", result.get("error", ""))


if __name__ == "__main__":
    unittest.main()
