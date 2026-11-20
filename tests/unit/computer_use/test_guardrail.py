# -*- coding: utf-8 -*-
"""护栏三招（实施计划项 8）红灯测试：复核失败即拒 / 跟随式免审。

- a) LLM 复核桩超时 → sensitive 动作执行计数 0（fail-closed，宁可不做）
- b) 同站导航免审、跨站必须复核
- 只读白名单成员可配置（默认集保守）
- NEUROVA_CUA_GUARDRAIL=off 直通（回滚开关，默认开）

不真开浏览器：BrowserManager 注入桩后端，只记录调用。
"""

import asyncio

import pytest

from neurova.computer_use import guardrail
from neurova.computer_use.browser_manager import BrowserManager, BrowserResult


class StubBackend:
    """桩后端：记录 navigate / extract_links 调用，不启动真实浏览器。"""

    def __init__(self, current_url: str = ""):
        self._initialized = True
        self._url = current_url
        self.navigateCalls: list = []
        self.links: list = []

    async def navigate(self, url, generation=None):
        self.navigateCalls.append(url)
        self._url = url
        return BrowserResult(success=True, url=url, generation=(generation or 0) + 1)

    async def extract_links(self):
        return BrowserResult(success=True, data=list(self.links))

    def currentUrl(self):
        return self._url


def _makeManager(current_url: str = "https://portal.example.com/inbox"):
    bm = BrowserManager(config={})
    stub = StubBackend(current_url=current_url)
    bm._backends["playwright"] = stub
    bm._active_backend = stub
    return bm, stub


@pytest.fixture
def wired():
    return _makeManager()


@pytest.fixture(autouse=True)
def guardrailClean(monkeypatch):
    monkeypatch.delenv("NEUROVA_CUA_GUARDRAIL", raising=False)
    monkeypatch.delenv("NEUROVA_CUA_REVIEW_TIMEOUT", raising=False)
    guardrail.resetReviewer()
    guardrail.resetReadonlyWhitelist()
    yield
    guardrail.resetReviewer()
    guardrail.resetReadonlyWhitelist()


class TestSameRegistrableDomain:
    def test_subdomain_and_scheme_port_differences_are_same_site(self):
        assert guardrail.sameRegistrableDomain(
            "https://app.example.com/page2", "http://portal.example.com:8080/inbox"
        )

    def test_loopback_special_case(self):
        assert guardrail.sameRegistrableDomain(
            "http://localhost:3000/a", "http://127.0.0.1:9000/b"
        )
        assert guardrail.sameRegistrableDomain("http://[::1]:80/x", "http://localhost/y")

    def test_different_domains(self):
        assert not guardrail.sameRegistrableDomain(
            "https://example.com", "https://example.org"
        )
        # 末两段比对：example.com.evil.org 的 registrable domain 是 evil.org
        assert not guardrail.sameRegistrableDomain(
            "https://example.com", "https://example.com.evil.org"
        )

    def test_empty_current_is_not_same(self):
        assert not guardrail.sameRegistrableDomain("https://example.com", "")


class TestClassify:
    def test_readonly_whitelist_passes_through(self):
        for action in (
            "screenshot",
            "dom_snapshot",
            "dom_read",
            "extract_text",
            "extract_links",
            "scroll_by",
            "go_back",
            "wait_for",
            "console_messages",
            "computer_screenshot",
            "computer_list_windows",
        ):
            verdict = guardrail.classify(action, {})
            assert verdict.level == "readonly", action

    def test_whitelist_is_configurable(self):
        guardrail.addReadonlyActions(["my_custom_probe"])
        assert guardrail.classify("my_custom_probe", {}).level == "readonly"

    def test_write_actions_are_not_whitelisted(self):
        for action in ("browser_navigate", "click", "type", "execute_js", "cookies"):
            assert guardrail.classify(action, {}).level != "readonly", action

    def test_same_site_navigation_is_follow_nav(self):
        ctx = {"currentUrl": "https://portal.example.com/inbox"}
        verdict = guardrail.classify(
            "browser_navigate", {"url": "https://app.example.com/page2"}, ctx
        )
        assert verdict.level == "follow_nav"

    def test_seen_link_navigation_is_follow_nav(self):
        ctx = {
            "currentUrl": "https://portal.example.com/inbox",
            "seenLinks": ["https://partner.io/landing"],
        }
        verdict = guardrail.classify(
            "browser_navigate", {"url": "https://partner.io/landing"}, ctx
        )
        assert verdict.level == "follow_nav"

    def test_cross_site_navigation_is_sensitive(self):
        ctx = {"currentUrl": "https://portal.example.com/inbox"}
        verdict = guardrail.classify(
            "browser_navigate", {"url": "https://stranger.org/x"}, ctx
        )
        assert verdict.level == "sensitive"

    def test_first_navigation_without_current_page_is_sensitive(self):
        verdict = guardrail.classify(
            "browser_navigate", {"url": "https://example.com"}, {}
        )
        assert verdict.level == "sensitive"

    def test_missing_url_is_sensitive(self):
        ctx = {"currentUrl": "https://portal.example.com/inbox"}
        assert guardrail.classify("browser_navigate", {}, ctx).level == "sensitive"


class TestReview:
    @pytest.mark.asyncio
    async def test_allow_and_deny(self):
        async def allow(action, params, context):
            return "allow"

        guardrail.setReviewer(allow)
        assert (
            await guardrail.review("browser_navigate", {"url": "https://x.org"}, {})
        ).decision == "allow"

        async def deny(action, params, context):
            return "deny"

        guardrail.setReviewer(deny)
        assert (
            await guardrail.review("browser_navigate", {"url": "https://x.org"}, {})
        ).decision == "deny"

    @pytest.mark.asyncio
    async def test_reviewer_exception_is_unavailable(self):
        async def broken(action, params, context):
            raise RuntimeError("reviewer down")

        guardrail.setReviewer(broken)
        outcome = await guardrail.review("browser_navigate", {"url": "https://x.org"}, {})
        assert outcome.decision == "unavailable"
        assert outcome.reason_code == "reviewer_error"

    @pytest.mark.asyncio
    async def test_reviewer_timeout_is_unavailable(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_CUA_REVIEW_TIMEOUT", "0.05")

        async def slow(action, params, context):
            await asyncio.sleep(2)
            return "allow"

        guardrail.setReviewer(slow)
        outcome = await guardrail.review("browser_navigate", {"url": "https://x.org"}, {})
        assert outcome.decision == "unavailable"
        assert outcome.reason_code == "reviewer_timeout"

    @pytest.mark.asyncio
    async def test_reviewer_garbage_answer_is_unavailable(self):
        async def nonsense(action, params, context):
            return "maybe"

        guardrail.setReviewer(nonsense)
        outcome = await guardrail.review("browser_navigate", {"url": "https://x.org"}, {})
        assert outcome.decision == "unavailable"

    @pytest.mark.asyncio
    async def test_default_reviewer_uses_llm_chat(self, monkeypatch):
        seen = []

        class StubClient:
            async def chat(self, messages, model=None, **kwargs):
                seen.append(messages)
                return {"success": True, "response": "allow：目标与当前任务相关"}

        from neurova.llm import multi_model_client as mmc

        monkeypatch.setattr(mmc, "get_multi_model_client", lambda scope=None: StubClient())
        outcome = await guardrail.review("browser_navigate", {"url": "https://x.org"}, {})
        assert outcome.decision == "allow"
        assert seen, "默认复核必须走 multi_model_client.chat 入口"

    @pytest.mark.asyncio
    async def test_default_reviewer_llm_failure_is_unavailable(self, monkeypatch):
        class StubClient:
            async def chat(self, messages, model=None, **kwargs):
                raise RuntimeError("no provider")

        from neurova.llm import multi_model_client as mmc

        monkeypatch.setattr(mmc, "get_multi_model_client", lambda scope=None: StubClient())
        outcome = await guardrail.review("browser_navigate", {"url": "https://x.org"}, {})
        assert outcome.decision == "unavailable"
        assert outcome.reason_code == "reviewer_error"


class TestNavigationGuardrail:
    @pytest.mark.asyncio
    async def test_sensitive_navigation_with_timeout_reviewer_executes_zero(
        self, wired, monkeypatch
    ):
        bm, stub = wired
        monkeypatch.setenv("NEUROVA_CUA_REVIEW_TIMEOUT", "0.05")

        async def slow(action, params, context):
            await asyncio.sleep(2)
            return "allow"

        guardrail.setReviewer(slow)
        result = await bm.navigate("https://stranger.org/x")
        assert stub.navigateCalls == [], "复核超时 → sensitive 动作必须 0 执行"
        assert result.success is False
        assert result.data["guardrail"]["code"] == "guardrail_unavailable"

    @pytest.mark.asyncio
    async def test_sensitive_navigation_denied(self, wired):
        bm, stub = wired

        async def deny(action, params, context):
            return "deny"

        guardrail.setReviewer(deny)
        result = await bm.navigate("https://stranger.org/x")
        assert stub.navigateCalls == []
        assert result.success is False
        assert result.data["guardrail"]["code"] == "guardrail_denied"

    @pytest.mark.asyncio
    async def test_sensitive_navigation_allowed_after_review(self, wired):
        bm, stub = wired

        async def allow(action, params, context):
            return "allow"

        guardrail.setReviewer(allow)
        result = await bm.navigate("https://stranger.org/x")
        assert stub.navigateCalls == ["https://stranger.org/x"]
        assert result.success is True

    @pytest.mark.asyncio
    async def test_same_site_navigation_skips_review(self, wired):
        bm, stub = wired
        reviewed = []

        async def deny(action, params, context):
            reviewed.append(1)
            return "deny"

        guardrail.setReviewer(deny)
        result = await bm.navigate("https://app.example.com/page2")
        assert reviewed == [], "同站导航免审，不得打扰复核"
        assert result.success is True
        assert stub.navigateCalls == ["https://app.example.com/page2"]

    @pytest.mark.asyncio
    async def test_seen_link_navigation_skips_review(self, wired):
        bm, stub = wired
        stub.links = [{"text": "伙伴页", "href": "https://partner.io/landing"}]
        reviewed = []

        async def deny(action, params, context):
            reviewed.append(1)
            return "deny"

        guardrail.setReviewer(deny)
        await bm.extract_links()  # 当前页链接入册
        result = await bm.navigate("https://partner.io/landing")
        assert reviewed == [], "当前页已见链接免审"
        assert result.success is True
        assert stub.navigateCalls == ["https://partner.io/landing"]

    @pytest.mark.asyncio
    async def test_kill_switch_bypasses_guardrail(self, wired, monkeypatch):
        bm, stub = wired
        monkeypatch.setenv("NEUROVA_CUA_GUARDRAIL", "off")
        result = await bm.navigate("https://stranger.org/x")  # 无复核者也直通
        assert stub.navigateCalls == ["https://stranger.org/x"]
        assert result.success is True
