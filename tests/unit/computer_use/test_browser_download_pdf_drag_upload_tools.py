# -*- coding: utf-8 -*-
"""browser_download/pdf/drag/upload 四工具接线守卫（P3 批D：采集与扩展）。

download：context.request 拉 URL 字节 → persist_bytes 落产物目录（与 write_pdf
同一落盘单源，复用产物命名/白名单口径）；pdf：page.pdf 打印当前页落产物目录；
drag/upload：role+name 定位协议补齐拖拽与文件上传。frame（iframe 内操作）
本轮裁掉——复杂度高且主文档+eval 可覆盖大部分场景，待真实需求再上。

重放轴口径：四个全部进 _NON_REPRODUCIBLE_TOOLS——download/pdf 落盘产物
（重放登记出第二份产物），drag/upload 是页面写操作。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.tool_executor import (
    _COMPUTER_TOOL_PARAM_KEYS,
    COMPUTER_USE_TOOLS,
    ToolExecutor,
    describe_computer_action,
)

NEW_TOOLS = ("browser_download", "browser_pdf", "browser_drag", "browser_upload")


class TestToolFaces:
    def test_schemasRegistered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        missing = [n for n in NEW_TOOLS if n not in _BUILTIN_SCHEMAS]
        assert not missing, f"schema 面缺登记: {missing}"

    def test_dispatchable(self):
        missing = [n for n in NEW_TOOLS if n not in ToolExecutor._builtin_dispatch]
        assert not missing, f"派生面缺登记: {missing}"

    def test_inGovernanceSurface(self):
        missing = [n for n in NEW_TOOLS if n not in COMPUTER_USE_TOOLS]
        assert not missing, f"治理面缺登记: {missing}"

    def test_paramKeysDeclaredAndMatchSchema(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        for name in NEW_TOOLS:
            assert name in _COMPUTER_TOOL_PARAM_KEYS, f"{name} 缺参数白名单"
            props = set(_BUILTIN_SCHEMAS[name]["parameters"].get("properties", {}))
            declared = set(_COMPUTER_TOOL_PARAM_KEYS[name])
            assert declared == props, f"{name} 参数面 {sorted(declared)} != schema {sorted(props)}"

    def test_permissionCategoryNetwork(self):
        from neurova.skills.permissions import tool_categories

        unclassified = [n for n in NEW_TOOLS if "network" not in tool_categories(n)]
        assert not unclassified, f"权限面未归类: {unclassified}"

    def test_capabilityDeclared(self):
        from neurova.agent.tool_coordinator import resolveToolCapability

        undeclared = [n for n in NEW_TOOLS if resolveToolCapability(n) is None]
        assert not undeclared, f"未声明并行能力: {undeclared}"

    def test_reproducibleAxisAllNonReproducible(self):
        from neurova.builtin_tools import _NON_REPRODUCIBLE_TOOLS

        missing = sorted(set(NEW_TOOLS) - set(_NON_REPRODUCIBLE_TOOLS))
        assert not missing, f"落盘产物/页面写操作漏出不可重现名单: {missing}"

    def test_humanReadableActionDescription(self):
        assert "下载" in describe_computer_action("browser_download", {"url": "https://x/f.zip"})
        assert "PDF" in describe_computer_action("browser_pdf", {})
        assert "拖拽" in describe_computer_action("browser_drag", {"source_role": "button"})
        assert "上传" in describe_computer_action("browser_upload", {"role": "button", "paths": ["a"]})


class TestPlaywrightBackend:
    @staticmethod
    def _backend():
        from neurova.computer_use.browser_manager import PlaywrightBackend

        b = PlaywrightBackend({})
        page = MagicMock()
        page.url = "https://example.com/page"
        page.title = AsyncMock(return_value="t")
        page.pdf = AsyncMock(return_value=b"%PDF-fake")
        context = MagicMock()
        response = MagicMock()
        response.status = 200
        response.body = AsyncMock(return_value=b"file-bytes")
        context.request = MagicMock()
        context.request.get = AsyncMock(return_value=response)
        b._context = context
        locator = MagicMock()
        locator.drag_to = AsyncMock(return_value=None)
        locator.set_input_files = AsyncMock(return_value=None)
        page.get_by_role = MagicMock(return_value=locator)
        tab = {"page": page, "generation": 1}
        b._tabs = {"tab_t": tab}
        b._active_target_id = "tab_t"
        return b, page, context, locator, tab

    @staticmethod
    def _patchPersist(monkeypatch):
        async def fake_persist(data, ext, task_id, index=0, out_dir=None):
            return f"/fake/out/{task_id}.{ext}"

        monkeypatch.setattr("neurova.llm.generators.runtime.persist_bytes", fake_persist)

    @pytest.mark.asyncio
    async def test_pdfPersistsAndReportsPath(self, monkeypatch):
        b, page, _, _, _ = self._backend()
        self._patchPersist(monkeypatch)
        result = await b.print_pdf()
        assert result.success
        page.pdf.assert_awaited_once()
        assert result.data["file_path"] == "/fake/out/browser-pdf.pdf"
        assert result.data["bytes"] == len(b"%PDF-fake")

    @pytest.mark.asyncio
    async def test_downloadFetchesAndPersists(self, monkeypatch):
        b, _, context, _, _ = self._backend()
        self._patchPersist(monkeypatch)
        result = await b.download_file("https://example.com/f/data.csv")
        assert result.success
        context.request.get.assert_awaited_once_with("https://example.com/f/data.csv")
        assert result.data["file_path"] == "/fake/out/browser-download.csv"
        assert result.data["bytes"] == len(b"file-bytes")
        assert result.data["status"] == 200

    @pytest.mark.asyncio
    async def test_downloadNon2xxIsHonest(self, monkeypatch):
        b, _, context, _, _ = self._backend()
        context.request.get = AsyncMock(return_value=MagicMock(status=404, body=AsyncMock(return_value=b"no")))
        result = await b.download_file("https://example.com/missing")
        assert not result.success and "404" in result.error

    @pytest.mark.asyncio
    async def test_downloadRequiresUrl(self, monkeypatch):
        b, _, _, _, _ = self._backend()
        result = await b.download_file("  ")
        assert not result.success and "url" in result.error

    @pytest.mark.asyncio
    async def test_dragUsesRoleLocators(self):
        b, page, _, locator, tab = self._backend()
        result = await b.drag_role("button", "拖块", "textbox", "落点", generation=1)
        assert result.success
        assert page.get_by_role.call_count == 2
        locator.drag_to.assert_awaited_once()
        assert tab["generation"] == 2

    @pytest.mark.asyncio
    async def test_dragRequiresBothRoles(self):
        b, _, _, _, _ = self._backend()
        result = await b.drag_role("", None, "textbox", None)
        assert not result.success and "source_role" in result.error
        result2 = await b.drag_role("button", None, " ", None)
        assert not result2.success and "target_role" in result2.error

    @pytest.mark.asyncio
    async def test_uploadSetsFiles(self, tmp_path):
        b, page, _, locator, _ = self._backend()
        f = tmp_path / "a.txt"
        f.write_text("hi")
        result = await b.upload_files("button", [str(f)], name="上传", generation=1)
        assert result.success
        locator.set_input_files.assert_awaited_once()
        assert locator.set_input_files.await_args.args[0] == [str(f)]

    @pytest.mark.asyncio
    async def test_uploadRejectsMissingFile(self, tmp_path):
        b, _, _, _, _ = self._backend()
        result = await b.upload_files("button", [str(tmp_path / "nope.txt")])
        assert not result.success and "不存在" in result.error

    @pytest.mark.asyncio
    async def test_uploadRejectsEmptyPaths(self, tmp_path):
        b, _, _, _, _ = self._backend()
        result = await b.upload_files("button", [])
        assert not result.success and "paths" in result.error


class FakeCollectManager:
    def __init__(self):
        self.calls = []
        from neurova.computer_use.browser_manager import BrowserResult

        self._result = BrowserResult(success=True)

    async def browser_download(self, url, filename=None, generation=None):
        self.calls.append(("browser_download", url, filename, generation))
        return self._result

    async def browser_pdf(self, generation=None):
        self.calls.append(("browser_pdf", generation))
        return self._result

    async def browser_drag(self, source_role, target_role, source_name=None, target_name=None, generation=None):
        self.calls.append(("browser_drag", source_role, target_role, source_name, target_name, generation))
        return self._result

    async def browser_upload(self, role, paths, name=None, generation=None):
        self.calls.append(("browser_upload", role, list(paths), name, generation))
        return self._result


@pytest.fixture
def executor(monkeypatch):
    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = MagicMock()
    inst._agent.current_session_id = None

    async def fake_emit(self, tool_name, params, result, screenshot_base64=None):
        return None

    monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
    fake = FakeCollectManager()
    monkeypatch.setattr("neurova.computer_use.get_computer_use_manager", lambda: fake)
    return inst, fake


class TestExecutorWiring:
    @pytest.mark.asyncio
    async def test_downloadPassesUrl(self, executor):
        inst, fake = executor
        result = await inst._execute_browser_download({"url": "https://x/f.zip"})
        assert result["success"] is True
        assert fake.calls[0][:3] == ("browser_download", "https://x/f.zip", None)

    @pytest.mark.asyncio
    async def test_downloadRequiresUrl(self, executor):
        inst, fake = executor
        assert "error" in await inst._execute_browser_download({})
        assert fake.calls == []

    @pytest.mark.asyncio
    async def test_pdfNoArgs(self, executor):
        inst, fake = executor
        result = await inst._execute_browser_pdf({})
        assert result["success"] is True
        assert fake.calls[0][0] == "browser_pdf"

    @pytest.mark.asyncio
    async def test_dragPassesRoles(self, executor):
        inst, fake = executor
        result = await inst._execute_browser_drag({"source_role": "button", "target_role": "textbox", "source_name": "a", "target_name": "b"})
        assert result["success"] is True
        assert fake.calls[0] == ("browser_drag", "button", "textbox", "a", "b", None)

    @pytest.mark.asyncio
    async def test_dragRequiresRoles(self, executor):
        inst, fake = executor
        assert "error" in await inst._execute_browser_drag({"target_role": "textbox"})
        assert "error" in await inst._execute_browser_drag({"source_role": "button"})
        assert fake.calls == []

    @pytest.mark.asyncio
    async def test_uploadPassesPaths(self, executor, tmp_path):
        inst, fake = executor
        f = tmp_path / "a.txt"
        f.write_text("x")
        result = await inst._execute_browser_upload({"role": "button", "paths": [str(f)]})
        assert result["success"] is True
        assert fake.calls[0][:3] == ("browser_upload", "button", [str(f)])

    @pytest.mark.asyncio
    async def test_uploadRequiresRoleAndPaths(self, executor):
        inst, fake = executor
        assert "error" in await inst._execute_browser_upload({"paths": ["x"]})
        assert "error" in await inst._execute_browser_upload({"role": "button"})
        assert fake.calls == []
