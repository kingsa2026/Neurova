"""CamofoxServerBackend 单元测试

TDD 步骤（红→绿）：
- 红：本文件先写，验证未实现时的失败状态
- 绿：实现 CamofoxServerBackend 直到测试通过

Mock 策略：
- 替换 backend._client 为 AsyncMock（httpx.AsyncClient 接口）
- 不使用 respx（项目未引入，调研已确认）
- 复刻 test_target_generation.py / test_aria_snapshot_integration.py 的 MagicMock 风格
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from neurova.computer_use.camofox_server_backend import (
    CamofoxServerBackend,
    _find_ref_in_yaml,
)


# ── 工具函数 ──


def _http_response(payload: dict | None = None, content: bytes = b"{}") -> MagicMock:
    """构造一个 httpx Response 替身：带 .json() / .content / .raise_for_status()"""
    r = MagicMock()
    r.status_code = 200
    r.content = content
    r.json = MagicMock(return_value=payload or {})
    r.raise_for_status = MagicMock(return_value=None)
    return r


def _make_backend(
    *,
    request_side_effect: list | None = None,
    request_return: MagicMock | None = None,
) -> tuple[CamofoxServerBackend, MagicMock]:
    """构造一个带 mock httpx 客户端的后端，跳过 initialize。

    返回 (backend, client_mock)。client_mock.request 是 AsyncMock。
    """
    client = MagicMock()
    if request_side_effect is not None:
        client.request = AsyncMock(side_effect=request_side_effect)
    elif request_return is not None:
        client.request = AsyncMock(return_value=request_return)
    else:
        client.request = AsyncMock(return_value=_http_response({}))
    client.get = AsyncMock(return_value=_http_response({"ok": True}))
    client.aclose = AsyncMock(return_value=None)

    b = CamofoxServerBackend({"base_url": "http://test:9377"})
    b._client = client
    b._initialized = True
    return b, client


def _seed_tab(
    b: CamofoxServerBackend,
    *,
    target_id: str = "tab_abc",
    tab_id: str = "cf_xyz",
    generation: int = 1,
    url: str = "https://x",
) -> str:
    """手动登记一个 tab，跳过 HTTP 调用"""
    b._tabs[target_id] = {
        "tab_id": tab_id,
        "generation": generation,
        "url": url,
        "title": "",
    }
    b._active_target_id = target_id
    return target_id


# ── 测试类 ──


class TestCamofoxServerBackendInit:
    """构造与配置读取"""

    def test_default_base_url(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_CAMOFOX_URL", raising=False)
        b = CamofoxServerBackend()
        assert b._base_url == "http://localhost:9377"

    def test_env_overrides_config(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_CAMOFOX_URL", "http://envhost:1234")
        monkeypatch.setenv("NEUROVA_CAMOFOX_ACCESS_KEY", "secret123")
        monkeypatch.setenv("NEUROVA_CAMOFOX_USER", "agent42")
        b = CamofoxServerBackend()
        assert b._base_url == "http://envhost:1234"
        assert b._access_key == "secret123"
        assert b._user_id == "agent42"

    def test_explicit_config_overrides_env(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_CAMOFOX_URL", "http://env:1")
        b = CamofoxServerBackend({
            "base_url": "http://cfg:2",
            "access_key": "cfg-key",
            "user_id": "cfg-user",
        })
        assert b._base_url == "http://cfg:2"
        assert b._access_key == "cfg-key"
        assert b._user_id == "cfg-user"


class TestCapabilities:
    """能力清单对齐 PlaywrightBackend"""

    def test_camofox_supports_aria_role_pixel(self):
        b = CamofoxServerBackend()
        assert b.capabilities == {
            "aria_snapshot": True,
            "role_locator": True,
            "pixel_screenshot": True,
        }


class TestNavigate:
    """navigate 路径：复用活动 tab / 新建 tab / generation 递增 / stale 拒绝"""

    @pytest.mark.asyncio
    async def test_navigate_without_active_tab_creates_new(self):
        b, client = _make_backend(request_return=_http_response({"tabId": "cf_new"}))
        r = await b.navigate("https://example.com")
        assert r.success is True
        assert r.generation == 1
        assert b._active_target_id is not None
        assert b._tabs[b._active_target_id]["tab_id"] == "cf_new"
        # 第一次调用必须是 POST /tabs
        call = client.request.call_args
        assert call.args == ("POST", "/tabs")
        assert call.kwargs["json"]["url"] == "https://example.com"
        assert "sessionKey" in call.kwargs["json"]
        assert call.kwargs["json"]["userId"] == "neurova"

    @pytest.mark.asyncio
    async def test_navigate_with_active_tab_reuses_and_bumps_generation(self):
        b, client = _make_backend(request_return=_http_response({"url": "https://new"}))
        _seed_tab(b, generation=3)
        r = await b.navigate("https://new")
        assert r.success is True
        assert r.generation == 4  # 3 + 1
        # 第二次调用必须是 POST /tabs/:tab_id/navigate
        call = client.request.call_args
        assert call.args == ("POST", "/tabs/cf_xyz/navigate")
        assert call.kwargs["json"]["url"] == "https://new"

    @pytest.mark.asyncio
    async def test_navigate_stale_generation_rejected_without_http(self):
        b, client = _make_backend()
        _seed_tab(b, generation=2)
        r = await b.navigate("https://x", generation=99)
        assert r.success is False
        assert r.data["stale"] is True
        assert r.data["current_generation"] == 2
        client.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_navigate_omitted_generation_skips_check(self):
        b, _client = _make_backend(request_return=_http_response({"url": "https://x"}))
        _seed_tab(b, generation=5)
        r = await b.navigate("https://x")  # 不传 generation
        assert r.success is True
        assert r.generation == 6


class TestDomSnapshot:
    """dom_snapshot 返回 YAML 文本 + refs_count"""

    @pytest.mark.asyncio
    async def test_snapshot_returns_yaml_and_refs_count(self):
        snap = "- heading 'Title' [e1]\n- button 'Login' [e3]\n"
        b, client = _make_backend(
            request_return=_http_response({"snapshot": snap, "refsCount": 2, "url": "https://x"}),
        )
        _seed_tab(b)
        r = await b.dom_snapshot()
        assert r.success is True
        assert r.data["snapshot"] == snap
        assert r.data["refs_count"] == 2
        assert r.data["truncated"] is False
        call = client.request.call_args
        assert call.args == ("GET", "/tabs/cf_xyz/snapshot")
        assert call.kwargs["params"]["userId"] == "neurova"

    @pytest.mark.asyncio
    async def test_snapshot_default_truncated_false(self):
        b, _client = _make_backend(request_return=_http_response({"snapshot": "x", "refsCount": 0}))
        _seed_tab(b)
        r = await b.dom_snapshot()
        assert r.data["truncated"] is False

    @pytest.mark.asyncio
    async def test_snapshot_stale_rejected(self):
        b, client = _make_backend()
        _seed_tab(b, generation=1)
        r = await b.dom_snapshot(generation=99)
        assert r.success is False
        assert r.data["stale"] is True
        client.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_snapshot_without_active_tab_returns_error(self):
        b, _client = _make_backend()
        r = await b.dom_snapshot()
        assert r.success is False
        assert "无活动" in r.error


class TestRoleLocator:
    """click_role/fill_role：先 snapshot → 正则找 ref → 调 click/type"""

    @pytest.mark.asyncio
    async def test_click_role_finds_ref_then_clicks(self):
        snap_resp = _http_response({
            "snapshot": "- heading 'Title'\n- button '登录' [e5]\n",
            "refsCount": 1,
        })
        click_resp = _http_response({"ok": True})
        b, client = _make_backend(request_side_effect=[snap_resp, click_resp])
        _seed_tab(b)
        r = await b.click_role("button", name="登录")
        assert r.success is True
        # 第二次调用必须是 POST /tabs/cf_xyz/click with ref=e5
        assert client.request.await_count == 2
        click_call = client.request.call_args_list[1]
        assert click_call.args == ("POST", "/tabs/cf_xyz/click")
        assert click_call.kwargs["json"]["ref"] == "e5"
        assert click_call.kwargs["json"]["userId"] == "neurova"

    @pytest.mark.asyncio
    async def test_click_role_role_only_picks_first(self):
        snap_resp = _http_response({
            "snapshot": "- button 'A' [e1]\n- button 'B' [e2]",
            "refsCount": 2,
        })
        click_resp = _http_response({"ok": True})
        b, client = _make_backend(request_side_effect=[snap_resp, click_resp])
        _seed_tab(b)
        r = await b.click_role("button")  # 不带 name
        assert r.success is True
        click_call = client.request.call_args_list[1]
        assert click_call.kwargs["json"]["ref"] == "e1"

    @pytest.mark.asyncio
    async def test_click_role_ref_not_found_returns_clear_error(self):
        b, client = _make_backend(
            request_return=_http_response({"snapshot": "- link 'Other' [e9]", "refsCount": 1}),
        )
        _seed_tab(b)
        r = await b.click_role("button", name="登录")
        assert r.success is False
        assert "未找到" in r.error
        # 不再发起 click HTTP 调用
        assert client.request.await_count == 1

    @pytest.mark.asyncio
    async def test_click_role_empty_role_rejected_without_http(self):
        b, client = _make_backend()
        _seed_tab(b)
        r = await b.click_role("")
        assert r.success is False
        assert "缺少 ARIA role" in r.error
        client.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_fill_role_calls_type_endpoint(self):
        snap_resp = _http_response({"snapshot": "- textbox '搜索' [e7]:", "refsCount": 1})
        type_resp = _http_response({"ok": True})
        b, client = _make_backend(request_side_effect=[snap_resp, type_resp])
        _seed_tab(b)
        r = await b.fill_role("textbox", name="搜索", text="hello")
        assert r.success is True
        type_call = client.request.call_args_list[1]
        assert type_call.args == ("POST", "/tabs/cf_xyz/type")
        assert type_call.kwargs["json"]["ref"] == "e7"
        assert type_call.kwargs["json"]["text"] == "hello"
        assert type_call.kwargs["json"]["clear"] is True

    @pytest.mark.asyncio
    async def test_fill_role_rejects_none_text(self):
        b, client = _make_backend()
        _seed_tab(b)
        r = await b.fill_role("textbox", name="x", text=None)
        assert r.success is False
        assert "缺少输入文本" in r.error
        client.request.assert_not_called()


class TestTabLifecycle:
    """open_target / list_targets / switch_target / close_target"""

    @pytest.mark.asyncio
    async def test_open_target_registers_and_activates(self):
        b, client = _make_backend(request_return=_http_response({"tabId": "cf_opened"}))
        r = await b.open_target("https://x")
        assert r.success is True
        assert r.generation == 1
        assert b._active_target_id in b._tabs
        assert b._tabs[b._active_target_id]["tab_id"] == "cf_opened"

    @pytest.mark.asyncio
    async def test_open_target_without_url_uses_about_blank(self):
        b, client = _make_backend(request_return=_http_response({"tabId": "cf_blank"}))
        r = await b.open_target()
        assert r.success is True
        call = client.request.call_args
        assert call.kwargs["json"]["url"] == "about:blank"

    @pytest.mark.asyncio
    async def test_list_targets_includes_all_tabs(self):
        b, _client = _make_backend()
        _seed_tab(b, target_id="t1", generation=2, url="https://a")
        _seed_tab(b, target_id="t2", generation=5, url="https://b")
        r = await b.list_targets()
        assert r.success is True
        assert len(r.data) == 2
        # 包含 target_id / generation / url / active
        ids = {row["target_id"] for row in r.data}
        assert ids == {"t1", "t2"}
        active = [row for row in r.data if row["active"]]
        assert len(active) == 1
        assert active[0]["target_id"] == "t2"  # 最后 seed 的

    @pytest.mark.asyncio
    async def test_switch_target_stale_rejected(self):
        b, _client = _make_backend()
        _seed_tab(b, generation=2)
        old_active = b._active_target_id
        r = await b.switch_target(old_active, generation=99)
        assert r.success is False
        assert r.data["stale"] is True
        # 活动 tab 不变
        assert b._active_target_id == old_active

    @pytest.mark.asyncio
    async def test_switch_target_unknown_returns_error(self):
        b, _client = _make_backend()
        r = await b.switch_target("nonexistent")
        assert r.success is False
        assert "不存在" in r.error

    @pytest.mark.asyncio
    async def test_close_active_falls_back_to_remaining(self):
        b, client = _make_backend(request_return=_http_response({"ok": True}))
        _seed_tab(b, target_id="t1", generation=1)
        _seed_tab(b, target_id="t2", generation=1)
        assert b._active_target_id == "t2"
        r = await b.close_target("t2")
        assert r.success is True
        assert "t2" not in b._tabs
        assert b._active_target_id == "t1"

    @pytest.mark.asyncio
    async def test_close_unknown_target_returns_error(self):
        b, _client = _make_backend()
        r = await b.close_target("nonexistent")
        assert r.success is False


class TestScreenshot:
    """screenshot 返回 base64 PNG"""

    @pytest.mark.asyncio
    async def test_screenshot_returns_base64_png(self):
        # camofox /screenshot 返回二进制，不是 JSON；用 get 走二进制
        b = CamofoxServerBackend({"base_url": "http://test:9377"})
        client = MagicMock()
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"fake-png-data"
        resp = MagicMock()
        resp.status_code = 200
        resp.content = png_bytes
        resp.raise_for_status = MagicMock(return_value=None)
        client.get = AsyncMock(return_value=resp)
        client.aclose = AsyncMock(return_value=None)
        b._client = client
        b._initialized = True
        _seed_tab(b)

        r = await b.screenshot()
        assert r.success is True
        import base64
        assert base64.b64decode(r.screenshot) == png_bytes
        # 调用了正确的 URL
        call = client.get.call_args
        assert call.args == ("/tabs/cf_xyz/screenshot",)
        assert call.kwargs["params"]["userId"] == "neurova"


class TestExtractAndExecute:
    """extract_text / extract_links / execute_js / snapshot"""

    @pytest.mark.asyncio
    async def test_extract_text_returns_inner_text(self):
        b, client = _make_backend(request_return=_http_response({"result": "hello world"}))
        _seed_tab(b)
        r = await b.extract_text()
        assert r.success is True
        assert r.data == "hello world"
        call = client.request.call_args
        assert call.args == ("POST", "/tabs/cf_xyz/evaluate")
        assert "innerText" in call.kwargs["json"]["expression"]

    @pytest.mark.asyncio
    async def test_extract_links_returns_array(self):
        b, _client = _make_backend(
            request_return=_http_response({"result": [{"text": "a", "href": "https://x"}]}),
        )
        _seed_tab(b)
        r = await b.extract_links()
        assert r.success is True
        assert r.data == [{"text": "a", "href": "https://x"}]

    @pytest.mark.asyncio
    async def test_execute_js_returns_result(self):
        b, client = _make_backend(request_return=_http_response({"result": 42}))
        _seed_tab(b)
        r = await b.execute_js("1 + 41")
        assert r.success is True
        assert r.data == 42
        assert client.request.call_args.kwargs["json"]["expression"] == "1 + 41"


class TestClose:
    """close 释放资源"""

    @pytest.mark.asyncio
    async def test_close_closes_client_and_clears_tabs(self):
        b, client = _make_backend()
        _seed_tab(b)
        await b.close()
        client.aclose.assert_awaited_once()
        assert b._tabs == {}
        assert b._active_target_id is None
        assert b._client is None


class TestYamlRefFinder:
    """_find_ref_in_yaml 纯函数测试"""

    def test_finds_match_with_name(self):
        yaml = "- heading 'Title'\n- button 'Login' [e3]\n- textbox '搜索' [e5]:"
        assert _find_ref_in_yaml(yaml, "button", "Login") == "e3"
        assert _find_ref_in_yaml(yaml, "textbox", "搜索") == "e5"

    def test_finds_first_role_match_when_name_omitted(self):
        yaml = "- button 'A' [e1]\n- button 'B' [e2]"
        assert _find_ref_in_yaml(yaml, "button", None) == "e1"

    def test_no_match_returns_none(self):
        yaml = "- link 'Other' [e9]"
        assert _find_ref_in_yaml(yaml, "button", "Login") is None

    def test_role_mismatch_returns_none(self):
        yaml = "- link 'Login' [e1]"  # role=link 不是 button
        assert _find_ref_in_yaml(yaml, "button", "Login") is None

    def test_empty_yaml(self):
        assert _find_ref_in_yaml("", "button", "x") is None

    def test_nested_yaml_picks_top_level_first(self):
        # camofox 缩进表示嵌套，取第一个匹配即可
        yaml = "- main:\n  - button 'Submit' [e7]"
        assert _find_ref_in_yaml(yaml, "button", "Submit") == "e7"


class TestBrowserManagerRegistration:
    """BrowserManager._load_config 注册行为"""

    def test_camofox_not_registered_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_CAMOFOX_URL", raising=False)
        from neurova.computer_use.browser_manager import BrowserManager
        mgr = BrowserManager()
        assert "camofox" not in mgr._backends
        status = mgr.get_status()
        assert status["has_camofox_server"] is False

    def test_camofox_registered_when_env_set(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_CAMOFOX_URL", "http://test:9377")
        from neurova.computer_use.browser_manager import BrowserManager
        mgr = BrowserManager()
        if "camofox" not in mgr._backends:
            pytest.skip("httpx not installed in test env")
        assert isinstance(mgr._backends["camofox"], CamofoxServerBackend)
        status = mgr.get_status()
        assert status["has_camofox_server"] is True
        assert status["camofox_url"] == "http://test:9377"

    def test_camofox_registered_when_config_enabled(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_CAMOFOX_URL", raising=False)
        from neurova.computer_use.browser_manager import BrowserManager
        mgr = BrowserManager({"camofox": {"enabled": True, "base_url": "http://cfg:1"}})
        if "camofox" not in mgr._backends:
            pytest.skip("httpx not installed in test env")
        assert mgr._backends["camofox"]._base_url == "http://cfg:1"