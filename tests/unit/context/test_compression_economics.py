# -*- coding: utf-8 -*-
"""002 · 压缩经济性判据与不动作原因枚举（Issue #289）。

本仓此前只回答"怎么塞下"，不回答"该不该塞"：`compression_ratio` 是"装不下
就等比缩小"的**结果**，算出来只进日志、跨趟无人回读；而 `envelope.py` 那条
"装不下弃整个信封"是净损失路径，此前不产生任何可归因读数。

验收契约（对应票面九条红灯）：
1. 收益为正但补不回代价 ⇒ 不动作，且原因是被点名的**那一个**；
2. 整封被弃 ⇒ 必须带可归因原因，不再静默丢弃；
3. "没测到"与"不划算"必须是两个不同值（未测量不得演成失败）；
4. 撞窗口硬顶时安全线让位，经济性不得削弱它；
5. 预演无物可切时不得先动作再失败；
6. `compression_ratio` 必须被决策回读，而不是只落日志；
7/8. 判据链路只允许一把尺子、只允许一处"代价"定义（静态守卫）；
9. 尺子未校准时闸不得进入生效态。
"""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from neurova.context.compression_economics import (
    ACTING_VALUES,
    INACTION_VALUES,
    CompressionAction,
    evaluateCompressionEconomics,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _verdict(**overrides):
    """基线的"划算"输入：折叠 4000、留存 100、未撞顶、上一轮实测 0.25。"""
    params = {
        "foldable_tokens": 4000,
        "summary_tokens": 100,
        "occupied_tokens": 900,
        "window_ceiling": 10000,
        "prior_compression_ratio": 0.25,
    }
    params.update(overrides)
    return evaluateCompressionEconomics(**params)


def _make_injector(**kwargs):
    from neurova.context.injector import UnifiedContextInjector
    from neurova.context.models import TokenBudget

    return UnifiedContextInjector(
        memory_manager=SimpleNamespace(),
        token_budget=TokenBudget(max_total=kwargs.pop("max_total", 1000)),
        enable_cache=False,
        **kwargs,
    )


def _big_history(turns=6):
    return [{"role": "user", "content": "历史消息" * 400} for _ in range(turns)]


#: 触发压缩的输入形态：历史会被 `_trim_history` 先裁到预算内，故由 user 侧吃满。
_OVER_BUDGET_INPUT = "问" * 2000


class TestClosedReasonEnumeration:
    """原因集合穷举且互斥，每个非动作原因至少一条用例。"""

    def testProfitPositiveButCostUnrecoverableYieldsDeferredReason(self):
        """折叠确实省了一点，但补不回为留存摘要付出的代价 ⇒ 不动作。"""
        v = _verdict(foldable_tokens=150, summary_tokens=100)
        assert v.act is False
        assert v.action is CompressionAction.UNECONOMICAL
        assert v.profit == 50, "收益要如实报出（正数），不得报 0 掩盖"
        assert v.cost == 100

    def testProfitNotPositiveYieldsOwnReason(self):
        """折叠后省不出 token ⇒ 另一个原因值，不与"不划算"混用。"""
        v = _verdict(foldable_tokens=100, summary_tokens=100)
        assert v.act is False
        assert v.action is CompressionAction.PROFIT_NOT_POSITIVE

    def testUnmeasuredPriorRoundReasonDiffersFromUneconomicalReason(self):
        """`None` = 从未测过 ≠ 测了但不划算。三态不许折叠。"""
        unmeasured = _verdict(prior_compression_ratio=None)
        uneconomical = _verdict(foldable_tokens=150, summary_tokens=100)
        assert unmeasured.act is False
        assert unmeasured.action is CompressionAction.INSUFFICIENT_DATA
        assert unmeasured.action is not uneconomical.action

    def testPriorRoundMeasuredFutileFoldIsUneconomical(self):
        """上一轮实测压缩比 1.0（压了等于没压）⇒ 重复同一动作不划算。"""
        v = _verdict(prior_compression_ratio=1.0)
        assert v.act is False
        assert v.action is CompressionAction.UNECONOMICAL

    def testInfeasibleCutIsDetectedBeforeAbort(self):
        """预演发现无物可切 ⇒ 不进入动作（不许动作之后再失败）。"""
        v = _verdict(foldable_tokens=0, summary_tokens=0)
        assert v.act is False
        assert v.action is CompressionAction.INFEASIBLE

    def testActingAndInactionValuesPartitionTheEnum(self):
        """两轴互补且穷举：集合之外没有第三个态。"""
        assert ACTING_VALUES | INACTION_VALUES == set(CompressionAction)
        assert not (ACTING_VALUES & INACTION_VALUES)

    def testEconomicalFoldActs(self):
        """正控：真省得下来时必须动作（否则这闸就是恒不放行的死闸）。"""
        v = _verdict()
        assert v.act is True
        assert v.action is CompressionAction.ECONOMICAL


class TestSafetyLineAndRuler:
    def testSafetyLineBypassesEconomicGate(self):
        """撞窗口硬顶必须压：经济性不得削弱安全线。"""
        v = _verdict(
            foldable_tokens=100, summary_tokens=100, occupied_tokens=10000, window_ceiling=10000
        )
        assert v.act is True
        assert v.action is CompressionAction.SAFETY_LINE_YIELD

    def testGateRefusesToArmWhileEstimatorRulerIsUncorrected(self):
        """尺子未校准 ⇒ 闸不得进入生效态，且以显式原因值暴露（不许"看起来在工作"）。"""
        v = _verdict(ruler_calibrated=False)
        assert v.act is False
        assert v.action is CompressionAction.RULER_UNCALIBRATED

    def testRulerCalibrationProbeIsSingleSource(self):
        """校准探针只有一处：判据不得自己再实现一遍 tiktoken 可用性判断。"""
        economics = (REPO_ROOT / "neurova/context/compression_economics.py").read_text(encoding="utf-8")
        assert "import tiktoken" not in economics
        probe = (REPO_ROOT / "neurova/context/token_estimator.py").read_text(encoding="utf-8")
        assert "def isRulerCalibrated" in probe


class TestEnvelopeDiscardAttribution:
    def testWholeEnvelopeDiscardEmitsAttributableReason(self):
        """整封被弃是净损失路径 ⇒ 产生该状态的地方就要出原因（今天静默返回空串）。"""
        from neurova.context.envelope import build_envelope, compress_envelope

        envelope = build_envelope({"memories": "\n".join(["记忆行" + "细节" * 20] * 50)})
        report = {}
        out = compress_envelope(envelope, budget_tokens=1, report=report)
        assert out == "", "预算小到外壳都装不下时应弃封"
        assert report.get("discarded") is True, "弃封必须留下可归因标记"
        assert report.get("reason") == CompressionAction.ENVELOPE_DISCARDED.value

    def testNonDiscardingPathLeavesNoDiscardMark(self):
        """反向控制：正常压缩不得被记成丢弃（否则账本恒真）。"""
        from neurova.context.envelope import compress_envelope

        report = {}
        compress_envelope("<system-reminder><memories>x</memories></system-reminder>", budget_tokens=500, report=report)
        assert report.get("discarded") is not True

    def testEnvelopeDiscardReasonIsInClosedEnum(self):
        assert CompressionAction.ENVELOPE_DISCARDED in INACTION_VALUES


class TestDiscardAttributionOnEveryEndpoint:
    """弃封出账必须在**两个**接入点都接上，不许只接池侧。

    `envelope.compress_envelope` 的 `report` 契约只被池分支传了
    （`orchestrator.py`），而非池主路径 `injector._compress_context`——它同时是
    非池直连与 builder 降级链两处的唯一压缩入口——调用时**没传**。
    于是"弃封不再静默"只在最不常走的池分支成立：用户侧最常走的这条，
    整封被丢之后仍从账上看不出来（教义第 5 条：同一契约的消费方一并修）。
    """

    def testNonPoolDiscardIsAttributableFromBuildResult(self):
        """非池弃封必须在装配结果里可归因（不是只在 `envelope.py` 直调时可归因）。"""
        injector = _make_injector(max_total=1000)
        result = injector.build_context(
            system_prompt="S" * 3000,  # 预算被 system 吃掉 ⇒ 信封额度落到 0
            memories=[{"content": "记忆内容" * 200}],
            conversation_history=[{"role": "user", "content": "历史" * 100}],
            user_input="问" * 800,
        )
        assert "<system-reminder>" not in result.context[-1]["content"], (
            "前置条件：该输入必须真的把整封弃掉，否则本条不成立"
        )
        readout = result.stats["compression_economics"]
        assert readout.get("discarded") is True, f"非池弃封未出账：{readout}"
        assert readout.get("reason") == CompressionAction.ENVELOPE_DISCARDED.value

    def testNonDiscardingTurnLeavesNoDiscardMark(self):
        """反向控制：真跑了压缩、但**没有**弃封的那一轮不得被记成丢弃（否则账本恒真）。

        额度取 2500：实测该输入下 `compress_envelope` 被调用且信封落回额度内
        （不是"压根没走压缩"那种"因为没发生所以没记"的假绿）。
        """
        injector = _make_injector(max_total=2500)
        result = injector.build_context(
            system_prompt="BASE",
            memories=[],
            conversation_history=_big_history(),
            user_input=_OVER_BUDGET_INPUT,
        )
        assert result.compression_ratio < 1.0, (
            "前置条件：该输入必须真的触发压缩，否则本条退化成'没发生所以没记'"
        )
        readout = result.stats["compression_economics"]
        assert readout.get("discarded") is not True, f"未弃封却记了丢弃：{readout}"


class TestPoolSideReadoutsAreReadable:
    """池分支的读数必须**可读**，不能只写进私有字段。

    根因（教义第 5 条同根扫荡）：`orchestrator` 侧新增的三个字段
    （`_poolCompressionRatio` / `_poolEconomicsReadout` / `_poolDiscardReadout`）
    全仓**零读者** —— 生产、测试、观测面都没有人读它。写进私有字段就等于
    写进日志：事后既查不到"这轮该不该压"，也查不到"整封是不是被丢了"，
    与本票要灭的"净损失路径不可归因"是同一形态换了个位置。
    """

    def testPoolDiscardAndVerdictReachContextHealth(self):
        """池侧弃封与判据读数必须经既有观测面（`get_context_health`）可读。

        不新开第二套读数体系（教义第 6 条）：`get_context_health` 是本仓上下文域
        降级/读数的既有单源，池侧读数并进它，`/metrics` 随即自动可见。
        """
        from tests.unit.context.test_pool_branch_envelope_transient import _orchestrator

        from tests.unit.context.test_pool_branch_envelope_transient import _orchestrator

        orch = _orchestrator(budget=1200)
        health = orch.get_context_health()
        assert "compression_economics" in health, (
            f"池侧读数未接上观测面，现有读面键：{sorted(health)}"
        )
        slot = health["compression_economics"]
        assert "enabled" in slot and "action" in slot, f"判据读数缺字段：{sorted(slot)}"

    @pytest.mark.asyncio
    async def testPoolCrossTurnFeedbackIsWrittenAndReadBack(self):
        """池侧跨趟反馈必须**写进去又被下一轮读回**（不是恒 None 的死字段）。

        不留存 `_poolCompressionRatio` 的后果不是"少一个数字"：池侧判据的
        `prior_compression_ratio` 恒为 `None` ⇒ 每一轮都停在
        `INSUFFICIENT_DATA`，开关打开也永不动作 —— 闸恒不开，且"开了"与
        "关着"在读面上长得一模一样。
        """
        from tests.unit.context.test_pool_branch_envelope_transient import (
            _build,
            _orchestrator,
        )

        orch = _orchestrator(budget=1200)
        bulky = "这是一条很长的记忆内容，用于撑爆信封预算。" * 40
        async def turn():
            return await _build(
                orch,
                user_input="问题",
                relevant_memories=[{"content": bulky}],
                session_context=[{"role": "user", "content": "短历史" * 20}],
            )

        await turn()
        assert orch._poolCompressionRatio is not None, (  # noqa: SLF001
            "首轮压缩后没有留下可被下一轮回读的实测读数（池侧跨趟反馈断了）"
        )
        first = orch._poolCompressionRatio  # noqa: SLF001
        assert 0.0 < first <= 1.0, f"折叠比不在合法区间：{first}"

        await turn()
        slot = orch.get_context_health()["compression_economics"]
        assert slot["prior_ratio"] is not None, (
            f"第二轮没把上一轮读数喂进判据（prior_ratio 恒 None）：{slot}"
        )

    @pytest.mark.asyncio
    async def testPoolDiscardIsVisibleAfterADiscardingTurn(self):
        """弃封之后读数必须翻转（不是恒真的形状位）。

        额度经**既有测试钩子** `_envelopeBudget` 注入 1 —— 池分支正常路径下
        信封额度有地板（`_ENVELOPE_MIN_TOKENS`），故弃封这条净损失路径必须
        显式构造；本文件与 `test_pool_branch_envelope_transient.py` 用的是
        同一个钩子（不手工赋私有字段）。
        """
        from tests.unit.context.test_pool_branch_envelope_transient import (
            _build,
            _orchestrator,
        )

        orch = _orchestrator(budget=1200)
        orch._envelopeBudget = lambda *a, **k: 1  # noqa: SLF001 - 既有测试钩子
        await _build(
            orch,
            user_input="问题",
            relevant_memories=[{"content": "记忆" * 400}],
        )
        slot = orch.get_context_health()["compression_economics"]
        assert slot.get("discarded") is True, f"弃封未在观测面出账：{slot}"
        assert slot.get("reason") == CompressionAction.ENVELOPE_DISCARDED.value


class TestWiringAndStaticGuards:
    def testCompressionRatioIsConsumedByDecisionNotOnlyLogged(self):
        """`compression_ratio` 必须成为判据输入之一（跨趟反馈），而不是只落日志。"""
        injector = _make_injector()
        assert injector.readCompressionFeedback() is None, "未跑过任何一轮 ⇒ 读回 None（未测量）"

        result = injector.build_context(
            system_prompt="BASE",
            memories=[],
            conversation_history=_big_history(),
            user_input=_OVER_BUDGET_INPUT,
        )
        assert result.compression_ratio < 1.0, "该输入必须真的触发压缩，否则本条不成立"
        ratio = injector.readCompressionFeedback()
        assert ratio is not None, "首轮压缩后必须留下可被下一轮回读的实测读数"
        assert ratio == pytest.approx(result.compression_ratio)

    def testFeedbackIsFedIntoNextRoundDecision(self):
        """跨趟闭环：上一轮读数必须真的进判据入参（接线，不是摆设）。"""
        injector = _make_injector()
        first = injector.build_context(
            system_prompt="BASE",
            memories=[],
            conversation_history=_big_history(),
            user_input=_OVER_BUDGET_INPUT,
        )
        first_readout = first.stats["compression_economics"]
        assert first_readout["enabled"] is False, "默认关：开关未开"
        assert first_readout["prior_ratio"] is None, "首轮无实测：入参必须是 None（未测量）"

        second = injector.build_context(
            system_prompt="BASE",
            memories=[],
            conversation_history=_big_history(),
            user_input=_OVER_BUDGET_INPUT,
        )
        assert second.stats["compression_economics"]["prior_ratio"] == pytest.approx(
            injector.readCompressionFeedback()
        ), "第二轮必须拿到第一轮的实测读数"
        assert second.stats["compression_economics"]["prior_ratio"] is not None

    def testSingleSourceForCostAcrossTickets(self):
        """静态守卫：全仓"一次动作代价"的定义处有且仅有一处。"""
        hits = [
            p
            for p in (REPO_ROOT / "neurova").rglob("*.py")
            if re.search(r"^def evaluateCompressionEconomics", p.read_text(encoding="utf-8"), re.M)
        ]
        assert [p.name for p in hits] == ["compression_economics.py"], hits
        for rel in ("neurova/context/injector.py", "neurova/context/orchestrator.py"):
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            assert re.search(r"^\s*cost\s*=\s*foldable", src, re.M) is None, rel

    def testEconomicsGateUsesOnlySharedTokenEstimator(self):
        """静态守卫：判据链路里不得出现第二处 token 估算实现。"""
        for rel in (
            "neurova/context/injector.py",
            "neurova/context/orchestrator.py",
            "neurova/context/compression_economics.py",
        ):
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            for pattern in (r"len\([^)]*\)\s*//\s*4", r"len\([^)]*\)\s*\*\s*1\.5", r"chars_per_token\s*\*"):
                assert re.search(pattern, src) is None, f"{rel} 命中就地近似：{pattern}"

    def testEconomicsSwitchIsDeclaredInGovernanceDefaults(self):
        """开关并入既有治理事实源，默认关 ⇒ 现网行为零变更。"""
        from neurova.security.governance_settings import DEFAULTS

        assert "compression_economics_enabled" in DEFAULTS
        assert DEFAULTS["compression_economics_enabled"] is False


class TestSwitchOnChangesDecisionHonestly:
    def testSwitchOnStillCompressesWhenSafetyLineRequires(self):
        """开关开 + 撞窗口硬顶 ⇒ 照压，不因经济性判据挡下（安全线优先）。"""
        injector = _make_injector(compression_economics=True, window_ceiling=1000)
        result = injector.build_context(
            system_prompt="BASE",
            memories=[],
            conversation_history=_big_history(),
            user_input=_OVER_BUDGET_INPUT,
        )
        readout = result.stats["compression_economics"]
        assert readout["enabled"] is True
        assert readout["action"] == CompressionAction.SAFETY_LINE_YIELD.value
        assert result.compression_ratio < 1.0

    def testSwitchOnRefusesFoldWhenNoPriorMeasurement(self):
        """开关开 + 无上一轮实测 ⇒ 不动作，且原因是 INSUFFICIENT_DATA（不是"不划算"）。"""
        injector = _make_injector(compression_economics=True, window_ceiling=50000)
        result = injector.build_context(
            system_prompt="BASE",
            memories=[],
            conversation_history=_big_history(),
            user_input=_OVER_BUDGET_INPUT,
        )
        readout = result.stats["compression_economics"]
        assert readout["action"] == CompressionAction.INSUFFICIENT_DATA.value, readout
        assert readout["deferred_reason"] == CompressionAction.INSUFFICIENT_DATA.value
        assert result.compression_ratio == 1.0, "判据不动作 ⇒ 不得发生有损折叠"

    def testDefaultOffKeepsCompressionBehaviorUnchanged(self):
        """默认关 ⇒ 判据只**观测**不出门：它本会挡下的这一刀，照旧照压。

        与 `testSwitchOnRefusesFoldWhenNoPriorMeasurement` 是同一输入的开关两侧：
        开关开 ⇒ ratio == 1.0（不压）；开关关 ⇒ ratio < 1.0（照压）。两行合起来
        才是"默认关 ⇒ 现网行为零变更"的可核形态。
        """
        injector = _make_injector(window_ceiling=50000)
        result = injector.build_context(
            system_prompt="BASE",
            memories=[],
            conversation_history=_big_history(),
            user_input=_OVER_BUDGET_INPUT,
        )
        readout = result.stats["compression_economics"]
        assert readout["enabled"] is False
        assert readout["action"] == CompressionAction.INSUFFICIENT_DATA.value, "判据本会挡下这一刀"
        assert readout["deferred_reason"] == CompressionAction.INSUFFICIENT_DATA.value
        assert result.compression_ratio < 1.0, "默认关时既有压缩路径必须仍然生效"

    def testSwitchOnRefusesToArmWhenRulerFallsBack(self, monkeypatch):
        """尺子掉档（无 tokenizer）时闸不得生效 —— 且是**接线**层面的拒绝，不只是纯函数。

        这是"不得在坏尺上建闸"的可核形态：探针报出未校准，注入器的判定链
        必须据此拒绝，而不是绕过探针自己判断。
        """
        from neurova.context import token_estimator

        monkeypatch.setattr(token_estimator, "isRulerCalibrated", lambda: False, raising=True)
        injector = _make_injector(compression_economics=True, window_ceiling=50000)
        injector._lastCompressionRatio = 0.25  # 即便前情"看起来很划算"，坏尺也不许开工
        result = injector.build_context(
            system_prompt="BASE",
            memories=[],
            conversation_history=_big_history(),
            user_input=_OVER_BUDGET_INPUT,
        )
        readout = result.stats["compression_economics"]
        assert readout["action"] == CompressionAction.RULER_UNCALIBRATED.value, readout
        assert result.compression_ratio == 1.0, "坏尺上的闸必须不动作"

    def testSwitchOnFoldsWhenPriorRoundProvesItPays(self):
        """开关开 + 上一轮实测证明折叠真的省下 ⇒ 判据放行（不是恒不放行的死闸）。"""
        injector = _make_injector(compression_economics=True, window_ceiling=50000)
        injector._lastCompressionRatio = 0.25
        result = injector.build_context(
            system_prompt="BASE",
            memories=[],
            conversation_history=_big_history(),
            user_input=_OVER_BUDGET_INPUT,
        )
        readout = result.stats["compression_economics"]
        assert readout["action"] == CompressionAction.ECONOMICAL.value, readout
        assert readout["profit"] > readout["cost"]
        assert result.compression_ratio < 1.0

class TestBothEntryPointsShareOneGate:
    """两条接入点（非池 `injector.py` / 池 `orchestrator.py`）必须过同一份判据。

    只接一条 = 第二形态的"视图与账本不一致"——同一件事在两处各有一套判法。
    """

    def testParserEntryPointExistsOnOrchestrator(self):
        from neurova.context.orchestrator import ContextOrchestrator

        assert hasattr(ContextOrchestrator, "_poolEconomicsAllows")
        src = (REPO_ROOT / "neurova/context/orchestrator.py").read_text(encoding="utf-8")
        assert "evaluateCompressionEconomics" in src, "池分支必须消费同一份判据"
        assert re.search(r"^def evaluateCompressionEconomics", src, re.M) is None, (
            "池分支不得自带第二份判据实现"
        )

    def testPoolBranchReadsSameGovernanceSwitch(self):
        """池分支开关与非池分支读同一个治理键（单源，不新开开关）。"""
        src = (REPO_ROOT / "neurova/context/orchestrator.py").read_text(encoding="utf-8")
        assert '"compression_economics_enabled"' in src
        injector_src = (REPO_ROOT / "neurova/context/injector.py").read_text(encoding="utf-8")
        assert '"compression_economics_enabled"' in injector_src

    def testPoolEnvelopeCompressionEmitsDiscardReadout(self):
        """池分支弃封同样出账：`report` 必须在池侧被接上（不许只有非池出账）。"""
        src = (REPO_ROOT / "neurova/context/orchestrator.py").read_text(encoding="utf-8")
        assert "report=_discard_report" in src, "池分支弃封未出账 = 同一块静默缺口留在另一条路上"

    def testBuilderPathAlsoPassesTheGate(self):
        """第三条接入点：`builder.compress_if_needed` 此前**直接**调 `_compress_context`。

        同一份契约里的三个消费方只接两条，等于把缺口留在降级链上——用户侧
        最常走的正是这条（无池可用时）。
        """
        src = (REPO_ROOT / "neurova/context/builder.py").read_text(encoding="utf-8")
        assert "_economics_allows" in src, "builder 路径绕过了判据"
        gate_pos = src.index("_economics_allows")
        compress_pos = src.index("_compress_context", gate_pos)
        assert gate_pos < compress_pos, "判据必须在压缩动作之前"

    def testEveryProductionCallerOfCompressContextPassesTheGate(self):
        """全量扫荡：注入器那份 `_compress_context` 的每个生产调用点都必须在判据之后。

        口径按**被调对象**限定（`self._unified_injector._compress_context` 与
        `injector.py` 内部的 `self._compress_context`）——同名不同类的两处实现
        （记忆层 `AutoContextModule` 自己那份）不属同一契约，不并入。
        这是"放大视角"的机器形态：新增一个调用点忘了过闸，本条即红。

        取数走 `tests/ast_scan` 的共享预算入口（`callNodes` 带文本预筛）：
        判据本身与代码总量、与机器快慢都无关，不许手写 `rglob + ast.parse`
        全仓扫描——那会把代码行数编码成时间上界，撞 30s 默认墙钟即偶发红
        （门禁：`tests/unit/test_ci_ast_scan_budget_guard.py`）。
        """
        import ast

        from tests import ast_scan

        offenders = []
        for path, node in ast_scan.callNodes(REPO_ROOT / "neurova", "_compress_context"):
            receiver = ast.unparse(node.func.value)
            if receiver == "self" and path.name != "injector.py":
                continue  # 同名不同类：不属本契约
            if receiver not in ("self", "self._unified_injector"):
                continue
            lines = ast_scan.sourceCode(path).splitlines()
            window = "\n".join(lines[max(0, node.lineno - 40): node.lineno])
            if "_economics_allows" not in window:
                offenders.append(f"{ast_scan.relativeToRepo(path)}:{node.lineno}")
        assert offenders == [], f"未过判据的压缩调用点：{offenders}"

class TestBaselineCompatibility:
    """003 的负债口径引用本模块的 `profit`/`cost`，故两字段必须在读数里可读。"""

    def testReceiptCanReadProfitAndCostFromReadout(self):
        injector = _make_injector(window_ceiling=50000)
        result = injector.build_context(
            system_prompt="BASE",
            memories=[],
            conversation_history=_big_history(),
            user_input=_OVER_BUDGET_INPUT,
        )
        readout = result.stats["compression_economics"]
        assert isinstance(readout["profit"], int)
        assert isinstance(readout["cost"], int)
        assert set(readout) >= {"enabled", "action", "profit", "cost", "prior_ratio", "deferred_reason"}

    def testReasonEnumValuesAreStableIdentifiers(self):
        """原因值是对外可引用的稳定标识串（003 与界面都按它对齐，不按序号）。"""
        for action in CompressionAction:
            assert re.fullmatch(r"[a-z][a-z_]*", action.value), action
