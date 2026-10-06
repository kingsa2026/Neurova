"""R1-1 桌面 UIA 语义层

契约（与浏览器侧对齐）：
- snapshot: {generation, window, elements[{index, role, name, rect, enabled, value, focused,
  settable, invokable, runtime_id}], truncated}；预算 max_nodes/max_depth 硬顶
- click_element 五级递降链：Invoke → Toggle → Expand → LegacyDefault → PostMessage(app_post)
  → 全局输入（env 门控 NEUROVA_ALLOW_GLOBAL_INPUT=1，默认关）
- 每级结果写 route + effect；全链失败 → refused background_unavailable + escalation
- generation：动作成功后递增（快照事实消费）；显式传过期 generation → refused
- set_value：ValuePattern 优先（value_readback 证据）→ 全局键入（门控）→ 拒绝

测试用 FakeUIABackend（与真实 UiautomationBackend 契约逐字段对齐，09-11 纪律）。
"""

import pytest

from neurova.computer_use import desktop_uia


def make_element(**overrides):
    base = {
        "role": "button",
        "name": "确定",
        "rect": (10, 20, 80, 30),
        "enabled": True,
        "value": None,
        "focused": False,
        "settable": False,
        "invokable": True,
        "togglable": False,
        "expandable": False,
        "legacy_default": False,
        "runtime_id": "42.1.7",
    }
    base.update(overrides)
    return base


class FakeUIABackend:
    """与真实后端同契约的测试替身；行为通过 flags 控制"""

    def __init__(self, elements=None, windows=None):
        self.elements = elements if elements is not None else [make_element()]
        self.windows = windows  # None → 单窗口缺省
        self.calls = []
        self.invoke_ok = True
        self.set_value_readback = "new-value"
        self.post_click_ok = True
        self.window_found = True

    def available(self):
        return True

    def get_window(self, window_title=None):
        self.calls.append(("get_window", window_title))
        if not self.window_found:
            return None
        return {"title": "记事本", "rect": (0, 0, 800, 600), "pid": 4242, "hwnd": 100}

    def walk(self, window, max_nodes, max_depth):
        self.calls.append(("walk", max_nodes, max_depth))
        return [dict(e) for e in self.elements][:max_nodes]

    def invoke(self, element):
        self.calls.append(("invoke", element["runtime_id"]))
        return self.invoke_ok

    def toggle(self, element):
        self.calls.append(("toggle", element["runtime_id"]))
        return True

    def expand(self, element):
        self.calls.append(("expand", element["runtime_id"]))
        return True

    def legacy_default(self, element):
        self.calls.append(("legacy", element["runtime_id"]))
        return True

    def post_click(self, element, button):
        self.calls.append(("post_click", element["runtime_id"], button))
        return self.post_click_ok

    def global_click(self, element, button):
        self.calls.append(("global_click", element["runtime_id"], button))
        return True

    def set_value(self, element, value):
        self.calls.append(("set_value", element["runtime_id"], value))
        return self.set_value_readback

    def focus(self, element):
        self.calls.append(("focus", element["runtime_id"]))
        return True

    def global_type(self, value):
        self.calls.append(("global_type", value))
        return True


@pytest.fixture
def manager():
    backend = FakeUIABackend()
    mgr = desktop_uia.DesktopUIAManager(backend=backend)
    return mgr, backend


class TestSnapshot:
    def test_snapshot_shape(self, manager):
        mgr, backend = manager
        result = mgr.snapshot()
        assert result["success"] is True
        assert result["generation"] == 1
        assert result["window"]["title"] == "记事本"
        els = result["elements"]
        assert els[0]["index"] == 0 and els[0]["role"] == "button"
        assert els[0]["runtime_id"] == "42.1.7"
        # 观察型结果不携带动作契约（无投递语义）
        assert "action_result" not in result

    def test_snapshot_budget_truncates(self, manager):
        mgr, backend = manager
        backend.elements = [make_element(name=f"btn{i}", runtime_id=str(i)) for i in range(10)]
        result = mgr.snapshot(max_nodes=3)
        assert len(result["elements"]) == 3
        assert result["truncated"] is True

    def test_snapshot_window_not_found_refused(self, manager):
        mgr, backend = manager
        backend.window_found = False
        result = mgr.snapshot(window_title="不存在")
        assert result["success"] is False
        assert result["action_result"]["refusal_code"] == "ref_not_found"

    def test_snapshot_without_backend_refused(self):
        mgr = desktop_uia.DesktopUIAManager(backend=None)
        result = mgr.snapshot()
        assert result["success"] is False
        assert result["action_result"]["refusal_code"] == "unsupported_method"


class TestClickDeliveryChain:
    def test_invoke_first(self, manager):
        mgr, backend = manager
        mgr.snapshot()
        result = mgr.click_element(index=0)
        assert ("invoke", "42.1.7") in backend.calls
        assert result["success"] is True
        assert result["action_result"] == {
            "route": "uia",
            "effect": "confirmed",
            "delivery": "background",
            "evidence": ["delivery_ack"],
        }

    def test_fallback_to_post_message(self, manager):
        """不可 Invoke → PostMessage 直投（app_post，不抢焦点）"""
        mgr, backend = manager
        backend.elements = [make_element(invokable=False)]
        mgr.snapshot()
        result = mgr.click_element(index=0)
        assert ("post_click", "42.1.7", "left") in backend.calls
        assert result["action_result"]["route"] == "app_post"
        assert result["action_result"]["delivery"] == "background"

    def test_full_chain_order(self, manager):
        """invoke 不可用（flag 关）→ legacy（唯一可用语义级）→ 不越级试探"""
        mgr, backend = manager
        backend.elements = [make_element(invokable=False, togglable=False, expandable=False, legacy_default=True)]
        mgr.snapshot()
        result = mgr.click_element(index=0)
        assert result["success"] is True
        kinds = [c[0] for c in backend.calls]
        assert "legacy" in kinds
        assert "toggle" not in kinds and "expand" not in kinds and "post_click" not in kinds

    def test_all_background_routes_fail_refused(self, manager, monkeypatch):
        mgr, backend = manager
        backend.elements = [make_element(invokable=False, togglable=False, expandable=False, legacy_default=False, rect=(5, 5, 10, 10))]
        backend.post_click_ok = False
        monkeypatch.delenv("NEUROVA_ALLOW_GLOBAL_INPUT", raising=False)
        mgr.snapshot()
        result = mgr.click_element(index=0)
        assert result["success"] is False
        assert result["action_result"]["refusal_code"] == "background_unavailable"
        assert result["action_result"]["escalation"] == {"target": "pixel", "reason": "route_unavailable"}

    def test_global_gate_enables_last_resort(self, manager, monkeypatch):
        mgr, backend = manager
        backend.elements = [make_element(invokable=False, togglable=False, expandable=False, legacy_default=False, rect=(5, 5, 10, 10))]
        backend.post_click_ok = False
        monkeypatch.setenv("NEUROVA_ALLOW_GLOBAL_INPUT", "1")
        mgr.snapshot()
        result = mgr.click_element(index=0)
        assert result["action_result"]["route"] == "global_input"
        assert result["action_result"]["delivery"] == "foreground"

    def test_no_element_rect_cannot_even_post(self, manager, monkeypatch):
        """无矩形（虚拟控件）连 PostMessage 都不可达 → 直接拒绝"""
        mgr, backend = manager
        backend.elements = [make_element(invokable=False, togglable=False, expandable=False, legacy_default=False, rect=None)]
        monkeypatch.delenv("NEUROVA_ALLOW_GLOBAL_INPUT", raising=False)
        mgr.snapshot()
        result = mgr.click_element(index=0)
        assert result["action_result"]["refusal_code"] == "background_unavailable"
        assert "escalation" not in result["action_result"]

    def test_click_without_snapshot_refused(self, manager):
        """先快照后交互——未快照直接点击拒绝并引导"""
        mgr, _ = manager
        result = mgr.click_element(index=0)
        assert result["success"] is False
        assert result["action_result"]["refusal_code"] == "stale_generation"
        assert "computer_dom_snapshot" in result["error"]

    def test_unknown_index_refused(self, manager):
        mgr, _ = manager
        mgr.snapshot()
        result = mgr.click_element(index=99)
        assert result["action_result"]["refusal_code"] == "ref_not_found"

    def test_stale_generation_explicit_check(self, manager):
        mgr, _ = manager
        mgr.snapshot()  # generation=1
        result = mgr.click_element(index=0, generation=999)
        assert result["action_result"]["refusal_code"] == "stale_generation"

    def test_action_bumps_generation(self, manager):
        mgr, _ = manager
        snap1 = mgr.snapshot()
        mgr.click_element(index=0)
        result = mgr.click_element(index=0, generation=snap1["generation"])
        assert result["success"] is False
        assert result["action_result"]["refusal_code"] == "stale_generation"


class TestSetValue:
    def test_value_pattern_with_readback(self, manager):
        mgr, backend = manager
        backend.elements = [make_element(settable=True)]
        mgr.snapshot()
        result = mgr.set_value(index=0, value="hello")
        assert ("set_value", "42.1.7", "hello") in backend.calls
        assert result["success"] is True
        assert result["action_result"] == {
            "route": "uia",
            "effect": "confirmed",
            "delivery": "background",
            "evidence": ["value_readback"],
        }

    def test_no_settable_no_gate_refused(self, manager, monkeypatch):
        mgr, backend = manager
        backend.elements = [make_element(settable=False)]
        monkeypatch.delenv("NEUROVA_ALLOW_GLOBAL_INPUT", raising=False)
        mgr.snapshot()
        result = mgr.set_value(index=0, value="x")
        assert result["action_result"]["refusal_code"] == "background_unavailable"

    def test_keyboard_fallback_gated(self, manager, monkeypatch):
        mgr, backend = manager
        backend.elements = [make_element(settable=False)]
        monkeypatch.setenv("NEUROVA_ALLOW_GLOBAL_INPUT", "1")
        mgr.snapshot()
        result = mgr.set_value(index=0, value="x")
        assert ("global_type", "x") in backend.calls
        assert result["action_result"] == {
            "route": "global_input",
            "effect": "unverifiable",
            "delivery": "foreground",
        }


class TestAvailability:
    def test_real_backend_probe_never_raises(self):
        """真实后端探测在任何环境都不炸（非 Windows / 未装库 → False）"""
        assert desktop_uia.is_available() in (True, False)

    def test_manager_uia_available_uses_module_probe(self, monkeypatch):
        """manager 的 uia 布尔必须走模块级探测点（T-07 后走 `availabilityDetail`，
        `is_available()` 自己也是它的派生），不许在 manager 里再判一次 import。"""
        from neurova.computer_use import ComputerUseManager
        from neurova.computer_use.capability_state import CAP_AVAILABLE, CAP_NOT_CONFIGURED

        monkeypatch.setattr(desktop_uia, "availabilityDetail", lambda: {
            "available": True, "state": CAP_AVAILABLE, "platform": "nt", "reason": "可导入"})
        manager = ComputerUseManager()
        assert manager.uia_available() is True
        assert manager.uiaProbe() == (CAP_AVAILABLE, "可导入")
        monkeypatch.setattr(desktop_uia, "availabilityDetail", lambda: {
            "available": False, "state": CAP_NOT_CONFIGURED, "platform": "posix",
            "reason": "UIA 只在 Windows 侧有意义"})
        assert manager.uia_available() is False
        assert manager.uiaProbe()[0] == CAP_NOT_CONFIGURED
        # 布尔与状态同源：is_available() 就是 detail["available"]，两处不许分叉
        assert desktop_uia.is_available() is desktop_uia.availabilityDetail()["available"]


class _RectLike:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom


class _LiveShapeControl:
    """照 2026-10-02 活体取到的**真实控件形状**构造。

    该库的 Control 只暴露 `Get*Pattern()`，不暴露任何 `Is*PatternAvailable`
    （实测 `dir(auto.Control)` 里 Available 一族为空，而真按钮上 `GetInvokePattern()`
    返回 InvokePattern）。旧探测写的正是后者，于是恒判不可用。
    `has_invoke=False` 表达另一种真实形态：window 类控件上连 `GetInvokePattern`
    这个成员都不存在（活体读数 "getter absent"）。
    """

    def __init__(
        self,
        control_type="ButtonControl",
        name="ProbeButton",
        *,
        has_invoke=True,
        invoke_raises=None,
        value_pattern=None,
        has_legacy=True,
    ):
        self.ControlTypeName = control_type
        self.Name = name
        self.IsEnabled = True
        self.HasKeyboardFocus = False
        self.BoundingRectangle = _RectLike(10, 20, 90, 50)
        self.NativeWindowHandle = 133716
        if has_invoke:
            def getInvokePattern():
                if invoke_raises is not None:
                    raise invoke_raises
                return object()

            self.GetInvokePattern = getInvokePattern
        if has_legacy:
            self.GetLegacyIAccessiblePattern = lambda: object()
        if value_pattern is not None:
            def getValuePattern():
                return value_pattern

            self.GetValuePattern = getValuePattern

    def GetRuntimeId(self):
        return [42, 1, 7]


class _ValuePatternLike:
    def __init__(self, value):
        self.Value = value


class TestLiveControlShapeDiscovery:
    """五轴 pattern 可用性必须由**真取用**得出（T-01 活体抓出的根因）

    `FakeUIABackend` 直接注入 `invokable=True` 的 element dict，替生产码回答了
    "探测得到吗"这个问题，于是"真控件 → flag"这一跳从未被测过，五轴恒 False 潜伏至今：
    五级链 ①②③④ 级永不可达，桌面点击全部掉到 app_post，`set_value` 恒 refused
    ——把用户推向"开 env 放开全局键入"（抢焦点）那条路。
    """

    def setup_method(self):
        self.backend = desktop_uia.UiautomationBackend()

    def test_invoke_is_discovered_on_a_real_button(self):
        info = self.backend._element_info(_LiveShapeControl())
        assert info["invokable"] is True

    def test_legacy_default_is_discovered(self):
        info = self.backend._element_info(_LiveShapeControl())
        assert info["legacy_default"] is True

    def test_value_pattern_makes_element_settable_and_reads_value(self):
        """settable 与 value 是同根因的第二处命中点（`:544` 也写了那个不存在的 API）。"""
        info = self.backend._element_info(
            _LiveShapeControl(
                control_type="EditControl",
                name="ProbeField",
                has_invoke=False,
                has_legacy=False,
                value_pattern=_ValuePatternLike("t01-live-verify"),
            )
        )
        assert info["settable"] is True
        assert info["value"] == "t01-live-verify"

    def test_control_without_the_getter_is_not_supported_and_does_not_raise(self):
        info = self.backend._element_info(
            _LiveShapeControl(control_type="WindowControl", name="ProbeWindow", has_invoke=False)
        )
        assert info["invokable"] is False
        assert info["legacy_default"] is True

    def test_probe_failure_is_not_disguised_as_unsupported(self, monkeypatch):
        """探测本身炸（COM 调用失败）≠ 控件不支持：必须留话，不得静默塌成 False。"""
        seen = []
        monkeypatch.setattr(
            desktop_uia.logger,
            "warning",
            lambda msg, *args, **kw: seen.append(str(msg) % args if args else str(msg)),
        )
        info = self.backend._element_info(
            _LiveShapeControl(invoke_raises=RuntimeError("com call failed"))
        )
        assert info["invokable"] is False
        assert seen, "pattern 探测失败被静默当作'控件不支持'（教义第 2 条禁止的谎报形态）"
