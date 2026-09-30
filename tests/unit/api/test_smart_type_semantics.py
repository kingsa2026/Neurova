# -*- coding: utf-8 -*-
"""`smart-type` 接通后的语义判据：与 `smart-click` 同一套码位、同一份事实来源。

## 为什么这条值得常驻（不是"把 501 换成实现"就完事）

`smart-click` 已按 D-6 落成三态（200/409/404，取不到事实时 502），而它旁边的
`smart-type` 还停在 `_refuseUnimplemented`。相邻两半、一半能执行一半"未实现"，
是**新造出来的不对称**：模型读到 `smart-click` 的 409 会合理推断 `smart-type` 同形，
结果拿到 501。用户 2026-10-01 拍板（工单集 §19 附带项）"实现，与 click 统一"。

"统一"在这条判据里是可检查的四件事，不是口号：

1. **同一份事实来源**：只吃当前 aria 快照事实，不猜 CSS 选择器（D-2 同向）；
2. **同一套码位**：唯一命中 200、多命中 409 且逐条列候选**不代为挑选**、无命中 404、
   取不到事实 502 且点名"未执行"；
3. **同一套失效语义**：动作成功后快照事实作废（`generation` 由动作侧推进），
   所以响应里必须回 `generation`，模型才知道手里那份快照还能不能用；
4. **动作真的落到元素上**：断言的是 `fill_role` 实收到的 `(role, name, text)`，
   不是"返回体里写了 success"——后者在假生产者下也会绿。

第 4 条是本文件与 `test_computer_placeholder_honesty.py` 的分工：那条管"不许谎报成功"，
这条管"成功必须是真发生的事"。
"""

from __future__ import annotations

import asyncio
import inspect
import typing

import pytest
from fastapi import HTTPException

from neurova.api.endpoints import computer as computer_ep
from neurova.computer_use.browser_manager import (
    BROWSER_NOT_STARTED_ERROR,
    NO_ACTIVE_TAB_ERROR,
    BrowserResult,
)

TREE_UNIQUE = "\n".join([
    "- document:",
    '  - textbox "用户名输入框"',
    '  - textbox "备注"',
    '  - button "提交订单"',
])

TREE_AMBIGUOUS = "\n".join([
    "- document:",
    '  - textbox "备注"',
    '  - textbox "备注"',            # 同一 role+name 的两个可交互行（必须逐字同形才算歧义）
    '  - button "提交"',
])

TREE_EMPTY_INTERACTIVE = "- document:\n  - paragraph: 只有正文"


class _FakeManager:
    """只替身"外部世界"（浏览器），处理函数本体与解析/编号链全是生产码。"""

    def __init__(self, snap: BrowserResult) -> None:
        self._snap = snap
        self.filled: list = []

    async def browser_dom_snapshot(self, *a, **k) -> BrowserResult:
        return self._snap

    async def browser_fill_role(self, role, name=None, text="", generation=None) -> BrowserResult:
        self.filled.append((role, name, text, generation))
        return BrowserResult(success=True, generation=(self._snap.generation or 1) + 1)


def _drive(monkeypatch, tree: str | None, *, snap: BrowserResult | None = None):
    """按签名自省地驱动 `smart_type(body)`，返回 (结果或异常, 记录到 fill 的调用)。"""
    manager = _FakeManager(snap or BrowserResult(success=True, data=tree, generation=3))
    import neurova.computer_use as cu

    monkeypatch.setattr(cu, "get_computer_use_manager", lambda *a, **k: manager)
    handler = computer_ep.smart_type
    model = typing.get_type_hints(inspect.signature(handler).parameters["body"].annotation)["body"] \
        if not isinstance(inspect.signature(handler).parameters["body"].annotation, type) \
        else inspect.signature(handler).parameters["body"].annotation
    return handler, model, manager


def _call(handler, model, target: str, text: str):
    return asyncio.run(handler(body=model(target=target, text=text)))


def _raises(handler, model, target: str, text: str) -> HTTPException:
    with pytest.raises(HTTPException) as exc:
        _call(handler, model, target, text)
    return exc.value


class TestSmartTypeIsUnifiedWithSmartClick:

    def test_unique_target_fills_that_field_and_reports_generation(self, monkeypatch):
        handler, model, manager = _drive(monkeypatch, TREE_UNIQUE)
        res = _call(handler, model, "用户名输入框", "alice")
        assert res["success"] is True and res["matched"] == {"role": "textbox", "name": "用户名输入框"}, res
        assert "generation" in res, "不回 generation，模型无从知道手里那份快照是否已作废"
        assert manager.filled == [("textbox", "用户名输入框", "alice", 3)], (
            f"动作没落到解析出的那个元素上：{manager.filled}"
        )

    def test_ambiguous_target_lists_candidates_and_fills_nothing(self, monkeypatch):
        handler, model, manager = _drive(monkeypatch, TREE_AMBIGUOUS)
        exc = _raises(handler, model, "备注", "bob")
        assert exc.status_code == 409, f"歧义须 409 并列出候选，实得 {exc.status_code}"
        assert "2 个可输入元素" in str(exc.detail), (
            f"歧义文案要点名候选的**性质**（可输入），不能沿用 click 的『可交互』："
            f"{exc.detail}"
        )
        assert manager.filled == [], "歧义时替模型挑了一个就动手——这是最坏的形态"

    def test_unresolved_target_is_404_not_a_guess(self, monkeypatch):
        handler, model, manager = _drive(monkeypatch, TREE_UNIQUE)
        exc = _raises(handler, model, "根本不存在的框", "x")
        assert exc.status_code == 404, exc.status_code
        assert manager.filled == []

    def test_page_without_any_field_is_404_not_500(self, monkeypatch):
        """"页面上确实没有" 是成功的观察 + 未命中，不是故障。"""
        handler, model, _ = _drive(monkeypatch, TREE_EMPTY_INTERACTIVE)
        exc = _raises(handler, model, "用户名输入框", "x")
        assert exc.status_code == 404, exc.status_code

    def test_unavailable_facts_is_502_naming_cause_and_that_nothing_ran(self, monkeypatch):
        handler, model, manager = _drive(
            monkeypatch, None,
            snap=BrowserResult(success=False, error=NO_ACTIVE_TAB_ERROR, generation=None),
        )
        exc = _raises(handler, model, "用户名输入框", "x")
        assert exc.status_code == 502, exc.status_code
        assert "未执行" in str(exc.detail), exc.detail
        assert NO_ACTIVE_TAB_ERROR in str(exc.detail), (
            f"detail 要把产出侧的具名原因原样带出，不得回落到英文内部词：{exc.detail}"
        )
        assert manager.filled == []

    def test_backend_not_started_is_a_different_cause_from_no_tab(self, monkeypatch):
        """两种"取不到事实"必须仍可分诊——动作是否值得重试取决于此。"""
        handler, model, _ = _drive(
            monkeypatch, None,
            snap=BrowserResult(success=False, error=BROWSER_NOT_STARTED_ERROR, generation=None),
        )
        exc = _raises(handler, model, "用户名输入框", "x")
        assert exc.status_code == 502
        detail = str(exc.detail)
        assert BROWSER_NOT_STARTED_ERROR in detail and NO_ACTIVE_TAB_ERROR not in detail, detail


class TestPlaceholderRegistryIsSynced:
    """撤 501 必须同批把"占位面"清单改掉，否则诚实守卫退化成空规则。"""

    def test_guard_ledger_dropped_smart_type(self):
        import tests.unit.api.test_computer_placeholder_honesty as guard

        assert "smart_type" not in [h for h, _ in guard.PLACEHOLDER_HANDLERS], (
            "smart_type 已接通却仍登记在占位清单里——那条守卫会把它继续当 501 断言，"
            "两侧不一致时红的是判据而不是代码"
        )
        assert "smart_type" not in guard._MINIMAL_BODIES, "最小请求体表也要同步撤面"
