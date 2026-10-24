"""`_retrieve_memories` 的 scopeCtx 入参契约守卫（§6-396，批 G）。

根因（一条签名变更留下的同根族，不是五份独立失败）：`ChatPipeline._retrieve_memories`
在批 3 里改成**必填** `scopeCtx`——作用域只由调用方单点解析
（`chat_pipeline.py:1649` `turnScopeContext(ctx.metadata, ctx.session_id)`），
理由写在该函数 docstring 里：「两处各算各的，一处漏掉就是本轮『检索按 A 作用域、
编排按 B 作用域』的分叉」（同源关系只能有一个持有者，§6-147）。
参数收得对，但**调用方没跟着扫**：到 2026-10-22 现算，仍有 4 个测试档按旧的单参形状调用，
整族 `TypeError` 常驻红——`tests/unit/agent/test_pipeline_adaptive_rag.py`(10 格)、
`tests/unit/agent/test_agent.py`(2)、`tests/unit/agent/test_context_bugs_pipeline.py`(2)、
`tests/test_memory/test_memory_retrieval_integration.py`(2)。四处都改成走生产那一个
`turnScopeContext()`，与 `tests/unit/agent/test_chat_pipeline.py` 里已有的正确写法同形。

同批顺出的一枚**第二形态**：`tests/test_memory/test_memory_retrieval_integration.py`
那唯一的 async 用例还没有 `@pytest.mark.asyncio`，在 `asyncio_mode=STRICT` 下报
`async def functions are not natively supported` —— 补上标记前它是 failed、补上是 passed，
**意味着这条集成链的用例从来没被执行过**（不是恒绿，是根本没跑）。落笔时我一度据此判定
"该档断言的是不存在的检索器接线"并 `git rm` 了它；用 `git show HEAD:` 把原档取回、
只补两处调用形状＋标记跑一遍，才证伪我自己的结论：它的每条断言都真过（`UnifiedRetriever`
确实经 `retriever_adapters.UnifiedRetrieverAdapter` 挂在链上，`chat_pipeline.py:245-247`）。
⇒ 已恢复原档并修到位。**退役判据不能靠一次 grep 就下结论**——与本仓形态
「判能力有无须核证据／『存在』≠『被消费』」是同一条规矩的反方向：
「看着像死档」≠「死档」，要真跑一遍再定。

本档两格：
1. `test_全仓不得再有单参调用形态`——AST 扫 `neurova/`＋`tests/`，任何
   `X._retrieve_memories(...)` 调用第一参之外还必须给 scopeCtx（`self._x` 形式的方法
   **定义**不算调用）；
2. `test_扫描器真会咬`——反向控制：单参合成样本必被点名，两参正确形不误报
   （否则第 1 格就是一条恒绿的假守卫，见形态 363／373 同族）。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import ast_scan

SCAN_ROOTS = ("neurova", "tests")

pytestmark = [pytest.mark.timeout(60)]


def _singleArgCallsIn(tree) -> list:
    """返回"只给了 ctx、没给 scopeCtx"的 `_retrieve_memories(...)` 调用行号。

    入参是**语法树**而不是源码：文件枚举与解析归 `tests/ast_scan.sourceRefsUnder`
    ＋ 一次性入口 `transientTree`，本档不再自付"自己枚举一整棵根树再逐个 parse"
    ——判据成本随代码总量涨正是本仓那条墙钟红的根因。
    """
    bad = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "_retrieve_memories":
            continue
        if len(node.args) + len(node.keywords) < 2:
            bad.append(node.lineno)
    return sorted(bad)


def test_全仓不得再有单参调用形态():
    offenders = []
    # 取数走共享解析预算（Issue #148）：一次性全仓扫描走 `sourceRefsUnder(hints=…)`，
    # 不留常驻语法树、不与代码总量和机器速度捆绑。
    # 候选面要**自己数**：收口成预筛后，`offenders` 为空既可能是"都改好了"，
    # 也可能是预筛/根写坏把命中滤空——两者必须在下面那句 assert 之前分开。
    scanned = 0
    for root in SCAN_ROOTS:
        for ref in ast_scan.sourceRefsUnder(REPO_ROOT / root, hints=("_retrieve_memories",)):
            scanned += 1
            lines = _singleArgCallsIn(ast_scan.transientTree(ref.path))
            if lines:
                offenders.append(
                    f"{ref.path.relative_to(REPO_ROOT).as_posix()}:{lines}"
                )
    corpusFiles = len(ast_scan.sourceRefsUnder(REPO_ROOT / "neurova", ".py"))
    assert corpusFiles >= 800, (
        "生产语料现读 %d 个 .py——REPO_ROOT 指错时这条判据根本不说话" % corpusFiles)
    # 候选面按**预筛后**读数定线：现算 13 个文件里含 `_retrieve_memories` 字样。
    # 掉到 0 ＝ 预筛词或根写坏（命中被滤空），而不是"调用方都改好了"。
    assert scanned >= 5, (
        "候选面现读 %d 个文件——预筛把命中滤空或根被改窄，此时『零 offender』不作数（面自证）" % scanned)
    assert not offenders, (
        "这些调用还按 `_retrieve_memories(ctx)` 的旧形状写，运行即 TypeError："
        + "; ".join(offenders)
        + "——作用域单点（`turnScopeContext`）是这条链的前提；把参数改回可选"
        "等于让『检索按 A 作用域、编排按 B 作用域』的分叉重新出现，所以只能修调用方。"
    )


def test_扫描器真会咬():
    # `await` 只能出现在 async 函数体内，样本得带宿主——否则解析即 SyntaxError，
    # 反向控制格本身先炸（本档落笔时踩过一次）。
    stale = "async def _probe(pipeline, ctx):\n    await pipeline._retrieve_memories(ctx)\n"
    fixed = (
        "async def _probe(pipeline, ctx):\n"
        "    await pipeline._retrieve_memories(\n"
        "        ctx, turnScopeContext(ctx.metadata, ctx.session_id)\n"
        "    )\n"
    )
    assert _singleArgCallsIn(ast.parse(stale)) == [2], "反向控制失效：单参调用没被点名＝本守卫恒绿"
    assert _singleArgCallsIn(ast.parse(fixed)) == [], "正确形被误报"
    assert _singleArgCallsIn(ast.parse("def _retrieve_memories(self, ctx, scopeCtx):\n    ...\n")) == [], (
        "方法定义被当成调用误报——守卫会咬住生产代码，口径不对"
    )
    # 合成样本自己得能过 ast.parse：带缩进的 def 顶格写会 IndentationError，
    # 于是反向控制格自身先炸（本档落笔时踩过两次，都在这一格）。
    with pytest.raises(SyntaxError):
        _singleArgCallsIn(ast.parse("    def _retrieve_memories(self):\n        ...\n"))
