# -*- coding: utf-8 -*-
"""AD-3（agent-desktop 对照工单）· computer_dom_snapshot drill-down。

对齐 agent-desktop 的 `snapshot --root @ref`：从已快照元素下钻子树，避免密集树
反复全量重枚举。语义约束：root 元素必须来自已有快照（ref 归属 snapshot）；
下钻结果 index 续接入缓存（不动既有 index），观察刷新不递增 generation；
缓存外 root 拒绝 ref_not_found（retry=reobserve）。
"""

import pytest

from neurova.computer_use.desktop_uia import DesktopUIAManager

TREE = {
    "name": "root", "rid": "r0", "children": [
        {"name": "branchA", "rid": "rA", "children": [
            {"name": "leafA1", "rid": "rA1"},
            {"name": "leafA2", "rid": "rA2"},
        ]},
        {"name": "branchB", "rid": "rB"},
    ],
}


class TreeFakeBackend:
    """树形 Fake：walk 根可切换（window["_control"] 携带树节点），契约与真实后端对齐"""

    def __init__(self):
        self.invoke_ok = True

    def available(self):
        return True

    def get_window(self, window_title=None):
        return {"title": "树窗口", "rect": (0, 0, 800, 600), "pid": 9, "hwnd": 9}

    def walk(self, window, max_nodes, max_depth):
        root = window.get("_control") if isinstance(window, dict) else None
        if not isinstance(root, dict) or "name" not in root:
            root = TREE
        elements = []
        stats = {"depth_truncated": False, "observed_max_depth": 0}

        def visit(node, depth):
            if len(elements) >= max_nodes:
                return
            if depth > max_depth:
                stats["depth_truncated"] = True
                return
            el = {
                "role": "pane", "name": node["name"], "runtime_id": node["rid"],
                "rect": (0, 0, 10, 10), "enabled": True,
                "invokable": True, "togglable": False, "expandable": False,
                "legacy_default": False, "settable": False,
                "_control": node,
            }
            elements.append(el)
            stats["observed_max_depth"] = max(stats["observed_max_depth"], depth)
            children = node.get("children", [])
            if children and depth == max_depth:
                el["subtree_truncated"] = True
            for child in children:
                visit(child, depth + 1)

        visit(root, 0)
        return elements, stats

    def invoke(self, element):
        return self.invoke_ok

    def toggle(self, element):
        return True

    def expand(self, element):
        return True

    def legacy_default(self, element):
        return True

    def post_click(self, element, button):
        return True

    def global_click(self, element, button):
        return True

    def set_value(self, element, value):
        return f"readback:{value}"

    def focus(self, element):
        return True

    def global_type(self, value):
        return True


class TestDrilldown:
    @staticmethod
    def _manager():
        return DesktopUIAManager(backend=TreeFakeBackend())

    def test_drilldown_returns_subtree_and_extends_cache(self):
        """全量被 depth 剪断 → 按 subtree_truncated 元素下钻补齐被剪子树。"""
        mgr = self._manager()
        full = mgr.snapshot(max_nodes=400, max_depth=1)
        assert [e["name"] for e in full["elements"]] == ["root", "branchA", "branchB"]
        assert full["truncated"] is True and full.get("depth_truncated") is True
        assert [e["name"] for e in full["elements"] if e.get("subtree_truncated")] == ["branchA"]
        gen_before = full["generation"]
        out = mgr.snapshot(max_nodes=400, max_depth=32, root_index=1)
        assert out["success"] is True
        assert [e["name"] for e in out["elements"]] == ["branchA", "leafA1", "leafA2"]
        by_name = {e["name"]: e for e in out["elements"]}
        assert by_name["branchA"]["index"] == 1, "已在缓存的元素保持原 index"
        assert by_name["leafA1"]["index"] == 3, "新元素 index 续接缓存"
        assert by_name["leafA2"]["index"] == 4
        assert out["drilled_from"] == {"index": 1, "runtime_id": "rA"}
        assert out["generation"] == gen_before, "观察刷新不递增代次"
        assert "subtree_truncated" not in by_name["branchA"], "子树补齐后 root 的被切标记应解除"
        click = mgr.click_element(runtime_id="rA1")
        assert click["success"] is True, "下钻新元素必须可被语义动作按 runtime_id 命中"

    def test_drilldown_by_runtime_id(self):
        mgr = self._manager()
        mgr.snapshot(max_nodes=400, max_depth=32)
        out = mgr.snapshot(max_nodes=400, max_depth=32, root_runtime_id="rA")
        assert out["success"] is True
        assert [e["name"] for e in out["elements"]] == ["branchA", "leafA1", "leafA2"]

    def test_drilldown_unknown_root_refused(self):
        mgr = self._manager()
        mgr.snapshot(max_nodes=400, max_depth=32)
        out = mgr.snapshot(max_nodes=400, max_depth=32, root_index=99)
        assert out["success"] is False
        assert out["action_result"]["refusal_code"] == "ref_not_found"
        assert out["action_result"]["retry"] == "reobserve"

    def test_drilldown_without_prior_snapshot_refused(self):
        """root 必须来自已有快照（ref 归属 snapshot），无先验快照直接拒绝。"""
        mgr = self._manager()
        out = mgr.snapshot(max_nodes=400, max_depth=32, root_index=0)
        assert out["success"] is False
        assert out["action_result"]["refusal_code"] == "ref_not_found"


class TestDrilldownSchema:
    def test_schema_advertises_root_params(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        props = _BUILTIN_SCHEMAS["computer_dom_snapshot"]["parameters"]["properties"]
        assert "root_index" in props, "schema 未声明 root_index"
        assert "root_runtime_id" in props, "schema 未声明 root_runtime_id"
