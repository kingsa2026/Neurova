# -*- coding: utf-8 -*-
"""T-09 死码处置批：`agent/tool_pipeline.py` 五段流水线面与重置出口（Issue #174 / #310）。

## 这一批处置的是什么

T-09 最后两条待处置符号与反向控制 `notify_tool_result` / `get_pipeline_observers`
**同处一个文件**，所以处置必须落在**类这一级**，且必须先确认「五段流水线是否要以
`PipelineConfig` / `PipelineGuardAdapter` 形态接线」（台账那一行原话）。

## 裁定：不接线，整体退场

机器事实（全部可复算）：

```
ToolExecutionPipeline       sites=1  只有自己的 def —— 全仓零引用，连 import 都没有
reset_pipeline_observers    sites=1  只有自己的 def —— 除 `__all__` 外零引用
PipelineConfig              类内自消费（:212 自己构造）
PipelineGuardAdapter        类内自消费（:183 定义，:216 只作类型标注）
ToolExecutionStep           类内自消费
PipelineReject              类内自消费
```

即：**五段流水线的每一段（pre / guard / execute / post）在生产侧都没有任何注册方**
——`add_pre_step` / `add_guard` / `add_execute_wrapper` / `add_post_step`
全仓零调用。唯一真活着的是 **result 段**，而它**已经独立成面**：
`PipelineObserversRegistry` + `get_pipeline_observers()` + `notify_tool_result()`
被 `security/tool_circuit_breaker.py:136`（挂熔断观察者）与
`tool_executor.py:5637`（`on_tool_executed` 尾部通知）真实消费。

所以「以 `PipelineConfig` 形态接线」不是待办，是**已被否证的方案**：流水线四段的
职责在生产上由 `ToolExecutor` 的信封（超时/治理预检/hooks/per-tool 超时）承担，
再挂一套五段框架只会是**第二份执行编排**（教义第 6 条）。本批把四段框架整体退场，
**只留 result 面**——它才是真面。

`ToolExecutionReport` / `ToolExecutionContext` 随流水线退场：
前者只服务五段报告（`resolve()` 的产出），后者是 `tool_layers/types.ToolExecutionContext`
的「旧构造兼容子类」（`success=` / `execution_time=` 关键字已无生产者）。
`PipelineObserversRegistry` 改用规范上下文类型，不再经兼容子类。

## 边界：文件不删，活着的两条接线一字不动

本文件**整模块保留**（`notify_tool_result` / `get_pipeline_observers` 是反向控制、
永远为 `待处置`），故本批是**符号级退役**而非文件级——这正是台账前置警告 1
（「按文件判死会连带砍断熔断器的观测接线」）的落点。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ci import tool_loop_deadline_ledger as ledger  # noqa: E402

PIPELINE_MODULE = PROJECT_ROOT / "neurova/agent/tool_pipeline.py"

#: 本批退役的五段框架符号（**实现**：类/函数定义）。
RETIRED_BY_THIS_BATCH = (
    "ToolExecutionPipeline",
    "reset_pipeline_observers",
    "PipelineConfig",
    "PipelineGuardAdapter",
    "PipelineReject",
    "ToolExecutionStep",
)

#: 必须**保留**的 result 面（真面）：熔断器与 ToolExecutor 真实消费。
#: `ToolExecutionReport` 与 `PipelineObserversRegistry` 属这一面 —— 前者是发给
#: 观察者的契约形状（`frozen()` 深拷贝快照），后者是注册表本身。它们由五段框架
#: **降级为独立面**，不是被删：本批删的是「编排」，不是「结果分发」。
KEPT_RESULT_FACE = (
    "notify_tool_result",
    "get_pipeline_observers",
    "ToolExecutionReport",
    "PipelineObserversRegistry",
)


def _moduleText() -> str:
    return PIPELINE_MODULE.read_text(encoding="utf-8")


def _defines(text: str, symbol: str) -> bool:
    """该模块是否还**定义**了这个符号（AST 落点级，不是文本级）。

    两道收窄，都不是洁癖：
    - 按 **AST 落点**（`ClassDef` / `FunctionDef` / 赋值目标）判，不按文本：
      模块 docstring 会**叙述**已退场的符号名（说明「别再把它接回来」），
      文本级匹配会把叙述当成残留。
    - 词边界而非子串：`ToolExecutionReport` 含 `ToolExecution` 前缀，
      子串匹配会把**另一组符号**误判成残留（与台账「按名字 grep 会误判」同一纪律）。
    """
    import ast

    tree = ast.parse(text)
    prefix = rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])"
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if re.fullmatch(prefix, node.name):
                return True
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and re.fullmatch(prefix, target.id):
                    return True
    return False


class TestPipelineFrameIsRetired:
    """五段框架整体退场：四段零注册方，真面已独立成 result 面。"""

    @pytest.mark.parametrize("symbol", RETIRED_BY_THIS_BATCH)
    def test_symbolIsGoneFromTheModule(self, symbol):
        """框架符号必须从这个文件里删净——`__all__` 一并收。"""
        assert not _defines(_moduleText(), symbol), (
            f"{symbol} 仍在 tool_pipeline.py 里——五段框架的每一段在生产侧零注册方，"
            "留着就是第二份执行编排（真面是 ToolExecutor 的信封）"
        )

    def test_noUnreachableFrameworkSymbolsRemain(self):
        """退役后，本模块**除了 result 面之外**不得再有生产零引用的公开符号。

        这条是「不留只写不读」的机器表达：把本模块的 `__all__` 逐名过一遍，
        每个名必须要么是 result 面（真面），要么在生产侧有消费点。
        """
        text = _moduleText()
        exported = re.findall(r'^\s{4}"([A-Za-z_][A-Za-z0-9_]*)"', text, re.M)
        assert exported, "从 __all__ 里读不到任何导出名——判据取数坏了（会恒真通过）"
        orphans = [
            name for name in exported
            if name not in KEPT_RESULT_FACE and not _consumedElsewhere(name)
        ]
        assert not orphans, (
            f"tool_pipeline.py 的 __all__ 里仍有生产零消费的导出 {orphans}——"
            "退役只删了实现、留下了再导出（半死面）"
        )

    def test_barrelNoLongerReExportsTheFrame(self):
        """`agent/__init__.py` 对本模块的再导出同批收——否则 import 侧指向空。

        **只查来自 `agent.tool_pipeline` 的那些名**：`agent/__init__.py` 里另有一个
        同名 `ToolExecutionContext`，它来自 `agent.tool_execution_manager`
        （后者的规范定义在 `tool_layers/types.py`）——与本模块的兼容子类**同源不同出**
        （正是本批反复遇到的同名第二份形态）。按名字断言会误伤那一份。
        """
        text = (PROJECT_ROOT / "neurova/agent/__init__.py").read_text(encoding="utf-8")
        assert "agent.tool_pipeline import" not in text and (
            "from neurova.agent.tool_pipeline import" not in text
        ), "agent/__init__.py 仍从 tool_pipeline 再导出——退役的框架符号会从桶里漏出"
        for symbol in ("ToolExecutionPipeline", "PipelineGuardAdapter", "PipelineConfig"):
            assert not re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text
            ), f"agent/__init__.py 仍导出 {symbol}——符号已退场而导出还在"

    @pytest.mark.parametrize("symbol", ["ToolExecutionPipeline", "reset_pipeline_observers"])
    def test_ledgerDisposalMatches(self, symbol):
        entry = ledger.readLedger().get(symbol)
        assert entry is not None, f"{symbol} 从取数表与台账同时消失——判据丢了一条"
        assert entry["disposal"] == ledger.DISPOSAL_RETIRED, (
            f"{symbol} 台账处置为 {entry['disposal']}，未标「已删除」"
        )


def _consumedElsewhere(name: str) -> bool:
    """该名在**任何生产模块**里是否还有消费点（用于 `__all__` 扫荡的补取数）。"""
    try:
        return any(
            site.form in ("call", "read") for site in ledger.referenceSites(name)
        )
    except KeyError:
        # 未登记进死线表的符号：按 AST 直接看它在生产侧有没有被调用/读取。
        import ast

        from tests import ast_scan

        for ref in ast_scan.sourceRefsUnder(ast_scan.PRODUCTION_ROOT, hints=(name,)):
            rel = ast_scan.relativeToRepo(ref.path)
            try:
                tree = ast.parse((PROJECT_ROOT / rel).read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == name):
                    return True
                if (isinstance(node, ast.Attribute) and node.attr == name):
                    return True
        return False


class TestResultFaceStaysLive:
    """result 面是**真面**：熔断器与 ToolExecutor 的接线一字不动。"""

    def test_fileIsNotDeletedAsAWhole(self):
        """本批是**符号级**退役，不是文件级——按文件判死会砍断熔断器的观测接线。

        这正是台账对 `ToolExecutionPipeline` 那一行写下的前置警告 1
        （与反向控制 `notify_tool_result` / `get_pipeline_observers` 同处一个文件）。
        """
        assert PIPELINE_MODULE.exists(), (
            "tool_pipeline.py 被整体删除——它同时承载 result 面（真面），"
            "按文件判死会连带砍断熔断器的观测接线"
        )

    @pytest.mark.parametrize("symbol", KEPT_RESULT_FACE)
    def test_resultFaceIsStillDefined(self, symbol):
        assert _defines(_moduleText(), symbol), f"真面 {symbol} 被本批连带删除"

    def test_circuitBreakerStillMountsObserverThroughTheFacade(self):
        """熔断器仍经 `get_pipeline_observers()` 挂观察者——这是 result 面存在的依据。"""
        breaker = (PROJECT_ROOT / "neurova/security/tool_circuit_breaker.py").read_text(encoding="utf-8")
        assert "get_pipeline_observers" in breaker and "add_result_observer" in breaker, (
            "熔断器不再经门面挂观察者——result 面的「唯一生产消费方」不成立了，"
            "本批的裁定前提（只留 result 面）随之需要重新论证"
        )

    def test_executorStillNotifiesThroughTheFacade(self):
        """`ToolExecutor.on_tool_executed` 尾部仍调 `notify_tool_result`。"""
        executor = (PROJECT_ROOT / "neurova/tool_executor.py").read_text(encoding="utf-8")
        assert "notify_tool_result" in executor, (
            "ToolExecutor 不再调 notify_tool_result——result 面的写入侧断了"
        )

    @pytest.mark.parametrize("symbol", ("notify_tool_result", "get_pipeline_observers"))
    def test_reverseControlsRemainPending(self, symbol):
        """反向控制永远为 `待处置`——本批不得顺手改它们的处置列。

        只对**登记为反向控制**的两条断言：`ToolExecutionReport` 与
        `PipelineObserversRegistry` 不是反向控制（未进 `REACHABLE_CONTROLS`），
        它们的处置由本批的「保留」状态决定，不套用这条纪律。
        """
        entry = ledger.readLedger().get(symbol)
        assert entry is not None, f"{symbol} 从台账消失——反向控制丢了一条"
        assert entry["disposal"] == ledger.DISPOSAL_PENDING, (
            f"{symbol} 台账处置变成 {entry['disposal']}——反向控制项的永远是「待处置」"
        )
        assert symbol in ledger.REACHABLE_CONTROLS, (
            f"{symbol} 不在台账的反向控制名单里——本判据的前提不成立"
        )
