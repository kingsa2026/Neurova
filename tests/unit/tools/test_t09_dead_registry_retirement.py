# -*- coding: utf-8 -*-
"""T-09 死码处置批：`tool_layers` 第二份注册面与它撑起的不可达链（Issue #174 / #310）。

## 这一批处置的是什么（根因）

台账里 9 条待处置，其中 7 条是**同一条不可达链**：

    UnifiedToolRegistry      判据 `no_consumer`（生产侧只有一处孤立再导出 import）
      ├─ ToolExecutionLogger  唯一外部消费点 = `_get_tool_logger` 工厂
      ├─ CLIToolExecutor      唯一外部消费点 = `_get_cli_executor` 工厂
      └─ ToolExecutionResult  唯一外部消费点 = `_get_execution_result_class` 工厂

后三者的判据类是 `consumed`（1 跳可达），但**消费方自己不可达** ⇒ 链路整体不通。
逐条删是治标：真正要回答的是「`ToolRouter` 与 `ToolEngine` 之间到底需不需要
第二份注册表」。

## 裁定：不需要（三条机器可验的事实）

① **真面的职责已在** `ToolRouter`：它 `register_builtin` / `register_builtin_batch` /
   `set_execution_engine` / `set_tool_executor` / `register_mcp_client` /
   `get_all_tools` 一应俱全，且被 `agent_core.init_tools` 真装配
   （`a.tool_router = ToolRouter()`、`register_builtin_batch(tools_dict)`）。
   两份类的**同名前四个公开方法签名逐字相同** —— 这正是「第二份定义」的机器长相。

② **`ToolEngine` 侧不需要经它中转**：`ToolExecutor._create_tool_engine()` 直接从
   `ExecutionEngine` 取 `_tool_engine`，不经 `UnifiedToolRegistry`。

③ **`UnifiedToolRegistry` 没有任何生产实例化点**：全仓唯一提及是
   `tool_layers/__init__.py` 的再导出；它的 `set_execution_engine` /
   `register_to_engine` / `execute_and_log` / `register_builtin_batch` /
   `get_capability_graph` / `get_cli_executor` / `get_tool_logger`
   **生产侧零调用**（调用全部只在测试里，而测试正是这些契约的唯一守卫）。

故本批按「**已删除**」处置（与 `MAX_TOOL_CALL_ROUNDS` 同一口径：把声明本身删掉，
不是给死面补一个消费者）。整个模块退场，连带退役唯一消费者为它的三个符号。

## 本守卫与「测试也删」的边界

`tests/unit/tools/test_unified_registry.py` 与 `test_unified_tool_registry.py` 锁的是
**被退役的类**，随能力一并退役；但同文件里混着对仍在役符号的用例时**只删该删的**。
`execute_and_log` 那条被删的能力里有一条**不随类消失**的契约：
「工具结果的成功判据不得由包装壳自己说了算」（`ToolRouter.route` 的
`_result_is_success` 单源）。它必须在真面上仍有判据 —— 本文件同时钉住这一点，
并把两处反向控制（同文件仍活着的 `notify_tool_result` / `get_pipeline_observers`、
阈值可达的 `TokenBudgetGate`）留证。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ci import tool_loop_deadline_ledger as ledger  # noqa: E402

#: 本批退役的符号：整条不可达链（注册面自身 + 它撑起的三个 1 跳可达符号）。
RETIRED_BY_THIS_BATCH = (
    "UnifiedToolRegistry",
    "ToolExecutionLogger",
    "CLIToolExecutor",
    "ToolExecutionResult",
)


class TestRegistryFaceIsRetired:
    """第二份注册面整体退场：声明与实现一起消失，不留空壳。"""

    def test_moduleIsGone(self):
        """模块退场——`tool_layers/unified_registry.py` 不再是生产码。"""
        assert not (PROJECT_ROOT / "neurova/tool_layers/unified_registry.py").exists(), (
            "第二份注册面仍在生产根内——它是 `ToolRouter` 的同名第二份定义"
            "（register_builtin / register_builtin_batch / set_execution_engine / "
            "register_to_engine 四方法签名逐字相同），留着就必然与真面漂移"
        )

    def test_barrelNoLongerExportsIt(self):
        """`tool_layers/__init__.py` 的再导出同批删净——否则 import 侧仍指向空。"""
        text = (PROJECT_ROOT / "neurova/tool_layers/__init__.py").read_text(encoding="utf-8")
        assert "unified_registry" not in text, (
            "barrel 里仍有 unified_registry 的导入或 `__all__` 条目——"
            "模块已退场而导出还在，import 侧会拿到半死面"
        )
        assert "UnifiedToolRegistry" not in text, (
            "barrel 的 `__all__` 仍导出 UnifiedToolRegistry"
        )

    @pytest.mark.parametrize("symbol", RETIRED_BY_THIS_BATCH)
    def test_symbolsAreAbsentInProduction(self, symbol):
        """链路四符号在生产侧判据必须为 `absent`——「已删除」由机器验，不由人声称。"""
        judge, detail = ledger.classify(symbol)
        assert judge == ledger.JUDGE_ABSENT, (
            f"{symbol} 判据类 {judge}（{detail.get('rule')}），未真正从生产侧消失："
            f"引用点 {detail.get('consumer_files')}"
        )

    @pytest.mark.parametrize("symbol", RETIRED_BY_THIS_BATCH)
    def test_ledgerDisposalMatches(self, symbol):
        """台账处置必须标「已删除」——处置轴与判据轴咬合（`disposalConflicts()` 复算）。"""
        entry = ledger.readLedger().get(symbol)
        assert entry is not None, f"{symbol} 已从取数表消失却也在台账里消失——判据丢了一条"
        assert entry["disposal"] == ledger.DISPOSAL_RETIRED, (
            f"{symbol} 台账处置为 {entry['disposal']}，未标「已删除」"
        )

    def test_disposalConflictsAreEmpty(self):
        """整册台账的处置与判据咬合——不留任何「说做完了、代码里没做完」。"""
        assert ledger.disposalConflicts() == [], repr(ledger.disposalConflicts())


class TestNoConsumerForTheRetiredFace:
    """退场之后不得留下「只写不读」的残骸——与 `MAX_TOOL_CALL_ROUNDS` 同一条口径。"""

    def test_toolLoggerHasNoProductionWriter(self):
        """`ToolExecutionLogger` 的 JSON Lines 序列此前无生产写入方，退役后仍必须无。

        这条是**反向控制**：若有人日后新建一个写入方，判据类会变 `consumed`，
        本批的「已删除」处置立刻在 `disposalConflicts()` 上报红 —— 即
        「同一根因全命中点扫荡」这件事被机器守住，不靠人记得。
        """
        judge, _detail = ledger.classify("ToolExecutionLogger")
        assert judge == ledger.JUDGE_ABSENT, (
            "ToolExecutionLogger 又有了生产消费者——本批的退役裁定需要重新论证"
            "（它当初被判死是因为唯一消费方 UnifiedToolRegistry 自身不可达）"
        )

    def test_successJudgementStaysSingleSourcedOnTheRealFace(self):
        """被退役的 `execute_and_log` 里那条**不随类消失**的契约必须仍在真面上有判据。

        `execute_and_log` 自己算 success；真面 `ToolRouter.route` 的成功判据
        **单源**在 `ToolExecutor._result_is_success`（工具以 `{"error": …}` 形态失败
        而不抛异常时，包装壳不得报成功）。这条是它退役后唯一需要「搬过去」的语义，
        故在此钉住真面仍在。
        """
        router = (PROJECT_ROOT / "neurova/tool_layers/tool_router.py").read_text(encoding="utf-8")
        assert "_result_is_success" in router, (
            "真面 ToolRouter.route 的成功判据不再是单源 `_result_is_success`——"
            "包装壳又在自己判成功了（审计 L-02 的形态）"
        )


class TestReverseControlsStillHold:
    """反向控制：同域仍活着的接线不得被本批的「删」波及。"""

    def test_liveObserversRemainConsumed(self):
        """`notify_tool_result` / `get_pipeline_observers` 与退役面**同域不同文件**，
        本批不得连带砍断熔断器的观测接线。"""
        for symbol in ("notify_tool_result", "get_pipeline_observers"):
            judge, _detail = ledger.classify(symbol)
            assert judge == ledger.JUDGE_CONSUMED, (
                f"{symbol} 判据类退成 {judge}——本批的退役波及了活着的接线"
            )

    def test_tokenBudgetGateThresholdAxisStillHasTeeth(self):
        """阈值轴不得因本批整体退化——`TokenBudgetGate` 必须仍是 `single_source`。"""
        axis, _detail = ledger.thresholdAxis("TokenBudgetGate")
        assert axis == ledger.THRESHOLD_SINGLE_SOURCE, (
            f"反向控制 TokenBudgetGate 的阈值轴为 {axis}——轴失去判别力"
        )
