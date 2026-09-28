# -*- coding: utf-8 -*-
"""`_auto_continue` 里不得留「只写不读」的上界常量（Issue #174 台账 T-09 命中点）。

## 现象与事实

`scripts/ci/toolLoopDeadlines.txt` 的两行（`MAX_TOOL_CALL_ROUNDS` 与
`tool_call_rounds`，判据类 `no_consumer`）实测复算：`_auto_continue` 函数作用域内
**只有 Store、零 Load**。同函数的其余上界常量（`MAX_CONTINUE_ROUNDS` /
`MAX_TOTAL_CHARS`）都有真实读取点，故这不是「常量都在函数头列出」的误判。

## 根因（不是「谁忘了读」）

前像（`git show 33b71a25:neurova/agent/chat_pipeline.py`）里它**是活的**：

```python
# 护栏 D: 工具调用循环
if getattr(response, "tool_calls", None):
    tool_call_rounds += 1
    if tool_call_rounds >= MAX_TOOL_CALL_ROUNDS:
        _tools = None
```

`dc9b9a0f` 的「Bug A-5 修复」判定这两处消费者恒为 False 并删除 —— 那个判定**是对的**：
`while` 条件里已有 `not getattr(response, "tool_calls", None)`，故分支内的
`response.tool_calls` 必然为空。**但声明被留下**：一条 guard 的三个部分（声明、
计数、判据）只删了两部分，剩下的那部分就成了「读起来像护栏、实际无人读」的残骸。

这正是台账"发现但未修"要抓的形态：`no_consumer` 的常量不会报错、不会拖慢、
也不会有测试失败 —— 它只会让下一个读代码的人以为"工具轮次有上界"。

## 处置口径：不是"给它加个消费者"

被删的消费者确实恒假，**不能恢复**（恢复即复活一处死分支）。
正确处置是删掉声明本身：护栏本来就没有存在的必要，因为 `while` 条件已经
排除了所有带 `tool_calls` 的轮次 —— 续写段从一开始就走不到"工具轮次"这件事。
"""
from __future__ import annotations

import ast
import io
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PIPELINE = PROJECT_ROOT / "neurova" / "agent" / "chat_pipeline.py"

#: 台账（scripts/ci/toolLoopDeadlines.txt）登记为 no_consumer 的两条。
LEDGER_ENTRIES = ("MAX_TOOL_CALL_ROUNDS", "tool_call_rounds")


def _auto_continue_node() -> ast.AST:
    tree = ast.parse(io.open(PIPELINE, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_auto_continue":
            return node
    pytest.fail("chat_pipeline._auto_continue 不见了——本判据的判据面失效，禁止空转通过")


def _nameAccesses(function: ast.AST) -> dict:
    """函数作用域内按名字记账的 Store / Load 行号（AST 事实，非文本匹配）。"""
    accesses: dict = {}
    for node in ast.walk(function):
        if isinstance(node, ast.Name):
            kind = "Store" if isinstance(node.ctx, ast.Store) else "Load"
            accesses.setdefault(node.id, {}).setdefault(kind, []).append(node.lineno)
    return accesses


class TestLedgerEntriesAreGone:
    """台账那两条要么真被消费、要么不存在——不许留在「只写不读」态。"""

    @pytest.mark.parametrize("name", LEDGER_ENTRIES)
    def test_no_storeOnlyLocal(self, name):
        accesses = _nameAccesses(_auto_continue_node()).get(name, {})
        stores = accesses.get("Store", [])
        loads = accesses.get("Load", [])
        assert not (stores and not loads), (
            f"`{name}` 在 chat_pipeline._auto_continue 里只写不读"
            f"（Store={stores}，Load={loads}）——\n"
            "这是一条护栏的残骸：声明还在，判据与计数被删了。\n"
            "它不会报错也不会变慢，只会让读者以为这里有个生效的上界。\n"
            "处置：删掉声明本身（不要为了「让它被读」把已判定恒假的消费者复活）。"
        )

    def test_theFunctionStillHasLiveBudgetConstants(self):
        """反向控制：同函数里活着的上界常量必须仍在且确实被读。

        若把这条也一起删了，下面的断言会失去判别力（判据退化成"删干净就算过"）。
        """
        accesses = _nameAccesses(_auto_continue_node())
        for name in ("MAX_CONTINUE_ROUNDS", "MAX_TOTAL_CHARS"):
            entry = accesses.get(name, {})
            assert entry.get("Store") and entry.get("Load"), (
                f"`{name}` 应当既是声明又有读取点（它是活护栏）；实测 {entry}。"
                "本判据不接受「把活常量也一起删掉」式的通过。"
            )


class TestWhileConditionAlreadyExcludesToolRounds:
    """口径自证：`while` 条件排除了所有带 tool_calls 的响应。

    这是"消费者恒假、不可恢复"的事实依据；写在守卫里是为了让下一个人
    不必再翻 git 历史重新论证一遍。
    """

    #: 判据形态：`not getattr(<...>, "tool_calls", None)`。
    #: **不比对 `ast.unparse` 的字符串**——它会把引号归一成单引号，
    #: 按字面量比对会得到"实现正确但判据报红"的假阳性（第一版就踩了这个）。
    #: 按 AST 结构判定，与源码书写风格解耦。
    EXPECTED_CALL = "getattr"
    EXPECTED_ATTR = "tool_calls"

    def test_whileGuardExcludesToolCallResponses(self):
        node = _auto_continue_node()
        whiles = [n for n in ast.walk(node) if isinstance(n, ast.While)]
        assert len(whiles) == 1, f"_auto_continue 的 while 数量变了（{len(whiles)}）——判据面需重核"
        condition = whiles[0].test
        found = False
        for candidate in ast.walk(condition):
            if not isinstance(candidate, ast.UnaryOp) or not isinstance(candidate.op, ast.Not):
                continue
            call = candidate.operand
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)):
                continue
            if call.func.id != self.EXPECTED_CALL:
                continue
            args = [a for a in call.args if isinstance(a, ast.Constant)
                    and a.value == self.EXPECTED_ATTR]
            if args:
                found = True
                break
        assert found, (
            "`while` 条件里不再排除带 `tool_calls` 的响应——\n"
            "本批「工具轮次上界没有存在必要」的论证前提不存在了，"
            "请重新评估是否真的需要在续写段加工具轮次上界（不要再把死分支原样贴回来）。"
            f"\n实测条件：{ast.unparse(condition)}"
        )
