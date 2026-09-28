# -*- coding: utf-8 -*-
"""两条「未分期」条目的裁定：成本记账面第二份定义退役 / `ctx_snapshot` 并入反向控制。

## 这一批处置的是什么（两条互不相同的裁定线）

台账里最后两条待处置项标着「未分期」——它们**不是同一类问题**，故本批不套同一个模板：

### ① `CostTrackingMixin`：成本记账面**已有真面** ⇒ 第二份定义退役

台账原文要求裁定「成本记账面是否已有真面（`llm_client` 的 `_stats` 与
`@track_llm_call` 装饰器）」。机器事实：真面已闭环，且是**四路写入 + 单点落盘**——

    llm_client.chat           @track_llm_call 装饰器       （:334）
    llm_client._call_api      @track_llm_call 装饰器       （:690）
    llm_client.chat_stream    方法体内显式 record_llm_cost （:545 / :673）
    归属                      chat_pipeline 每轮 set_llm_cost_context（:480）
    落盘                      api/app.py install_llm_cost_store() + 小时聚合（:833）
    单一入口                  models/cost_tracking.record_llm_cost（docstring 自陈）

`_stats` 亦非死面：`Agent.get_stats()`（`agent_core.py:205`）→
`api/endpoints/agent.py:673` 真实对外暴露。

而 `llm/cost_tracking_middleware.py` 是**第三份并行定义**——与 T-09 处置的
`UnifiedToolRegistry` / `ToolExecutionLogger`、以及 `architecture-findings.md:284`
早已点名的「三套并行装饰器（分头写了三遍，一次都没接通）」同一条根因。
故处置口径与 T-09 同：**删声明本身，不给死面补消费者**（教义第 1/6 条）。

### ② `ctx_snapshot`：**它是活的** ⇒ 并入反向控制，永远「待处置」

台账原文已说明登记目的：「与 `MAX_TOOL_CALL_ROUNDS` 同处一个函数，一条活一条死，
判据必须能分开」。即它存在的意义是给判据留一把标尺，不是待删项。
机器事实：写入 1 处 + 读取 3 处，全在 `_auto_continue` 自身作用域内，
读改写后送 `predict_step`。

它与 `notify_tool_result` / `get_pipeline_observers` / `TokenBudgetGate` 是
**同一件东西**：已知可达、登记的目的是钉住判据的判别力。故并入 `REACHABLE_CONTROLS`，
处置列**永远**为「待处置」——不是「暂时没空处理」，而是「它的正解就是待处置」。

## 同根因扫荡（教义第 5 条）

`cost_tracking_middleware` 被点名后，同契约的**全部生产方**一并过：

    collaboration/cost_ledger_integration.py:27  track_llm_call_integration
        第三套并行装饰器，零生产引用 —— **但该文件不能整删**
        （on_agent_created / on_session_started / on_task_completed 被 phase3_api
         真实消费），故这是**符号级**退役，不是模块级。
    api/endpoints/computer_api.py                5 个 cost_tracking 孤儿 import
        （CostTracker / LLMCall / LLMProvider / LLMDirection / get_cost_tracker
         只导入、不使用）—— 同批清掉，不留「只导入不消费」的悬空引用。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ci import tool_loop_deadline_ledger as ledger  # noqa: E402

MIDDLEWARE_MODULE = PROJECT_ROOT / "neurova/llm/cost_tracking_middleware.py"
COST_LEDGER_INTEGRATION = PROJECT_ROOT / "neurova/collaboration/cost_ledger_integration.py"
COMPUTER_API = PROJECT_ROOT / "neurova/api/endpoints/computer_api.py"

#: 本批退役的第三份记账面（整模块退场）。
#: `CostTrackingMixin` 是台账登记的那个符号；`track_llm_call_decorator` 是同文件
#: 另一个公开导出，随模块一并退场（模块级处置不必逐符号登记——登记的目的是
#: 「钉住判据的可达性」，而模块退场后两者都是 `absent`）。
RETIRED_MIDDLEWARE_SYMBOLS = ("CostTrackingMixin",)
MIDDLEWARE_PUBLIC_SURFACE = ("CostTrackingMixin", "track_llm_call_decorator")

#: 同一根因的第二个命中点：符号级退役（文件保留，另有活面）。
RETIRED_INTEGRATION_SYMBOL = "track_llm_call_integration"


def _defines(tree: ast.AST, symbol: str) -> bool:
    """该语法树是否**定义**了这个符号（AST 落点级，不是文本级）。

    词边界而非子串：`track_llm_call_integration` 含 `track_llm_call` 前缀，
    子串匹配会把另一组符号误判（与台账「按名字 grep 会误判」同一纪律）。
    """
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


class TestCostTrackingSecondFaceIsRetired:
    """第三份成本记账面整体退场——真面已闭环，接第二份即第二份定义。"""

    def test_middlewareModuleIsGone(self):
        """模块退场——`llm/cost_tracking_middleware.py` 不再是生产码。"""
        assert not MIDDLEWARE_MODULE.exists(), (
            "第三份成本记账面仍在生产根内——真面（models/cost_tracking.record_llm_cost "
            "+ @track_llm_call + install_llm_cost_store）已四路闭环，"
            "再接一份就是第二份记账面（教义第 6 条）"
        )

    @pytest.mark.parametrize("symbol", RETIRED_MIDDLEWARE_SYMBOLS)
    def test_symbolsAreAbsentInProduction(self, symbol):
        """两符号判据必须为 `absent`——「已删除」由机器验，不由人声称。"""
        judge, detail = ledger.classify(symbol)
        assert judge == ledger.JUDGE_ABSENT, (
            f"{symbol} 判据类 {judge}（{detail.get('rule')}），未真正从生产侧消失："
            f"引用点 {detail.get('consumer_files')}"
        )

    def test_llmBarrelNoLongerExportsIt(self):
        """`llm/__init__.py` 若对本模块有再导出，同批删净——不留半死面。"""
        barrel = PROJECT_ROOT / "neurova/llm/__init__.py"
        if barrel.exists():
            text = barrel.read_text(encoding="utf-8")
            assert "cost_tracking_middleware" not in text, (
                "llm/__init__.py 仍从已退役的 cost_tracking_middleware 再导出"
            )
            for symbol in MIDDLEWARE_PUBLIC_SURFACE:
                assert not re.search(
                    rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text
                ), f"llm/__init__.py 仍导出 {symbol}——实现已退场而导出还在"


class TestRealCostFaceStaysWired:
    """真面（models/cost_tracking + llm_client 四路 + app 装配）一字不动。

    这是本批裁定的**前提**：真面若不再闭环，「不接线、退货」这个结论立刻不成立。
    故本类把这些接线钉成常驻判据——它们同时是「以后别再写第三份」的机器依据。
    """

    def test_recordLlmCostIsTheSingleEntry(self):
        """`record_llm_cost` 必须仍存在，且 docstring 自陈「唯一入口」。"""
        source = (PROJECT_ROOT / "neurova/models/cost_tracking.py").read_text(encoding="utf-8")
        assert "def record_llm_cost(" in source, "真面单一记账入口 record_llm_cost 消失了"
        assert "唯一入口" in source, (
            "record_llm_cost 的「唯一入口」声明消失了——真面口径被改写，"
            "本批「不接线」的裁定依据随之需要重新论证"
        )

    def test_llmClientCarriesTheThreeCallSiteWrites(self):
        """`llm_client.py` 仍承载三处调用点写入：装饰器 ×2 + 流式显式记账。

        这是**逐路**断言，不是「看一眼文件里有没有这个词」——非流式两路
        （`chat` / `_call_api` 的装饰器）与流式两路（`chat_stream` / `chat_stream_sync`
        末尾的显式 `record_llm_cost`）各算一处。
        """
        text = (PROJECT_ROOT / "neurova/llm_client.py").read_text(encoding="utf-8")
        assert text.count("@track_llm_call(") >= 2, (
            f"llm_client.py 的 @track_llm_call 装饰器少于 2 处"
            f"（实测 {text.count('@track_llm_call(')}）——非流式两路写入断了"
        )
        assert text.count("record_llm_cost(") >= 2, (
            f"llm_client.py 的显式 record_llm_cost 少于 2 处"
            f"（实测 {text.count('record_llm_cost(')}）——流式两路写入断了"
        )

    def test_chatPipelineStillBindsPerTurnOwnership(self):
        """`chat_pipeline.py` 每轮仍绑定成本归属——否则记账落到 "unknown"。"""
        text = (PROJECT_ROOT / "neurova/agent/chat_pipeline.py").read_text(encoding="utf-8")
        assert "set_llm_cost_context(" in text, (
            "chat_pipeline.py 不再设置每轮的 llm_cost_context——记账归属断链"
        )

    def test_appStillInstallsTheLedger(self):
        """`api/app.py` 启动装配仍保留——真面落盘侧是它接通的。"""
        text = (PROJECT_ROOT / "neurova/api/app.py").read_text(encoding="utf-8")
        assert "install_llm_cost_store" in text, (
            "api/app.py 不再装配成本账本——record_llm_cost 会静默降级（store is None），"
            "真面落盘侧断链"
        )


class TestSameRootCauseSweep:
    """同一根因（第三套并行记账装饰器）的全部命中点一并处置（教义第 5 条）。"""

    def test_integrationDecoratorIsRetired(self):
        """`track_llm_call_integration` 必须从生产侧消失（零引用的第三套装饰器）。"""
        tree = ast.parse(COST_LEDGER_INTEGRATION.read_text(encoding="utf-8"))
        assert not _defines(tree, RETIRED_INTEGRATION_SYMBOL), (
            f"{RETIRED_INTEGRATION_SYMBOL} 仍在 cost_ledger_integration.py 里——"
            "它是同一根因的第二个命中点（第三套并行记账装饰器），零生产引用"
        )

    def test_integrationFileSurvivesBecauseItCarriesLiveFace(self):
        """该文件**不能整删**：它另有被真实的消费面（phase3 的 on_* 回调）。

        这条是本批「符号级而非模块级」退役的机器依据——若活面消失，
        该文件就该整体退场；若活面仍在，整删会砍断 phase3 的回调接线。
        """
        assert COST_LEDGER_INTEGRATION.exists(), (
            "cost_ledger_integration.py 被整体删除——它同时承载 phase3 的 on_* 回调"
            "（活面），按文件判死会砍断那条接线"
        )
        tree = ast.parse(COST_LEDGER_INTEGRATION.read_text(encoding="utf-8"))
        for symbol in ("on_agent_created", "on_session_started", "on_task_completed"):
            assert _defines(tree, symbol), (
                f"活面 {symbol} 被本批连带删除——它是该文件不能整删的依据"
            )
        phase3 = (PROJECT_ROOT / "neurova/api/endpoints/phase3_api.py").read_text(encoding="utf-8")
        assert "cost_ledger_integration" in phase3, (
            "phase3_api.py 不再消费 cost_ledger_integration——活面不存在了，"
            "本批「符号级退役」的裁定需要重新论证"
        )

    def test_computerApiOrphanImportsAreGone(self):
        """`computer_api.py` 的 5 个 cost_tracking 孤儿 import 同批清掉。

        「只导入不消费」正是台账对孤立 `import` 的收窄口径（不算消费点）——
        留着就是悬空引用，指向本批正在收口的同一个记账域。
        """
        text = COMPUTER_API.read_text(encoding="utf-8")
        orphans = [
            name for name in (
                "CostTracker", "LLMCall", "LLMProvider", "LLMDirection", "get_cost_tracker"
            )
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text)
        ]
        assert not orphans, (
            f"computer_api.py 仍有 cost_tracking 孤儿 import {orphans}——"
            "只导入不消费的悬空引用必须清掉"
        )


class TestLedgerDisposalMatches:
    """台账处置与机器判据咬合——本批不留「说做完了、代码里没做完」。"""

    @pytest.mark.parametrize("symbol", RETIRED_MIDDLEWARE_SYMBOLS)
    def test_retiredSymbolsAreMarkedRetired(self, symbol):
        entry = ledger.readLedger().get(symbol)
        assert entry is not None, f"{symbol} 从台账消失——判据丢了一条"
        assert entry["disposal"] == ledger.DISPOSAL_RETIRED, (
            f"{symbol} 台账处置为 {entry['disposal']}，未标「已删除」"
        )

    def test_disposalConflictsAreEmpty(self):
        assert ledger.disposalConflicts() == [], repr(ledger.disposalConflicts())


class TestCtxSnapshotJoinsReverseControls:
    """`ctx_snapshot` 是**活的** ⇒ 并入反向控制，永远「待处置」。"""

    def test_itIsRegisteredAsAReverseControl(self):
        assert "ctx_snapshot" in ledger.REACHABLE_CONTROLS, (
            "ctx_snapshot 未并入反向控制——它是已知可达的活符号，"
            "登记目的是钉住判据的判别力（与 notify_tool_result 同类）"
        )

    def test_itsDisposalIsPermanentlyPending(self):
        entry = ledger.readLedger().get("ctx_snapshot")
        assert entry is not None, "ctx_snapshot 从台账消失——反向控制丢了一条"
        assert entry["disposal"] == ledger.DISPOSAL_PENDING, (
            f"ctx_snapshot 台账处置变成 {entry['disposal']}——反向控制项永远是「待处置」"
            "（它的正解就是待处置，不是「暂时没空处理」）"
        )

    def test_itIsActuallyLiveInItsOwnScope(self):
        """机器事实：写入 1 处 + 读取 3 处，全在 `_auto_continue` 作用域内。

        这条是「它为什么是反向控制」的**事实依据**：判据类 `self_loop` 不是缺陷，
        而是「活在自己函数里」——与死掉的 `MAX_TOOL_CALL_ROUNDS` 同处一个函数，
        判据必须能分开（台账原文）。
        """
        row = {str(r["symbol"]): r for r in ledger.facts()}.get("ctx_snapshot")
        assert row is not None, "取数表里没有 ctx_snapshot——判据取数坏了"
        assert row["judge"] == ledger.JUDGE_SELF_LOOP, (
            f"ctx_snapshot 判据类变 {row['judge']}——它应当仍活在自己函数作用域内"
        )
        assert row["consumer_count"] >= 1, (
            "ctx_snapshot 的读取点数归零——它不再是活的，反向控制的登记理由消失"
        )
        source = (PROJECT_ROOT / "neurova/agent/chat_pipeline.py").read_text(encoding="utf-8")
        assert "ctx_snapshot" in source, "chat_pipeline.py 里已无 ctx_snapshot"

    def test_pendingBatchEnumKeepsTheIssueScopeSentinel(self):
        """「未分期」哨兵必须**留在枚举里**——它是判据的可表达能力，不是域状态。

        本域清零的是「有哪条待处置项还没归属」，不是「能不能表达未归属」。
        删掉哨兵等于把「单条待处置无从表达归属」这个缺口重新打开
        （`test_dead_ledger_pending_progress.py` 的 `test_pendingBatchEnumIsDefinedInTheLedgerModule`
        一并钉住）。
        """
        assert ledger.PENDING_BATCH_ISSUE_SCOPE in ledger.PENDING_BATCHES, (
            "「未分期」哨兵被删——枚举失去「尚未并入任何批」的可表达能力"
        )

    def test_noUnscheduledPendingRemainsInThisDomain(self):
        """本域不再有「未分期」的待处置项——两条都已裁定归属。"""
        offenders = [
            symbol
            for symbol, entry in ledger.readLedger().items()
            if entry["disposal"] == ledger.DISPOSAL_PENDING
            and ledger.pendingBatchOf(entry) == ledger.PENDING_BATCH_ISSUE_SCOPE
        ]
        assert not offenders, (
            f"本域仍有「未分期」的待处置项 {offenders}——"
            "它们已被本批裁定（退役 / 反向控制），不得再挂在无归属的哨兵上"
        )

    def test_unownedPendingIsEmpty(self):
        """无人认领的待处置条目必须归零——本批是这一域的收口。"""
        assert ledger.unownedPendingSymbols() == [], (
            f"仍有无人认领的待处置条目 {ledger.unownedPendingSymbols()}"
        )
