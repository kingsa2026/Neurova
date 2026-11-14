# -*- coding: utf-8 -*-
"""browser_install 工具 + 内核缺失分诊守卫。

## 背景

浏览器内核缺失时，browser_* 工具只会报「initialize() 返回失败」——模型与
用户都不知道是内核没装、也不知道能装。本批落地方案 A：

1. **分诊**：`diagnoseKernelFailure` 识别内核缺失（判据与 web_reach/browser_read
   同族），`initialize()` 失败把 `initFailure`（missing/install_command/
   remediation）挂在后端实例上，`_get_backend` 拒绝文案附加补救指引；
2. **受控安装**：`browser_install` 工具固定执行 `playwright install chromium`
   （不接受任意命令），装完 `reprobe()` 重建后端；`arbitrary_command` 高危档
   声明——**调用前模型必须经 ask_user 征得用户同意**（环境变更）。
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

TOOL = "browser_install"


# ── 五面登记 ──────────────────────────────────────────────

class TestToolFaces:
    def test_schemaRegistered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        assert TOOL in _BUILTIN_SCHEMAS, "schema 面缺登记（模型看不到）"

    def test_dispatchable(self):
        assert TOOL in ToolExecutor._builtin_dispatch, "派生面缺登记"

    def test_inGovernanceSurface(self):
        assert TOOL in COMPUTER_USE_TOOLS, "治理面缺登记"

    def test_paramKeysDeclaredAndMatchSchema(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        props = set(_BUILTIN_SCHEMAS[TOOL]["parameters"].get("properties", {}))
        assert set(_COMPUTER_TOOL_PARAM_KEYS[TOOL]) == props

    def test_permissionCategoryNetwork(self):
        from neurova.skills.permissions import tool_categories

        assert "network" in tool_categories(TOOL), "权限面未归类（会走未归类即放行）"

    def test_capabilityAndArbitraryCommandDeclared(self):
        from neurova.agent.tool_coordinator import resolveToolCapability
        from neurova.builtin_tools import get_builtin_tool_flags

        assert resolveToolCapability(TOOL) is not None
        flags = get_builtin_tool_flags(TOOL)
        assert flags.get("arbitrary_command") is True, "安装内核是环境变更命令，必须进高危档"

    def test_nonReproducible(self):
        from neurova.builtin_tools import _NON_REPRODUCIBLE_TOOLS

        assert TOOL in _NON_REPRODUCIBLE_TOOLS, "装内核是环境变更，重放会再改环境"

    def test_humanReadableActionDescription(self):
        assert "安装" in describe_computer_action(TOOL, {})


# ── 分诊 ──────────────────────────────────────────────

class TestDiagnosis:
    def test_kernelMissingDetected(self):
        from neurova.computer_use.browser_manager import diagnoseKernelFailure

        d = diagnoseKernelFailure("Executable doesn't exist at C:\\x. Please run playwright install")
        assert d and d["missing"] == "browser-kernel"
        assert "playwright install chromium" in d["install_command"]
        assert "同意" in d["remediation"], "补救指引必须点出'先征得用户同意'"

    def test_otherFailureNotMisdiagnosed(self):
        from neurova.computer_use.browser_manager import diagnoseKernelFailure

        assert diagnoseKernelFailure("connection refused") is None
        assert diagnoseKernelFailure("") is None

    @pytest.mark.asyncio
    async def test_initializeFailureCarriesDiagnosis(self, monkeypatch):
        """launch 报内核缺失时，initialize 失败必须把分诊挂在实例上。"""
        from neurova.computer_use.browser_manager import PlaywrightBackend

        class FakePw:
            async def start(self):
                raise RuntimeError("Executable doesn't exist at C:\\ms-playwright. Please run playwright install")

        monkeypatch.setattr("playwright.async_api.async_playwright", lambda: FakePw())
        b = PlaywrightBackend({})
        assert await b.initialize() is False
        assert b.initFailure and b.initFailure["missing"] == "browser-kernel"

    @pytest.mark.asyncio
    async def test_getBackendRefusalCarriesRemediation(self):
        """_get_backend 的拒绝文案必须带上补救指引——模型据此向用户转述并发起同意。"""
        from neurova.computer_use.browser_manager import BrowserManager, PlaywrightBackend

        bm = BrowserManager(config={})
        backend = PlaywrightBackend({})
        backend._initialized = False
        backend.initialize = AsyncMock(return_value=False)  # 不真启动浏览器，只走失败分支
        backend.initFailure = {
            "missing": "browser-kernel",
            "install_command": "playwright install chromium",
            "remediation": "浏览器内核缺失：可运行 playwright install chromium 安装",
        }
        bm._backends["playwright"] = backend
        with pytest.raises(RuntimeError) as ei:
            await bm._get_backend()
        assert "playwright install chromium" in str(ei.value)


# ── install_kernel / reprobe 行为 ─────────────────────────

class TestInstallKernel:
    @staticmethod
    def _manager():
        from neurova.computer_use.browser_manager import BrowserManager

        return BrowserManager(config={})

    @pytest.mark.asyncio
    async def test_installSuccessThenReprobe(self):
        bm = self._manager()

        async def fake_run(browser):
            assert browser == "chromium"
            return 0, "chromium is already installed"

        async def fake_reprobe():
            return {"ok": True, "backend": "playwright"}

        bm._runPlaywrightInstall = fake_run
        bm.reprobe = fake_reprobe
        result = await bm.install_kernel()
        assert result.success and result.data["probe"]["ok"] is True

    @pytest.mark.asyncio
    async def test_installFailureIsHonest(self):
        bm = self._manager()

        async def fake_run(browser):
            return 1, "download failed: network unreachable"

        bm._runPlaywrightInstall = fake_run
        result = await bm.install_kernel()
        assert not result.success and "network unreachable" in result.error

    @pytest.mark.asyncio
    async def test_onlyChromiumSupported(self):
        bm = self._manager()
        result = await bm.install_kernel("firefox")
        assert not result.success and "chromium" in result.error

    @pytest.mark.asyncio
    async def test_requiresPlaywrightPackage(self, monkeypatch):
        import neurova.computer_use.browser_manager as bmmod

        monkeypatch.setattr(bmmod, "HAS_PLAYWRIGHT", False)
        bm = self._manager()
        result = await bm.install_kernel()
        assert not result.success and "pip install playwright" in result.error

    @pytest.mark.asyncio
    async def test_reprobeRebuildsBackend(self):
        """reprobe 必须重建 playwright 后端条目——pop 掉不补会让选路落到 scrapling。"""
        bm = self._manager()
        stale = MagicMock()
        stale.close = AsyncMock(return_value=None)
        bm._backends["playwright"] = stale
        probe = await bm.reprobe()
        assert probe["ok"] is True, f"重探应成功: {probe}"
        assert "playwright" in bm._backends and bm._backends["playwright"] is not stale
        stale.close.assert_awaited_once()


# ── 执行链路（fake manager） ─────────────────────────────

class FakeInstallManager:
    def __init__(self):
        self.calls = []
        from neurova.computer_use.browser_manager import BrowserResult

        self._result = BrowserResult(success=True, data={"probe": {"ok": True}})

    async def browser_install(self, browser="chromium"):
        self.calls.append(("browser_install", browser))
        return self._result


@pytest.fixture
def executor(monkeypatch):
    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = MagicMock()
    inst._agent.current_session_id = None

    async def fake_emit(self, tool_name, params, result, screenshot_base64=None):
        return None

    monkeypatch.setattr(ToolExecutor, "_emit_computer_event", fake_emit)
    fake = FakeInstallManager()
    monkeypatch.setattr("neurova.computer_use.get_computer_use_manager", lambda: fake)
    return inst, fake


class TestExecutorWiring:
    @pytest.mark.asyncio
    async def test_installPassesBrowser(self, executor):
        inst, fake = executor
        result = await inst._execute_browser_install({})
        assert result["success"] is True
        assert fake.calls == [("browser_install", "chromium")]

    @pytest.mark.asyncio
    async def test_installPassesExplicitBrowser(self, executor):
        inst, fake = executor
        await inst._execute_browser_install({"browser": "chromium"})
        assert fake.calls == [("browser_install", "chromium")]
