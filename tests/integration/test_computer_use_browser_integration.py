# -*- coding: utf-8 -*-
"""配置面贯通 + 组件可见性单源判据（§25.4 已拍：B 改判到能力面、C 退役留反向锁）。

## 这个文件为什么被重写

原 15 例里有 10 例断言的是**从未存在过的门面**，逐条实测：

- `ComputerUseManager.get_status()` —— 生产没有这个方法（facade 的读侧叫
  `doctor_report()`），而脚本用 `except` 吞掉 `AttributeError` 后 `return`，
  于是它后半段从未执行过（工单集 §25.3 第 1 条）；
- `neurova.computer_use.HAS_BROWSER` —— 全仓 0 命中；
- `BrowserManager._camofox_adapter` / `CamofoxAdapter` —— 全仓 0 命中；
- `BrowserManager._supervisor` —— `BrowserSupervisor` 类存在但**零实例化**，
  构造需要一个从未接通的 CDP `ws_url`；
- 动作入参 `browser_navigate("test_agent", url, backend=…)` /
  `browser_screenshot(url, selector="#main", backend=…)` / `browser_snapshot(...)` ——
  生产签名分别是 `browser_navigate(url, generation=None)` 与 `browser_screenshot()`，
  且没有 `browser_snapshot` 这个方法。

## 采纳的两条处置

- **组件可见性不另立一张表**：原例子要的 `status["components"]` / `["dependencies"]` /
  `capabilities["browser_supervisor"]`，问的正是 T-07 已落地的 `capability_state` 六轴
  （"某个部件在不在、能不能用"）。再造一份就是教义第 6 条禁的第二份事实源。
- **旧契约退役 + 签名反向锁**：`agent_id` 手工传参是教义第 3 条点名的绕过装配点写法
  （T-01 已撤）、`selector=` 与 D-2"不暴露 selector/xpath"相反、`result["status"]`
  从未是生产形状（生产是 `BrowserResult.success`）。它们**不会被重新实现**，
  所以不挂 `xfail`（xfail 的语义是"将来要绿"），改为退役 + 签名反向锁拦回潮。
"""

from __future__ import annotations

import inspect
import os
import tempfile

import pytest
import yaml

from neurova.computer_use import (
    ComputerUseManager,
    get_computer_use_manager,
    reset_computer_use_manager,
)
from neurova.computer_use.browser_manager import (
    BrowserManager,
    get_browser_manager,
    reset_browser_manager,
)


def _writeYaml(tmp_path, payload) -> str:
    path = os.path.join(str(tmp_path), "backends.yaml")
    with open(path, "w", encoding="utf-8") as handle:
        yaml.dump(payload, handle)
    return path


@pytest.fixture(autouse=True)
def _cleanSingletons():
    """单例语义下"首次构造决定配置"，每例都从真 reset 入口起步。"""
    reset_computer_use_manager()
    reset_browser_manager()
    yield
    reset_computer_use_manager()
    reset_browser_manager()


class TestConfigPathReachesTheBrowserManager:
    """① 的贯通面：路径必须真走到 `BrowserManager`，否则 `_config_path` 只写不读。"""

    def test_explicitConfigPathIsRecordedOnTheFacade(self, tmp_path):
        path = _writeYaml(tmp_path, {"backends": {"playwright": {"headless": True}}})
        assert ComputerUseManager(config_path=path)._config_path == path

    def test_withoutConfigPathTheFacadeStaysUnconfigured(self):
        assert ComputerUseManager()._config_path is None

    def test_factoryKeepsSingletonIdentityAcrossCalls(self, tmp_path):
        path = _writeYaml(tmp_path, {"backends": {"playwright": {"headless": True}}})
        first = get_computer_use_manager(config_path=path)
        assert first._config_path == path
        assert get_computer_use_manager() is first, "工厂第二次调用换了实例"

    def testFacadeActuallyHandsThePathDownToBrowserManager(self, tmp_path, monkeypatch):
        """贯通的正证：路径停在 facade 上的话，配置文件对后端行为毫无影响。"""
        seen: list = []

        def spy(config=None, config_path=None):
            seen.append(config_path)
            return BrowserManager(config=config, config_path=config_path)

        import neurova.computer_use.browser_manager as bm

        monkeypatch.setattr(bm, "get_browser_manager", spy)
        path = _writeYaml(tmp_path, {"backends": {"playwright": {"headless": True}}})
        ComputerUseManager(config_path=path)._get_browser_manager()
        assert seen == [path], f"配置路径没交给 BrowserManager：{seen}"

    def testYamlFeedsDeclarationsAndRoutingTogether(self, tmp_path):
        """一份 YAML 同时喂"声明面"与"选路面"——两处各读各的就会漂。"""
        path = _writeYaml(tmp_path, {
            "routing": {"timeout": 60,
                        "rules": [{"pattern": r"test\.com", "backend": "playwright"}]},
            "backends": {"playwright": {"headless": False},
                         "scrapling-stealthy": {"mode": "stealth"}},
        })
        manager = BrowserManager(config_path=path)

        assert manager._config["routing"]["timeout"] == 60
        assert manager._backend_configs["playwright"]["headless"] is False
        assert "scrapling-stealthy" in manager._backend_configs, manager._backend_configs
        assert manager._resolve_backend("https://test.com/x") == "playwright"
        assert manager.configLoadError() is None


class TestComponentVisibilityHasOneOwner:
    """B 族改判：组件/依赖可见性只有能力面那一张表。"""

    def test_browserManagerGrowsNoSecondComponentTable(self):
        assert not hasattr(BrowserManager, "_camofox_adapter"), (
            "`CamofoxAdapter` 全仓 0 命中——补这个属性等于为凑判据造新抽象"
        )
        assert not hasattr(BrowserManager, "_supervisor"), (
            "`BrowserSupervisor` 是需要 CDP ws_url 的零实例化死类；挂到 manager 上等于"
            "接通一条没人走过的通道，而不是补契约"
        )
        status = BrowserManager(config={}).get_status()
        assert "components" not in status and "dependencies" not in status, (
            f"状态面又长出第二张组件表：{sorted(status)}"
        )

    def test_unconfiguredCamofoxCannotArmTheImpersonationGate(self):
        """两张表不得打架：能力面说"没配"，附身授权门就不能说"会以用户身份对外"。"""
        from neurova.computer_use import capability_state as cs

        manager = BrowserManager(config={})
        reading = cs.reading("camofox", refresh=True)
        assert reading.reason.strip(), "能力轴没有具名原因，读它等于没读"
        if reading.state == cs.CAP_NOT_CONFIGURED:
            assert manager.camofox_active() is False, (
                "camofox 未配置，附身授权门却判成会走登录态 profile"
            )
        else:
            # 反空转：配了 URL 的机器上，上一分支整条不执行——这里钉住
            # "具名原因必须带上它探的是哪个地址"，两档都必须交出可核对的读数
            assert "http" in reading.reason, (
                f"已配置却报不出探的是哪个地址，这条读数无法核对：{reading.asDict()}")

    def test_configuredCamofoxIsProbedEvenWhenPlaywrightOutranksIt(self, monkeypatch):
        """两个谓词的分界——本轮探针抓出来的缺陷就钉在这条上。

        能力轴曾拿授权门 `camofox_active()` 当"配没配"用：playwright 在册时它是 False，
        于是"配了 camofox"的机器上这条轴永远报 `not-configured`，那次真 `/health` 探测
        根本不会发生（§13.3 现场量的正是这个形态：URL 设了而 `:9377` 超时）。
        """
        from neurova.computer_use import capability_state as cs

        manager = BrowserManager(config={})
        assert "playwright" in manager.get_status()["available_backends"], (
            "前提变了：这台机器没有 playwright 在册，本条要的另一半无从判起")
        monkeypatch.setattr(manager, "camofoxConfigured", lambda: True)
        monkeypatch.setattr(manager, "camofoxBaseUrl", lambda: "http://127.0.0.1:1")
        monkeypatch.setattr(cs, "_browserManager", lambda: manager)

        reading = cs.reading("camofox", refresh=True)
        assert reading.state == cs.CAP_CONFIGURED_UNREACHABLE, (
            f"配了却没去真探（或探到却报别的）：{reading.asDict()}")
        assert manager.camofox_active() is False, (
            "playwright 在册时授权门必须仍说『不会以用户身份对外』——两个谓词不许合并")

    def test_ariaAxisMatchesTheRegisteredBackends(self):
        """aria 轴的可用性必须与在册后端表同口径。"""
        from neurova.computer_use import capability_state as cs

        registered = get_browser_manager().get_status()["available_backends"]
        reading = cs.reading("aria", refresh=True)
        if registered:
            assert reading.state == cs.CAP_AVAILABLE, (
                f"在册有 {registered} 却报 aria 不可用：{reading.asDict()}")
        else:
            assert reading.state != cs.CAP_AVAILABLE, (
                f"没有在册后端却报 aria 可用：{reading.asDict()}")


class TestFacadeDegradesWhenBrowserManagerIsUnreachable:
    """原 `status_without_browser` 的真实意图：拿不到浏览器时要落成读数而不是崩。"""

    def test_managerFailureBecomesAReadingInsteadOfAnException(self, monkeypatch):
        from neurova.computer_use import capability_state as cs

        def broken():
            raise RuntimeError("浏览器管理器起不来")

        monkeypatch.setattr(cs, "_browserManager", broken)
        for axis in ("aria", "camofox"):
            cs.invalidate(axis)
            reading = cs.reading(axis, refresh=True)
            assert reading.state == cs.CAP_CONFIGURED_UNREACHABLE, reading.asDict()
            assert "浏览器管理器起不来" in reading.reason, reading.asDict()


class TestRetiredArgumentShapesCannotComeBack:
    """C 族退役后的反向锁：这些入参形状是被决策撤掉的，不是待实现的。"""

    def test_browserActionsTakeNoAgentArgument(self):
        """`agent_id` 手工传参 = 绕过装配点（教义第 3 条点名，T-01 已撤）。"""
        manager = ComputerUseManager()
        for action in ("browser_navigate", "browser_screenshot", "browser_dom_snapshot",
                       "browser_click_role", "browser_click_ref"):
            params = list(inspect.signature(getattr(manager, action)).parameters)
            assert "agent_id" not in params and "agentId" not in params, \
                f"{action} 又收 agent_id：{params}"

    def test_refAddressingStillExposesNoSelectorPath(self):
        """D-2：ref 工具的参数面不得出现 selector/xpath/css/query。"""
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        for tool in ("browser_click_ref", "browser_fill_ref"):
            props = set(_BUILTIN_SCHEMAS[tool]["parameters"]["properties"])
            forbidden = {p for p in props
                         if any(k in p.lower() for k in ("selector", "xpath", "css", "query"))}
            assert not forbidden, f"{tool} 长出了绕开快照事实的入口：{sorted(forbidden)}"

    def test_facadeScreenshotTakesNoUrlOrSelector(self):
        """截图打的是当前活动 tab；`url`/`selector`/`backend` 三个位都属于旧契约。"""
        params = list(inspect.signature(ComputerUseManager().browser_screenshot).parameters)
        assert params == [], f"browser_screenshot 的入参面又长出东西：{params}"
