# -*- coding: utf-8 -*-
"""歧义分支的出口：409 必须交出**可用的编号**，带 ref 重发要真点到那一个。

## 为什么这条值得常驻

D-6 第一片把歧义定成 409 并"列出候选、不代为挑选"，但列出的只有
`role「name」`——两行同名同 role 时那份清单**读得出却动不了**：调用方照着它
再发一次 `target`，仍然撞同一个 409。T-08 把 ref 做成一等寻址之后，
歧义的出路才真正存在：候选带上编号，调用方选一个带回来。

本文件钉三件事，缺一件就是"半接的路"：

1. **409 交出编号**：候选逐条带 `[eN]`，且文案点名"带 ref 重发本端点"——
   不是只把编号埋在快照正文里要调用方自己再快照一次。
2. **带 ref 重发真的按编号动手**：断言的是 `browser_click_ref`/`browser_fill_ref`
   **实收到的 `(ref, ..., generation)`**，且解析路径（role+name）这轮**不被调用**——
   否则"选了 e2 却点了 e1"照样绿。
3. **无编号时不许空头承诺**：候选来自未编号的树时，文案不得教人用 ref
   （模型/用户照做只会拿到 `ref-not-found`），退回既有的 role+name 指引。

夹具用生产形态的**已编号**快照文本——`browser_dom_snapshot` 自 T-08 起就在可动作行
尾注 `[eN]`，camofox 侧的编号由服务端发。拿未编号文本当生产形状会让判据松掉。
"""

from __future__ import annotations

import asyncio
import inspect
import typing

import pytest
from fastapi import HTTPException

from neurova.api.endpoints import computer as computer_ep
from neurova.computer_use.browser_manager import BrowserResult

TREE_AMBIGUOUS = "\n".join([
    "- document:",
    '  - textbox "备注" [e1]:',
    '  - textbox "备注" [e2]:',
    '  - button "提交" [e3]',
])

# 未编号形态：只用于反向锁（真实生产不再产出它，但降级路径必须仍然诚实）
TREE_UNANNOTATED = "\n".join([
    "- document:",
    '  - textbox "备注"',
    '  - textbox "备注"',
])


class _FakeManager:
    """只替身外部世界；解析、编号透出、码位选择全部走生产码。"""

    def __init__(self, tree: str, generation: int = 7) -> None:
        self._tree = tree
        self._generation = generation
        self.byRole: list = []
        self.byRef: list = []
        self.refFailure: str = ""

    async def browser_dom_snapshot(self, *a, **k) -> BrowserResult:
        return BrowserResult(success=True, data=self._tree, generation=self._generation)

    async def browser_click_role(self, role, name=None, generation=None) -> BrowserResult:
        self.byRole.append((role, name, generation))
        return BrowserResult(success=True, generation=self._generation + 1)

    async def browser_fill_role(self, role, name=None, text="", generation=None) -> BrowserResult:
        self.byRole.append((role, name, text, generation))
        return BrowserResult(success=True, generation=self._generation + 1)

    async def browser_click_ref(self, ref, generation=None) -> BrowserResult:
        self.byRef.append(("click", ref, generation))
        if self.refFailure:
            return BrowserResult(success=False, error=self.refFailure)
        return BrowserResult(success=True, generation=self._generation + 1)

    async def browser_fill_ref(self, ref, text, generation=None) -> BrowserResult:
        self.byRef.append(("fill", ref, text, generation))
        if self.refFailure:
            return BrowserResult(success=False, error=self.refFailure)
        return BrowserResult(success=True, generation=self._generation + 1)


def _handler(name: str):
    handler = getattr(computer_ep, name)
    param = inspect.signature(handler).parameters["body"]
    hint = param.annotation
    model = typing.get_type_hints(hint)["body"] if not isinstance(hint, type) else hint
    return handler, model


def _drive(monkeypatch, endpoint: str, tree: str, **body_kwargs):
    manager = _FakeManager(tree)
    import neurova.computer_use as cu

    monkeypatch.setattr(cu, "get_computer_use_manager", lambda *a, **k: manager)
    handler, model = _handler(endpoint)
    return handler, model, manager, body_kwargs


def _call(monkeypatch, endpoint: str, tree: str, **body_kwargs):
    handler, model, manager, kwargs = _drive(monkeypatch, endpoint, tree, **body_kwargs)
    return asyncio.run(handler(body=model(**kwargs))), manager


def _raises(monkeypatch, endpoint: str, tree: str, **body_kwargs) -> HTTPException:
    handler, model, manager, kwargs = _drive(monkeypatch, endpoint, tree, **body_kwargs)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(body=model(**kwargs)))
    return exc.value


class TestAmbiguityHandsBackRefs:
    """409 不只是"告诉你有几个同名"，必须给出选完就能用的编号。"""

    @pytest.mark.parametrize("endpoint,tree,word", [
        ("smart_click", TREE_AMBIGUOUS, "可交互"),
        ("smart_type", TREE_AMBIGUOUS, "可输入"),
    ])
    def test_ambiguous_lists_eachCandidateRef(self, monkeypatch, endpoint, tree, word):
        kwargs = {"target": "备注"} if endpoint == "smart_click" else {"target": "备注", "text": "bob"}
        exc = _raises(monkeypatch, endpoint, tree, **kwargs)
        assert exc.status_code == 409, exc.status_code
        detail = str(exc.detail)
        assert word in detail, f"两端的候选性质不得混读：{detail}"
        for ref in ("e1", "e2"):
            assert ref in detail, f"候选没带编号，调用方选完还是动不了：{detail}"

    @pytest.mark.parametrize("endpoint", ["smart_click", "smart_type"])
    def test_ambiguous_names_theRefResendPath(self, monkeypatch, endpoint):
        kwargs = {"target": "备注"} if endpoint == "smart_click" else {"target": "备注", "text": "bob"}
        detail = str(_raises(monkeypatch, endpoint, TREE_AMBIGUOUS, **kwargs).detail)
        assert "ref" in detail, f"文案没指出出路是可带 ref 重发：{detail}"
        assert 'ref="e2"' in detail, f"示例编号必须是本代真实存在的编号：{detail}"

    def test_unannotatedTreeDoesNotPromiseARefPath(self, monkeypatch):
        """反向锁：手里没有编号时不许教人用编号。"""
        detail = str(_raises(monkeypatch, "smart_click", TREE_UNANNOTATED, target="备注").detail)
        assert "e1" not in detail and "ref" not in detail, detail


class TestRefResendActsOnThatElement:
    """带 ref 重发：走编号链，不走解析链，且断言的是实收参数。"""

    def test_click_with_ref_calls_the_ref_path_only(self, monkeypatch):
        res, manager = _call(monkeypatch, "smart_click", TREE_AMBIGUOUS,
                             target="备注", ref="e2")
        assert res["success"] is True, res
        # generation 传 None：编号表随代次作废，"页面变了"由后端回 ref-not-found，
        # 不必为这一步再付一次全页快照（T-08 省下的账正是本条链的收益）
        assert manager.byRef == [("click", "e2", None)], manager.byRef
        assert manager.byRole == [], "带 ref 却又跑了 role+name 解析——选定的编号被丢掉"
        assert res["matched"]["ref"] == "e2", res
        assert res["generation"] == 8, f"动作推进的代次必须回给调用方：{res}"

    def test_type_with_ref_fills_thatRefWith_text(self, monkeypatch):
        res, manager = _call(monkeypatch, "smart_type", TREE_AMBIGUOUS,
                             target="备注", text="bob", ref="e1")
        assert manager.byRef == [("fill", "e1", "bob", None)], manager.byRef
        assert manager.byRole == []
        assert res["matched"]["ref"] == "e1", res

    def test_stale_ref_surfaces_theProducerNamedFailure(self, monkeypatch):
        """编号失效不是"执行失败"一句话：产出侧的 marker 必须原样带出。"""
        handler, model, manager, kwargs = _drive(
            monkeypatch, "smart_click", TREE_AMBIGUOUS, target="备注", ref="e2")
        manager.refFailure = (
            "target generation 过期（当前 9，传入 7）——页面已变化，快照事实失效，请重新 dom_snapshot")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(handler(body=model(**kwargs)))
        assert exc.value.status_code == 502, exc.value.status_code
        assert "generation 过期" in str(exc.value.detail), exc.value.detail

    def test_ref_alone_is_accepted_without_a_target(self, monkeypatch):
        """ref 是 target 的替代入口，不是附加装饰——两个都给是多余的耦合。"""
        res, manager = _call(monkeypatch, "smart_click", TREE_AMBIGUOUS, ref="e3")
        assert manager.byRef == [("click", "e3", None)], manager.byRef
        assert res["matched"]["ref"] == "e3"

    def test_neither_target_nor_ref_is_rejected_at_the_contract_edge(self, monkeypatch):
        """必填校验在边界做：空 body 走到解析层只会吐一句没有信息量的 404。"""
        handler, model, _manager, _kwargs = _drive(monkeypatch, "smart_click", TREE_AMBIGUOUS)
        with pytest.raises(Exception) as exc:
            model()
        assert type(exc.value).__name__ == "ValidationError", type(exc.value).__name__
