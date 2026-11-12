"""lost-in-the-middle 位置缓解判据（候选 C5）

断言三面：
1. 发牌算法：输入序（=抽屉裁决序）→ 最优置首、次优置尾、三优次首……最弱居中；
2. 开关：默认关（工单 015 口径，行为变更显式开启）、env 显式 0/1 最优先；
3. 接线守卫：orchestrator 的 draw 召回装配路径必须调用缓解函数
   （AST 形态判，沿 test_toolOutputRefWiring 先例——防静默拆除）。
"""

import ast
import pathlib
from unittest import mock

import pytest
from tests.ast_scan import parseSource

ORCH_PY = (
    pathlib.Path(__file__).resolve().parents[3] / "neurova" / "context" / "orchestrator.py"
)


class _Drop:
    def __init__(self, content: str, priority=None):
        self.content = content
        self.priority = priority


def test_gate_default_off():
    from neurova.context.position_strategy import isLostInMiddleEnabled

    with mock.patch.dict("os.environ", {}, clear=False):
        import os

        os.environ.pop("NEUROVA_LOST_IN_MIDDLE", None)
        assert isLostInMiddleEnabled() is False, "默认关＝现网语义（工单 015 口径）"


def test_gate_env_overrides():
    from neurova.context.position_strategy import isLostInMiddleEnabled

    with mock.patch.dict("os.environ", {"NEUROVA_LOST_IN_MIDDLE": "1"}):
        assert isLostInMiddleEnabled() is True
    with mock.patch.dict("os.environ", {"NEUROVA_LOST_IN_MIDDLE": "0"}):
        assert isLostInMiddleEnabled() is False


def test_deal_places_best_first_second_last_weakest_middle():
    from neurova.context.position_strategy import applyLostInMiddleMitigation

    items = ["rank1", "rank2", "rank3", "rank4", "rank5"]
    out = applyLostInMiddleMitigation(items)
    assert out == ["rank1", "rank3", "rank5", "rank4", "rank2"], (
        "首=最优、次首=第三、中=最弱、次尾=第四、尾=第二（两端向内发牌）"
    )


def test_deal_even_count():
    from neurova.context.position_strategy import applyLostInMiddleMitigation

    out = applyLostInMiddleMitigation(["a", "b", "c", "d"])
    assert out == ["a", "c", "d", "b"]


def test_short_list_identity():
    from neurova.context.position_strategy import applyLostInMiddleMitigation

    for items in ([], ["x"], ["x", "y"]):
        assert applyLostInMiddleMitigation(items) == items, "≤2 条恒等映射"


def test_no_second_ranking_definition():
    """rank 必须取输入序（抽屉裁决），本模块不得自带打分（教义第 6 条）。"""
    import inspect

    from neurova.context import position_strategy as ps

    src = inspect.getsource(ps.applyLostInMiddleMitigation)
    for forbidden in ("sort", "score", "priority", "hits", "rank("):
        assert forbidden not in src.replace("rank 序", "").replace("rank=", ""), (
            f"缓解函数内出现排序/打分词汇「{forbidden}」——rank 只能取输入序"
        )


def test_orchestrator_draw_path_calls_mitigation():
    """AST 接线守卫：draw 召回装配路径必须调用 applyLostInMiddleMitigation。"""
    tree = parseSource(ORCH_PY.read_text(encoding="utf-8"), str(ORCH_PY))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "applyLostInMiddleMitigation")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "applyLostInMiddleMitigation")
        )
    ]
    assert calls, "orchestrator 未调用位置缓解——C5 断点未闭环"
