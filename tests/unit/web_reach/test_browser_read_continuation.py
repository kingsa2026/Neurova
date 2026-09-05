"""browser_read 续读游标测试（红→绿 TDD）。

契约（对标 Dokobot canContinue/sessionId，本地化命名 read session）：
- 首读：超过 chunk（默认 60_000，与既有 _MAX_TEXT 契约一致）→ 建 session，
  返回首片 + session_id + can_continue + next_offset；未超 → 行为与现状完全一致（无 session）
- 续读：传 session_id（+可选 offset）→ 纯内存切片，不再启动浏览器
- 会话过期/不存在 → 明确错误引导重新首读
- SSRF 守卫只在首读生效；续读零网络
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from neurova.core.read_sessions import get_read_session_store, reset_read_session_store  # noqa: E402


def _make_fake_page(result: dict) -> AsyncMock:
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


_LONG_TEXT = ("甲" * 40_000) + ("乙" * 25_000)  # 65_000 > 60_000


class TestBrowserReadFreshSession(unittest.TestCase):
    def setUp(self):
        reset_read_session_store()

    def tearDown(self):
        reset_read_session_store()

    def test_long_page_creates_session_with_cursor(self):
        from neurova.web_reach.browser_read import browser_read

        page = _make_fake_page({"title": "长页", "text": _LONG_TEXT})
        browser = _make_fake_browser(page)
        pw = _make_fake_playwright(browser)

        with patch("neurova.web_reach.browser_read.async_playwright", return_value=pw):
            result = browser_read("https://example.com/long")

        self.assertTrue(result["success"])
        data = result["data"]
        self.assertEqual(len(data["text"]), 60_000)          # 首片维持既有 60k 契约
        self.assertTrue(data["truncated"])
        self.assertEqual(data["text_length"], 65_000)        # 全文长度
        self.assertTrue(data["can_continue"])
        self.assertEqual(data["next_offset"], 60_000)
        self.assertTrue(data.get("session_id"))
        self.assertEqual(data["total_length"], 65_000)
        # 全文进了会话缓存，尾部不再丢失
        store = get_read_session_store()
        sess = store.get(data["session_id"])
        self.assertIsNotNone(sess)
        self.assertEqual(len(sess.text), 65_000)

    def test_short_page_behavior_unchanged(self):
        from neurova.web_reach.browser_read import browser_read

        page = _make_fake_page({"title": "短页", "text": "正文内容"})
        browser = _make_fake_browser(page)
        pw = _make_fake_playwright(browser)

        with patch("neurova.web_reach.browser_read.async_playwright", return_value=pw):
            result = browser_read("https://example.com/short")

        data = result["data"]
        self.assertTrue(result["success"])
        self.assertFalse(data["truncated"])
        self.assertFalse(data["can_continue"])
        self.assertIsNone(data["next_offset"])
        self.assertIsNone(data.get("session_id"))
        # 未产生会话
        self.assertEqual(len(get_read_session_store()._sessions), 0)

    def test_custom_chunk_size(self):
        from neurova.web_reach.browser_read import browser_read

        page = _make_fake_page({"title": "t", "text": "x" * 500})
        browser = _make_fake_browser(page)
        pw = _make_fake_playwright(browser)

        with patch("neurova.web_reach.browser_read.async_playwright", return_value=pw):
            result = browser_read("https://example.com/c", chunk_size=200)

        data = result["data"]
        self.assertEqual(len(data["text"]), 200)
        self.assertTrue(data["can_continue"])
        self.assertEqual(data["next_offset"], 200)


class TestBrowserReadContinuation(unittest.TestCase):
    def setUp(self):
        reset_read_session_store()
        # 预置一个 65k 会话（served=60k：模拟首读已直接吐出首片）
        self.store = get_read_session_store()
        self.session_id = self.store.create(
            domain="browser_read", url="https://example.com/long",
            title="长页", text=_LONG_TEXT, chunk_size=60_000, served=60_000,
        ).session_id

    def tearDown(self):
        reset_read_session_store()

    def test_continuation_without_browser(self):
        from neurova.web_reach.browser_read import browser_read

        pw = _make_fake_playwright(AsyncMock())
        with patch("neurova.web_reach.browser_read.async_playwright", return_value=pw) as mock_pw:
            result = browser_read(session_id=self.session_id)

        mock_pw.assert_not_called()  # 续读零浏览器开销
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertEqual(data["text"], _LONG_TEXT[60_000:])
        self.assertEqual(data["offset"], 60_000)
        self.assertFalse(data["can_continue"])
        self.assertIsNone(data["next_offset"])
        self.assertEqual(data["total_length"], 65_000)
        self.assertEqual(data["url"], "https://example.com/long")

    def test_full_read_chain_reassembles(self):
        from neurova.web_reach.browser_read import browser_read

        # 模拟 LLM 的真实消费方式：首读(带 chunk_size) → 循环续读 → 拼接
        sid = self.store.create(
            domain="browser_read", url="https://example.com/chain",
            title="t", text=_LONG_TEXT, chunk_size=30_000, served=30_000,
        ).session_id
        pieces = [_LONG_TEXT[:30_000]]  # 首读已直接返回的首片
        res = browser_read(session_id=sid)
        pieces.append(res["data"]["text"])
        while res["data"]["can_continue"]:
            res = browser_read(session_id=sid)
            pieces.append(res["data"]["text"])
        self.assertEqual("".join(pieces), _LONG_TEXT)

    def test_continuation_with_explicit_offset(self):
        from neurova.web_reach.browser_read import browser_read

        result = browser_read(session_id=self.session_id, offset=0)
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["text"], _LONG_TEXT[:60_000])

    def test_unknown_session_clear_error(self):
        from neurova.web_reach.browser_read import browser_read

        result = browser_read(session_id="rs_nonexistent")
        self.assertFalse(result["success"])
        self.assertIn("会话", result["error"])
        self.assertIn("重新", result["error"])

    def test_continuation_does_not_require_url(self):
        """url 在续读时可省略（会话自带）"""
        from neurova.web_reach.browser_read import browser_read

        result = browser_read(session_id=self.session_id)
        self.assertTrue(result["success"])

    def test_continuation_ignores_ssrf_check(self):
        """续读零网络——不触发 URL 守卫（该 URL 甚至可能是续读时拼错的）"""
        from neurova.web_reach.browser_read import browser_read

        result = browser_read(session_id=self.session_id, url="http://127.0.0.1/x")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["url"], "https://example.com/long")  # 以会话为准


if __name__ == "__main__":
    unittest.main()
