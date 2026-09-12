"""R1-1 桌面 UIA 语义层（CUA 升级方案 Phase 1）

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
        from neurova.computer_use import ComputerUseManager

        monkeypatch.setattr(desktop_uia, "is_available", lambda: True)
        manager = ComputerUseManager()
        assert manager.uia_available() is True
        monkeypatch.setattr(desktop_uia, "is_available", lambda: False)
        assert manager.uia_available() is False
