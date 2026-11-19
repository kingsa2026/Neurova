# -*- coding: utf-8 -*-
"""AD-4（agent-desktop 对照工单后置项拍板立项）· computer_dom_snapshot skeleton 骨架模式。

对齐 agent-desktop 的 `snapshot --skeleton --compact`：密集树先看「有名字/可交互/
结构根」的骨架概览，匿名不可交互容器折叠成 omitted 计数，细节用 AD-3 的 drill-down
补齐。同时给元素补 depth 字段（walk 时已知，供模型读层级）。
"""

import pytest

from neurova.computer_use.desktop_uia import DesktopUIAManager


class MixedFakeBackend:
    """混合树：无名容器 + 有名元素 + 可交互无名控件，契约与真实后端对齐"""

    def __init__(self):
        self.nodes = [
            {"role": "window", "name": "主窗口", "rid": "r0", "interactive": False},
            {"role": "pane", "name": "", "rid": "r1", "interactive": False},        # 无名容器→折
            {"role": "pane", "name": "", "rid": "r2", "interactive": False},        # 无名容器→折
            {"role": "button", "name": "确定", "rid": "r3", "interactive": True},   # 有名→留
            {"role": "edit", "name": "", "rid": "r4", "interactive": True},         # 可交互无名→留
            {"role": "text", "name": "", "rid": "r5", "interactive": False},        # 无名文本→折
            {"role": "listitem", "name": "项目七", "rid": "r6", "interactive": False},
            {"role": "pane", "name": "", "rid": "r7", "interactive": False,
             "legacy_only": True},                                                   # 仅 legacy_default→折（真机教训）
        ]

    def available(self):
        return True

    def get_window(self, window_title=None):
        return {"title": "骨架窗口", "rect": (0, 0, 800, 600), "pid": 3, "hwnd": 3}

    def walk(self, window, max_nodes, max_depth):
        elements = []
        stats = {"depth_truncated": False, "observed_max_depth": 0}
        for i, n in enumerate(self.nodes):
            if len(elements) >= max_nodes:
                stats["depth_truncated"] = True
                break
            el = {
                "role": n["role"], "name": n["name"], "runtime_id": n["rid"],
                "depth": i % 3,
                "invokable": n["interactive"], "togglable": False,
                "expandable": False, "legacy_default": bool(n.get("legacy_only")),
                "settable": False,
            }
            elements.append(el)
            stats["observed_max_depth"] = max(stats["observed_max_depth"], el["depth"])
        return elements, stats


class TestSkeletonMode:
    def test_skeleton_folds_anonymous_noninteractive(self):
        mgr = DesktopUIAManager(backend=MixedFakeBackend())
        out = mgr.snapshot(max_nodes=400, max_depth=32, skeleton=True)
        assert out["success"] is True
        names = [(e.get("role"), e.get("name")) for e in out["elements"]]
        assert ("pane", "") not in names, "无名不可交互容器必须被折叠"
        assert ("text", "") not in names
        assert ("button", "确定") in names, "有名元素保留"
        assert ("edit", "") in names, "可交互无名控件保留（交互位不靠名字）"
        assert ("window", "主窗口") in names, "结构根保留"
        assert out["skeleton"] is True
        assert out["omitted_count"] == 4, f"折叠计数：{out['omitted_count']}"

    def test_legacy_default_alone_is_not_interactive(self):
        """真机教训（2026-11-19 Notepad 活体）：LegacyIAccessible 几乎处处可取用，
        仅带 legacy_default 的无名元素必须折叠——否则骨架折叠率归零。"""
        mgr = DesktopUIAManager(backend=MixedFakeBackend())
        out = mgr.snapshot(max_nodes=400, max_depth=32, skeleton=True)
        rids = [e.get("runtime_id") for e in out["elements"]]
        assert "r7" not in rids, "仅 legacy_default 的空名元素不得保留"

    def test_skeleton_off_keeps_full_list(self):
        mgr = DesktopUIAManager(backend=MixedFakeBackend())
        out = mgr.snapshot(max_nodes=400, max_depth=32)
        assert len(out["elements"]) == 8
        assert "skeleton" not in out and "omitted_count" not in out, "非骨架模式不加新键"

    def test_elements_carry_depth(self):
        """walk 产出的元素带 depth（层级可读，供 skeleton/drill-down 消费）。"""
        mgr = DesktopUIAManager(backend=MixedFakeBackend())
        out = mgr.snapshot(max_nodes=400, max_depth=32)
        assert all("depth" in e for e in out["elements"]), "元素必须带 depth"


class TestSkeletonSchema:
    def test_schema_advertises_skeleton(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        props = _BUILTIN_SCHEMAS["computer_dom_snapshot"]["parameters"]["properties"]
        assert "skeleton" in props, "schema 未声明 skeleton"
