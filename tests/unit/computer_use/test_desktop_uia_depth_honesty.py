# -*- coding: utf-8 -*-
"""AD-2（agent-desktop 对照工单）· UIA 快照 depth 剪枝诚实上报。

现状缺陷：`desktop_uia.walk` 对 `depth > max_depth` 静默剪枝，`snapshot` 返回的
`truncated` 只看节点数——depth 剪过的残树报 `truncated=False`，模型会把残树当全貌。
对齐浏览器侧截断诚实纪律（test_snapshot_truncation_honesty）：被切事实必须进
模型可见结果；未超限不得加噪声字段。
"""

import pytest

from neurova.computer_use.desktop_uia import DesktopUIAManager


def _chain(tree_depth: int) -> dict:
    """构造 tree_depth+1 层单链树：n0 → n1 → … → n{tree_depth}"""
    node = {"name": f"n{tree_depth}", "rid": f"r{tree_depth}"}
    for d in range(tree_depth - 1, -1, -1):
        node = {"name": f"n{d}", "rid": f"r{d}", "children": [node]}
    return node


class DepthChainFakeBackend:
    """按真实 walk 剪枝语义（len>=max_nodes 或 depth>max_depth 即停）返回剪后列表"""

    def __init__(self, tree_depth: int):
        self.tree = _chain(tree_depth)

    def available(self) -> bool:
        return True

    def get_window(self, window_title=None):
        return {"title": "深树窗口", "rect": (0, 0, 800, 600), "pid": 7, "hwnd": 7}

    def walk(self, window, max_nodes, max_depth):
        elements = []
        stats = {"depth_truncated": False, "observed_max_depth": 0}

        def visit(node, depth):
            if len(elements) >= max_nodes:
                return
            if depth > max_depth:
                stats["depth_truncated"] = True
                return
            el = {"role": "pane", "name": node["name"], "runtime_id": node["rid"]}
            elements.append(el)
            stats["observed_max_depth"] = max(stats["observed_max_depth"], depth)
            children = node.get("children", [])
            if children and depth == max_depth:
                el["subtree_truncated"] = True
            for child in children:
                visit(child, depth + 1)

        visit(self.tree, 0)
        return elements, stats


class TestDepthTruncationHonesty:
    def test_depth_cut_is_reported(self):
        """5 层树 max_depth=2：depth 剪枝必须可见——truncated 升义、
        depth_truncated/observed_max_depth 上报、被切元素自标 subtree_truncated。"""
        mgr = DesktopUIAManager(backend=DepthChainFakeBackend(4))
        out = mgr.snapshot(max_nodes=400, max_depth=2)
        assert out["success"] is True
        assert out["truncated"] is True, "depth 剪过的树必须报 truncated"
        assert out["depth_truncated"] is True
        assert out["observed_max_depth"] == 2
        cut = [e for e in out["elements"] if e.get("subtree_truncated")]
        assert [e["name"] for e in cut] == ["n2"], (
            "被切元素（depth==max_depth 且仍有子代）必须自标 subtree_truncated"
        )

    def test_no_cut_no_noise(self):
        """预算内完整树：不带 depth 截断字段（未超限就静），元素不带标记。"""
        mgr = DesktopUIAManager(backend=DepthChainFakeBackend(2))
        out = mgr.snapshot(max_nodes=400, max_depth=8)
        assert out["success"] is True
        assert out["truncated"] is False
        for key in ("depth_truncated", "observed_max_depth"):
            assert key not in out, f"完整树不应出现 {key}"
        assert all("subtree_truncated" not in e for e in out["elements"])

    def test_node_budget_still_reports_truncated(self):
        """节点数截断语义保持：max_nodes 先到 → truncated=True（升义不改旧语义）。"""
        mgr = DesktopUIAManager(backend=DepthChainFakeBackend(4))
        out = mgr.snapshot(max_nodes=2, max_depth=8)
        assert out["truncated"] is True
