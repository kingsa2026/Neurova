# -*- coding: utf-8 -*-
"""T-05 · SOM 编号映射必须按会话隔离（工单集 T-05）。

## 根因（亲验）

编号→坐标映射原先是 `ToolExecutor` 上的一个裸实例属性
`self._last_som_id2xy`（写在 `tool_executor.py:4764`、读在 `:4792`）：
**无锁、无会话键、单槽覆盖**。而 ToolExecutor 随 agent 长期存活 ⇒

    会话 A：computer_som_snapshot   → 存下 A 那张图的 id2xy
    会话 B：computer_som_snapshot   → 覆盖成 B 的
    会话 A：computer_click_mark(id)  → 按 **B 图上的坐标** 点击

而 SOM 编号本身是按"量化中心 + label"散列出来的确定值
（`som.stable_id`，注释即"跨调用/跨进程稳定"），所以两个会话**完全可能拿到同一个
id 却指向不同元素**。这不是"点了没反应"，是"点错了还报成功"。

与 G1 已修掉的"轮次态挂 per-agent 单例"是同一病形（跨会话共享可变实例态）。

## 判据形状

不测"存没存进字典"（同义反复），只测**坐标归谁**：驱动真实处理函数
`_execute_computer_som_snapshot` / `_execute_computer_click_mark`，
在像素点击那一层记下实际收到的 (cx, cy)，断言 A 拿到的是 A 图上的坐标。

三条对照缺一不可：
- 正对照：单会话下解析必须正确（否则"隔离"可能只是"什么都点不到"）；
- 前提对照：两个会话的 id 必须**真的重叠**且坐标不同（否则隔离测了个寂寞）；
- 反向对照：修复前的形态（单槽覆盖）必须能被判据抓住——见 commit 里的真变异记录。
"""

from __future__ import annotations

import typing

import pytest

from neurova.core.turn_context import set_turn_identity
from neurova.tool_executor import ToolExecutor

SESSION_A = "t05-session-A"
SESSION_B = "t05-session-B"
MARK_ID = "1"
COORD_A = (111, 222)
COORD_B = (999, 888)


class _StubManager:
    def __init__(self) -> None:
        self.calls = 0

    def screenshot(self) -> bytes:
        self.calls += 1
        return b"fake-png"


def _marksForSession(sessionId: str) -> dict:
    """按当前会话返回不同的坐标——模拟"两个会话各自截了自己那块屏"。

    刻意让两个会话共用同一个编号 MARK_ID：SOM 编号是稳定散列，现实中就会撞。
    """
    coord = COORD_A if sessionId == SESSION_A else COORD_B
    return {
        "success": True,
        "count": 1,
        "marks": [{"id": int(MARK_ID), "center": list(coord), "label": "按钮"}],
        "id2xy": {MARK_ID: coord},
        "annotated_png_b64": "x",
    }


@pytest.fixture
def probe(monkeypatch) -> dict:
    """把桌面与 SOM 的三处外部依赖换成可记录的桩，保留被测的两个处理函数本体。"""
    import neurova.computer_use as cu
    import neurova.computer_use.actions as actions
    import neurova.computer_use.som as som

    manager = _StubManager()
    monkeypatch.setattr(cu, "get_computer_use_manager", lambda *a, **k: manager)
    monkeypatch.setattr(
        som, "mark_screenshot",
        lambda png, detector=None: _marksForSession(_currentSession()),
    )
    clicked: list = []

    def _recordClick(m, cx, cy, button="left", *a, **k):
        clicked.append((cx, cy, button))
        # 返回失败：跳过成功分支的补拍/事件面，本判据只关心"点在哪"
        return {"success": False, "error": "probe-stop"}

    monkeypatch.setattr(actions, "click_screenshot_point", _recordClick)
    return {"clicked": clicked, "manager": manager}


def _currentSession() -> str:
    from neurova.core.turn_context import get_turn_session_id

    return get_turn_session_id() or ""


def _executor() -> ToolExecutor:
    """构造一个不依赖真实 Agent 的执行器（两个处理函数都不触达 agent_ref）。"""
    return ToolExecutor(agent_ref=None)  # type: ignore[arg-type]


async def _snapshot(executor: ToolExecutor) -> dict:
    return await executor._execute_computer_som_snapshot({})


async def _clickMark(executor: ToolExecutor, markId: str) -> dict:
    return await executor._execute_computer_click_mark({"index": markId})


class TestSomMarksAreSessionScoped:

    @pytest.mark.asyncio
    async def test_concurrentSessionsDoNotCrossResolveMarks(self, probe):
        """交叠两个会话：A 的编号必须解到 A 图的坐标，而不是最后快照那个会话的。"""
        executor = _executor()

        set_turn_identity("a", session_id=SESSION_A)
        snapA = await _snapshot(executor)
        set_turn_identity("b", session_id=SESSION_B)
        snapB = await _snapshot(executor)

        # 前提对照：两会话编号确实重叠且坐标不同，否则本判据测不到隔离
        assert snapA.get("marks") and snapB.get("marks")
        assert snapA["marks"][0]["center"] != snapB["marks"][0]["center"], "对照前提不成立"

        set_turn_identity("a", session_id=SESSION_A)
        await _clickMark(executor, MARK_ID)
        assert probe["clicked"], "点击根本没发生（判据会在'什么都点不到'上假通过）"
        assert probe["clicked"][-1][:2] == COORD_A, (
            f"会话 A 的编号解到了别人的坐标：{probe['clicked'][-1][:2]} ≠ {COORD_A}"
        )

        set_turn_identity("b", session_id=SESSION_B)
        await _clickMark(executor, MARK_ID)
        assert probe["clicked"][-1][:2] == COORD_B, (
            f"会话 B 的编号解错坐标：{probe['clicked'][-1][:2]} ≠ {COORD_B}"
        )

    @pytest.mark.asyncio
    async def test_singleSessionResolvesItsOwnCoordinates(self, probe):
        """正对照：单会话下解析必须正确——否则"隔离"可能只是"谁都点不到"。"""
        executor = _executor()
        set_turn_identity("a", session_id=SESSION_A)
        await _snapshot(executor)
        await _clickMark(executor, MARK_ID)
        assert probe["clicked"] and probe["clicked"][-1][:2] == COORD_A

    @pytest.mark.asyncio
    async def test_markAbsentFromThisSessionIsRefusedNotGuessed(self, probe):
        """本会话没快照过就必须拒绝，且**不得发出点击**（不许借用他人在的映射）。"""
        executor = _executor()
        set_turn_identity("a", session_id=SESSION_A)
        await _snapshot(executor)

        set_turn_identity("c", session_id="t05-session-C")
        result = await _clickMark(executor, MARK_ID)
        assert result.get("success") is not True and "refusal_code" in result, (
            f"C 会话无快照却拿到了可执行结果: {result}"
        )
        assert not probe["clicked"], "拒绝路径上仍然发出了点击"

    def test_storeIsNotABareInstanceAttribute(self):
        """静态钉桩：裸的 `_last_som_id2xy` 单槽属性不得回潮。

        按 AST 里的**属性访问**判，不按子串——上一版用子串扫源码，被解释旧缺陷的
        docstring 里的文字提及误判成"回潮"（本会话在别处也栽过同款探测 naive）。
        """
        import ast
        import pathlib

        import neurova.tool_executor as te

        tree = ast.parse(pathlib.Path(te.__file__).read_text(encoding="utf-8"))
        bare = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr == "_last_som_id2xy"
        ]
        assert not bare, f"单槽无锁无键的实例属性回潮（行 {bare}）——会话间会互相覆盖编号映射"

    def testExecutorInitializesStoreOutsideDocstring(self):
        """判据咬合装配点：属性必须在实例上真存在。

        本用例不是形式检查——实现时曾把这三行插进了 __init__ 的 docstring 里，
        AST 能过、import 能过，运行时才 AttributeError。
        """
        executor = _executor()
        assert hasattr(executor, "_somMarksBySession") and hasattr(executor, "_somMarksLock")
