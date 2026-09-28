# -*- coding: utf-8 -*-
"""T-03 存量的终局：协议桥收口为一份形态判别（Issue #177 / #310）。

## 这一批处置的是什么

T-03（Issue #177）把原生协议通路接上了线，把 `ToolSchemaConverter` / `ToolCallParser`
/ `tool_choice` 三条从死面变成真面，但台账三行的处置仍停在「待处置」，理由是
**「T-03 只接线，未清除存量判断口径」**。本批把那句存量清掉。

存量的机器长相是**同一份「三协议形态判别」写了两遍**：

    请求侧  tool_transport._asOpenAIFunction(tool)
              if tool.get("function")   → OpenAI 形态
              elif tool.get("input_schema") is not None → Anthropic 形态
              elif tool.get("parameters") is not None   → Google 形态
              else → 裸 {name, description}

    响应侧  openai_schema.ToolCallParser.parse_tool_call(block)
              if "function" in block              → OpenAI 形态
              elif block.get("type") == "tool_use" → Anthropic 形态
              elif "functionCall" in block         → Google 形态
              else → 通用兜底

两处各自维护一份「哪个键标识哪个协议」的判别表。判别表一旦漂移（例如某天加了
第四种协议、或 Anthropic 的标识键改名），**两边会各自按自己的那一份走**，而
没有任何东西会报红——这正是教义第 6 条点名的第二份定义。

## 裁定：判别收口到一处，两处调用方都走它

单一事实源选在 `tool_layers/openai_schema.py`（`ToolCallParser` 所在的模块）——
它是本仓既有的 OpenAI↔Anthropic↔Google 归一器，且已被两处真实消费
（`tool_transport` 请求侧、`protocol_thinking` 响应侧）。新增一个纯函数
`detectToolCallFormat(...)` 承担判别，`ToolCallParser.parse_tool_call` 与
`tool_transport._asOpenAIFunction` 都改走它。

**为什么不是把判别挪去 `tool_transport`**：`protocol_thinking` 是响应侧的唯一
消费方（它在 `llm/providers/` 里与 `tool_transport` 平级），把判别放进
`tool_transport` 会让响应侧反向依赖请求侧模块——方向错了。

## 判据口径

本批不新增第五个「判据类」——台账三行的判据类与引用点数**本来就对**（`consumed`），
本批改的是**依据里那句存量**：收口完成后，依据必须点名「判别只有一处实现」。
故本守卫的断言是结构性的：判别表只允许存在一份，两处调用方都必须调它。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ci import tool_loop_deadline_ledger as ledger  # noqa: E402

#: 判别单一事实源所在模块。
DETECTOR_MODULE = PROJECT_ROOT / "neurova/tool_layers/openai_schema.py"

#: **直接**调用判别器的调用方（请求侧）。
DIRECT_CALLERS = (PROJECT_ROOT / "neurova/llm/providers/tool_transport.py",)

#: **间接**走判别的调用方（响应侧：经 `ToolCallParser.parse_tool_call`）。
#: 它不 import 判别器——那会让响应侧反向依赖请求侧模块。判据因此查的是
#: 「它调的解析器是不是已经把判别收口了」，而不是「它有没有 import」。
INDIRECT_CALLERS = (PROJECT_ROOT / "neurova/llm/providers/protocol_thinking.py",)

#: 判别的对外名（单一事实源：判别表只此一份）。
DETECTOR_NAME = "detectToolCallFormat"


class TestDetectionHasASingleSource:
    """三协议形态判别只允许有一份实现。"""

    def test_detectorIsDefinedInTheSchemaModule(self):
        """判别函数必须在归一器模块里，且是**模块级纯函数**（两边都能调）。"""
        tree = ast.parse(DETECTOR_MODULE.read_text(encoding="utf-8"))
        found = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == DETECTOR_NAME
        ]
        assert found, (
            f"{DETECTOR_MODULE.name} 里没有模块级 {DETECTOR_NAME}()——"
            "协议形态判别没有单一事实源，两处调用方会各自维护一份判别表"
        )

    @pytest.mark.parametrize("caller", DIRECT_CALLERS, ids=lambda p: p.name)
    def test_directCallerDelegatesToTheDetector(self, caller):
        """请求侧必须**直接** import 并调用它——不许自己再判一遍。"""
        text = caller.read_text(encoding="utf-8")
        assert DETECTOR_NAME in text, (
            f"{caller.name} 没有走 {DETECTOR_NAME}()——它自己维护了一份判别表，"
            "与响应侧会各自漂移（教义第 6 条）"
        )

    @pytest.mark.parametrize("caller", INDIRECT_CALLERS, ids=lambda p: p.name)
    def test_indirectCallerUsesTheCollapsedParser(self, caller):
        """响应侧必须经 `ToolCallParser.parse_tool_call` 归一到 `LLMResponse.tool_calls`。

        这是**间接**走同一份判别的证明：它不 import 判别器（响应侧反向依赖请求侧
        模块是方向错的），而是调那个已经把判别收口掉的解析器。
        """
        text = caller.read_text(encoding="utf-8")
        assert "ToolCallParser" in text and "parse_tool_call" in text, (
            f"{caller.name} 不再经 ToolCallParser.parse_tool_call 归一工具块——"
            "它若自己解包，就是第三份形态判别"
        )

    def test_detectorHandlesAllThreeProtocols(self):
        """三协议标识键必须都在判别表里——收口不得顺手丢掉一种。"""
        text = DETECTOR_MODULE.read_text(encoding="utf-8")
        detector = text[text.index(f"def {DETECTOR_NAME}("):]
        for marker in ('"function"', "input_schema", "functionCall", "tool_use"):
            assert marker in detector, (
                f"判别表里没有 {marker}——收口把一种协议的标识键弄丢了，"
                "那会让它在真链路上退化成兜底分支（静默错判）"
            )


class TestNoSecondDetectionTable:
    """不许有第二份判别表——按「有没有在本地重新判三形态」复算。"""

    @pytest.mark.parametrize("caller", DIRECT_CALLERS, ids=lambda p: p.name)
    def test_callerDoesNotRebuildTheTable(self, caller):
        """直接调用方不得在函数体里**按形态分支**。

        判据从「有没有出现标识键字面量」收窄为「有没有**按形态走不同分支**」：
        收口后的请求侧仍会读 `tool["function"]` / `tool["input_schema"]`
        （那是**判别结果的消费**，两种形态本来就要取不同的键），但它**不再
        自己判**——判别由 `detectToolCallFormat()` 给出，分支条件是判别结果。
        所以真正的红线是：函数体里出现 `if <某个标识键> in ...` 这类**按形态
        自己判**的比较。
        """
        tree = ast.parse(caller.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Compare):
                    continue
                text = ast.unparse(sub)
                # 自己按形态判：拿某个协议标识键做 in / == 比较
                if any(marker in text for marker in ('"function" in', "'function' in",
                                                     'input_schema" in', "input_schema' in",
                                                     'functionCall" in', "functionCall' in")):
                    offenders.append(f"{node.name}:{sub.lineno} {text}")
        assert not offenders, (
            f"{caller.name} 里仍在按形态自己判 {offenders}——"
            "判别应当在归一器的单一事实源里，调用方只消费判别结果"
        )


class TestLedgerBasisIsUpdated:
    """台账三行的依据必须点名收口——把「未清除存量判断口径」那句清掉。"""

    @pytest.mark.parametrize("symbol", ("ToolSchemaConverter", "ToolCallParser"))
    def test_basisRecordsTheCollapse(self, symbol):
        basis = ledger.readLedger()[symbol]["basis"]
        assert "形态判别" in basis and "单一事实源" in basis, (
            f"{symbol} 的依据没有记录协议桥收口——台账会继续声称"
            "「T-03 只接线、未清除存量判断口径」，而存量已经清了"
        )

    def test_toolChoiceBasisRecordsPhases(self):
        """`tool_choice` 的依据必须点明它这一条**没有**待清存量。"""
        basis = ledger.readLedger()["tool_choice"]["basis"]
        assert "无待清存量" in basis or "不存在第二份" in basis, (
            "tool_choice 的依据没有交代它的存量到底是什么——"
            "三行都叫「T-03 存量」，但只有两条是真存量"
        )

    @pytest.mark.parametrize(
        "symbol", ("ToolSchemaConverter", "ToolCallParser", "tool_choice")
    )
    def test_disposalIsWiredNotPending(self, symbol):
        """三条必须标「已接线」——收口完成后它们不该再挂在待处置轴下。"""
        entry = ledger.readLedger()[symbol]
        assert entry["disposal"] == ledger.DISPOSAL_WIRED, (
            f"{symbol} 处置为 {entry['disposal']}——协议桥收口完成后仍停在待处置，"
            "T-03 会永远带着存量"
        )

    def test_disposalConflictsAreEmpty(self):
        assert ledger.disposalConflicts() == [], repr(ledger.disposalConflicts())


class TestT03ClosesOut:
    """T-03 这一批清空之后，批次读数必须显示「已清」。"""

    def test_t03HasNoPendingLeft(self):
        progress = ledger.batchProgress()["T-03"]
        assert progress["closed"], (
            f"T-03 仍有 {progress['pending']} 条待处置——本批的目标是把它清零"
        )

    def test_t03EntriesAreJustifiedInTheDisposalGuard(self):
        """三条必须进 `WIRED_BY_LATER_WAVES` 的逐条论证（不许顺手改台账）。"""
        guardText = (
            PROJECT_ROOT / "tests/unit/tools/test_tool_loop_deadline_disposal.py"
        ).read_text(encoding="utf-8")
        for symbol in ("ToolSchemaConverter", "ToolCallParser", "tool_choice"):
            assert f'"{symbol}"' in guardText, (
                f"{symbol} 标了已接线却不在处置批论证里——无据的处置即红"
            )
